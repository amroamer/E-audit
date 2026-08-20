"""Turn adjudicated hypotheses into findings worded the way the Authority words them.

This is the only bridge between the investigation and anything a taxpayer reads. A confirmed
hypothesis carries an `outcome_code`; the code resolves to a statement in `app.outcomes` that
the auditors supplied verbatim; the statement is what goes in the letter and the report. The
agent's own `claim` never appears in outbound correspondence — it is exploratory language
written to be tested, not a determination fit to be sent.

The amount always comes from the adjudication, never from the outcome and never from a model.

A confirmed hypothesis with no `outcome_code` is not a finding. The keying tests are the case in
point: a decimal slip explains a difference, it is not a defect the Authority states in these
terms. Those settle the investigation without ever becoming a line in a letter.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .. import outcomes as oc


@dataclass
class Finding:
    code: str
    statement: str            # the Authority's wording, verbatim from the vocabulary
    amount: float             # SAR at stake, computed by the adjudicator
    effect: str               # disallows-input | increases-output | documentation
    direction: str
    agent: str
    hypothesis_id: str
    basis: str = ""           # the evidence this rests on — see `exposure`
    why: str = ""             # what triggered the hypothesis
    explanation: str = ""     # the adjudicator's engine-authored account of the verdict
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"code": self.code, "statement": self.statement, "amount": self.amount,
                "effect": self.effect, "direction": self.direction, "agent": self.agent,
                "hypothesis_id": self.hypothesis_id, "basis": self.basis, "why": self.why,
                "explanation": self.explanation, "detail": self.detail}


def _basis(h, a) -> str:
    """What a finding rests on — the *evidence*, not the test that surfaced it.

    The adjudicator declares it, because only the adjudicator knows when one test's amount is
    another's. `trial-balance-absent` delegates to `listing-vs-declared` and returns its figure,
    so both must land on the same basis or the excess is assessed twice.

    Several outcomes can be true of the same evidence at once. A sales listing that exceeds the
    return supports "records submitted are higher than declared", "sales not disclosed", "the
    documents do not correspond" and — if no trial balance came — the no-trial-balance variant,
    all from a single `listing-vs-declared` test over a single file. They are four ways to
    characterise one excess, not four amounts, and adding them would multiply the same riyals by
    four in a letter to a taxpayer.
    """
    detail = getattr(a, "detail", None) or (a.get("detail") if isinstance(a, dict) else {}) or {}
    declared = detail.get("basis")
    if declared:
        return str(declared)
    test = getattr(h, "test", None)
    if test is None:
        return getattr(h, "id", "")
    doc = (test.params or {}).get("document", "")
    return f"{test.kind}|{test.box}|{doc}"


def from_investigation(hypotheses: list, adjudications: list) -> list[Finding]:
    """Every confirmed hypothesis that names an outcome, worded by the vocabulary.

    Ordered by what is at stake, because that is the order an auditor wants to read them in and
    the order they belong in a report.
    """
    verdicts = {a.hypothesis_id if hasattr(a, "hypothesis_id") else a["hypothesis_id"]: a
                for a in adjudications}
    out: list[Finding] = []
    for h in hypotheses:
        code = getattr(h, "outcome_code", "") or ""
        outcome = oc.BY_CODE.get(code)
        if not outcome:
            continue
        a = verdicts.get(getattr(h, "id", ""))
        if a is None:
            continue
        status = getattr(a, "status", None) or a.get("status")
        if status != "confirmed":
            continue
        amount = float(getattr(a, "amount", None) or (a.get("amount") if isinstance(a, dict) else 0) or 0.0)
        out.append(Finding(
            code=outcome.code, statement=outcome.statement, amount=round(amount, 2),
            effect=outcome.effect, direction=outcome.direction, agent=outcome.agent,
            hypothesis_id=getattr(h, "id", ""), basis=_basis(h, a),
            why=getattr(h, "why", ""),
            explanation=getattr(a, "explanation", None) or (a.get("explanation", "") if isinstance(a, dict) else ""),
            detail=getattr(a, "detail", None) or (a.get("detail", {}) if isinstance(a, dict) else {}),
        ))
    return sorted(out, key=lambda f: -abs(f.amount))


def _once_per_basis(findings: list[Finding], effect: str) -> float:
    """Sum an effect, counting each evidence basis only once.

    Findings that share a basis are alternative readings of the same money, so the total takes
    the largest of them rather than adding them up. Without this the same excess is assessed
    two or three times over, and the figure reaches a taxpayer letter.
    """
    largest: dict[str, float] = {}
    for f in findings:
        if f.effect != effect:
            continue
        key = f.basis or f.hypothesis_id
        largest[key] = max(largest.get(key, 0.0), f.amount)
    return round(sum(largest.values()), 2)


def exposure(findings: list[Finding]) -> dict:
    """What the findings come to, split by what they do to the assessment.

    Kept apart deliberately: output VAT understated and input VAT over-recovered are both
    revenue to the Authority but they are different adjustments, and a documentation defect is
    not an amount at all until someone decides what follows from it.
    """
    out = _once_per_basis(findings, oc.INCREASES_OUTPUT)
    inp = _once_per_basis(findings, oc.DISALLOWS_INPUT)

    # Documentation risk covers only evidence that is not already producing an adjustment. The
    # same excess can be read as "sales exceed the return" and as "the documents do not
    # correspond"; the first is assessed, and reporting the second as further money at risk
    # would show the auditor one difference as two problems.
    assessed = {f.basis or f.hypothesis_id for f in findings
                if f.effect in (oc.INCREASES_OUTPUT, oc.DISALLOWS_INPUT)}
    doc = _once_per_basis(
        [f for f in findings if (f.basis or f.hypothesis_id) not in assessed],
        oc.DOCUMENTATION)

    bases = {f.basis or f.hypothesis_id for f in findings}
    return {"increases_output": out, "disallows_input": inp,
            "documentation_at_risk": doc, "total": round(out + inp, 2),
            "count": len(findings), "distinct_bases": len(bases)}


def grouped_by_basis(findings: list[Finding]) -> list[dict]:
    """Findings clustered by the evidence they rest on, largest first.

    The auditor needs to see that four statements describe one excess — otherwise the list
    reads as four separate problems and the case looks worse than it is.
    """
    groups: dict[str, dict] = {}
    for f in findings:
        key = f.basis or f.hypothesis_id
        g = groups.setdefault(key, {"basis": key, "amount": 0.0, "findings": []})
        g["amount"] = max(g["amount"], f.amount)
        g["findings"].append(f.to_dict())
    return sorted(groups.values(), key=lambda g: -abs(g["amount"]))
