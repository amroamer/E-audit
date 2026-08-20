"""The four post-receipt agents, and the deterministic tests that settle them.

The contract these protect: an agent says what is worth testing and why, and never states a
figure or reaches a conclusion. Every amount in a verdict is computed in `document_tests.py`.
"""
import re

import pytest

from app.agents import roster
from app.agents.adjudicator import CaseContext, adjudicate
from app import outcomes as oc

BOX = {"declared": 1_000_000.0, "expected_vat": 1_000_000.0, "expected_base": 6_666_666.0,
       "difference": 0.0, "evidence_total": 0.0, "unexplained": 0.0, "materiality": 10_000.0,
       "band": "immaterial", "state": "supported", "funnel": [], "composition": [],
       "evidence": [], "evidence_invoices": [], "invoices_considered": 0,
       "population_lines": 0, "counted_lines": 0}
RECON = {**BOX, "purchase": {**BOX, "declared": 200_000.0, "expected_vat": 200_000.0}}

SALES = {
    "filename": "sales_listing.xlsx",
    "columns": ["invoice_date", "invoice_number", "customer_name", "description",
                "taxable_amount", "vat_amount"],
    "rows": [
        ["2025-01-10", "INV-001", "Acme", "wholesale foodstuff supply", "400000", "60000"],
        ["2025-02-04", "INV-002", "Beta", "wholesale foodstuff supply", "400000", "60000"],
        ["2025-03-19", "INV-003", "Gamma", "equipment leasing income", "200000", "30000"],
        ["2025-03-20", "", "Delta", "wholesale foodstuff supply", "100000", "15000"],
    ],
}
PURCHASES = {
    "filename": "purchase_listing.xlsx",
    "columns": ["invoice_date", "invoice_number", "supplier_name", "supplier_vat_number",
                "description", "taxable_amount", "vat_amount"],
    "rows": [
        ["2025-01-11", "P-001", "Supplier A", "300999999900003", "packaging materials",
         "100000", "15000"],
        ["2025-02-02", "P-002", "Supplier B", "", "staff entertainment dinner", "20000", "3000"],
        ["2025-03-03", "", "Supplier C", "300888888800003", "office rent", "50000", "7500"],
    ],
}
ACTIVITIES = [{"isic": "4630", "description": "Wholesale of food, beverages and tobacco",
               "primary": True}]


def ctx(**kw) -> CaseContext:
    return CaseContext(recon=kw.pop("recon", RECON), **kw)


def settle(hyps, c):
    return {h.id: adjudicate(h, c) for h in hyps}


# ================================================================ the contract
def test_no_agent_ever_states_a_figure():
    """The invariant the whole design rests on. A claim is language; the engine computes."""
    c = ctx(documents=[SALES, PURCHASES], cr_activities=ACTIVITIES,
            calculations=[{"status": "disagree", "label": "x", "delta": 5.0}],
            gaps=[{"kind": "missing-item", "item_label": "Trial balance"}])
    for h in roster.propose(c):
        assert not re.search(r"\d", h.claim), f"{h.id} states a figure in its claim"


def test_every_hypothesis_records_why_it_was_raised():
    c = ctx(documents=[SALES, PURCHASES], cr_activities=ACTIVITIES)
    for h in roster.propose(c):
        assert h.why, f"{h.id} does not say what triggered it"


def test_outcome_codes_are_real_vocabulary_entries():
    c = ctx(documents=[SALES, PURCHASES], cr_activities=ACTIVITIES,
            gaps=[{"kind": "missing-item", "item_label": "Trial balance"}])
    for h in roster.propose(c):
        if h.outcome_code:
            assert h.outcome_code in oc.BY_CODE, f"{h.id} names an unknown outcome"


def test_hypothesis_ids_are_unique_across_the_roster():
    c = ctx(documents=[SALES, PURCHASES], cr_activities=ACTIVITIES,
            gaps=[{"kind": "missing-item", "item_label": "TB"}],
            calculations=[{"status": "disagree", "label": "x", "delta": 5.0}])
    ids = [h.id for h in roster.propose(c)]
    assert len(ids) == len(set(ids))


