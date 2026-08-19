"""Guards for the requested-versus-received check.

The property that matters: the deterministic layer must be strict about what is genuinely
missing and generous about what is merely named differently. Reporting a column absent because
the taxpayer called it "Invoice No." would be worse than missing the check entirely — it would
put a false accusation in an outbound letter.

No database and no model: the checker is a pure function over items and documents.
"""
from datetime import date
from types import SimpleNamespace

from app.requests.catalog import ITEM_BY_KEY, SALES_COLUMNS
from app.requests.completeness import BLOCKING, TOLERANCE, check
from app.requests.extract import display, extract, normalise
from app.seed import demo_files

PERIOD_FROM, PERIOD_TO = date(2025, 1, 1), date(2025, 3, 31)


def item(key="sales-analysis", *, id=1, status="outstanding", **over):
    c = ITEM_BY_KEY[key]
    fields = {
        "id": id, "label": c.label, "kind": c.kind, "status": status,
        "required_columns": list(c.required_columns),
        "mandatory_columns": list(c.mandatory_columns),
        "expected_format": c.expected_format, "footed_by": list(c.footed_by),
        "period_from": PERIOD_FROM, "period_to": PERIOD_TO,
    }
    fields.update(over)
    return SimpleNamespace(**fields)


def doc(*, id=1, item_id=1, columns=None, rows=None, totals=None, fmt="xlsx",
        period=(("2025-01-05"), ("2025-03-28")), filename="response.xlsx"):
    cols = [normalise(c) for c in (columns if columns is not None else SALES_COLUMNS)]
    return SimpleNamespace(
        id=id, request_item_id=item_id, filename=filename, file_format=fmt,
        content={"format": fmt, "columns": cols, "rows": rows or [],
                 "stated_totals": totals or {}, "raw_headers": list(columns or SALES_COLUMNS),
                 "period_from": period[0], "period_to": period[1], "note": ""},
    )


def run(items, docs):
    return check(case_id="CASE-TEST", round_=1, items=items, documents=docs,
                 period_from=PERIOD_FROM, period_to=PERIOD_TO)


def kinds(report):
    return sorted(g.kind for g in report.gaps)


# ------------------------------------------------------------------ nothing wrong
def test_a_complete_response_produces_no_gaps():
    rows = [["2025-01-10", "INV-1", "Buyer", "300000000000003", "Goods", 1000.0, "15%", 150.0],
            ["2025-03-28", "INV-2", "Buyer", "300000000000003", "Goods", 2000.0, "15%", 300.0]]
    r = run([item()], [doc(rows=rows, totals={"vat_amount": 450.0})])
    assert r.gaps == []
    assert r.complete


def test_the_gate_opens_only_when_nothing_blocking_remains():
    r = run([item()], [doc(rows=[], columns=SALES_COLUMNS)])
    assert not r.complete or not r.blocking


# ------------------------------------------------------------------ missing things
def test_missing_columns_are_reported_one_by_one():
    supplied = [c for c in SALES_COLUMNS if c not in ("customer_vat_number", "description")]
    r = run([item()], [doc(columns=supplied, rows=[["2025-01-10", "INV-1", "B", 1.0, "15%", 0.15]])])
    missing = [g for g in r.gaps if g.kind == "missing-column"]
    assert len(missing) == 2
    assert all(g.severity == BLOCKING for g in missing)


def test_an_item_with_nothing_against_it_is_a_missing_item():
    r = run([item(), item("credit-note-listing", id=2)], [doc(item_id=1, rows=[])])
    assert "missing-item" in kinds(r)
    gap = next(g for g in r.gaps if g.kind == "missing-item")
    assert gap.request_item_id == 2


def test_a_waived_item_is_not_chased():
    r = run([item(status="waived")], [])
    assert r.gaps == []


def test_an_unrequested_document_is_advisory_not_blocking():
    r = run([item()], [doc(rows=[["2025-01-10", "I", "B", "3", "G", 1.0, "15%", 0.15]]),
                       doc(id=2, item_id=None, filename="random.xlsx")])
    unreq = [g for g in r.gaps if g.kind == "unrequested-document"]
    assert len(unreq) == 1
    assert unreq[0].severity == "advisory"


# ------------------------------------------------------------------ blank mandatory fields
def test_blank_mandatory_fields_are_found_and_the_rows_cited():
    rows = [["2025-01-10", "INV-1", "B", "3", "G", 1000.0, "15%", 150.0],
            ["2025-01-11", "", "B", "3", "G", 1000.0, "15%", 150.0],
            ["2025-03-28", "   ", "B", "3", "G", 1000.0, "15%", 150.0]]
    r = run([item()], [doc(rows=rows, totals={"vat_amount": 450.0})])
    blanks = [g for g in r.gaps if g.kind == "empty-mandatory-field"]
    assert len(blanks) == 1
    assert "2 of 3 rows" in blanks[0].detail
    assert blanks[0].citation == "rows 2, 3"


def test_a_missing_column_is_not_also_reported_as_a_blank_field():
    supplied = [c for c in SALES_COLUMNS if c != "invoice_number"]
    rows = [["2025-01-10", "B", "3", "G", 1000.0, "15%", 150.0]]
    r = run([item()], [doc(columns=supplied, rows=rows, totals={"vat_amount": 150.0})])
    assert [g.kind for g in r.gaps].count("missing-column") == 1
    assert "empty-mandatory-field" not in kinds(r)


