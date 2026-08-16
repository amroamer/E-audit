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

Every line keeps its decision trail, which is what the bridge, the drill-downs and (next)
the investigation agents read.
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
    """The expected return, and the rule contributions that produced it.

    `base + Σ row.amount == expected_vat` by construction, so the bridge can never claim a
    movement the line-level decisions do not support.
    """
    base_vat: float
    base_lines: list[QualifiedLine]
    rows: list[dict]
    expected_vat: float
    expected_base: float
    counted: int
    population: int
    netted_lines: list[QualifiedLine]


def compose(lines: list[QualifiedLine], enabled: set[str], direction: str) -> Composition:
    pop = [l for l in lines if l.in_population]
    coded = [r for r in rules_in_order(direction) if not r.structural]

    # The baseline is the population minus the lines a netting rule owns (credit notes),
    # so it does not move when a rule is toggled — only the contributions do.
    netting = {r.code for r in coded if r.exclude_when_disabled}
    base_lines = [l for l in pop if not (l.matched & netting)]
    base_vat = round(sum(l.tax_amount for l in base_lines), 2)

    rows: list[dict] = []
    for rule in coded:
        owned = [l for l in pop if rule.code in l.matched]
        if not owned:
            continue
        live = rule.code in enabled
        if rule.exclude_when_disabled:
            # netting rule: its lines join the sum when live (they carry a negative amount)
            amount = round(sum(l.tax_amount for l in owned), 2) if live else 0.0
        else:
            # period/exclusion rule: it removes its lines from the sum when live
            amount = round(-sum(l.tax_amount for l in owned), 2) if live else 0.0
        if not live or abs(amount) <= 0.005:
            continue
        rows.append({
            "rule": rule.code, "stage": rule.stage, "reason_code": rule.reason_code,
            "verdict": "deferred-next" if rule.action is Action.DEFER_NEXT else "admitted",
            "label": rule.label, "note": rule.note,
            "amount": amount, "count": len(owned), "lines": owned,
        })

    counted = [l for l in lines if l.counted]
    return Composition(
        base_vat=base_vat, base_lines=base_lines, rows=rows,
        expected_vat=round(sum(l.tax_amount for l in counted), 2),
        expected_base=round(sum(l.taxable_amount for l in counted), 2),
        counted=len(counted), population=len(pop),
        netted_lines=[l for l in pop if l.matched & netting],
    )


def deferred(lines: list[QualifiedLine]) -> list[QualifiedLine]:
    """Lines that left this period — they must arrive in the next one."""
    return [l for l in lines if l.in_population and l.period == "next"]
