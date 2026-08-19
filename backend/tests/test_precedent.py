"""Guards for precedent retrieval and the planner.

Two properties carry the whole feature.

**The ranked list must be reproducible.** An auditor who sees a different set of comparable
cases on a second look has no reason to believe either. Retrieval is deterministic scoring over
structured fields precisely so this can be asserted.

**The tally must be arithmetic, not assertion.** Every percentage the agent quotes has to be a
count over the matches it actually retrieved — otherwise "57% closed with no finding" is just a
sentence, and the whole point was to replace sentences with a population.
"""
from sqlalchemy import select

from app.agents.precedent_analyst import brief
from app.models import AuditCase
from app.precedent import find_comparable, summarise
from app.precedent.index import compliance_band, score_band
from app.requests.catalog import ITEM_BY_KEY
from app.requests.planner import plan


# ------------------------------------------------------------------ retrieval
def test_the_ranked_list_is_stable_across_runs(seeded, case):
    a, _ = find_comparable(seeded, case)
    b, _ = find_comparable(seeded, case)
    assert [m.case.case_id for m in a] == [m.case.case_id for m in b]
    assert [m.score for m in a] == [m.score for m in b]


def test_matches_are_sorted_by_similarity(seeded, case):
    matches, _ = find_comparable(seeded, case)
    assert matches
    assert all(a.score >= b.score for a, b in zip(matches, matches[1:]))


def test_only_closed_cases_are_comparable(seeded, case):
    matches, _ = find_comparable(seeded, case)
    assert all(m.case.status == "closed" for m in matches)
    assert all(m.case.case_id != case.case_id for m in matches)


def test_the_indicator_is_the_hard_filter(seeded, case):
    matches, widened = find_comparable(seeded, case)
    if not widened:
        assert {m.case.case_reason_code for m in matches} == {case.case_reason_code}


def test_every_match_can_say_why_it_matched(seeded, case):
    matches, _ = find_comparable(seeded, case)
    for m in matches:
        if m.score > 0:
            assert m.reasons, f"{m.case.case_id} scored {m.score} with no stated reason"


def test_the_taxpayers_own_prior_case_ranks_top(seeded, case):
    """Same taxpayer, same sector, same size — nothing should out-rank it."""
    matches, _ = find_comparable(seeded, case)
    assert matches[0].case.case_id == "CASE-2024-0310"


# ------------------------------------------------------------------ the tally
def test_the_outcome_tally_counts_the_matches_it_retrieved(seeded, case):
    s = summarise(seeded, case)
    matches, _ = find_comparable(seeded, case, limit=s["limit"])
    assert s["comparable"] == len(matches)
    assert sum(o["count"] for o in s["outcomes"]) == len(matches)
    assert abs(sum(o["pct"] for o in s["outcomes"]) - 100.0) < 0.2


def test_root_causes_split_by_outcome(seeded, case):
    """A reason a case was explained is never also a reason one was assessed."""
    s = summarise(seeded, case)
    explained = {r["key"] for r in s["explained_by"]}
    matches, _ = find_comparable(seeded, case, limit=s["limit"])
    for m in matches:
        if m.case.root_cause_code in explained:
            assert m.case.audit_result_type == "NO_FINDING" or \
                   m.case.root_cause_code in {r["key"] for r in s["caused_by"]}


def test_decisive_can_never_exceed_requested(seeded, case):
    s = summarise(seeded, case)
    assert s["evidence"]
    for e in s["evidence"]:
        assert e["decisive"] <= e["requested"]
        assert 0.0 <= e["decisive_rate"] <= 100.0


def test_evidence_is_ranked_by_what_actually_closed_cases(seeded, case):
    s = summarise(seeded, case)
    counts = [e["decisive"] for e in s["evidence"]]
    assert counts == sorted(counts, reverse=True)


def test_recurrence_reports_the_taxpayers_own_history(seeded, case):
    s = summarise(seeded, case)
    assert s["recurrence"]["cases"] == 1
    assert s["recurrence"]["findings"] == 1
    assert s["recurrence"]["root_causes"] == ["OUT-01"]


def test_banding_is_coarse_and_total(seeded, case):
    tp = case.taxpayer
    assert compliance_band(tp) in ("clean", "minor", "poor")
    assert score_band(case.referral) in ("under", "over", "high", "unknown")
    assert score_band(None) == "unknown"


# ------------------------------------------------------------------ the agent
def test_the_agents_claims_state_no_figure(seeded):
    """Same rule as every other agent: it proposes language, the engine supplies numbers."""
    import re

    for c in seeded.scalars(select(AuditCase).where(AuditCase.status != "closed")).all():
        for h in brief(seeded, c).hypotheses:
            assert not re.search(r"\d", h.claim), f"{h.id} states a figure: {h.claim}"


def test_the_briefing_narrative_is_engine_authored_and_specific(seeded, case):
    b = brief(seeded, case)
    assert b.narrative
    joined = " ".join(b.narrative)
    assert "closed cases carry" in joined
    assert any(i["recommend"] for i in b.suggested_items)


# ------------------------------------------------------------------ the planner
def test_the_planner_never_asks_for_what_zatca_holds(seeded):
    """§1's rule, made mechanical: an item whose source is on file is dropped, with a reason."""
    for c in seeded.scalars(select(AuditCase).where(AuditCase.status != "closed")).all():
        p = plan(seeded, c)
        for planned in p.include:
            source = planned.item.satisfied_by
            assert source not in p.held, \
                f"{c.case_id} asks for {planned.item.key}, which ZATCA holds ({source})"


def test_dropped_items_always_carry_a_reason(seeded, case):
    p = plan(seeded, case)
    assert p.dropped
    assert all(d.reason for d in p.dropped)


def test_import_declarations_are_dropped_for_an_importer(seeded):
    """The clearest demonstration: customs data is held, so it is never requested."""
    c = next(x for x in seeded.scalars(
        select(AuditCase).where(AuditCase.case_id == "CASE-2025-0482")).all())
    p = plan(seeded, c)
    dropped = {d.item.key: d.reason for d in p.dropped}
    assert "customs-declarations" in dropped
    assert "Held by ZATCA" in dropped["customs-declarations"]


def test_the_plan_stays_targeted(seeded):
    from app.requests.planner import MAX_ITEMS

    for c in seeded.scalars(select(AuditCase).where(AuditCase.status != "closed")).all():
        assert len(plan(seeded, c).include) <= MAX_ITEMS


def test_planned_items_come_from_the_catalogue(seeded, case):
    for planned in plan(seeded, case).include:
        assert planned.item.key in ITEM_BY_KEY
        assert planned.rationale