def test_an_agent_with_nothing_to_work_on_proposes_nothing():
    """Silence beats a hypothesis that can only come back 'insufficient evidence'."""
    assert roster.regulations(ctx()) == []
    assert roster.evidence(ctx()) == []


# ================================================================ regulations
def test_invoice_conditions_finds_the_row_missing_its_number():
    c = ctx(documents=[SALES])
    h = next(x for x in roster.regulations(c) if x.test.kind == "invoice-conditions")
    a = adjudicate(h, c)
    assert a.status == "confirmed"
    assert a.detail["rows_failing"] == 1
    assert a.amount == 15000.0                       # the VAT on the defective row
    assert "invoice_number" in a.explanation


def test_invoice_conditions_refuted_when_every_row_is_complete():
    clean = {**SALES, "rows": SALES["rows"][:3]}
    c = ctx(documents=[clean])
    h = next(x for x in roster.regulations(c) if x.test.kind == "invoice-conditions")
    assert adjudicate(h, c).status == "refuted"


def test_blocked_input_flags_entertainment_for_review():
    c = ctx(documents=[PURCHASES])
    h = next(x for x in roster.regulations(c) if x.test.kind == "blocked-input")
    a = adjudicate(h, c)
    assert a.status == "confirmed" and a.amount == 3000.0
    assert "entertainment" in a.detail["terms"]
    assert "review" in a.explanation.lower()         # flagged, never concluded


def test_a_document_that_is_not_on_file_is_insufficient_evidence():
    c = ctx(documents=[SALES])
    h = next(x for x in roster.regulations(c) if x.test.kind == "invoice-conditions")
    h.test.params["document"] = "ghost.xlsx"
    assert adjudicate(h, c).status == "insufficient-evidence"


# =================================================================== evidence
def test_missing_support_finds_lines_with_no_invoice_or_supplier_id():
    c = ctx(documents=[PURCHASES])
    h = next(x for x in roster.evidence(c) if x.test.kind == "missing-support")
    a = adjudicate(h, c)
    assert a.status == "confirmed" and a.detail["rows_unsupported"] == 2
    assert a.amount == 10500.0                       # 3,000 + 7,500


def test_secondary_activity_needs_the_registration():
    c = ctx(documents=[SALES])
    assert not [x for x in roster.evidence(c) if x.test.kind == "secondary-activity"]

    c2 = ctx(documents=[SALES], cr_activities=ACTIVITIES)
    h = next(x for x in roster.evidence(c2) if x.test.kind == "secondary-activity")
    a = adjudicate(h, c2)
    assert a.status == "confirmed"
    assert a.detail["rows_outside"] == 1             # the equipment leasing line
    assert a.amount == 30000.0


def test_trial_balance_absent_needs_both_conditions():
    """A missing trial balance is only a finding when there is an excess to substantiate."""
    c = ctx(documents=[SALES])                       # listing totals 165,000 vs 1,000,000
    h = next(x for x in roster.evidence(c) if x.test.kind == "trial-balance-absent")
    a = adjudicate(h, c)
    assert a.status == "refuted" and "nothing to substantiate" in a.explanation


def test_trial_balance_absent_confirms_when_the_listing_exceeds_the_return():
    low = {**RECON, "declared": 10_000.0, "purchase": RECON["purchase"]}
    c = ctx(recon=low, documents=[SALES])
    h = next(x for x in roster.evidence(c) if x.test.kind == "trial-balance-absent")
    a = adjudicate(h, c)
    assert a.status == "confirmed" and a.amount == 155_000.0
    assert "No trial balance was supplied" in a.explanation


def test_a_supplied_trial_balance_refutes_it_outright():
    tb = {"filename": "trial_balance.xlsx", "columns": ["account_code"], "rows": [["4000"]]}
    low = {**RECON, "declared": 10_000.0, "purchase": RECON["purchase"]}
    c = ctx(recon=low, documents=[SALES, tb])
    assert not [x for x in roster.evidence(c) if x.test.kind == "trial-balance-absent"]


