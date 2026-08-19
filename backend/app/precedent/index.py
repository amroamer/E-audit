"""Find comparable closed cases, and tally what happened to them.

The auditors' fourth pain point: sector knowledge, regulatory interpretation and lessons learned
sit in individual auditors rather than anywhere the next auditor can reach. A new auditor picking
up a case cannot know that on this indicator, in this sector, four cases in five turn out to be
credit notes — or that the sales analysis closes them and the bank statements almost never do.

That is a retrieval problem over labelled closed cases, and this module is the retrieval.

**Deterministic scoring over structured fields, not an embedding search.** Two reasons. An
auditor has to be able to see *why* a case was called comparable, and a test has to be able to
assert a stable ranked list. Similarity is four named components that sum to 1.0, and every
comparison is reproducible.

Nothing here is a judgement. It counts, ranks and takes medians. What the tally *means* for the
case in hand is the auditor's call — and every figure the agent later quotes comes from here.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditCase, RiskReferral, Taxpayer
from ..requests.catalog import ITEM_BY_KEY
from ..risk_indicators import BY_CODE

# similarity weights — they sum to 1.0, and each one is nameable to an auditor
W_SECTOR_EXACT = 0.40
W_SECTOR_DIVISION = 0.22        # same ISIC division (first two digits)
W_SIZE_EXACT = 0.30
W_SIZE_ADJACENT = 0.15
W_COMPLIANCE = 0.15
W_SCORE_BAND = 0.15

SIZE_ORDER = ("micro", "small", "medium", "large")

MIN_COMPARABLE = 12             # below this we widen the indicator filter and say so
DEFAULT_LIMIT = 40


# --------------------------------------------------------------------------------- banding

def compliance_band(tp: Taxpayer) -> str:
    """clean / minor / poor — a coarse filing record, stable enough to match on."""
    c = tp.filing_compliance or {}
    late = int(c.get("filed_late", 0) or 0)
    missing = int(c.get("returns_due", 0) or 0) - int(c.get("returns_filed", 0) or 0)
    if missing > 0 or late >= 4:
        return "poor"
    if late >= 1:
        return "minor"
    return "clean"


def score_band(referral: RiskReferral | None) -> str:
    """How far past its threshold the engine pushed this case."""
    if referral is None or not referral.threshold:
        return "unknown"
    ratio = float(referral.score) / float(referral.threshold)
    if ratio >= 1.3:
        return "high"
    if ratio >= 1.0:
        return "over"
    return "under"


def _division(tp: Taxpayer) -> str:
    acts = tp.economic_activities or []
    primary = next((a for a in acts if a.get("primary")), acts[0] if acts else {})
    return str(primary.get("isic", ""))[:2]


# --------------------------------------------------------------------------------- similarity

@dataclass
class Match:
    case: AuditCase
    score: float
    reasons: list[str] = field(default_factory=list)


def _similarity(a: Taxpayer, a_band: str, a_score_band: str,
                b: Taxpayer, b_referral: RiskReferral | None) -> tuple[float, list[str]]:
    score, reasons = 0.0, []

    if a.ind_sector and a.ind_sector == b.ind_sector:
        score += W_SECTOR_EXACT
        reasons.append("same sector")
    elif _division(a) and _division(a) == _division(b):
        score += W_SECTOR_DIVISION
        reasons.append("same ISIC division")

    if a.business_size == b.business_size:
        score += W_SIZE_EXACT
        reasons.append("same size band")
    elif (a.business_size in SIZE_ORDER and b.business_size in SIZE_ORDER
          and abs(SIZE_ORDER.index(a.business_size) - SIZE_ORDER.index(b.business_size)) == 1):
        score += W_SIZE_ADJACENT
        reasons.append("adjacent size band")

    if a_band == compliance_band(b):
        score += W_COMPLIANCE
        reasons.append(f"{a_band} filing record")

    if a_score_band != "unknown" and a_score_band == score_band(b_referral):
        score += W_SCORE_BAND
        reasons.append("similar risk score")

    return round(score, 4), reasons


def find_comparable(db: Session, case: AuditCase, *,
                    limit: int = DEFAULT_LIMIT) -> tuple[list[Match], bool]:
    """Closed cases comparable to this one, best first. Returns (matches, widened)."""
    tp = db.get(Taxpayer, case.taxpayer_id)
    a_band = compliance_band(tp)
    a_score_band = score_band(case.referral)
    indicator = case.case_reason_code

    def cohort(codes: set[str]) -> list[AuditCase]:
        return list(db.scalars(
            select(AuditCase).where(AuditCase.status == "closed",
                                    AuditCase.case_id != case.case_id,
                                    AuditCase.case_reason_code.in_(codes))
            .order_by(AuditCase.case_id)
        ).all())

    rows = cohort({indicator})
    widened = False
    if len(rows) < MIN_COMPARABLE:
        # too thin to say anything: widen to indicators that turn on the same boxes, and be
        # explicit about having done so rather than quietly reporting a bigger number.
        ind = BY_CODE.get(indicator)
        focus = set(ind.focus) if ind else set()
        kin = {i.code for i in BY_CODE.values() if focus & set(i.focus)} or {indicator}
        rows = cohort(kin)
        widened = True

    matches: list[Match] = []
    for c in rows:
        other = db.get(Taxpayer, c.taxpayer_id)
        s, why = _similarity(tp, a_band, a_score_band, other, c.referral)
        matches.append(Match(case=c, score=s, reasons=why))

    # score first, case_id second — a stable order, so the ranked list is testable
    matches.sort(key=lambda m: (-m.score, m.case.case_id))
    return matches[:limit], widened


# --------------------------------------------------------------------------------- the tally

def _rank(counter: dict[str, int], total: int) -> list[dict]:
    return [
        {"key": k, "count": n, "pct": round(n / total * 100, 1) if total else 0.0}
        for k, n in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def summarise(db: Session, case: AuditCase, *, limit: int = DEFAULT_LIMIT) -> dict:
    """What comparable cases turned out to be, and what actually closed them."""
    matches, widened = find_comparable(db, case, limit=limit)
    n = len(matches)
    base = {
        "case_id": case.case_id,
        "indicator": case.case_reason_code,
        "indicator_label": (BY_CODE[case.case_reason_code].label
                            if case.case_reason_code in BY_CODE else case.case_reason_code),
        "comparable": n,
        "widened": widened,
        "limit": limit,
    }
    if not n:
        return {**base, "outcomes": [], "explained_by": [], "caused_by": [], "evidence": [],
                "effort": {}, "assessed": {}, "recurrence": None, "matches": []}

    outcomes: dict[str, int] = {}
    explained: dict[str, int] = {}
    caused: dict[str, int] = {}
    requested: dict[str, int] = {}
    decisive: dict[str, int] = {}
    rounds: list[int] = []
    days: list[int] = []
    assessed: list[float] = []

    for m in matches:
        c = m.case
        result = c.audit_result_type or "UNKNOWN"
        outcomes[result] = outcomes.get(result, 0) + 1
        if c.root_cause_code:
            bucket = explained if result == "NO_FINDING" else caused
            bucket[c.root_cause_code] = bucket.get(c.root_cause_code, 0) + 1
        ev = c.evidence_used or {}
        for k in ev.get("requested", []) or []:
            requested[k] = requested.get(k, 0) + 1
        for k in ev.get("decisive", []) or []:
            decisive[k] = decisive.get(k, 0) + 1
        if c.rounds_of_correspondence:
            rounds.append(int(c.rounds_of_correspondence))
        if c.days_to_close:
            days.append(int(c.days_to_close))
        if result == "FINDING" and c.diff_tax_amt:
            assessed.append(float(c.diff_tax_amt))

    evidence = [
        {
            "key": k,
            "label": ITEM_BY_KEY[k].label if k in ITEM_BY_KEY else k,
            "requested": cnt,
            "decisive": decisive.get(k, 0),
            "decisive_rate": round(decisive.get(k, 0) / cnt * 100, 1) if cnt else 0.0,
        }
        for k, cnt in requested.items()
    ]
    # rank by how often the item actually closed a case, not by how often it was asked for
    evidence.sort(key=lambda e: (-e["decisive"], -e["decisive_rate"], e["key"]))

    # has this taxpayer itself appeared in the cohort, and with what result?
    own = [m.case for m in matches if m.case.taxpayer_id == case.taxpayer_id]
    own_findings = [c for c in own if c.audit_result_type == "FINDING"]
    recurrence = None
    if own:
        recurrence = {
            "cases": len(own),
            "findings": len(own_findings),
            "root_causes": sorted({c.root_cause_code for c in own_findings if c.root_cause_code}),
            "case_ids": [c.case_id for c in own],
        }

    return {
        **base,
        "outcomes": _rank(outcomes, n),
        "explained_by": _rank(explained, sum(explained.values())),
        "caused_by": _rank(caused, sum(caused.values())),
        "evidence": evidence,
        "effort": {
            "median_rounds": statistics.median(rounds) if rounds else None,
            "max_rounds": max(rounds) if rounds else None,
            "median_days_to_close": statistics.median(days) if days else None,
            "single_round_pct": (round(sum(1 for r in rounds if r == 1) / len(rounds) * 100, 1)
                                 if rounds else None),
        },
        "assessed": {
            "findings": len(assessed),
            "median": round(statistics.median(assessed), 2) if assessed else None,
            "total": round(sum(assessed), 2) if assessed else 0.0,
        },
        "recurrence": recurrence,
        "matches": [
            {"case_id": m.case.case_id, "similarity": m.score, "reasons": m.reasons,
             "sector": db.get(Taxpayer, m.case.taxpayer_id).ind_sector,
             "size": db.get(Taxpayer, m.case.taxpayer_id).business_size,
             "result": m.case.audit_result_type, "root_cause": m.case.root_cause_code,
             "rounds": m.case.rounds_of_correspondence,
             "assessed": round(float(m.case.diff_tax_amt or 0), 2),
             "note": m.case.conclusion_note}
            for m in matches[:12]
        ],
    }
