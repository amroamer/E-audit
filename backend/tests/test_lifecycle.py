"""Guards for the five-stage case machine and the closure letter.

The property that matters: the rail is *derived*, never stored. A status column can fall out
of step with the case it describes, and the auditor stops trusting the queue. Every assertion
here is really the same one — the stage states have to follow from the case's own data.

The second property is the product's headline claim. A case the internal evidence settles
should show that the taxpayer was never contacted, not a request the auditor does not need to
send. That is the minimise-contact principle from §1, and if the rail cannot express it the
claim is invisible.
"""
import re

from sqlalchemy import select

from app.agents.correspondence import draft_verdict, verdict_facts
from app.casefile import STAGES, status
from app.casefile.orchestrator import ACTIVE, DONE, PENDING, SKIPPED, WAITING
from app.llm.verify import verify_correspondence
from app.models import AuditCase
from app.recon_engine import reconcile_case
from app.requests import service as requests_service


def stages(s):
    return {st["key"]: st["state"] for st in s["stages"]}


# ------------------------------------------------------------------ shape
def test_every_case_reports_all_five_stages_in_order(seeded):
    for c in seeded.scalars(select(AuditCase).where(AuditCase.status != "closed")).all():
        s = status(seeded, c)
        assert [st["key"] for st in s["stages"]] == list(STAGES)


def test_the_current_stage_is_the_first_one_still_open(seeded):
    for c in seeded.scalars(select(AuditCase).where(AuditCase.status != "closed")).all():
        s = status(seeded, c)
        opens = [st for st in s["stages"] if st["state"] in (ACTIVE, WAITING)]
        if opens:
            assert s["current"] == opens[0]["key"]


def test_an_open_stage_always_says_what_happens_next(seeded):
    """A rail that says a case is stuck without saying on what is worse than no rail."""
    for c in seeded.scalars(select(AuditCase).where(AuditCase.status != "closed")).all():
        for st in status(seeded, c)["stages"]:
            if st["state"] in (ACTIVE, WAITING):
                assert st["next_action"], f"{c.case_id}/{st['key']} is open with no next action"


def test_intake_is_done_for_every_seeded_case(seeded):
    for c in seeded.scalars(select(AuditCase).where(AuditCase.status != "closed")).all():
        assert stages(status(seeded, c))["intake"] == DONE


# ------------------------------------------------------------------ the auto-clear claim
def test_a_case_the_evidence_settles_skips_the_taxpayer_entirely(seeded):
    """CASE-2025-0483 is credit notes: the return is right, and nobody needed to be asked."""
    c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0483"))
    s = status(seeded, c)
    assert s["no_contact_needed"]
    assert stages(s)["planning"] == SKIPPED
    assert stages(s)["correspondence"] == SKIPPED
    assert stages(s)["review"] == DONE
    assert s["current"] == "closure"


def test_the_government_timing_case_also_clears_without_contact(seeded):
    """The whole apparent gap is Etimad approval timing — a rule, not a request."""
    c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0488"))
    assert status(seeded, c)["no_contact_needed"]


def test_a_material_case_does_not_claim_it_needs_no_contact(seeded):
    c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0487"))
    s = status(seeded, c)
    assert not s["no_contact_needed"]
    assert stages(s)["planning"] == ACTIVE


# ------------------------------------------------------------------ the correspondence loop
def test_an_answered_round_with_gaps_puts_the_ball_back_with_the_auditor(seeded):
    """The hero case is seeded mid-loop: answered, but the response falls short."""
    c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0481"))
    s = status(seeded, c)
    corr = next(st for st in s["stages"] if st["key"] == "correspondence")
    assert corr["state"] == ACTIVE
    assert corr["owner"] == "auditor"
    assert corr["detail"]["blocking"] > 0


def test_an_issued_round_is_waiting_on_the_taxpayer(seeded):
    """Waiting is its own state: a case blocked on the taxpayer is slow, not stuck."""
    c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0485"))
    requests_service.open_request(seeded, c)
    req = requests_service.current_request(seeded, c.case_id)
    requests_service.issue(seeded, req)
    corr = next(st for st in status(seeded, c)["stages"] if st["key"] == "correspondence")
    assert corr["state"] == WAITING
    assert corr["owner"] == "taxpayer"
    seeded.rollback()


def test_the_review_is_provisional_until_the_evidence_is_complete(seeded):
    """It may open early — the reconciliation is internal — but it must not read as concluded."""
    c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0481"))
    review = next(st for st in status(seeded, c)["stages"] if st["key"] == "review")
    assert review["state"] == ACTIVE
    assert review["detail"].get("provisional") is True
    assert "do not conclude" in review["next_action"]


def test_closure_stays_shut_while_the_review_cannot_conclude(seeded):
    c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0487"))
    assert stages(status(seeded, c))["closure"] == PENDING


# ------------------------------------------------------------------ the verdict letter
def test_the_verdict_states_only_figures_the_engine_computed(seeded):
    """The same guard as the request letters, for the letter that states our position."""
    for cid in ("CASE-2025-0483", "CASE-2025-0487", "CASE-2025-0486"):
        c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == cid))
        recon = reconcile_case(seeded, cid, persist=False)
        facts = verdict_facts(c, c.taxpayer, recon)
        draft = draft_verdict(c, c.taxpayer, recon)
        assert draft["text"]
        assert verify_correspondence(draft["text"], facts)["ok"], draft["source"]


def test_a_supported_case_letter_proposes_nothing(seeded):
    c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0483"))
    recon = reconcile_case(seeded, c.case_id, persist=False)
    text = draft_verdict(c, c.taxpayer, recon)["text"]
    assert "no adjustment is proposed" in text.lower()
    assert not re.search(r"\bassessment\b", text, re.I)


def test_a_finding_letter_is_a_proposal_not_an_assessment(seeded):
    """Agents propose, the human decides — the letter must not pre-empt the decision."""
    c = seeded.scalar(select(AuditCase).where(AuditCase.case_id == "CASE-2025-0487"))
    recon = reconcile_case(seeded, c.case_id, persist=False)
    text = draft_verdict(c, c.taxpayer, recon)["text"]
    assert "proposed position and not an assessment" in text.lower()
