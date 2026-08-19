"""Decide what to ask the taxpayer for — and, just as importantly, what not to ask for.

The auditors were emphatic about the order of work: investigate what ZATCA already holds,
form hypotheses, identify the gaps, and only then request the specific things that are missing.
They were equally emphatic that they do not request information the Authority already has.

Leaving that second rule to memory is what makes it unreliable. Here it is mechanical: every
catalogue item names the internal source that would answer it, the dossier reports which sources
are actually held, and an item whose source is held is dropped — visibly, with the reason
attached, so the auditor can see the decision rather than trust it.

What survives is then ranked by *precedent*: how often this item actually closed a comparable
case. An item that gets requested every time and settles nothing costs a round trip, and a round
trip is measured in weeks.

Nothing here writes prose. It produces a plan of typed items; drafting the letter is a separate
step, and the numbers in the rationale are computed here rather than by any model.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..agents.precedent_analyst import brief
from ..dossier import collect, held_sources
from ..models import AuditCase
from ..risk_indicators import SOURCES
from .catalog import ITEM_BY_KEY, RequestItem, items_for_indicator

MAX_ITEMS = 5           # a targeted request; a long one gets a slow, partial answer
DECISIVE_FLOOR = 20.0   # % of comparable cases an item closed, to be worth a round trip


@dataclass
class PlannedItem:
    item: RequestItem
    include: bool
    reason: str                     # why included, or why dropped
    rationale: str = ""             # what we would do with it
    decisive_rate: float | None = None
    requested_in: int = 0
    hypothesis_id: str = ""

    def to_dict(self) -> dict:
        i = self.item
        return {
            "key": i.key, "label": i.label, "kind": i.kind, "description": i.description,
            "required_columns": list(i.required_columns),
            "mandatory_columns": list(i.mandatory_columns),
            "expected_format": i.expected_format,
            "addresses": list(i.addresses),
            "footed_by": list(i.footed_by),
            "include": self.include, "reason": self.reason, "rationale": self.rationale,
            "decisive_rate": self.decisive_rate, "requested_in": self.requested_in,
            "hypothesis_id": self.hypothesis_id,
        }


@dataclass
class RequestPlan:
    case_id: str
    indicator: str
    include: list[PlannedItem] = field(default_factory=list)
    dropped: list[PlannedItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    held: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "indicator": self.indicator,
            "held_internally": self.held,
            "items": [p.to_dict() for p in self.include],
            "dropped": [p.to_dict() for p in self.dropped],
            "notes": self.notes,
        }


def _hypothesis_for(item: RequestItem, hypotheses: list[dict]) -> str:
    """Link an item to an open hypothesis whose reason code it addresses."""
    for h in hypotheses:
        if h.get("reason_code") and h["reason_code"] in item.addresses:
            return h.get("id", "")
    return ""


def plan(db: Session, case: AuditCase, *, hypotheses: list[dict] | None = None) -> RequestPlan:
    """Build the request plan for a case from the dossier and precedent."""
    dossier = collect(db, case.case_id)
    held = held_sources(dossier)
    briefing = brief(db, case)
    precedent = {s["key"]: s for s in briefing.suggested_items}
    hyps = hypotheses or []

    indicator = case.case_reason_code
    # candidates: what an auditor opens with on this indicator, plus anything precedent says
    # actually closes cases of this kind
    candidate_keys: list[str] = [i.key for i in items_for_indicator(indicator)]
    for key, s in precedent.items():
        if key not in candidate_keys and s["decisive_rate"] >= DECISIVE_FLOOR:
            candidate_keys.append(key)

    include: list[PlannedItem] = []
    dropped: list[PlannedItem] = []
    for key in candidate_keys:
        item = ITEM_BY_KEY.get(key)
        if item is None:
            continue
        p = precedent.get(key, {})
        rate = p.get("decisive_rate")
        seen = p.get("requested_in", 0)

        # 1. ZATCA already holds it — never ask (§1)
        if item.satisfied_by and item.satisfied_by in held:
            block = dossier["blocks"].get(item.satisfied_by, {})
            count = block.get("count")
            detail = f" ({count} on file)" if count else ""
            dropped.append(PlannedItem(
                item=item, include=False,
                reason=f"Held by ZATCA — {SOURCES.get(item.satisfied_by, item.satisfied_by)}"
                       f"{detail}. Do not request.",
                decisive_rate=rate, requested_in=seen))
            continue

        # 2. precedent says it costs a round trip and settles nothing
        if rate is not None and seen >= 8 and rate < DECISIVE_FLOOR:
            dropped.append(PlannedItem(
                item=item, include=False,
                reason=f"Requested in {seen} comparable cases and decisive in "
                       f"{rate}% of them. Not worth a round trip on its own.",
                decisive_rate=rate, requested_in=seen))
            continue

        if rate is not None and seen:
            reason = (f"Decisive in {rate}% of the {seen} comparable cases it was requested in.")
        else:
            reason = "Standard opening request for this risk indicator."
        include.append(PlannedItem(
            item=item, include=True, reason=reason, decisive_rate=rate, requested_in=seen,
            hypothesis_id=_hypothesis_for(item, hyps),
            rationale=_rationale(item, case)))

    # best-evidence first; unranked items keep catalogue order behind the ranked ones
    include.sort(key=lambda p: (-(p.decisive_rate or -1), p.item.key))
    if len(include) > MAX_ITEMS:
        for p in include[MAX_ITEMS:]:
            p.include = False
            p.reason = (f"Held back to keep the request targeted — "
                        f"{MAX_ITEMS} items already cover the open questions.")
            dropped.append(p)
        include = include[:MAX_ITEMS]

    notes: list[str] = []
    held_labels = [SOURCES.get(h, h) for h in sorted(held)]
    if held_labels:
        notes.append("Consulted before drafting: " + ", ".join(held_labels) + ".")
    n_dropped_held = sum(1 for p in dropped if p.item.satisfied_by in held)
    if n_dropped_held:
        notes.append(f"{n_dropped_held} item(s) dropped because ZATCA already holds them.")
    if briefing.summary.get("comparable"):
        eff = briefing.summary.get("effort", {})
        if eff.get("median_rounds") is not None:
            notes.append(
                f"Comparable cases took a median of {eff['median_rounds']:g} rounds and "
                f"{eff['median_days_to_close']:g} days to close. Every avoidable item is a "
                f"round trip.")

    return RequestPlan(case_id=case.case_id, indicator=indicator, include=include,
                       dropped=dropped, notes=notes, held=sorted(held))


def _rationale(item: RequestItem, case: AuditCase) -> str:
    """What the auditor would do with this item once it arrives."""
    if item.kind == "analysis" and item.required_columns:
        n = len(item.required_columns)
        return (f"A {n}-column analysis for {case.period_from:%d %b %Y} to "
                f"{case.period_to:%d %b %Y}, one row per document, so the declared figure can be "
                f"traced to the underlying transactions.")
    if item.kind == "explanation":
        return ("A written explanation referring to specific transactions, so the difference can "
                "be tied to identifiable documents rather than described in general terms.")
    return (f"Supporting documentation covering {case.period_from:%d %b %Y} to "
            f"{case.period_to:%d %b %Y}.")
