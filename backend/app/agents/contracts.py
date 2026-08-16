"""The contracts every investigation agent speaks.

The rule that keeps this safe: **agents hypothesise, the engine adjudicates.** An agent
never states a figure. It returns a `TestSpec` — a typed, engine-executable question — and
a deterministic adjudicator answers it against the reconciliation, returning the verdict
*and* the SAR amount. So the core invariant is unchanged: the numbers live in Python.

Agents also never talk to each other in free text. They read and append typed entries on a
shared case file, which is what makes a conclusion auditable after the fact.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

TestKind = Literal[
    "decimal-shift",          # declared is the expected figure with the decimal point moved
    "digit-transposition",    # declared has the expected figure's digits in another order
    "single-document",        # the difference is exactly one document
    "paired-offset",          # one box's shortfall equals another's excess
    "period-shift",           # the difference equals supplies belonging to an adjacent period
    "rate-misapplication",    # the difference equals base x (rate a - rate b)
    "recurrence",             # this taxpayer has been found with this cause before
    "historical-magnitude",   # the declaration is out of line with this taxpayer's own history
]

Status = Literal["confirmed", "refuted", "insufficient-evidence"]
Confidence = Literal["high", "medium", "low"]


class TestSpec(BaseModel):
    """A question the deterministic adjudicator can settle without judgement."""

    __test__ = False        # it is a spec, not a pytest case, despite the name

    kind: TestKind
    box: Literal["output", "input"] = "output"
    params: dict[str, Any] = Field(default_factory=dict)

    def describe(self) -> str:
        p = ", ".join(f"{k}={v}" for k, v in sorted(self.params.items()))
        return f"{self.kind}({self.box}{', ' + p if p else ''})"


class Hypothesis(BaseModel):
    """A proposed root cause. `claim` is language only — it must carry no figures."""

    id: str
    agent: str
    claim: str
    reason_code: str = ""
    test: TestSpec
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"


class Adjudication(BaseModel):
    """The engine's verdict. Every figure here was computed, never proposed."""

    hypothesis_id: str
    status: Status
    amount: float = 0.0            # SAR of the difference this accounts for
    detail: dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""          # engine-authored, so real digits are allowed


class Entry(BaseModel):
    """One typed line on the case file. Append-only; the order is the audit trail."""

    seq: int
    round: int
    kind: Literal["fact", "hypothesis", "adjudication", "objection", "conclusion"]
    agent: str
    payload: dict[str, Any]


class Investigation(BaseModel):
    case_id: str
    rounds: int
    entries: list[Entry]
    hypotheses: list[Hypothesis]
    adjudications: list[Adjudication]
    leading: str | None = None      # hypothesis id
    conclusion: str = ""
    unexplained: float = 0.0
    source: str = "deterministic"   # deterministic | claude | mixed
