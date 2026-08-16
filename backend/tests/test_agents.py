"""Guards for the investigation layer.

The property that matters: an agent may propose, but only the adjudicator may conclude, and
only the adjudicator may state a figure. These tests run without a database or a model.
"""
import re

from app.agents.adjudicator import CaseContext, adjudicate
from app.agents.contracts import Hypothesis, TestSpec
from app.agents.detectors import propose
from app.agents.orchestrator import investigate


def recon(*, declared=52_000.0, expected=520_000.0, residual=468_000.0, materiality=1_000.0,
          state="potential-finding", input_residual=0.0, deferred=None, base=3_466_666.67,
          evidence=None):
    box = {
        "declared": declared, "expected_vat": expected, "expected_base": base,
        "residual": residual, "materiality": materiality, "state": state,
        "deferred_out": deferred or {"count": 0, "amount": 0.0},
        "evidence_invoices": evidence or [],
    }
    return {
        **box, "case_id": "CASE-TEST",
        "purchase": {**box, "declared": 45_000.0, "expected_vat": 45_000.0,
                     "residual": input_residual,
                     "state": "potential-finding" if input_residual else "supported"},
    }


# --------------------------------------------------------------- the adjudicator
def h(kind, **params):
    return Hypothesis(id="X-01", agent="test", claim="language only",
                      test=TestSpec(kind=kind, box="output", params=params))


def test_decimal_shift_confirms_the_manual_entry_case():
    a = adjudicate(h("decimal-shift"), CaseContext(recon=recon()))
    assert a.status == "confirmed"
    assert a.amount == 468_000.0
    assert a.detail["factor"] == 10


def test_decimal_shift_refutes_a_genuine_under_declaration():
    """Najd's shape: reconstruction far above the return, but not a power of ten."""
    a = adjudicate(h("decimal-shift"),
                   CaseContext(recon=recon(declared=1_000_000.0, expected=1_550_000.0,
                                           residual=550_000.0, materiality=5_000.0)))
    assert a.status == "refuted"
    assert a.amount == 0.0


def test_digit_transposition():
    ctx = CaseContext(recon=recon(declared=520_000.0, expected=250_000.0, residual=-270_000.0))
    assert adjudicate(h("digit-transposition"), ctx).status == "confirmed"
    ctx2 = CaseContext(recon=recon(declared=111_000.0, expected=520_000.0))
    assert adjudicate(h("digit-transposition"), ctx2).status == "refuted"


def test_period_shift_matches_the_deferred_supplies():
    ctx = CaseContext(recon=recon(residual=100_000.0,
                                  deferred={"count": 2, "amount": 100_000.0}))
    a = adjudicate(h("period-shift"), ctx)
    assert a.status == "confirmed" and a.amount == 100_000.0


def test_single_document():
    ctx = CaseContext(recon=recon(residual=61_000.0, evidence=[
        {"uuid": "INV-1", "tax_amount": 61_000.0, "issue_date": "2025-02-15"},
        {"uuid": "INV-2", "tax_amount": 119_000.0, "issue_date": "2025-01-10"}]))
    a = adjudicate(h("single-document"), ctx)
    assert a.status == "confirmed" and a.detail["uuid"] == "INV-1"


def test_paired_offset_needs_equal_and_opposite_boxes():
    ctx = CaseContext(recon=recon(residual=40_000.0, input_residual=-40_000.0))
    assert adjudicate(h("paired-offset"), ctx).status == "confirmed"
    assert adjudicate(h("paired-offset"), CaseContext(recon=recon())).status == "refuted"


def test_historical_magnitude_needs_enough_history():
    thin = CaseContext(recon=recon(), prior_returns=[{"vat_amount": 500_000.0}])
    assert adjudicate(h("historical-magnitude"), thin).status == "insufficient-evidence"

    rich = CaseContext(recon=recon(), prior_returns=[
        {"vat_amount": 498_000.0}, {"vat_amount": 515_000.0}, {"vat_amount": 527_000.0}])
    a = adjudicate(h("historical-magnitude"), rich)
    assert a.status == "confirmed" and a.detail["periods"] == 3


def test_unknown_test_is_insufficient_not_confirmed():
    bad = Hypothesis(id="X", agent="t", claim="c", test=TestSpec.model_construct(
        kind="not-a-test", box="output", params={}))
    assert adjudicate(bad, CaseContext(recon=recon())).status == "insufficient-evidence"


# --------------------------------------------------------------- the agents
def test_agents_never_state_a_figure():
    """The core invariant: a hypothesis is language only. Digits come from the adjudicator."""
    ctx = CaseContext(recon=recon(), prior_returns=[{"vat_amount": 1.0}] * 3,
                      prior_cases=[{"case_id": "C-1", "root_cause_code": "OUT-01"}])
    for hyp in propose(ctx):
        assert not re.search(r"\d", hyp.claim), f"{hyp.id} put a digit in its claim: {hyp.claim}"


def test_no_hypotheses_when_there_is_nothing_to_explain():
    ctx = CaseContext(recon=recon(residual=0.0, expected=52_000.0, state="supported"))
    assert propose(ctx) == []


# --------------------------------------------------------------- orchestration
def test_supported_case_is_not_investigated():
    inv = investigate(recon(residual=0.0, expected=52_000.0, state="supported"))
    assert inv.leading is None and inv.rounds == 1
    assert "no difference to investigate" in inv.conclusion.lower()


def test_manual_entry_case_is_led_by_the_forensics_agent():
    inv = investigate(recon(), prior_returns=[
        {"vat_amount": 498_000.0}, {"vat_amount": 515_000.0}, {"vat_amount": 527_000.0}])
    assert inv.leading == "DE-01"
    assert inv.unexplained == 0.0
    assert "decimal" in inv.conclusion.lower()


def test_zero_amount_findings_are_context_not_conclusions():
    """A recurrence or magnitude hit corroborates; it cannot be the explanation."""
    inv = investigate(recon(declared=1_000_000.0, expected=1_550_000.0, residual=550_000.0,
                            materiality=5_000.0),
                      prior_cases=[{"case_id": "C-1", "root_cause_code": "OUT-01"}])
    assert inv.leading is None                     # nothing explained the SAR figure
    assert inv.unexplained == 550_000.0
    assert "no tested pattern explains" in inv.conclusion.lower()
    assert "supporting context" in inv.conclusion.lower()


def test_case_file_is_ordered_and_typed():
    inv = investigate(recon())
    assert [e.seq for e in inv.entries] == list(range(1, len(inv.entries) + 1))
    kinds = {e.kind for e in inv.entries}
    assert {"fact", "hypothesis", "adjudication", "objection", "conclusion"} == kinds
    assert [e.round for e in inv.entries] == sorted(e.round for e in inv.entries)


def test_every_hypothesis_is_adjudicated():
    inv = investigate(recon())
    assert {a.hypothesis_id for a in inv.adjudications} == {x.id for x in inv.hypotheses}


def test_challenger_objects_when_the_leader_leaves_a_material_gap():
    """A partial explanation must not be allowed to look like a complete one."""
    inv = investigate(recon(residual=200_000.0, materiality=1_000.0,
                            deferred={"count": 2, "amount": 200_000.0}))
    objection = next(e for e in inv.entries if e.kind == "objection")
    assert objection.payload["against"] is not None
