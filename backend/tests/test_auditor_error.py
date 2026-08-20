"""Guards for §7's second line of defence, and for scoping a rule to a counterparty.

The auditors named two error sources, not one. The taxpayer keying SAR 10,000 for SAR 1,000 was
already covered. The other is ours: an auditor totalling supplied documents by hand and
recording the wrong figure, which every later number then inherits silently.

The property that matters most here is that a confirmed recomputation must never be allowed to
*explain* the case. It carries an amount, so without care it would out-rank the real hypotheses
and close the case using our own transcription error as the answer.
"""
from datetime import date

from app.agents.adjudicator import CaseContext, adjudicate
from app.agents.contracts import Hypothesis, TestSpec
from app.agents.detectors import propose, recomputation
from app.agents.orchestrator import investigate
from app.pipeline.rules import RULES
from app.pipeline.run import compose, qualify

PERIOD_FROM, PERIOD_TO = date(2025, 1, 1), date(2025, 3, 31)
ALL_ON = {"COR-01", "COR-02", "OUT-07", "OUT-11", "INP-09"}


def recon(*, declared=52_000.0, expected=520_000.0, unexplained=468_000.0, materiality=1_000.0,
          state="potential-finding", input_unexplained=0.0):
    box = {"declared": declared, "expected_vat": expected, "expected_base": 3_466_666.67,
           "difference": round(expected - declared, 2), "evidence_total": 0.0, "evidence": [],
           "unexplained": unexplained, "materiality": materiality, "state": state,
           "funnel": [], "composition": [],
           "deferred_out": {"count": 0, "amount": 0.0}, "evidence_invoices": []}
    return {**box, "case_id": "CASE-TEST",
            "purchase": {**box, "declared": 45_000.0, "expected_vat": 45_000.0,
                         "difference": 0.0, "unexplained": input_unexplained,
                         "state": "potential-finding" if input_unexplained else "supported"}}


def line(tax, *, type_code=388, delivery=date(2025, 1, 10), category="S", rate=15,
         status="cleared", direction="sale", counterparty_class="", approval=None, sector=""):
    return {"type_code": type_code, "delivery_date": delivery, "issue_date": date(2025, 1, 10),
            "approval_date": approval, "counterparty_class": counterparty_class,
            "sector": sector, "category": category, "rate": rate, "status": status,
            "direction": direction, "tax_amount": float(tax),
            "taxable_amount": float(tax) / 0.15,
            "period_from": PERIOD_FROM, "period_to": PERIOD_TO, "invoice_uuid": f"INV-{tax}"}

DOC = {
    "id": 1, "filename": "Sales_Analysis_Q1_2025.xlsx",
    "columns": ["invoice_date", "invoice_number", "vat_amount"],
    "rows": [["2025-01-10", "INV-1", 400.0],
             ["2025-01-11", "INV-2", 300.0],
             ["2025-01-12", "INV-3", 300.0]],          # totals 1,000.00
}


def h(recorded, *, column="vat_amount", document_id=1):
    return Hypothesis(
        id="RC-01", agent="test", claim="language only",
        test=TestSpec(kind="recomputed-total", box="output",
                      params={"recorded": recorded, "column": column,
                              "document_id": document_id}))


def ctx(recorded=None, documents=None, **over):
    return CaseContext(recon=recon(**over), documents=documents or [DOC],
                       recorded=recorded or [])


# ------------------------------------------------------------------ the arithmetic
def test_a_wrong_recorded_total_is_confirmed_with_the_difference():
    """Ten invoices total SAR 1,000, the auditor recorded SAR 900 — their own example."""
    a = adjudicate(h(900.0), ctx())
    assert a.status == "confirmed"
    assert a.amount == 100.0
    assert a.detail["computed"] == 1_000.0
    assert a.detail["rows"] == 3


def test_a_correct_recorded_total_is_refuted():
    a = adjudicate(h(1_000.0), ctx())
    assert a.status == "refuted"
    assert a.amount == 0.0


def test_a_rounding_difference_is_not_a_finding():
    a = adjudicate(h(1_000.40), ctx())
    assert a.status == "refuted"


def test_numbers_written_as_text_still_add_up():
    doc = {**DOC, "rows": [["2025-01-10", "INV-1", "1,000.00"]]}
    a = adjudicate(h(1_000.0, document_id=1), ctx(documents=[{**doc, "id": 1}]))
    assert a.status == "refuted"


def test_a_missing_document_is_insufficient_evidence_not_a_finding():
    a = adjudicate(h(900.0, document_id=99), ctx())
    assert a.status == "insufficient-evidence"


