"""The calculation agent answers the auditor's arithmetic and checks their own.

The property that matters most: the model parses, Python computes. These tests exercise the
Python half directly — if the arithmetic here is wrong, a wrong figure reaches an audit report
with the engine's authority behind it.
"""
from app.agents import calculation as calc

DOC = {
    "filename": "sales_analysis_Q1.xlsx",
    "columns": ["invoice_date", "invoice_number", "customer_name", "customer_vat_number",
                "taxable_amount", "vat_rate", "vat_amount"],
    "rows": [
        ["2025-01-10", "INV-001", "Acme Ltd", "300111111100003", "100,000.00", 15, "15,000.00"],
        ["2025-02-04", "INV-002", "Beta Co", "300222222200003", "200000", 15, "30000"],
        ["2025-03-19", "INV-003", "Acme Ltd", "300111111100003", "50,000", 15, "7,500"],
        ["2025-04-02", "INV-004", "Delta LLC", "", "80,000", 15, "12,000"],
        ["2025-03-28", "CN-001", "Beta Co", "300222222200003", "(20,000)", 15, "(3,000)"],
    ],
}


# ------------------------------------------------------------------- coercion
def test_reads_the_number_formats_taxpayers_actually_send():
    assert calc.as_number("15,000.00") == 15000.0
    assert calc.as_number("(3,000)") == -3000.0          # accounting negative
    assert calc.as_number("SAR 1 200") == 1200.0
    assert calc.as_number(" ") is None and calc.as_number("n/a") is None
    assert calc.as_number(True) is None                  # a bool is not an amount


# ------------------------------------------------------------------ execution
def test_sum_over_every_row():
    r = calc.run(calc.CalcQuery(op="sum", column="vat_amount"), DOC)
    assert r.status == "ok" and r.value == 61500.0       # 15000+30000+7500+12000-3000
    assert r.scanned == 5 and r.matched == 5


def test_sum_filtered_to_the_period():
    q = calc.CalcQuery(op="sum", column="vat_amount", filters=(
        calc.Filter("invoice_date", "between", ["2025-01-01", "2025-03-31"]),))
    r = calc.run(q, DOC)
    assert r.value == 49500.0                            # the April invoice drops out
    assert r.matched == 4 and r.scanned == 5


def test_count_and_count_distinct():
    assert calc.run(calc.CalcQuery(op="count"), DOC).value == 5.0
    r = calc.run(calc.CalcQuery(op="count_distinct", column="customer_name"), DOC)
    assert r.value == 3.0


def test_blankness_filter_finds_the_missing_vat_number():
    q = calc.CalcQuery(op="count", filters=(calc.Filter("customer_vat_number", "is_blank"),))
    assert calc.run(q, DOC).value == 1.0


def test_an_unknown_column_is_not_checkable_and_says_what_is_there():
    r = calc.run(calc.CalcQuery(op="sum", column="profit_margin"), DOC)
    assert r.status == calc.NOT_CHECKABLE
    assert "profit_margin" in r.note and "invoice_date" in r.note


def test_an_unknown_aggregation_is_refused():
    r = calc.run(calc.CalcQuery(op="median", column="vat_amount"), DOC)
    assert r.status == calc.NOT_CHECKABLE


def test_cited_rows_are_capped_and_carry_the_columns():
    r = calc.run(calc.CalcQuery(op="sum", column="vat_amount"), DOC)
    assert 0 < len(r.rows) <= calc.MAX_CITED_ROWS
    assert "invoice_number" in r.rows[0]


# --------------------------------------------------------------------- verify
def test_agrees_with_a_correct_auditor_figure():
    q = calc.CalcQuery(op="sum", column="vat_amount", filters=(
        calc.Filter("invoice_date", "between", ["2025-01-01", "2025-03-31"]),))
    v = calc.verify(49500.0, q, DOC)
    assert v.status == calc.AGREE and v.delta == 0.0
    assert "49,500" in v.explanation


def test_disagrees_and_quantifies_the_difference():
    """The auditor forgot the credit note: they get the delta and where to look."""
    q = calc.CalcQuery(op="sum", column="vat_amount", filters=(
        calc.Filter("invoice_date", "between", ["2025-01-01", "2025-03-31"]),))
    v = calc.verify(52500.0, q, DOC)
    assert v.status == calc.DISAGREE
    assert v.computed == 49500.0 and v.delta == -3000.0
    assert "3,000" in v.explanation and "4 of 5 rows" in v.explanation


def test_a_method_that_cannot_be_reproduced_says_so_rather_than_guessing():
    v = calc.verify(1000.0, calc.CalcQuery(op="sum", column="nope"), DOC)
    assert v.status == calc.NOT_CHECKABLE and v.computed is None


# ---------------------------------------------------------------- model parsing
def test_model_output_outside_the_algebra_is_dropped():
    assert calc.query_from_dict({"op": "exec", "column": "vat_amount"}) is None
    assert calc.query_from_dict({"op": "sum"}) is not None          # column checked at run time
    assert calc.query_from_dict("not a dict") is None


def test_invented_filter_ops_are_stripped_not_executed():
    q = calc.query_from_dict({"op": "sum", "column": "vat_amount", "filters": [
        {"column": "vat_amount", "op": "drop_table", "value": 1},
        {"column": "invoice_date", "op": "gte", "value": "2025-01-01"},
    ]})
    assert len(q.filters) == 1 and q.filters[0].op == "gte"


def test_document_is_picked_by_name():
    small = {"filename": "notes.csv", "columns": ["a"], "rows": [[1]]}
    docs = [small, DOC]
    assert calc.pick_document(docs, "sales_analysis_Q1.xlsx") is DOC
    assert calc.pick_document(docs, "sales") is DOC        # lenient contains-match
    assert calc.pick_document([DOC], "") is DOC            # only one candidate: unambiguous


def test_an_unnamed_document_on_a_multi_document_case_is_ambiguous():
    """Defaulting to the largest table would answer a sales question off the purchase
    listing. The caller must ask which, not guess."""
    docs = [{"filename": "notes.csv", "columns": ["a"], "rows": [[1]]}, DOC]
    assert calc.pick_document(docs, "") is None


def test_a_document_that_is_not_there_is_never_substituted():
    assert calc.pick_document([DOC], "ghost.xlsx") is None
