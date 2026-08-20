"""Drive the calculation agent: parse the auditor's method, execute it, record the verdict.

Three steps, and the split between them is the safety property. The model turns a sentence into
a query (`llm.parse_calculation`), Python executes the query (`calculation.run`), and the result
is written down with the query beside it. Nobody has to trust the model's arithmetic, because
the model never performs any.

Two entry points, because the auditors described two habits:

* `ask` — "how many invoices did they actually send?" The auditor wants a number off the
  documents and does not want to build a pivot table to get it.
* `check` — "I made it SAR 2,075,000." The auditor already has a number and wants it tested
  against the source.

Both run the same executor. `check` is `ask` plus a comparison, which is why a disagreement can
always say *what* was recomputed and over how many rows: the auditor can see whose assumption
differs instead of simply being told they are wrong.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..llm.service import llm
from ..models import AuditorCalculation, ReceivedDocument
from . import calculation as calc


def documents_for(db: Session, case_id: str) -> list[dict]:
    """Every extracted document on the case, in the shape the executor reads."""
    rows = db.scalars(
        select(ReceivedDocument).where(ReceivedDocument.case_id == case_id)
        .order_by(ReceivedDocument.id)).all()
    out: list[dict] = []
    for r in rows:
        content = r.content or {}
        out.append({
            "id": r.id,
            "filename": r.filename,
            "columns": content.get("columns") or [],
            "rows": content.get("rows") or [],
            "row_count": content.get("row_count") or len(content.get("rows") or []),
            "stated_totals": content.get("stated_totals") or {},
        })
    return out


def _resolve(description: str, docs: list[dict],
             spec: dict | None) -> tuple[calc.CalcQuery | None, dict, str, str]:
    """Get to an executable query, either from the auditor's own spec or by parsing their words.

    An auditor-supplied spec is used as-is and never sent to a model: if they have already said
    "sum vat_amount", there is nothing to interpret, and interpreting it anyway would only
    introduce a way to get it wrong.
    """
    if spec:
        q = calc.query_from_dict(spec)
        return q, spec, "Specified by the auditor.", "auditor"
    parsed = llm.parse_calculation(description, docs)
    if not parsed.get("checkable"):
        return None, parsed, parsed.get("understood", ""), parsed.get("source", "")
    q = calc.query_from_dict(parsed)
    return q, parsed, parsed.get("understood", ""), parsed.get("source", "")


def ask(db: Session, case_id: str, question: str,
        spec: dict | None = None) -> dict:
    """Answer a question off the uploaded documents. The figure comes from Python."""
    docs = documents_for(db, case_id)
    if not docs:
        return {"status": calc.NOT_CHECKABLE, "answer": None, "understood": "",
                "note": "No documents have been uploaded for this case yet.",
                "detail": {}, "source": "deterministic-fallback"}

    query, raw, understood, source = _resolve(question, docs, spec)
    if query is None:
        return {"status": calc.NOT_CHECKABLE, "answer": None, "understood": understood,
                "note": raw.get("understood") or "The question could not be turned into a "
                                                 "calculation over these documents.",
                "detail": {}, "source": source}

    doc = calc.pick_document(docs, query.document)
    if doc is None:
        return {"status": calc.NOT_CHECKABLE, "answer": None, "understood": understood,
                "note": _which_document(docs, query.document),
                "detail": {}, "source": source}
    result = calc.run(query, doc)
    return {"status": result.status, "answer": result.value, "understood": understood,
            "note": result.note, "detail": result.to_dict(), "source": source}


def _which_document(docs: list[dict], wanted: str) -> str:
    """Say what is on file rather than picking one — the auditor names it, not the engine."""
    if wanted:
        return (f"'{wanted}' is not among the documents on this case. "
                f"Documents on file: {calc.names(docs)}.")
    return ("Several documents are on this case, so it is not clear which one to use. "
            f"Name one of: {calc.names(docs)}.")


def check(db: Session, case_id: str, label: str, method: str, stated: float,
          spec: dict | None = None, document_name: str = "") -> dict:
    """Verify a figure the auditor computed, and record what was checked."""
    docs = documents_for(db, case_id)
    seq = 1 + (db.query(AuditorCalculation)
               .filter(AuditorCalculation.case_id == case_id).count())

    if not docs:
        rec = AuditorCalculation(
            case_id=case_id, seq=seq, label=label, method=method, stated_amount=stated,
            document_name=document_name, status=calc.NOT_CHECKABLE,
            explanation="No documents have been uploaded for this case yet.",
            parse_source="deterministic-fallback")
        db.add(rec)
        db.commit()
        return _as_dict(rec)

    query, raw, understood, source = _resolve(method, docs, spec)
    if query is None:
        rec = AuditorCalculation(
            case_id=case_id, seq=seq, label=label, method=method, stated_amount=stated,
            document_name=document_name, understood=understood, status=calc.NOT_CHECKABLE,
            explanation=raw.get("understood") or "The stated method could not be expressed as a "
                                                 "calculation over these documents.",
            parse_source=source)
        db.add(rec)
        db.commit()
        return _as_dict(rec)

    doc = calc.pick_document(docs, query.document or document_name)
    if doc is None:
        rec = AuditorCalculation(
            case_id=case_id, seq=seq, label=label, method=method, stated_amount=stated,
            document_name=document_name, query=query.describe(), query_spec=raw,
            understood=understood, status=calc.NOT_CHECKABLE,
            explanation=_which_document(docs, query.document or document_name),
            parse_source=source)
        db.add(rec)
        db.commit()
        return _as_dict(rec)

    v = calc.verify(stated, query, doc)
    rec = AuditorCalculation(
        case_id=case_id, seq=seq, label=label, method=method, stated_amount=stated,
        document_name=(doc or {}).get("filename", document_name),
        query=query.describe(), query_spec=raw, understood=understood,
        status=v.status, computed_amount=v.computed, delta=v.delta,
        explanation=v.explanation, parse_source=source)
    db.add(rec)
    db.commit()
    return _as_dict(rec, v.result.to_dict())


def _as_dict(rec: AuditorCalculation, detail: dict | None = None) -> dict:
    return {
        "id": rec.id, "seq": rec.seq, "label": rec.label, "method": rec.method,
        "stated": float(rec.stated_amount or 0), "document": rec.document_name,
        "query": rec.query, "understood": rec.understood, "status": rec.status,
        "computed": float(rec.computed_amount) if rec.computed_amount is not None else None,
        "delta": float(rec.delta or 0), "explanation": rec.explanation,
        "source": rec.parse_source, "detail": detail or {},
    }


def listing(db: Session, case_id: str) -> list[dict]:
    rows = db.scalars(
        select(AuditorCalculation).where(AuditorCalculation.case_id == case_id)
        .order_by(AuditorCalculation.seq)).all()
    return [_as_dict(r) for r in rows]


def disagreements(db: Session, case_id: str) -> list[dict]:
    """Recorded figures the engine could not reproduce — what the calculation agent reports on."""
    return [c for c in listing(db, case_id) if c["status"] == calc.DISAGREE]
