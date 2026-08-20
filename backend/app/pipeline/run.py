"""Run the qualification pipeline: lines in, decisions and an expected return out.

The order is the whole point. Every tax-subtotal line is walked through the stages in
`rule_taxonomy.STAGES` order, and each stage may admit, exclude or reassign it. Only the
lines that survive are summed. Nothing is summed and then adjusted.

Two phases, because they answer different questions:

1. **structural** — is this line part of the population for this box at all? (status,
   category). Not toggleable; a rejected document is not an explanation an auditor may
   switch off.
2. **coded** — the rule_library rules that decide period and netting. Toggling one in the
   Rulebook page changes the expected return.

Every line keeps its decision trail, which is what the funnel, the drill-downs and the
investigation agents read.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .rules import Action, BOX_BY_DIRECTION, QualificationRule, rules_in_order


@dataclass
class Decision:
    """One rule's verdict on one line."""
    stage: str
    rule_code: str          # "" for structural rules
    reason_code: str
    verdict: str            # admitted / excluded / deferred-next
    note: str
    label: str = ""


@dataclass
class QualifiedLine:
    row: dict
    in_population: bool = True        # survived the structural stages
    admitted: bool = True             # counts toward this period's expected return
    period: str = "current"           # current / next
    box: str = ""
    matched: set[str] = field(default_factory=set)   # coded rule codes that matched
    decisions: list[Decision] = field(default_factory=list)

    @property
    def tax_amount(self) -> float:
        return float(self.row["tax_amount"])

    @property
    def taxable_amount(self) -> float:
        return float(self.row["taxable_amount"])

    @property
    def counted(self) -> bool:
        return self.in_population and self.admitted and self.period == "current"


def _decide(rule: QualificationRule, verdict: str) -> Decision:
    return Decision(stage=rule.stage, rule_code=rule.code, reason_code=rule.reason_code,
                    verdict=verdict, note=rule.note, label=rule.label)


def qualify(rows: list[dict], enabled: set[str], direction: str) -> list[QualifiedLine]:
    """Walk every line through the stages. `enabled` = live rule_library codes."""
    ordered = rules_in_order(direction)
    structural = [r for r in ordered if r.structural]
    coded = [r for r in ordered if not r.structural]
    out: list[QualifiedLine] = []

    for row in rows:
        line = QualifiedLine(row=row, box=BOX_BY_DIRECTION.get(row["direction"], ""))

        # phase 1 — population boundary
        for rule in structural:
            if rule.matches(row):
                line.in_population = False
                line.admitted = False
                line.decisions.append(_decide(rule, "excluded"))
                break

        # phase 2 — coded rules, in stage order
        if line.in_population:
            for rule in coded:
                if not rule.matches(row):
                    continue
                line.matched.add(rule.code)
                live = rule.code in enabled
                if rule.action is Action.DEFER_NEXT and live:
                    line.period = "next"
                    line.decisions.append(_decide(rule, "deferred-next"))
                    break
                if rule.action is Action.EXCLUDE and live:
                    line.admitted = False
                    line.decisions.append(_decide(rule, "excluded"))
                    break
                if rule.action is Action.ADMIT:
                    if live:
                        line.decisions.append(_decide(rule, "admitted"))
                    elif rule.exclude_when_disabled:
                        line.admitted = False
                        line.decisions.append(_decide(rule, "excluded"))
                        break
        out.append(line)
    return out


# --------------------------------------------------------------------- composition
@dataclass
class Composition:
    """The expected return, and the narrowing that produced it.

    There is no "baseline" here, and deliberately so. A pre-qualification total would be a
    figure that corresponds to nothing: it would have to include documents the rules put in
    another period and exclude documents the rules admit, purely so a waterfall could be
    drawn from it. The rules decide *which lines are in this box for this period*; the sum
    follows. The only real quantities are the population it started from and the total it
    arrived at, and `funnel` is the audit trail between them.
    """
    expected_vat: float
    expected_base: float
    counted: int
    counted_lines: list[QualifiedLine]
    population: int
    population_lines: list[QualifiedLine]
    funnel: list[dict]         # ordered: how the population narrowed, and why
    composition: list[dict]    # what the qualifying set is made of, by document type


TYPE_LABEL = {388: "Tax invoices", 381: "Credit notes", 383: "Debit notes",
              386: "Prepayment invoices"}


def _terminal(line: QualifiedLine) -> Decision | None:
    """The decision that kept this line out — the last one that excluded or deferred it."""
    for d in reversed(line.decisions):
        if d.verdict in ("excluded", "deferred-next"):
            return d
    return None


def compose(lines: list[QualifiedLine], enabled: set[str], direction: str) -> Composition:
    """Sum what qualifies, and record how the population narrowed to it."""
    counted = [l for l in lines if l.counted]
    stage_rank = {s: i for i, s in enumerate(
        r.stage for r in rules_in_order(direction))}

    # group every line that did NOT qualify by the decision responsible for it
    groups: dict[tuple, dict] = {}
    for line in lines:
        if line.counted:
            continue
        d = _terminal(line)
        if d is None:                       # admitted but not counted — should not happen
            continue
        key = (d.stage, d.rule_code, d.verdict)
        g = groups.setdefault(key, {
            "stage": d.stage, "rule": d.rule_code or None, "verdict": d.verdict,
            "reason_code": d.reason_code,
            "label": d.label or d.note, "note": d.note,
            "count": 0, "amount": 0.0, "lines": [],
        })
        g["count"] += 1
        g["amount"] = round(g["amount"] + line.tax_amount, 2)
        g["lines"].append(line)

    funnel = sorted(groups.values(),
                    key=lambda g: (stage_rank.get(g["stage"], 99), g["rule"] or ""))

    # what the qualifying set is actually made of — invoices, credit notes, and so on
    by_type: dict[int, dict] = {}
    for line in counted:
        code = int(line.row["type_code"])
        c = by_type.setdefault(code, {
            "type_code": code, "label": TYPE_LABEL.get(code, f"Type {code}"),
            "count": 0, "amount": 0.0, "lines": [],
        })
        c["count"] += 1
        c["amount"] = round(c["amount"] + line.tax_amount, 2)
        c["lines"].append(line)
    composition = sorted(by_type.values(), key=lambda c: -abs(c["amount"]))

    return Composition(
        expected_vat=round(sum(l.tax_amount for l in counted), 2),
        expected_base=round(sum(l.taxable_amount for l in counted), 2),
        counted=len(counted), counted_lines=counted,
        population=len(lines), population_lines=list(lines),
        funnel=funnel, composition=composition,
    )


def deferred(lines: list[QualifiedLine]) -> list[QualifiedLine]:
    """Lines that left this period — they must arrive in the next one."""
    return [l for l in lines if l.in_population and l.period == "next"]