def test_non_cooperation_names_what_is_outstanding():
    c = ctx(documents=[SALES],
            gaps=[{"kind": "missing-item", "item_label": "Trial balance"},
                  {"kind": "missing-column", "item_label": "Sales analysis"}])
    h = next(x for x in roster.evidence(c) if x.test.kind == "non-cooperation")
    a = adjudicate(h, c)
    assert a.status == "confirmed" and a.detail["outstanding"] == 1   # only missing-item counts
    assert "Trial balance" in a.explanation


# ================================================================ calculation
def test_listing_vs_declared_confirms_an_excess():
    low = {**RECON, "declared": 10_000.0, "purchase": RECON["purchase"]}
    c = ctx(recon=low, documents=[SALES])
    h = next(x for x in roster.calculation(c) if x.id == "CA-01")
    a = adjudicate(h, c)
    assert a.status == "confirmed" and a.amount == 155_000.0
    assert a.detail["listing_total"] == 165_000.0


def test_listing_vs_declared_refutes_when_they_agree():
    agree = {**RECON, "declared": 165_000.0, "purchase": RECON["purchase"]}
    c = ctx(recon=agree, documents=[SALES])
    h = next(x for x in roster.calculation(c) if x.id == "CA-01")
    assert adjudicate(h, c).status == "refuted"


def test_auditor_figure_reports_the_largest_discrepancy():
    c = ctx(documents=[SALES], calculations=[
        {"status": "agree", "label": "ok", "stated": 1.0, "computed": 1.0, "delta": 0.0},
        {"status": "disagree", "label": "Q1 output VAT", "stated": 60000.0,
         "computed": 52500.0, "delta": -7500.0},
    ])
    h = next(x for x in roster.calculation(c) if x.test.kind == "auditor-figure")
    a = adjudicate(h, c)
    assert a.status == "confirmed" and a.amount == 7500.0
    assert "Q1 output VAT" in a.explanation


def test_auditor_figure_refuted_when_everything_reproduced():
    c = ctx(documents=[SALES],
            calculations=[{"status": "agree", "label": "ok", "delta": 0.0}])
    h = roster.calculation(c)
    assert not [x for x in h if x.test.kind == "auditor-figure"]


# ================================================== both rosters, run together
def test_ids_are_unique_across_BOTH_rosters():
    """The orchestrator runs the reconciliation detectors and the document agents together.

    Testing each roster alone missed a real collision: the old data_entry_forensics and the new
    Data Entry agent both emitted DE-01 and DE-02, which put duplicate hypotheses on the case
    file and duplicate keys in the UI. The combined set is what has to be unique.
    """
    from app.agents.detectors import propose as propose_recon
    from app.agents.roster import propose as propose_documents

    low = {**RECON, "declared": 10_000.0, "purchase": {**BOX, "declared": 10_000.0}}
    c = CaseContext(recon=low, documents=[SALES, PURCHASES], cr_activities=ACTIVITIES,
                    prior_returns=[{"vat_amount": 500_000.0}, {"vat_amount": 520_000.0}],
                    prior_cases=[{"case_id": "OLD", "root_cause_code": "OUT-01"}],
                    calculations=[{"status": "disagree", "label": "x", "delta": 5.0}],
                    gaps=[{"kind": "missing-item", "item_label": "TB"}])
    ids = [h.id for h in propose_recon(c) + propose_documents(c)]
    assert len(ids) == len(set(ids)), f"duplicate ids: {sorted({i for i in ids if ids.count(i) > 1})}"


def test_the_keying_specialist_is_not_run_twice():
    """One Data Entry agent, under the name the auditors gave it."""
    from app.agents.detectors import AGENTS as RECON_AGENTS

    assert all(a.__name__ != "data_entry_forensics" for a in RECON_AGENTS)


def test_retiring_the_old_agent_lost_no_test():
    """DE-03's historical-magnitude check moved across rather than disappearing."""
    off = {**RECON, "declared": 10_000.0, "unexplained": 155_000.0,
           "purchase": RECON["purchase"]}
    kinds = {h.test.kind for h in roster.data_entry(ctx(recon=off))}
    assert kinds == {"decimal-shift", "digit-transposition", "historical-magnitude"}


def test_the_keying_agent_stays_quiet_on_an_immaterial_difference():
    """Nothing was keyed wrong if nothing is out — proposing anyway wastes the auditor."""
    assert roster.data_entry(ctx()) == []