def test_a_missing_column_is_insufficient_evidence_not_a_finding():
    a = adjudicate(h(900.0, column="gross_amount"), ctx())
    assert a.status == "insufficient-evidence"


# ------------------------------------------------------------------ the detector
def test_nothing_is_proposed_when_no_figure_was_keyed_by_hand():
    assert recomputation(ctx()) == []


def test_a_recorded_figure_with_its_source_on_file_is_proposed():
    c = ctx(recorded=[{"seq": 1, "label": "Sales ledger", "amount": 900.0,
                       "doc_name": DOC["filename"]}])
    hyps = recomputation(c)
    assert len(hyps) == 1
    assert hyps[0].test.kind == "recomputed-total"
    assert hyps[0].test.params["recorded"] == 900.0


def test_the_claim_states_no_figure():
    import re

    c = ctx(recorded=[{"seq": 1, "label": "Sales ledger", "amount": 900.0,
                       "doc_name": DOC["filename"]}])
    for hyp in propose(c):
        assert not re.search(r"\d", hyp.claim), f"{hyp.id} states a figure"


# ------------------------------------------------------------------ the orchestrator
def _recorded():
    return [{"seq": 1, "label": "Sales ledger", "amount": 900.0, "doc_name": DOC["filename"]}]


def test_our_own_error_never_becomes_the_explanation():
    """A confirmed recomputation carries an amount, but it explains nothing about the taxpayer."""
    inv = investigate(recon(), documents=[DOC], recorded=_recorded())
    leading = inv.leading
    assert leading is None or not leading.startswith("RC-")
    # and it is still reported — reported first, in fact
    assert "was recorded against this case" in inv.conclusion


def test_a_supported_case_is_not_waved_through_when_our_arithmetic_is_wrong():
    """A case that looks clean *because* a figure was transcribed wrongly is the dangerous one."""
    clean = dict(unexplained=0.0, state="supported")
    quiet = investigate(recon(**clean))
    assert quiet.rounds == 1                       # nothing to investigate, as before

    checked = investigate(recon(**clean), documents=[DOC], recorded=_recorded())
    assert checked.rounds == 5
    assert any(a.status == "confirmed" and a.hypothesis_id.startswith("RC-")
               for a in checked.adjudications)


def test_a_correct_transcription_leaves_a_supported_case_alone():
    ok = [{"seq": 1, "label": "Sales ledger", "amount": 1_000.0, "doc_name": DOC["filename"]}]
    inv = investigate(recon(unexplained=0.0, state="supported"), documents=[DOC], recorded=ok)
    assert not any(a.status == "confirmed" and a.hypothesis_id.startswith("RC-")
                   for a in inv.adjudications)


# ------------------------------------------------------------------ sector scoping
GOV = dict(counterparty_class="government")


def test_a_government_supply_awaiting_approval_leaves_the_period():
    rows = [line(75_000) for _ in range(20)]
    rows += [line(60_000, approval=date(2025, 5, 12), **GOV) for _ in range(6)]
    comp = compose(qualify(rows, ALL_ON, "sale"), ALL_ON, "sale")
    assert comp.expected_vat == 1_500_000.0
    step = next(g for g in comp.funnel if g["rule"] == "OUT-11")
    assert step["count"] == 6 and step["amount"] == 360_000.0
    assert step["verdict"] == "deferred-next"


def test_the_same_delay_on_a_commercial_customer_is_not_that_rule():
    """Scope is the whole point: without it the rule would defer supplies it has no business
    deferring, and the reconstruction would be wrong in the taxpayer's favour."""
    rows = [line(60_000, approval=date(2025, 5, 12)) for _ in range(6)]
    comp = compose(qualify(rows, ALL_ON, "sale"), ALL_ON, "sale")
    assert comp.expected_vat == 360_000.0
    assert not any(g["rule"] == "OUT-11" for g in comp.funnel)


def test_an_approved_government_supply_stays_in_the_period():
    rows = [line(60_000, approval=date(2025, 3, 5), **GOV) for _ in range(6)]
    comp = compose(qualify(rows, ALL_ON, "sale"), ALL_ON, "sale")
    assert comp.expected_vat == 360_000.0


def test_disabling_the_rule_brings_the_supplies_back():
    rows = [line(60_000, approval=date(2025, 5, 12), **GOV) for _ in range(6)]
    off = ALL_ON - {"OUT-11"}
    comp = compose(qualify(rows, off, "sale"), off, "sale")
    assert comp.expected_vat == 360_000.0


def test_the_scope_travels_with_the_rule_into_sql():
    rule = next(r for r in RULES if r.code == "OUT-11")
    assert rule.scoped
    assert "counterparty_class = 'government'" in rule.sql_when()