# ------------------------------------------------------------------ period coverage
def test_coverage_stopping_short_of_the_period_is_blocking():
    rows = [["2025-01-10", "INV-1", "B", "3", "G", 1000.0, "15%", 150.0]]
    r = run([item()], [doc(rows=rows, period=("2025-01-05", "2025-02-20"),
                           totals={"vat_amount": 150.0})])
    gap = next(g for g in r.gaps if g.kind == "wrong-period")
    assert gap.severity == BLOCKING
    assert "39 days" in gap.detail


def test_rows_before_the_period_are_only_advisory():
    rows = [["2024-12-01", "INV-1", "B", "3", "G", 1000.0, "15%", 150.0]]
    r = run([item()], [doc(rows=rows, period=("2024-12-01", "2025-03-30"),
                           totals={"vat_amount": 150.0})])
    gap = next(g for g in r.gaps if g.kind == "wrong-period")
    assert gap.severity == "advisory"


def test_a_day_or_two_short_is_not_worth_a_round_trip():
    rows = [["2025-01-10", "INV-1", "B", "3", "G", 1000.0, "15%", 150.0]]
    r = run([item()], [doc(rows=rows, period=("2025-01-01", "2025-03-30"),
                           totals={"vat_amount": 150.0})])
    assert "wrong-period" not in kinds(r)


# ------------------------------------------------------------------ arithmetic (taxpayer side)
def test_a_stated_total_that_does_not_foot_is_reported():
    rows = [["2025-01-10", "INV-1", "B", "3", "G", 1000.0, "15%", 150.0],
            ["2025-03-28", "INV-2", "B", "3", "G", 1000.0, "15%", 150.0]]
    r = run([item()], [doc(rows=rows, totals={"vat_amount": 400.0})])
    gap = next(g for g in r.gaps if g.kind == "arithmetic-mismatch")
    assert "100.00" in gap.detail


def test_a_total_within_tolerance_is_accepted():
    rows = [["2025-01-10", "INV-1", "B", "3", "G", 1000.0, "15%", 150.0]]
    r = run([item()], [doc(rows=rows, totals={"vat_amount": 150.0 + TOLERANCE / 2})])
    assert "arithmetic-mismatch" not in kinds(r)


def test_no_stated_total_means_nothing_to_disagree_with():
    rows = [["2025-01-10", "INV-1", "B", "3", "G", 1000.0, "15%", 150.0]]
    r = run([item()], [doc(rows=rows, totals={})])
    assert "arithmetic-mismatch" not in kinds(r)


# ------------------------------------------------------------------ wrong thing entirely
def test_a_document_answering_a_different_request_is_flagged():
    tb = ["account_code", "account_name", "debit", "credit"]
    r = run([item()], [doc(columns=tb, rows=[["4000", "Sales", 0.0, 100.0]])])
    gap = next(g for g in r.gaps if g.kind == "wrong-document")
    assert "trial balance" in gap.detail.lower()


def test_a_pdf_where_an_analysis_was_asked_for_is_blocking():
    d = doc(fmt="pdf", columns=[], rows=[], filename="scan.pdf")
    d.content = {"format": "pdf", "columns": [], "rows": [], "stated_totals": {},
                 "note": "Not a tabular format — structured checks cannot run on it."}
    r = run([item()], [d])
    gap = next(g for g in r.gaps if g.kind == "wrong-format")
    assert gap.severity == BLOCKING


# ------------------------------------------------------------------ naming generosity
def test_the_taxpayers_own_column_names_are_understood():
    """'Invoice No.' is the invoice number. Flagging it missing would be a false accusation."""
    assert normalise("Invoice No.") == "invoice_number"
    assert normalise("Net Amount") == "taxable_amount"
    assert normalise("Customer") == "customer_name"
    assert normalise("VAT") == "vat_amount"
    assert normalise(" Supplier VAT ") == "supplier_vat_number"


def test_gap_wording_uses_human_column_names():
    assert display("customer_vat_number") == "Customer VAT number"
    assert display("invoice_date") == "Invoice date"


# ------------------------------------------------------------------ the real file
def test_the_seeded_response_reproduces_the_demo_gaps_through_the_real_extractor():
    """End to end over an actual .xlsx: five defects, and no false positive on naming."""
    content = extract("Sales_Analysis_Q1_2025.xlsx", demo_files.sales_analysis_xlsx())
    assert content["row_count"] == demo_files.N_ROWS
    # the taxpayer's own spellings resolved, so these are NOT reported missing
    for col in ("invoice_date", "invoice_number", "customer_name",
                "taxable_amount", "vat_rate", "vat_amount"):
        assert col in content["columns"]

    d = SimpleNamespace(id=1, request_item_id=1, filename="Sales_Analysis_Q1_2025.xlsx",
                        file_format="xlsx", content=content)
    r = run([item()], [d])
    found = kinds(r)
    assert found.count("missing-column") == 2          # customer VAT number, description
    assert "empty-mandatory-field" in found
    assert "wrong-period" in found
    assert "arithmetic-mismatch" in found
    assert "wrong-document" not in found               # it IS a sales analysis
    assert len(r.blocking) == 5
