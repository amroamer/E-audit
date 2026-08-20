"""The calculation agent end to end, against the seeded database.

`test_calculation.py` proves the arithmetic in isolation. These prove the part that touches the
case: that a figure the auditor records is checked against the documents actually on file, that
the verdict is written down with the query beside it, and that with no credentials the whole
thing still works because the auditor can specify the query themselves.
"""
import pytest

from app.agents import calc_service
from app.agents import calculation as calc
from app.models import AuditorCalculation, ReceivedDocument

CASE = "CASE-2025-0481"


@pytest.fixture()
def with_docs(seeded):
    """Put one known sales listing on the case, and take it away afterwards."""
    doc = ReceivedDocument(
        case_id=CASE, filename="sales_listing.xlsx", media_type="xlsx",
        content={
            "columns": ["invoice_date", "invoice_number", "taxable_amount", "vat_amount"],
            "rows": [
                ["2025-01-10", "INV-001", "100000", "15000"],
                ["2025-02-04", "INV-002", "200000", "30000"],
                ["2025-03-19", "INV-003", "50000", "7500"],
                ["2025-04-02", "INV-004", "80000", "12000"],
            ],
            "row_count": 4, "stated_totals": {},
        })
    seeded.add(doc)
    seeded.commit()
    yield seeded
    seeded.delete(doc)
    seeded.query(AuditorCalculation).filter(AuditorCalculation.case_id == CASE).delete()
    seeded.commit()


# ------------------------------------------------------------------------- ask
def test_ask_answers_from_the_uploaded_rows(with_docs):
    out = calc_service.ask(with_docs, CASE, "how many invoices",
                           spec={"op": "count", "document": "sales_listing.xlsx"})
    assert out["status"] == "ok" and out["answer"] == 4.0
    assert out["detail"]["document"] == "sales_listing.xlsx"


def test_ask_with_a_filter_the_auditor_specified(with_docs):
    out = calc_service.ask(with_docs, CASE, "", spec={
        "op": "sum", "column": "vat_amount", "document": "sales_listing.xlsx",
        "filters": [{"column": "invoice_date", "op": "between",
                     "value": ["2025-01-01", "2025-03-31"]}]})
    assert out["answer"] == 52500.0          # the April invoice is out of the period


def test_ask_without_documents_says_so(seeded):
    out = calc_service.ask(seeded, "CASE-2025-0488", "how many invoices",
                           spec={"op": "count"})
    assert out["status"] == calc.NOT_CHECKABLE
    assert "no documents" in out["note"].lower()


# ----------------------------------------------------------------------- check
def test_a_correct_figure_is_agreed_and_recorded(with_docs):
    out = calc_service.check(
        with_docs, CASE, label="Total output VAT on the listing",
        method="summed the VAT column", stated=64500.0,
        spec={"op": "sum", "column": "vat_amount", "document": "sales_listing.xlsx"})
    assert out["status"] == calc.AGREE and out["delta"] == 0.0
    assert out["query"] == "sum(vat_amount)"          # what was checked, not merely that it was

    rows = calc_service.listing(with_docs, CASE)
    assert len(rows) == 1 and rows[0]["label"].startswith("Total output VAT")


def test_a_wrong_figure_is_disagreed_with_the_delta_and_the_rows(with_docs):
    out = calc_service.check(
        with_docs, CASE, label="Q1 output VAT", method="summed VAT for the quarter",
        stated=60000.0,
        spec={"op": "sum", "column": "vat_amount", "document": "sales_listing.xlsx",
              "filters": [{"column": "invoice_date", "op": "between",
                           "value": ["2025-01-01", "2025-03-31"]}]})
    assert out["status"] == calc.DISAGREE
    assert out["computed"] == 52500.0 and out["delta"] == -7500.0
    assert "7,500" in out["explanation"] and "3 of 4 rows" in out["explanation"]
    assert calc_service.disagreements(with_docs, CASE)


def test_a_method_outside_the_algebra_is_recorded_as_not_checkable(with_docs):
    """Honest refusal beats a query that quietly answers a different question."""
    out = calc_service.check(
        with_docs, CASE, label="Margin", method="divided sales by purchases",
        stated=1.4, spec={"op": "ratio", "column": "taxable_amount",
                          "document": "sales_listing.xlsx"})
    assert out["status"] == calc.NOT_CHECKABLE and out["computed"] is None


def test_an_auditor_spec_is_never_sent_to_a_model(with_docs, monkeypatch):
    """If the auditor already said what to compute, there is nothing to interpret."""
    def boom(*a, **k):
        raise AssertionError("the model was called for an auditor-supplied query")

    monkeypatch.setattr(calc_service.llm, "parse_calculation", boom)
    out = calc_service.check(with_docs, CASE, label="Count", method="counted the rows",
                             stated=4.0,
                             spec={"op": "count", "document": "sales_listing.xlsx"})
    assert out["status"] == calc.AGREE and out["source"] == "auditor"


def test_calculations_are_numbered_per_case(with_docs):
    for i in range(3):
        calc_service.check(with_docs, CASE, label=f"Check {i}", method="counted",
                           stated=4.0,
                           spec={"op": "count", "document": "sales_listing.xlsx"})
    assert [c["seq"] for c in calc_service.listing(with_docs, CASE)] == [1, 2, 3]


# -------------------------------------------------------------- document choice
def test_an_unnamed_query_on_a_multi_document_case_asks_which(with_docs):
    """The seeded case already carries a response, so 'the document' is ambiguous.

    Answering off the largest table would let a question about sales be settled from the
    purchase listing — the exact error this agent exists to catch.
    """
    out = calc_service.ask(with_docs, CASE, "", spec={"op": "count"})
    assert out["status"] == calc.NOT_CHECKABLE
    assert "sales_listing.xlsx" in out["note"]
    assert "not clear which one" in out["note"]


def test_naming_a_document_that_is_not_there_is_refused_not_substituted(with_docs):
    out = calc_service.ask(with_docs, CASE, "",
                           spec={"op": "count", "document": "ghost.xlsx"})
    assert out["status"] == calc.NOT_CHECKABLE
    assert "ghost.xlsx" in out["note"] and "not among the documents" in out["note"]


def test_an_ambiguous_check_is_still_recorded_so_the_auditor_sees_it(with_docs):
    out = calc_service.check(with_docs, CASE, label="Ambiguous", method="counted rows",
                             stated=4.0, spec={"op": "count"})
    assert out["status"] == calc.NOT_CHECKABLE
    assert calc_service.listing(with_docs, CASE)[0]["status"] == calc.NOT_CHECKABLE
