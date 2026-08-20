"""The audit outcome vocabulary — the verdicts this PoC is allowed to reach.

These are the auditors' own statements, supplied verbatim, and they are the **only** wording
that reaches an audit report or a taxpayer email. Nothing is phrased ad hoc at the call site:
an agent raises an outcome *code*, and the statement below is what gets written down. That is
what makes two findings of the same kind read identically across cases, which is the whole point
of having a controlled vocabulary rather than free prose.

The auditors gave fifteen statements. Three pairs are the same finding written twice — their
6 and 15 are word-for-word identical, 8 and 14 differ only by "the taxpayer's", and 1 states as
non-deductibility what 8/14 state as exclusion — so the vocabulary carries **twelve** distinct
outcomes. `client_refs` records which of the original fifteen each one covers, so nothing is
silently lost and the mapping can be checked against their list.

`statement` is the finding as the Authority words it. It is deliberately not parameterised: an
outcome names *what was found*, and the SAR amount attached to it is computed by the engine and
carried alongside, never interpolated into the sentence by a model.
"""
from __future__ import annotations

from dataclasses import dataclass

# the four agents that may raise an outcome
REGULATIONS = "Regulations"
DATA_ENTRY = "Data Entry"
CALCULATION = "Calculation"
EVIDENCE = "Evidence & Coverage"

# what the finding does to the assessment
DISALLOWS_INPUT = "disallows-input"      # recoverable input VAT is reduced
INCREASES_OUTPUT = "increases-output"    # output VAT due is increased
DOCUMENTATION = "documentation"          # a defect in the evidence, quantified separately


@dataclass(frozen=True)
class Outcome:
    code: str
    statement: str            # the auditors' wording — verbatim, and what gets written down
    short: str                # a chip-length label for the UI
    agent: str                # which agent may raise it
    direction: str            # sale | purchase | both
    effect: str
    needs: tuple[str, ...]    # what must be on the case file before it can be raised
    client_refs: tuple[int, ...]   # which of the auditors' fifteen statements this covers


OUTCOMES: tuple[Outcome, ...] = (
    # ------------------------------------------------------------------ purchases
    Outcome(
        code="PUR-NODOC",
        statement="Purchases for which input VAT cannot be deducted due to the absence of "
                  "supporting documentation.",
        short="No supporting documentation",
        agent=EVIDENCE,
        direction="purchase",
        effect=DISALLOWS_INPUT,
        needs=("purchase-listing",),
        client_refs=(1, 8, 14),
    ),
    Outcome(
        code="PUR-BLOCKED",
        statement="Purchases for which the purchaser is not entitled to deduct input VAT.",
        short="Input VAT not deductible",
        agent=REGULATIONS,
        direction="purchase",
        effect=DISALLOWS_INPUT,
        needs=("purchase-listing",),
        client_refs=(10,),
    ),
    Outcome(
        code="PUR-NOCOOP",
        statement="Purchases excluded due to the taxpayer's lack of cooperation.",
        short="Lack of cooperation",
        agent=EVIDENCE,
        direction="purchase",
        effect=DISALLOWS_INPUT,
        needs=(),
        client_refs=(11,),
    ),
    # ------------------------------------------------------- document conditions
    Outcome(
        code="DOC-INVOICE",
        statement="Failure to meet all the requirements of a valid tax invoice.",
        short="Invalid tax invoice",
        agent=REGULATIONS,
        direction="both",
        effect=DOCUMENTATION,
        needs=("invoice-rows",),
        client_refs=(2,),
    ),
    Outcome(
        code="DOC-CREDIT",
        statement="Failure to meet the required conditions for a valid credit note.",
        short="Invalid credit note",
        agent=REGULATIONS,
        direction="both",
        effect=DOCUMENTATION,
        needs=("credit-notes",),
        client_refs=(9,),
    ),
    # ---------------------------------------------------------------------- sales
    Outcome(
        code="SAL-MISMATCH",
        statement="The documents provided do not correspond to the declared sales.",
        short="Documents do not correspond",
        agent=EVIDENCE,
        direction="sale",
        effect=DOCUMENTATION,
        needs=("sales-listing", "vat-return"),
        client_refs=(3,),
    ),
    Outcome(
        code="SAL-SECONDARY",
        statement="Sales from secondary business activities that were not disclosed in the "
                  "VAT return.",
        short="Undisclosed secondary activity",
        agent=EVIDENCE,
        direction="sale",
        effect=INCREASES_OUTPUT,
        needs=("sales-listing", "cr-activities"),
        client_refs=(4,),
    ),
    Outcome(
        code="SAL-HIGHER",
        statement="Sales based on the data provided by the taxpayer are higher than the sales "
                  "reported in the VAT return.",
        short="Submitted sales exceed declared",
        agent=CALCULATION,
        direction="sale",
        effect=INCREASES_OUTPUT,
        needs=("sales-listing", "vat-return"),
        client_refs=(13,),
    ),
    Outcome(
        code="SAL-NOTB",
        statement="Sales records submitted are higher than the sales declared in the VAT "
                  "return, with no trial balance provided.",
        short="Exceeds declared, no trial balance",
        agent=EVIDENCE,
        direction="sale",
        effect=INCREASES_OUTPUT,
        needs=("sales-listing", "vat-return"),
        client_refs=(5,),
    ),
    Outcome(
        code="SAL-POS",
        statement="Sales based on POS records or bank statements are higher than the sales "
                  "amount reported in the VAT return.",
        short="POS/bank exceed declared",
        agent=CALCULATION,
        direction="sale",
        effect=INCREASES_OUTPUT,
        needs=("pos-or-bank", "vat-return"),
        client_refs=(6, 15),
    ),
    Outcome(
        code="SAL-POSADJ",
        statement="Adjustment of sales subject to the standard VAT rate based on POS data.",
        short="Standard-rated adjustment from POS",
        agent=CALCULATION,
        direction="sale",
        effect=INCREASES_OUTPUT,
        needs=("pos-or-bank",),
        client_refs=(12,),
    ),
    Outcome(
        code="SAL-UNDISCLOSED",
        statement="Sales that were not disclosed in the VAT returns.",
        short="Undisclosed sales",
        agent=CALCULATION,
        direction="sale",
        effect=INCREASES_OUTPUT,
        needs=("sales-listing", "vat-return"),
        client_refs=(7,),
    ),
)

BY_CODE: dict[str, Outcome] = {o.code: o for o in OUTCOMES}


def statement(code: str) -> str:
    """The Authority's wording for an outcome. Empty for an unknown code, never invented."""
    o = BY_CODE.get(code)
    return o.statement if o else ""


def short(code: str) -> str:
    o = BY_CODE.get(code)
    return o.short if o else code


def for_agent(agent: str) -> tuple[Outcome, ...]:
    return tuple(o for o in OUTCOMES if o.agent == agent)


def for_direction(direction: str) -> tuple[Outcome, ...]:
    return tuple(o for o in OUTCOMES if o.direction in (direction, "both"))


def covered_client_refs() -> frozenset[int]:
    """Every one of the auditors' fifteen statements that the vocabulary accounts for.

    `test_outcomes.py` asserts this is the full set 1..15 — so if the auditors add a statement
    and it is not mapped, the suite says so instead of it quietly having no code.
    """
    return frozenset(r for o in OUTCOMES for r in o.client_refs)
