"""The adjudicator — deterministic Python, deliberately not a model.

Every hypothesis an agent proposes is settled here, against the reconciliation the engine
already computed. This is the component that lets the investigation layer be useful without
letting a model near a figure: an agent may claim "the declared figure looks like a decimal
slip", but only this file decides whether declared x 10 actually equals the expected return,
and only this file states the amount.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .contracts import Adjudication, Hypothesis, TestSpec

TOLERANCE = 1.0     # SAR; the tests below are near-exact by design


@dataclass
class CaseContext:
    """Everything the adjudicator may look at. All of it engine-computed or filed data."""

    recon: dict                                   # reconcile_case output
    prior_returns: list[dict] = field(default_factory=list)   # {period_from, period_to, vat_amount}
    prior_cases: list[dict] = field(default_factory=list)     # {case_id, root_cause_code, result}
    # documents the taxpayer supplied, as extracted: {id, filename, columns, rows}
    documents: list[dict] = field(default_factory=list)
    # figures the AUDITOR keyed in by hand: {seq, label, amount, doc_name}
    recorded: list[dict] = field(default_factory=list)
    # --- added with the post-receipt rescope: what the agents reason over now that the
    #     planning inputs are gone and the uploaded files are the evidence.
    # the registration's economic activities: {isic, description, primary}
    cr_activities: list[dict] = field(default_factory=list)
    # auditor calculations already checked: {label, status, stated, computed, delta}
    calculations: list[dict] = field(default_factory=list)
    # outstanding completeness gaps: {kind, item_label, detail, severity}
    gaps: list[dict] = field(default_factory=list)
    # the confirmed request spec: {key, label, required_columns}
    requested: list[dict] = field(default_factory=list)

    def tabular(self) -> list[dict]:
        return [d for d in self.documents if d.get("rows")]

    def document_like(self, *fragments: str) -> dict | None:
        """The uploaded document whose name suggests a kind — 'sales', 'purchase', 'trial'."""
        for d in self.documents:
            name = (d.get("filename") or "").lower()
            if any(f in name for f in fragments):
                return d
        return None

    def has_document_like(self, *fragments: str) -> bool:
        return self.document_like(*fragments) is not None

    def box(self, which: str) -> dict:
        return self.recon if which == "output" else self.recon["purchase"]

    def document(self, ref) -> dict | None:
        """Find a supplied document by id or by filename."""
        for d in self.documents:
            if d.get("id") == ref or d.get("filename") == ref:
                return d
        return None


def _close(a: float, b: float, tol: float = TOLERANCE) -> bool:
    return abs(a - b) <= tol


def _digits(v: float) -> str:
    return "".join(sorted(str(int(round(abs(v))))))


def adjudicate(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    fn = _TESTS.get(h.test.kind)
    if fn is None:
        return Adjudication(hypothesis_id=h.id, status="insufficient-evidence",
                            explanation=f"No adjudicator implements {h.test.kind}.")
    return fn(h, ctx)


# ------------------------------------------------------------------ the tests
def _decimal_shift(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    box = ctx.box(h.test.box)
    declared, expected = box["declared"], box["expected_vat"]
    unexplained = box["unexplained"]
    for factor in (10, 100, 0.1, 0.01):
        if declared and _close(declared * factor, expected):
            return Adjudication(
                hypothesis_id=h.id, status="confirmed", amount=round(unexplained, 2),
                detail={"declared": declared, "factor": factor, "expected": expected,
                        "product": round(declared * factor, 2)},
                explanation=(f"Declared SAR {declared:,.0f} x {factor:g} = SAR "
                             f"{declared * factor:,.0f}, which equals the expected return of "
                             f"SAR {expected:,.0f} exactly. The difference of SAR "
                             f"{unexplained:,.0f} is consistent with a misplaced decimal point "
                             f"in the declared figure, not with unreported supplies."))
    return Adjudication(
        hypothesis_id=h.id, status="refuted", detail={"declared": declared, "expected": expected},
        explanation=(f"No power-of-ten multiple of the declared SAR {declared:,.0f} reaches the "
                     f"expected SAR {expected:,.0f}."))


def _digit_transposition(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    box = ctx.box(h.test.box)
    declared, expected = box["declared"], box["expected_vat"]
    same_digits = declared and expected and _digits(declared) == _digits(expected)
    if same_digits and not _close(declared, expected):
        return Adjudication(
            hypothesis_id=h.id, status="confirmed", amount=round(box["unexplained"], 2),
            detail={"declared": declared, "expected": expected},
            explanation=(f"The declared SAR {declared:,.0f} and the expected SAR "
                         f"{expected:,.0f} use the same digits in a different order — the "
                         f"signature of a keying error rather than a missing supply."))
    return Adjudication(hypothesis_id=h.id, status="refuted",
                        detail={"declared": declared, "expected": expected},
                        explanation="The declared and expected figures do not share the same digits.")


def _single_document(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    box = ctx.box(h.test.box)
    unexplained = box["unexplained"]
    for inv in box.get("evidence_invoices", []):
        if _close(abs(float(inv["tax_amount"])), abs(unexplained)) and abs(unexplained) > 0:
            return Adjudication(
                hypothesis_id=h.id, status="confirmed", amount=round(unexplained, 2),
                detail={"uuid": inv["uuid"], "tax_amount": inv["tax_amount"],
                        "issue_date": inv["issue_date"]},
                explanation=(f"The difference of SAR {abs(unexplained):,.0f} equals exactly one "
                             f"document, {inv['uuid']} issued {inv['issue_date']}. A single "
                             f"omitted or duplicated invoice explains it."))
    return Adjudication(hypothesis_id=h.id, status="refuted",
                        explanation="No single document matches the difference.")


def _paired_offset(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    out_r = ctx.recon["unexplained"]
    in_r = ctx.recon["purchase"]["unexplained"]
    if abs(out_r) > TOLERANCE and _close(out_r, -in_r):
        return Adjudication(
            hypothesis_id=h.id, status="confirmed", amount=round(abs(out_r), 2),
            detail={"output_unexplained": out_r, "input_unexplained": in_r},
            explanation=(f"The output box is out by SAR {out_r:,.0f} and the input box by SAR "
                         f"{in_r:,.0f} — equal and opposite. That is the signature of a "
                         f"misposting between the two boxes, not of a revenue loss."))
    return Adjudication(hypothesis_id=h.id, status="refuted",
                        detail={"output_unexplained": out_r, "input_unexplained": in_r},
                        explanation="The two boxes' differences are not equal and opposite.")


def _period_shift(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    box = ctx.box(h.test.box)
    deferred = box.get("deferred_out", {})
    amount, unexplained = float(deferred.get("amount", 0)), box["unexplained"]
    if amount and _close(amount, unexplained):
        return Adjudication(
            hypothesis_id=h.id, status="confirmed", amount=round(unexplained, 2),
            detail=dict(deferred),
            explanation=(f"The difference of SAR {unexplained:,.0f} equals the SAR {amount:,.0f} of "
                         f"supplies ({deferred.get('count')} documents) whose tax point falls in "
                         f"the next period — a timing difference, not an under-declaration."))
    return Adjudication(hypothesis_id=h.id, status="refuted", detail=dict(deferred),
                        explanation="The difference does not match the supplies moved between periods.")


def _rate_misapplication(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    box = ctx.box(h.test.box)
    a, b = float(h.test.params.get("from_rate", 15)), float(h.test.params.get("to_rate", 5))
    base, unexplained = box["expected_base"], box["unexplained"]
    implied = round(base * (a - b) / 100.0, 2)
    if abs(unexplained) > TOLERANCE and _close(implied, unexplained):
        return Adjudication(
            hypothesis_id=h.id, status="confirmed", amount=round(unexplained, 2),
            detail={"base": base, "from_rate": a, "to_rate": b, "implied": implied},
            explanation=(f"The difference of SAR {unexplained:,.0f} equals the taxable base of SAR "
                         f"{base:,.0f} at {a:g}% rather than {b:g}% — a rate applied to the "
                         f"whole base, not a missing supply."))
    return Adjudication(hypothesis_id=h.id, status="refuted",
                        detail={"base": base, "implied": implied},
                        explanation="The difference does not correspond to a rate difference on this base.")


def _recurrence(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    hits = [c for c in ctx.prior_cases if c.get("root_cause_code")]
    if hits:
        codes = sorted({c["root_cause_code"] for c in hits})
        return Adjudication(
            hypothesis_id=h.id, status="confirmed", amount=0.0,
            detail={"prior_cases": [c["case_id"] for c in hits], "root_causes": codes},
            explanation=(f"This taxpayer has {len(hits)} prior case{'' if len(hits) == 1 else 's'} closed with a recorded "
                         f"root cause ({', '.join(codes)}). The same treatment should be applied "
                         f"unless the facts differ."))
    return Adjudication(hypothesis_id=h.id, status="refuted",
                        explanation="No prior case with a recorded root cause for this taxpayer.")


def _historical_magnitude(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    box = ctx.box(h.test.box)
    declared = box["declared"]
    history = [float(r["vat_amount"]) for r in ctx.prior_returns if r.get("vat_amount")]
    if len(history) < 2:
        return Adjudication(hypothesis_id=h.id, status="insufficient-evidence",
                            detail={"prior_periods": len(history)},
                            explanation="Too few prior periods on file to judge the magnitude.")
    typical = round(sum(history) / len(history), 2)
    if typical and declared and (declared < typical / 3 or declared > typical * 3):
        direction = "far below" if declared < typical else "far above"
        return Adjudication(
            hypothesis_id=h.id, status="confirmed", amount=0.0,
            detail={"declared": declared, "prior_average": typical, "periods": len(history)},
            explanation=(f"Declared SAR {declared:,.0f} is {direction} this taxpayer's own "
                         f"average of SAR {typical:,.0f} across {len(history)} prior periods. "
                         f"The declaration is out of character for the business, which points at "
                         f"how the figure was entered rather than at the trading itself."))
    return Adjudication(hypothesis_id=h.id, status="refuted",
                        detail={"declared": declared, "prior_average": typical},
                        explanation="The declared figure is in line with this taxpayer's history.")


def _recomputed_total(h: Hypothesis, ctx: CaseContext) -> Adjudication:
    """§7's second line of defence: check the auditor's own arithmetic.

    The auditors raised two sources of error, not one. A taxpayer may key SAR 10,000 for SAR
    1,000 — the decimal-shift test. But an auditor totalling ten invoices by hand may record
    SAR 900 where the documents say SAR 1,000, and nothing in the case would ever catch it,
    because every downstream figure inherits the mistake.

    So this recomputes the total from the source rows and compares it with what was recorded.
    "Confirmed" here means a discrepancy exists — the hypothesis is that the recorded figure is
    wrong, and confirming it is a finding against our own working, not against the taxpayer.
    """
    params = h.test.params
    recorded = float(params.get("recorded", 0.0))
    column = params.get("column", "vat_amount")
    doc = ctx.document(params.get("document_id", params.get("document", "")))
    if doc is None:
        return Adjudication(hypothesis_id=h.id, status="insufficient-evidence",
                            explanation="The source document for the recorded figure is not on file.")
    columns = doc.get("columns") or []
    if column not in columns:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            detail={"filename": doc.get("filename"), "columns": columns},
            explanation=(f"{doc.get('filename')} has no '{column}' column, so the recorded "
                         f"figure cannot be recomputed from it."))
    idx = columns.index(column)
    values, counted = [], 0
    for row in doc.get("rows") or []:
        v = row[idx] if idx < len(row) else None
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            values.append(float(v)); counted += 1
        else:
            try:
                values.append(float(str(v).replace(",", "").strip())); counted += 1
            except (TypeError, ValueError):
                continue
    computed = round(sum(values), 2)
    diff = round(recorded - computed, 2)
    if _close(recorded, computed):
        return Adjudication(
            hypothesis_id=h.id, status="refuted", amount=0.0,
            detail={"recorded": recorded, "computed": computed, "rows": counted,
                    "filename": doc.get("filename")},
            explanation=(f"The recorded SAR {recorded:,.2f} agrees with the SAR {computed:,.2f} "
                         f"across {counted} rows of {doc.get('filename')}."))
    return Adjudication(
        hypothesis_id=h.id, status="confirmed", amount=round(abs(diff), 2),
        detail={"recorded": recorded, "computed": computed, "difference": diff,
                "rows": counted, "filename": doc.get("filename")},
        explanation=(f"{counted} rows of {doc.get('filename')} total SAR {computed:,.2f}, but "
                     f"SAR {recorded:,.2f} was recorded against this case — a difference of SAR "
                     f"{diff:,.2f}. Correct the recorded figure before it carries into the "
                     f"conclusion."))


from .document_tests import TESTS as _DOCUMENT_TESTS   # noqa: E402  (needs Adjudication above)

_TESTS = {
    **_DOCUMENT_TESTS,
    "decimal-shift": _decimal_shift,
    "digit-transposition": _digit_transposition,
    "single-document": _single_document,
    "paired-offset": _paired_offset,
    "period-shift": _period_shift,
    "rate-misapplication": _rate_misapplication,
    "recurrence": _recurrence,
    "historical-magnitude": _historical_magnitude,
    "recomputed-total": _recomputed_total,
}
