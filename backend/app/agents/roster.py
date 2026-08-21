"""The four agents that work a case once the taxpayer's documents are in.

The auditors named three and left the fourth to us; the fourth is Evidence & Coverage, because
their own outcome list is dominated by it — missing supporting documentation, documents that do
not correspond to the declared sales, revenue from an activity the registration does not carry,
and outright non-cooperation are five of the fifteen statements between them.

Every agent obeys the same contract as the original roster and for the same reason: it proposes
a `Hypothesis` carrying **language only**, plus a typed `TestSpec` a deterministic adjudicator
executes. No agent states a figure, and no agent reaches a conclusion — it says what is worth
testing and why, and the engine settles it.

Two fields matter more here than they did before:

* `why` records the observation that triggered the hypothesis. The auditors have to defend a
  finding to a taxpayer, and "an agent suggested it" is not a defence. The trigger is shown
  beside the verdict so the reasoning is on the page, not in the model.
* `outcome_code` is the entry in `app.outcomes` the hypothesis becomes **if confirmed** — the
  only route from an agent to the words in a report.

An agent proposes nothing when its preconditions are absent. Silence on a case where the
evidence cannot support a finding is correct behaviour, not a gap: a hypothesis that can only
ever come back "insufficient evidence" wastes the auditor's attention.
"""
from __future__ import annotations

from .adjudicator import CaseContext
from .contracts import Hypothesis, TestSpec
from .. import outcomes as oc

REGULATIONS = oc.REGULATIONS
DATA_ENTRY = oc.DATA_ENTRY
CALCULATION = oc.CALCULATION
EVIDENCE = oc.EVIDENCE


def _material(ctx: CaseContext, box: str) -> bool:
    b = ctx.box(box)
    return abs(b["unexplained"]) > b["materiality"]


# ========================================================== 1 · REGULATIONS
# The agent the auditors called most important. Retrieval-only and cite-or-drop: it may not
# assert a condition without an article behind it, so with no corpus loaded it proposes only the
# conditions checks — which are field presence, and therefore deterministic — and stays silent on
# deductibility, which is a question of law it cannot answer from nothing.
def regulations(ctx: CaseContext) -> list[Hypothesis]:
    out: list[Hypothesis] = []
    sales = ctx.document_like("sales", "revenue", "output")
    purchases = ctx.document_like("purchase", "input", "expense")
    notes = ctx.document_like("credit", "note", "debit")

    for doc, direction in ((sales, "sale"), (purchases, "purchase")):
        if not doc:
            continue
        out.append(Hypothesis(
            id=f"RG-{'S' if direction == 'sale' else 'P'}1",
            agent=REGULATIONS, outcome_code="DOC-INVOICE", reason_code="D01",
            confidence="high",
            why=f"{doc['filename']} carries {len(doc.get('rows') or [])} rows to test against "
                f"the conditions of a valid tax invoice.",
            claim="Some rows may not meet all the conditions of a valid tax invoice, which "
                  "would put the documents themselves in question rather than the arithmetic.",
            test=TestSpec(kind="invoice-conditions",
                          box="output" if direction == "sale" else "input",
                          params={"document": doc["filename"]})))

    if notes:
        out.append(Hypothesis(
            id="RG-C1", agent=REGULATIONS, outcome_code="DOC-CREDIT", reason_code="D03",
            confidence="high",
            why=f"{notes['filename']} was supplied, so the note conditions can be tested.",
            claim="Some credit notes may not meet the conditions required for them to reduce "
                  "the output tax already accounted for.",
            test=TestSpec(kind="credit-note-conditions", box="output",
                          params={"document": notes["filename"]})))

    if purchases:
        out.append(Hypothesis(
            id="RG-P2", agent=REGULATIONS, outcome_code="PUR-BLOCKED", reason_code="D07",
            confidence="medium",
            why="A purchase listing is on file, so the claimed lines can be tested against the "
                "categories on which input VAT is not recoverable.",
            claim="Input VAT may have been claimed on purchases the purchaser is not entitled "
                  "to deduct.",
            test=TestSpec(kind="blocked-input", box="input",
                          params={"document": purchases["filename"]})))
    return out


