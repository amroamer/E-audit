"""The evidence agents.

Hypothesis *generation* is pattern work, not language work, so these run deterministically
and need no model or API key — which is why the investigation still works in the offline
demo. Each agent looks at the shape of the reconciled case and proposes the questions worth
asking; none of them answers one. Claims are deliberately figure-free: the adjudicator
supplies every number.

A model can later enrich the claim language or add agents that need judgement (legal,
policy, precedent) without changing this contract.
"""
from __future__ import annotations

from .adjudicator import CaseContext
from .contracts import Hypothesis, TestSpec

RECONSTRUCTION = "Reconstruction Analyst"
FORENSICS = "Data-Entry Forensics"
HISTORY = "Historical Pattern"
RECOMPUTE = "Recomputation Check"


def _material(ctx: CaseContext, box: str) -> bool:
    b = ctx.box(box)
    return abs(b["residual"]) > b["materiality"]


def reconstruction_analyst(ctx: CaseContext) -> list[Hypothesis]:
    """Reads the box differences and the line decisions; proposes structural causes."""
    out: list[Hypothesis] = []
    if _material(ctx, "output"):
        out.append(Hypothesis(
            id="RA-01", agent=RECONSTRUCTION, reason_code="T02", confidence="medium",
            claim="The difference may be a timing one — supplies whose tax point falls in the "
                  "next period rather than supplies that were never declared.",
            test=TestSpec(kind="period-shift", box="output")))
        out.append(Hypothesis(
            id="RA-02", agent=RECONSTRUCTION, reason_code="R01", confidence="medium",
            claim="A single omitted or duplicated document would account for the difference on "
                  "its own.",
            test=TestSpec(kind="single-document", box="output")))
        out.append(Hypothesis(
            id="RA-03", agent=RECONSTRUCTION, reason_code="R07", confidence="low",
            claim="The whole taxable base may have been declared at the wrong rate.",
            test=TestSpec(kind="rate-misapplication", box="output",
                          params={"from_rate": 15, "to_rate": 5})))
    if _material(ctx, "output") and _material(ctx, "input"):
        out.append(Hypothesis(
            id="RA-04", agent=RECONSTRUCTION, reason_code="R08", confidence="medium",
            claim="The two boxes may be out by equal and opposite amounts, which would point at "
                  "a misposting between them rather than a loss of revenue.",
            test=TestSpec(kind="paired-offset", box="output")))
    return out


def data_entry_forensics(ctx: CaseContext) -> list[Hypothesis]:
    """The keying-error specialist: decimal slips, transpositions, out-of-character figures."""
    out: list[Hypothesis] = []
    if not _material(ctx, "output"):
        return out
    out.append(Hypothesis(
        id="DE-01", agent=FORENSICS, reason_code="A09", confidence="high",
        claim="The declared figure may be the expected one with the decimal point in the wrong "
              "place — a keying error rather than an under-declaration.",
        test=TestSpec(kind="decimal-shift", box="output")))
    out.append(Hypothesis(
        id="DE-02", agent=FORENSICS, reason_code="A09", confidence="medium",
        claim="The declared figure may carry the expected figure's digits in a different order, "
              "which would indicate a transposition when the return was keyed.",
        test=TestSpec(kind="digit-transposition", box="output")))
    out.append(Hypothesis(
        id="DE-03", agent=FORENSICS, reason_code="R10", confidence="medium",
        claim="The declaration may be out of character for this taxpayer's own trading history, "
              "which would support a data-entry explanation over a trading one.",
        test=TestSpec(kind="historical-magnitude", box="output")))
    return out


def historical_pattern(ctx: CaseContext) -> list[Hypothesis]:
    """This taxpayer's own past: has the Authority been here before?"""
    out: list[Hypothesis] = []
    if ctx.prior_cases:
        out.append(Hypothesis(
            id="HP-01", agent=HISTORY, reason_code="R06", confidence="medium",
            claim="This taxpayer has been audited before, and the earlier root cause may apply "
                  "again — in which case the resolution already exists.",
            test=TestSpec(kind="recurrence", box="output")))
    if _material(ctx, "output") and len(ctx.prior_returns) >= 2:
        out.append(Hypothesis(
            id="HP-02", agent=HISTORY, reason_code="R10", confidence="medium",
            claim="The declared position sits outside the range this taxpayer has filed in "
                  "previous periods.",
            test=TestSpec(kind="historical-magnitude", box="output")))
    return out


def recomputation(ctx: CaseContext) -> list[Hypothesis]:
    """The second line of defence — over our own working, not the taxpayer's.

    §7 named two error sources. The taxpayer keying SAR 10,000 for SAR 1,000 is covered by the
    forensics agent above. The other is ours: an auditor totalling supplied documents by hand
    and recording SAR 900 where they add to SAR 1,000. Nothing downstream would ever notice,
    because every later figure inherits it.

    So wherever a figure has been recorded against this case by hand and the document it came
    from is on file, propose recomputing it. The adjudicator does the arithmetic.
    """
    out: list[Hypothesis] = []
    for n, rec in enumerate(ctx.recorded, start=1):
        doc = ctx.document(rec.get("doc_name", ""))
        if doc is None or not rec.get("amount"):
            continue
        column = next((c for c in ("vat_amount", "taxable_amount", "amount", "gross_amount")
                       if c in (doc.get("columns") or [])), None)
        if column is None:
            continue
        out.append(Hypothesis(
            id=f"RC-{n:02d}", agent=RECOMPUTE, reason_code="A09", confidence="high",
            claim="A figure recorded against this case by hand can be recomputed from the "
                  "document it was taken from; if the two disagree, the error is ours and "
                  "every later figure inherits it.",
            test=TestSpec(kind="recomputed-total", box="output",
                          params={"recorded": float(rec["amount"]), "column": column,
                                  "document_id": doc.get("id")}),
            evidence_refs=[str(doc.get("filename", ""))]))
    return out


AGENTS = (reconstruction_analyst, data_entry_forensics, historical_pattern, recomputation)


def propose(ctx: CaseContext) -> list[Hypothesis]:
    """Round 1 — every evidence agent proposes in parallel; they do not need each other."""
    out: list[Hypothesis] = []
    for agent in AGENTS:
        out.extend(agent(ctx))
    return out
