"""Building qualification lines from an uploaded listing rather than an e-invoice feed.

The property that matters is honesty about what a spreadsheet cannot say. A listing has no
clearance status and usually no delivery date, so the rules that depend on those must simply
not match — never be assumed satisfied, and never be papered over with a default that would
place supplies in a period the evidence says nothing about.
"""
from datetime import date

from app.pipeline import source
from app.pipeline.rules import RULES
from app.pipeline.run import compose, qualify

P_FROM, P_TO = date(2025, 1, 1), date(2025, 3, 31)

SALES = {
    "filename": "sales_listing.xlsx",
    "columns": ["invoice_date", "invoice_number", "customer_name", "taxable_amount",
                "vat_rate", "vat_amount"],
    "rows": [
        ["2025-01-10", "INV-001", "Acme", "100,000", 15, "15,000"],
        ["2025-02-04", "INV-002", "Beta", "200000", 15, "30000"],
        ["2025-03-19", "CN-001", "Acme", "-20,000", 15, "(3,000)"],
        ["2025-03-25", "INV-003", "Gamma", "", "", ""],          # unreadable: skipped
    ],
}


def lines(doc=SALES, direction="sale"):
    return source.lines_from_document(doc, direction=direction, period_from=P_FROM,
                                      period_to=P_TO)


# ------------------------------------------------------------------ line building
def test_rows_become_lines_at_the_grain_the_pipeline_qualifies():
    rows = lines()
    assert len(rows) == 3                       # the unreadable row is skipped, not zeroed
    r = rows[0]
    assert r["direction"] == "sale" and r["category"] == "S" and r["rate"] == 15
    assert r["tax_amount"] == 15000.0 and r["taxable_amount"] == 100000.0
    assert r["period_from"] == P_FROM and r["period_to"] == P_TO


def test_a_row_with_no_readable_vat_is_skipped_not_counted_as_zero():
    """A blank cell is a completeness problem, already reported. Summing it as nothing would
    quietly shrink the expected figure instead of surfacing the defect."""
    assert all(r["invoice_uuid"] != "INV-003" for r in lines())


def test_credit_notes_are_recognised_from_the_only_signals_a_listing_gives():
    note = next(r for r in lines() if r["invoice_uuid"] == "CN-001")
    assert note["type_code"] == source.CREDIT_NOTE
    assert note["tax_amount"] == -3000.0        # accounting parentheses read as negative


def test_a_negative_amount_alone_marks_a_note():
    doc = {**SALES, "rows": [["2025-01-10", "X-9", "Acme", "-1000", 15, "-150"]]}
    assert lines(doc)[0]["type_code"] == source.CREDIT_NOTE


def test_status_is_reported_never_cleared():
    """A listing is what the taxpayer says they issued. Claiming clearance would assert
    something the document does not evidence."""
    assert all(r["status"] == "reported" for r in lines())


def test_a_rate_written_as_a_fraction_is_the_same_rate():
    doc = {**SALES, "rows": [["2025-01-10", "INV-9", "Acme", "100000", 0.15, "15000"]]}
    assert lines(doc)[0]["rate"] == 15


def test_taxable_amount_is_derived_when_the_listing_omits_it():
    doc = {"filename": "s.xlsx", "columns": ["invoice_number", "vat_rate", "vat_amount"],
           "rows": [["INV-1", 15, "15000"]]}
    assert lines(doc)[0]["taxable_amount"] == 100000.0


def test_a_document_without_a_vat_column_yields_nothing():
    doc = {"filename": "notes.csv", "columns": ["invoice_number"], "rows": [["INV-1"]]}
    assert lines(doc) == []


# --------------------------------------------------------------- what it cannot say
def test_a_listing_without_delivery_dates_cannot_fire_the_timing_rule():
    """OUT-07 needs a delivery date. Absent one it must simply never match — the funnel then
    shows no timing step, which is the honest reading of the evidence."""
    rows = lines()
    enabled = {r.code for r in RULES if r.code}
    result = qualify(rows, enabled, "sale")
    comp = compose(result, enabled, "sale")
    assert not any(step["rule"] == "OUT-07" for step in comp.funnel)
    assert comp.counted == 3                     # everything qualifies; nothing is set aside


