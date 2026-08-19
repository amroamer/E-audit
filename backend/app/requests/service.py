"""Drive one case through the request/response loop.

The loop is: plan → issue → receive → check → (follow up | proceed). Each pass through it is a
*round*, and the round counter is the number the auditors care most about, because every round
is weeks of waiting. The whole point of the completeness checks is to make round two rarer, and
round three rare.

State lives in the database rather than in memory because the wait between issuing a request and
receiving an answer is measured in months — there is no session to hold it in.

Gaps are always recomputed from the current documents, never edited in place. That makes the
state machine trivial: an item is satisfied when nothing blocking references it, a round is
answered when every item has something against it, and the substantive review opens when the
round is complete.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import (
    AuditCase, GapFinding, InformationRequest, ReceivedDocument, RequestItem,
)
from . import extract as extractor
from .completeness import BLOCKING, Report, check
from .planner import RequestPlan, plan as build_plan

RESPONSE_WINDOW_DAYS = 20


# --------------------------------------------------------------------------------- reading

def current_request(db: Session, case_id: str) -> InformationRequest | None:
    return db.scalar(
        select(InformationRequest).where(InformationRequest.case_id == case_id)
        .order_by(InformationRequest.seq.desc())
    )


def rounds(db: Session, case_id: str) -> list[InformationRequest]:
    return list(db.scalars(
        select(InformationRequest).where(InformationRequest.case_id == case_id)
        .order_by(InformationRequest.seq)
    ).all())


def documents(db: Session, case_id: str, request_id: int | None = None
              ) -> list[ReceivedDocument]:
    q = select(ReceivedDocument).where(ReceivedDocument.case_id == case_id)
    if request_id is not None:
        q = q.where(ReceivedDocument.request_id == request_id)
    return list(db.scalars(q.order_by(ReceivedDocument.id)).all())


# --------------------------------------------------------------------------------- writing

def open_request(db: Session, case: AuditCase, *, plan: RequestPlan | None = None,
                 items: list | None = None, subject: str = "") -> InformationRequest:
    """Create the next round from a plan (or an explicit item list), in draft."""
    plan = plan or build_plan(db, case)
    seq = len(rounds(db, case.case_id)) + 1
    req = InformationRequest(
        case_id=case.case_id, seq=seq, status="draft",
        subject=subject or f"Information request — VAT period "
                           f"{case.period_from:%b %Y} to {case.period_to:%b %Y}",
    )
    db.add(req)
    db.flush()

    planned = items if items is not None else [p for p in plan.include if p.include]
    for i, p in enumerate(planned, start=1):
        item = p.item
        db.add(RequestItem(
            request_id=req.id, seq=i, catalog_key=item.key, kind=item.kind, label=item.label,
            description=item.description,
            required_columns=list(item.required_columns),
            mandatory_columns=list(item.mandatory_columns),
            expected_format=item.expected_format,
            period_from=case.period_from, period_to=case.period_to,
            footed_by=list(item.footed_by), addresses=list(item.addresses),
            hypothesis_id=p.hypothesis_id, rationale=p.rationale, status="outstanding",
        ))
    db.flush()
    db.refresh(req)
    return req


def issue(db: Session, req: InformationRequest, *, body: str = "", source: str = "",
          when: date | None = None) -> InformationRequest:
    req.status = "issued"
    req.issued_at = when or date.today()
    req.due_at = req.issued_at + timedelta(days=RESPONSE_WINDOW_DAYS)
    if body:
        req.body, req.body_source = body, source
    db.flush()
    return req


def record_document(db: Session, *, case: AuditCase, req: InformationRequest,
                    filename: str, item_id: int | None = None,
                    data: bytes | None = None, structure: dict | None = None,
                    file_format: str = "", received: date | None = None) -> ReceivedDocument:
    """Log one file the taxpayer sent, extracting whatever structure it has."""
    if structure is not None:
        content = extractor.from_structure(structure)
    elif data is not None:
        content = extractor.extract(filename, data)
    else:
        content = {"format": file_format or "", "columns": [], "rows": [],
                   "stated_totals": {}, "note": "No content supplied."}
    doc = ReceivedDocument(
        case_id=case.case_id, request_id=req.id, request_item_id=item_id,
        filename=filename, file_format=file_format or content.get("format", ""),
        media_type="", received_at=received or date.today(), round=req.seq,
        content=content, extraction_note=content.get("note", ""),
    )
    db.add(doc)
    db.flush()
    if item_id is not None:
        item = db.get(RequestItem, item_id)
        if item is not None and item.status == "outstanding":
            item.status = "received"
    if req.status == "issued":
        req.status = "answered"
        req.answered_at = doc.received_at
    db.flush()
    return doc


def run_checks(db: Session, case: AuditCase) -> Report:
    """Recompute the gaps for the current round and persist them."""
    req = current_request(db, case.case_id)
    if req is None:
        return Report(case_id=case.case_id, round=0)

    items = list(req.items)
    docs = documents(db, case.case_id, req.id)
    report = check(case_id=case.case_id, round_=req.seq, items=items, documents=docs,
                   period_from=case.period_from, period_to=case.period_to)

    db.execute(delete(GapFinding).where(GapFinding.case_id == case.case_id,
                                        GapFinding.round == req.seq))
    for g in report.gaps:
        db.add(GapFinding(
            case_id=case.case_id, round=req.seq, request_item_id=g.request_item_id,
            document_id=g.document_id, item_label=g.item_label, kind=g.kind,
            severity=g.severity, detail=g.detail, citation=g.citation, source=g.source,
        ))

    blocking_items = {g.request_item_id for g in report.gaps if g.severity == BLOCKING}
    for item in items:
        if item.status == "waived":
            continue
        item.status = "outstanding" if item.id in blocking_items else (
            "satisfied" if item.status in ("received", "satisfied") else "outstanding")
    if report.complete and req.status in ("answered", "issued"):
        req.status = "satisfied"
    db.flush()
    return report


def add_model_gaps(db: Session, case: AuditCase, gaps: list[dict]) -> int:
    """Append the judgement-shaped gaps the document reviewer proposed, tagged as its own."""
    req = current_request(db, case.case_id)
    if req is None:
        return 0
    n = 0
    for g in gaps:
        db.add(GapFinding(
            case_id=case.case_id, round=req.seq,
            request_item_id=g.get("request_item_id"), document_id=g.get("document_id"),
            item_label=g.get("item_label", ""), kind=g.get("kind", "too-vague"),
            severity=g.get("severity", "advisory"), detail=g.get("detail", ""),
            citation=g.get("citation", ""), source="claude",
        ))
        n += 1
    db.flush()
    return n


# --------------------------------------------------------------------------------- state

def state(db: Session, case: AuditCase) -> dict:
    """Everything the UI needs to render the loop for this case."""
    all_rounds = rounds(db, case.case_id)
    req = all_rounds[-1] if all_rounds else None
    gaps = list(db.scalars(
        select(GapFinding).where(GapFinding.case_id == case.case_id)
        .order_by(GapFinding.round, GapFinding.id)).all())
    docs = documents(db, case.case_id)
    by_round: dict[int, list] = {}
    for g in gaps:
        by_round.setdefault(g.round, []).append(g)

    def _gap(g: GapFinding) -> dict:
        return {"id": g.id, "kind": g.kind, "severity": g.severity, "detail": g.detail,
                "citation": g.citation, "item_label": g.item_label, "source": g.source,
                "request_item_id": g.request_item_id, "document_id": g.document_id}

    open_blocking = [g for g in by_round.get(req.seq, []) if g.severity == BLOCKING] if req else []
    return {
        "case_id": case.case_id,
        "round": req.seq if req else 0,
        "status": req.status if req else "not-started",
        "complete": bool(req) and not open_blocking,
        "rounds": [
            {
                "seq": r.seq, "status": r.status, "subject": r.subject,
                "issued_at": r.issued_at.isoformat() if r.issued_at else None,
                "due_at": r.due_at.isoformat() if r.due_at else None,
                "answered_at": r.answered_at.isoformat() if r.answered_at else None,
                "body": r.body, "body_source": r.body_source,
                "items": [
                    {"id": i.id, "seq": i.seq, "key": i.catalog_key, "kind": i.kind,
                     "label": i.label, "description": i.description,
                     "required_columns": i.required_columns,
                     "mandatory_columns": i.mandatory_columns,
                     "expected_format": i.expected_format, "rationale": i.rationale,
                     "hypothesis_id": i.hypothesis_id, "status": i.status,
                     "period": (f"{i.period_from:%Y-%m-%d} → {i.period_to:%Y-%m-%d}"
                                if i.period_from and i.period_to else "")}
                    for i in r.items
                ],
                "gaps": [_gap(g) for g in by_round.get(r.seq, [])],
            }
            for r in all_rounds
        ],
        "documents": [
            {"id": d.id, "filename": d.filename, "format": d.file_format, "round": d.round,
             "request_item_id": d.request_item_id,
             "received_at": d.received_at.isoformat() if d.received_at else None,
             "columns": (d.content or {}).get("columns", []),
             "raw_headers": (d.content or {}).get("raw_headers", []),
             "row_count": (d.content or {}).get("row_count", 0),
             "stated_totals": (d.content or {}).get("stated_totals", {}),
             "period_from": (d.content or {}).get("period_from"),
             "period_to": (d.content or {}).get("period_to"),
             "note": d.extraction_note}
            for d in docs
        ],
        "blocking": len(open_blocking),
    }