# ========================================================== 2 · DATA ENTRY
# The keying-error specialist, now working the uploaded rows as well as the declaration. Their
# own example — SAR 10,000 keyed for SAR 1,000 — is the decimal-shift test.
def data_entry(ctx: CaseContext) -> list[Hypothesis]:
    out: list[Hypothesis] = []
    if _material(ctx, "output"):
        out.append(Hypothesis(
            id="DE-01", agent=DATA_ENTRY, reason_code="A09", confidence="high",
            why="The declared figure and the figure the documents support differ by more than "
                "materiality, which is the precondition for a keying test.",
            claim="The declared figure may be the supported one with the decimal point in the "
                  "wrong place — a keying error rather than an under-declaration.",
            test=TestSpec(kind="decimal-shift", box="output")))
        out.append(Hypothesis(
            id="DE-02", agent=DATA_ENTRY, reason_code="A09", confidence="medium",
            why="A transposition produces the same digits in another order, which is worth "
                "excluding before treating the difference as undeclared revenue.",
            claim="The declared figure may carry the supported figure's digits in a different "
                  "order, which would indicate a transposition when the return was keyed.",
            test=TestSpec(kind="digit-transposition", box="output")))
        out.append(Hypothesis(
            id="DE-03", agent=DATA_ENTRY, reason_code="R10", confidence="medium",
            why="A declaration far outside this taxpayer's own filing range supports a keying "
                "explanation over a trading one.",
            claim="The declaration may be out of character for this taxpayer's own trading "
                  "history, which would support a data-entry explanation over a trading one.",
            test=TestSpec(kind="historical-magnitude", box="output")))
    return out


# ========================================================= 3 · CALCULATION
# Two jobs. It tests the taxpayer's own listing against what they declared — which is where most
# of the auditors' sales outcomes come from — and it reports any figure the auditor recorded that
# the engine could not reproduce.
def calculation(ctx: CaseContext) -> list[Hypothesis]:
    out: list[Hypothesis] = []
    sales = ctx.document_like("sales", "revenue", "output")
    pos = ctx.document_like("pos", "point-of-sale", "till", "bank")

    if sales:
        out.append(Hypothesis(
            id="CA-01", agent=CALCULATION, outcome_code="SAL-HIGHER", reason_code="R01",
            confidence="high",
            why=f"{sales['filename']} can be totalled and set against the declared box.",
            claim="The sales the taxpayer's own listing supports may exceed the sales reported "
                  "in the return.",
            test=TestSpec(kind="listing-vs-declared", box="output",
                          params={"document": sales["filename"]})))
        out.append(Hypothesis(
            id="CA-02", agent=CALCULATION, outcome_code="SAL-UNDISCLOSED", reason_code="R01",
            confidence="medium",
            why="If the listing exceeds the return, the excess is either a timing difference or "
                "revenue that was never disclosed.",
            claim="Part of the supplies evidenced by the listing may not have been disclosed in "
                  "the return at all.",
            test=TestSpec(kind="listing-vs-declared", box="output",
                          params={"document": sales["filename"], "undisclosed": True})))

    if pos:
        out.append(Hypothesis(
            id="CA-03", agent=CALCULATION, outcome_code="SAL-POS", reason_code="R01",
            confidence="high",
            why=f"{pos['filename']} is an independent record of takings and can be set against "
                f"the declared box.",
            claim="Takings evidenced by the point-of-sale or bank records may exceed the sales "
                  "reported in the return.",
            test=TestSpec(kind="listing-vs-declared", box="output",
                          params={"document": pos["filename"]})))

    unreproduced = [c for c in ctx.calculations if c.get("status") == "disagree"]
    if unreproduced:
        out.append(Hypothesis(
            id="CA-04", agent=CALCULATION, reason_code="A09", confidence="high",
            why=f"{len(unreproduced)} figure{'' if len(unreproduced) == 1 else 's'} recorded on this case could not be reproduced "
                f"from the documents they were said to come from.",
            claim="A figure recorded during the review does not follow from the document it was "
                  "taken from, and should be re-derived before it supports a conclusion.",
            test=TestSpec(kind="auditor-figure", box="output")))
    return out


