"""The Precedent Analyst — what comparable cases turned out to be, and what closed them.

This is the agent that answers the auditors' fourth pain point: the knowledge of how a case
like this usually resolves currently lives in whichever auditor has seen enough of them.

It runs in **planning**, before any request goes out, because its most useful output is not a
verdict — it is *which evidence to ask for*. Knowing that on this indicator the sales analysis
closed half the comparable cases and the bank statements closed almost none is worth more at
the drafting stage than at the conclusion.

Two rules keep it honest:

* Every figure comes from `precedent.index.summarise()`, which counts and takes medians over
  labelled closed cases. The agent computes nothing itself.
* Its `Hypothesis` claims stay figure-free, like every other agent's. The one hypothesis it
  raises — that a taxpayer seen before may be here for the same reason — reuses the existing
  `recurrence` test rather than adding a parallel mechanism.

Prose in `narrative()` is engine-authored, so it may state digits; text a model writes about
this briefing may not, and is checked as usual.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ..models import AuditCase
from ..precedent import summarise
from ..requests.catalog import ITEM_BY_KEY
from .contracts import Hypothesis, TestSpec

PRECEDENT = "Precedent Analyst"

# below this many comparable cases the tally is not worth quoting as a rate
MIN_QUOTABLE = 8
# an item has to have closed at least this share of the cases it was requested in to lead
DECISIVE_FLOOR = 20.0


@dataclass
class Briefing:
    """The precedent read on a case: what happened before, and what to ask for now."""

    summary: dict
    narrative: list[str] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    suggested_items: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "agent": PRECEDENT,
            "summary": self.summary,
            "narrative": self.narrative,
            "hypotheses": [h.model_dump() for h in self.hypotheses],
            "suggested_items": self.suggested_items,
        }


def _pct(rows: list[dict], key: str) -> float | None:
    for r in rows:
        if r["key"] == key:
            return r["pct"]
    return None


def _narrative(s: dict) -> list[str]:
    """Engine-authored prose. Every figure here was counted, not proposed."""
    n = s["comparable"]
    if not n:
        return ["No closed case in the corpus is comparable to this one, so there is no "
                "precedent to draw on."]

    out: list[str] = []
    scope = (f"{n} closed cases carry the same risk indicator"
             if not s["widened"] else
             f"{n} closed cases carry a related risk indicator (too few shared this exact one, "
             f"so the search was widened)")
    out.append(f"{scope}: {s['indicator_label']}.")

    if n >= MIN_QUOTABLE:
        no_finding = _pct(s["outcomes"], "NO_FINDING")
        finding = _pct(s["outcomes"], "FINDING")
        if no_finding is not None and finding is not None:
            verdict = ("more often explained away than assessed" if no_finding > finding
                       else "more often assessed than explained away")
            out.append(f"They were {verdict}: {no_finding}% closed with no finding, "
                       f"{finding}% with one.")
        if s["explained_by"]:
            top = s["explained_by"][0]
            out.append(f"Where they were explained, the most common reason was {top['key']} "
                       f"({top['pct']}% of those cases).")
        if s["caused_by"]:
            top = s["caused_by"][0]
            out.append(f"Where a finding was raised, the most common root cause was "
                       f"{top['key']} ({top['pct']}% of those cases).")

    lead = next((e for e in s["evidence"] if e["decisive"] > 0), None)
    if lead:
        out.append(f"{lead['label']} was the evidence that closed the case most often — "
                   f"decisive in {lead['decisive']} of the {lead['requested']} cases it was "
                   f"requested in ({lead['decisive_rate']}%).")
    weak = [e for e in s["evidence"] if e["requested"] >= MIN_QUOTABLE
            and e["decisive_rate"] < 10.0]
    if weak:
        names = ", ".join(e["label"] for e in weak[:2])
        out.append(f"Asked for often but rarely decisive: {names}. Requesting it costs a round "
                   f"trip and usually settles nothing.")

    effort = s["effort"]
    if effort.get("median_rounds") is not None:
        out.append(f"Median effort was {effort['median_rounds']:g} rounds of correspondence and "
                   f"{effort['median_days_to_close']:g} days to close; "
                   f"{effort['single_round_pct']}% closed in a single round.")

    assessed = s["assessed"]
    if assessed.get("median"):
        out.append(f"Where an assessment was raised, the median was "
                   f"SAR {assessed['median']:,.0f}.")

    rec = s["recurrence"]
    if rec:
        if rec["findings"]:
            causes = ", ".join(rec["root_causes"])
            out.append(f"This taxpayer is itself in the comparable set: {rec['cases']} closed "
                       f"case(s), {rec['findings']} with a finding ({causes}).")
        else:
            out.append(f"This taxpayer is itself in the comparable set — {rec['cases']} closed "
                       f"case(s), none of which resulted in a finding.")
    return out


def _suggested(s: dict) -> list[dict]:
    """Request items ranked by how often they actually closed a comparable case."""
    out = []
    for e in s["evidence"]:
        item = ITEM_BY_KEY.get(e["key"])
        if item is None:
            continue
        out.append({
            "key": e["key"],
            "label": item.label,
            "kind": item.kind,
            "decisive_rate": e["decisive_rate"],
            "requested_in": e["requested"],
            "decisive_in": e["decisive"],
            "held_internally": item.satisfied_by,
            "recommend": (e["decisive_rate"] >= DECISIVE_FLOOR and not item.satisfied_by),
            "why": (f"held by ZATCA ({item.satisfied_by}) — do not request"
                    if item.satisfied_by else
                    f"closed {e['decisive_rate']}% of the comparable cases it was asked for in"),
        })
    return out


def brief(db: Session, case: AuditCase) -> Briefing:
    """The precedent read on one case."""
    s = summarise(db, case)
    hypotheses: list[Hypothesis] = []
    rec = s.get("recurrence")
    if rec and rec.get("findings"):
        hypotheses.append(Hypothesis(
            id="PR-01", agent=PRECEDENT, reason_code="R06", confidence="medium",
            claim="This taxpayer has closed with a finding on this indicator before, so the "
                  "earlier root cause is the first thing to rule out — if it applies again, the "
                  "resolution is already on file.",
            test=TestSpec(kind="recurrence", box="output"),
            evidence_refs=list(rec.get("case_ids", [])),
        ))
    return Briefing(summary=s, narrative=_narrative(s), hypotheses=hypotheses,
                    suggested_items=_suggested(s))