def test_a_listing_that_does_carry_delivery_dates_fires_it():
    doc = {
        "filename": "sales_listing.xlsx",
        "columns": ["invoice_date", "invoice_number", "delivery_date", "taxable_amount",
                    "vat_rate", "vat_amount"],
        "rows": [
            ["2025-03-20", "INV-001", "2025-03-25", "100000", 15, "15000"],
            ["2025-03-28", "INV-002", "2025-04-05", "200000", 15, "30000"],   # next period
        ],
    }
    enabled = {r.code for r in RULES if r.code}
    comp = compose(qualify(lines(doc), enabled, "sale"), enabled, "sale")
    step = next(s for s in comp.funnel if s["rule"] == "OUT-07")
    assert step["count"] == 1 and step["amount"] == 30000.0
    assert comp.counted == 1 and comp.expected_vat == 15000.0


def test_capability_states_what_the_document_supports():
    plain = source.capability(SALES["columns"])
    assert plain["has_delivery_date"] is False
    assert "nothing to act on" in plain["note"]

    rich = source.capability([*SALES["columns"], "delivery_date"])
    assert rich["has_delivery_date"] is True
    assert "can act" in rich["note"]


# -------------------------------------------------------------------- picking one
def test_the_listing_is_picked_by_name_first():
    sales = {"filename": "Sales_Analysis.xlsx", "columns": ["vat_amount"], "rows": []}
    purch = {"filename": "Purchase_Analysis.xlsx", "columns": ["vat_amount"], "rows": []}
    assert source.pick_listing([purch, sales], "sale") is sales
    assert source.pick_listing([purch, sales], "purchase") is purch


def test_the_listing_is_picked_by_shape_when_the_name_says_nothing():
    """A file with a supplier column is a purchase listing whatever it is called."""
    odd = {"filename": "annex_b.xlsx",
           "columns": ["invoice_number", "supplier_name", "vat_amount"], "rows": []}
    assert source.pick_listing([odd], "purchase") is odd
    assert source.pick_listing([odd], "sale") is None


def test_no_listing_means_no_rows_and_no_document():
    rows, doc = source.document_rows([], direction="sale", period_from=P_FROM, period_to=P_TO)
    assert rows == [] and doc is None


# ------------------------------------------------- the seam, on a seeded case
def test_an_uploaded_listing_becomes_the_population(seeded):
    """Planning is out of scope, so the taxpayer's listing IS the evidence under review."""
    from app.recon_engine import reconcile_case

    r = reconcile_case(seeded, "CASE-2025-0481", persist=False)
    assert r["population_source"] == "document"
    assert r["population_document"] == "Sales_Analysis_Q1_2025.xlsx"
    assert r["population_document"] in r["funnel"][0]["label"]


def test_a_case_with_no_upload_still_reconciles_from_the_e_invoice_feed(seeded):
    from app.recon_engine import reconcile_case

    r = reconcile_case(seeded, "CASE-2025-0484", persist=False)
    assert r["population_source"] == "e-invoice"
    assert "e-invoices on file" in r["funnel"][0]["label"]
    # the timing story survives: an e-invoice carries the delivery date a listing lacks
    assert any(s["rule"] == "OUT-07" for s in r["funnel"])


def test_a_figure_built_from_an_incomplete_response_is_flagged_as_a_floor(seeded):
    """A verdict resting on a listing the Authority has already called incomplete would
    state as its position a figure derived from evidence it rejected."""
    from app.recon_engine import reconcile_case

    r = reconcile_case(seeded, "CASE-2025-0481", persist=False)
    assert r["population_complete"] is False
    assert "floor" in r["population_caveat"]
    assert r["population_gaps"]


def test_no_caveat_when_the_population_is_the_e_invoice_feed(seeded):
    from app.recon_engine import reconcile_case

    r = reconcile_case(seeded, "CASE-2025-0484", persist=False)
    assert r["population_complete"] is True and r["population_caveat"] == ""