# =============================================== 4 · EVIDENCE & COVERAGE
# The largest share of the auditors' outcome list: is there documentation behind what was
# claimed, do the documents correspond to the declaration, is there revenue from an activity the
# registration does not carry, and did the taxpayer simply not answer.
def evidence(ctx: CaseContext) -> list[Hypothesis]:
    out: list[Hypothesis] = []
    purchases = ctx.document_like("purchase", "input", "expense")
    sales = ctx.document_like("sales", "revenue", "output")

    if purchases:
        out.append(Hypothesis(
            id="EV-01", agent=EVIDENCE, outcome_code="PUR-NODOC", reason_code="D01",
            confidence="high",
            why=f"{purchases['filename']} claims input VAT line by line, so each line can be "
                f"tested for the document behind it.",
            claim="Input VAT may have been claimed on purchases with no supporting documentation "
                  "behind them.",
            test=TestSpec(kind="missing-support", box="input",
                          params={"document": purchases["filename"]})))

    if sales:
        out.append(Hypothesis(
            id="EV-02", agent=EVIDENCE, outcome_code="SAL-MISMATCH", reason_code="R01",
            confidence="medium",
            why="The documents supplied can be set against the declared sales to see whether "
                "they describe the same population.",
            claim="The documents provided may not correspond to the sales declared in the "
                  "return.",
            test=TestSpec(kind="listing-vs-declared", box="output",
                          params={"document": sales["filename"], "correspondence": True})))

        if not ctx.has_document_like("trial", "balance", "tb"):
            out.append(Hypothesis(
                id="EV-03", agent=EVIDENCE, outcome_code="SAL-NOTB", reason_code="R01",
                confidence="medium",
                why="No trial balance is among the documents received, so an excess over the "
                    "return cannot be traced into the accounts.",
                claim="Sales evidenced by the records submitted may exceed those declared, with "
                      "no trial balance supplied to substantiate the difference.",
                test=TestSpec(kind="trial-balance-absent", box="output",
                              params={"document": sales["filename"]})))

        if ctx.cr_activities:
            out.append(Hypothesis(
                id="EV-04", agent=EVIDENCE, outcome_code="SAL-SECONDARY", reason_code="R09",
                confidence="medium",
                why=f"The registration carries {len(ctx.cr_activities)} economic "
                    f"activit{'y' if len(ctx.cr_activities) == 1 else 'ies'}, so the listing can "
                    f"be tested for revenue outside the disclosed ones.",
                claim="The listing may contain supplies from a secondary business activity that "
                      "the return does not disclose.",
                test=TestSpec(kind="secondary-activity", box="output",
                              params={"document": sales["filename"]})))

    outstanding = [g for g in ctx.gaps if g.get("kind") == "missing-item"]
    if outstanding:
        out.append(Hypothesis(
            id="EV-05", agent=EVIDENCE, outcome_code="PUR-NOCOOP", reason_code="D01",
            confidence="high",
            why=(f"{len(outstanding)} requested item{'' if len(outstanding) == 1 else 's'} "
                f"{'has' if len(outstanding) == 1 else 'have'} still not been supplied."),
            claim="Items requested from the taxpayer remain outstanding, and claims that depend "
                  "on them cannot be substantiated.",
            test=TestSpec(kind="non-cooperation", box="input")))
    return out


AGENTS = (regulations, data_entry, calculation, evidence)


def propose(ctx: CaseContext) -> list[Hypothesis]:
    """Every agent's hypotheses, in roster order. Ids are unique across the roster."""
    out: list[Hypothesis] = []
    for agent in AGENTS:
        out.extend(agent(ctx))
    return out
