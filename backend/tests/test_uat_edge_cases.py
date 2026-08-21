"""The awkward cases — the ones a sceptical stakeholder reaches for at a demo.

The SIT suite proves the agents work on well-formed material and the UAT walk proves the journey
holds together. This is the third question: what happens at the edges, where a wrong answer is
delivered confidently rather than refused?

Most of these assert a **silence** or a **refusal**. That is deliberate. Every one of them is a
place where the engine could produce a plausible-looking number that is wrong — a purchase
listing totalled into the sales box, a blank cell counted as zero, a taxpayer who over-declared
reported as having understated. A tool that is wrong in those places is worse than no tool,
because the auditor has no way to see it happening.
"""
from __future__ import annotations

import pytest

from app.agents import calc_language
from app.agents import calculation as calc
from app.agents.adjudicator import CaseContext, adjudicate
from app.agents import roster
from app.agents.findings import exposure, from_investigation
from tests.fixtures import vat_documents as vd

MATERIALITY = 10_000.0


def box(declared: float, unexplained: float = 0.0) -> dict:
    return {"declared": declared, "expected_vat": declared + unexplained,
            "expected_base": 0.0, "difference": unexplained, "evidence_total": 0.0,
            "unexplained": unexplained, "materiality": MATERIALITY,
            "band": "material" if abs(unexplained) > MATERIALITY else "immaterial",
            "state": "potential-finding" if unexplained > MATERIALITY else "supported",
            "funnel": [], "composition": [], "evidence": [], "evidence_invoices": [],
            "invoices_considered": 0, "population_lines": 0, "counted_lines": 0}


def ctx(*, sales_vat=2_000_000.0, purchase_vat=150_000.0, documents=(), activities=(),
        gaps=(), calculations=()) -> CaseContext:
    return CaseContext(recon={**box(sales_vat), "purchase": box(purchase_vat)},
                       documents=list(documents), cr_activities=list(activities),
                       gaps=list(gaps), calculations=list(calculations))


def codes(c: CaseContext) -> dict[str, float]:
    hyps = roster.propose(c)
    adjs = [adjudicate(h, c) for h in hyps]
    return {f.code: f.amount for f in from_investigation(hyps, adjs)}


def doc(filename: str, columns: list[str], rows: list[list], **extra) -> dict:
    return {"filename": filename, "columns": columns, "rows": rows,
            "row_count": len(rows), "stated_totals": {}, **extra}


# ============================================================ the taxpayer who over-declared
def test_a_listing_below_the_return_is_not_an_understatement():
    """Declaring more than the records show is not a finding in this vocabulary.

    It may be an overpayment worth a refund claim, or a listing that is itself incomplete. What
    it is not is "sales records higher than declared", and reporting it as one would put an
    assessment on a taxpayer who paid too much.
    """
    listing = vd.sales_listing(count=20, vat_each=15_000.0)      # SAR 300,000 against 2,000,000
    assert codes(ctx(sales_vat=2_000_000.0, documents=[listing])) == {}


def test_a_difference_exactly_at_materiality_is_not_a_finding():
    """The boundary is stated once and has to hold: material means *above* the threshold."""
    at = vd.sales_listing(count=1, vat_each=2_000_000.0 + MATERIALITY)
    assert codes(ctx(sales_vat=2_000_000.0, documents=[at])) == {}

    over = vd.sales_listing(count=1, vat_each=2_000_000.0 + MATERIALITY + 1)
    assert "SAL-HIGHER" in codes(ctx(sales_vat=2_000_000.0, documents=[over]))


# ==================================================================== the wrong document
def test_a_purchase_listing_is_never_totalled_into_the_sales_box():
    """The error the calculation agent exists to catch must not be one the engine makes."""
    purchases = vd.purchase_listing(count=10, vat_each=15_000.0)
    assert "SAL-HIGHER" not in codes(ctx(sales_vat=100_000.0, documents=[purchases]))


def test_a_trial_balance_is_not_read_as_a_sales_listing():
    """Its columns are debit and credit. Nothing in it is a VAT amount on an invoice."""
    tb = vd.trial_balance()
    assert "SAL-HIGHER" not in codes(ctx(sales_vat=100_000.0, documents=[tb]))


def test_a_credit_note_listing_is_not_totalled_as_sales():
    """Credit notes reduce output VAT. Adding them to it would move the figure the wrong way."""
    notes = vd.credit_note_listing(count=5, vat_each=6_000.0)     # positive, as a taxpayer may key
    assert "SAL-HIGHER" not in codes(ctx(sales_vat=100_000.0, documents=[notes]))


def test_an_empty_file_produces_no_finding():
    """A file with no rows is a completeness defect. It is not evidence of anything."""
    assert codes(ctx(sales_vat=2_000_000.0, documents=[doc("Empty.xlsx", [], [])])) == {}


# ================================================================== reading the cells
def test_the_conventions_a_taxpayer_spreadsheet_actually_uses():
    """Currency codes, thousands separators and accounting parentheses are not unreadable."""
    d = doc("Sales.xlsx", ["invoice_number", "vat_amount"],
            [["INV-1", "SAR 15,000.00"],       # currency code and separators
             ["INV-2", "(3,000.00)"],          # accounting negative — a credit
             ["INV-3", "15 000"],              # space as the separator
             ["INV-4", ""]])                   # nothing to read
    result = calc.run(calc.CalcQuery(op="sum", column="vat_amount", document="Sales.xlsx"), d)
    assert result.status == "ok"
    assert result.value == pytest.approx(27_000.0), "15,000 − 3,000 + 15,000, with the blank skipped"


def test_a_blank_cell_is_skipped_not_counted_as_zero_and_it_says_so():
    """Counting a blank as zero would quietly shrink the total and shrink an average further.

    The auditor is comparing against their own spreadsheet, so the narration has to say which
    rows carried nothing — otherwise "over all 4 rows" is misleading in a way they cannot see.
    """
    d = doc("Sales.xlsx", ["invoice_number", "vat_amount"],
            [["INV-1", 10_000.0], ["INV-2", 20_000.0], ["INV-3", ""]])
    q = calc.CalcQuery(op="average", column="vat_amount", document="Sales.xlsx")
    result = calc.run(q, d)
    assert result.value == pytest.approx(15_000.0), "the average divides by the rows with a value"
    assert result.readable == 2 and result.matched == 3

    v = calc.verify(15_000.0, q, d)
    assert v.status == calc.AGREE
    assert "skipped" in v.explanation, v.explanation


def test_a_column_that_is_not_there_is_refused_by_name():
    """"Insufficient evidence" beats a confident answer computed from nothing."""
    d = doc("Bank.xlsx", ["date", "narrative", "credit"], [["2025-01-05", "Deposit", 100_000.0]])
    result = calc.run(calc.CalcQuery(op="sum", column="vat_amount", document="Bank.xlsx"), d)
    assert result.status == calc.NOT_CHECKABLE
    assert "vat_amount" in result.note and "credit" in result.note, \
        "say which column is missing and what the file does have"


def test_a_query_outside_the_algebra_is_refused_rather_than_approximated():
    """A key the caller invents does not become a query — it becomes None."""
    assert calc.query_from_dict({"op": "median", "column": "vat_amount"}) is None
    assert calc.query_from_dict({"op": "sum"}) is not None      # valid shape, checked later
    ok, why = calc.CalcQuery(op="sum").valid()
    assert not ok and "column" in why


# ============================================================= reading the auditor's sentence
@pytest.mark.parametrize("sentence,expected", [
    ("I summed the VAT column and got 2,618,000", 2_618_000.0),
    ("total is SAR 1,200.50", 1_200.50),
    ("I make it 45,000", 45_000.0),
    ("the VAT comes to 618,000 for the quarter", 618_000.0),
])
def test_the_figure_is_read_out_of_the_sentence(sentence, expected):
    """The auditors write freely. Making them retype the figure into a box gets it ignored."""
    assert calc_language.stated_amount_in(sentence) == pytest.approx(expected)


def test_a_sentence_with_no_figure_says_so_rather_than_inventing_one():
    assert calc_language.stated_amount_in("I totalled the VAT column on the sales analysis") is None
    assert calc_language.stated_amount_in("") is None


@pytest.mark.parametrize("sentence,op,column", [
    ("I summed the VAT column on the sales analysis", "sum", "vat_amount"),
    ("total of the taxable amount", "sum", "taxable_amount"),
    ("how many invoices are there", "count", ""),      # a count is over rows, not a column
    ("how many distinct customers", "count_distinct", "customer_name"),
    ("the average VAT per invoice", "average", "vat_amount"),
    ("the largest VAT amount", "max", "vat_amount"),
])
def test_the_plain_methods_need_no_model(sentence, op, column):
    """Deterministic first: a total of a named column is a cue table, not judgement."""
    docs = [vd.sales_listing(count=3)]
    read = calc_language.read_method(sentence, docs)
    assert read["checkable"] is True, read["understood"]
    assert read["op"] == op
    assert read["column"] == column


@pytest.mark.parametrize("sentence", [
    "I summed the VAT column for January only",
    "total of the VAT column excluding the credit notes",
    "the total VAT on invoices over SAR 50,000",
    "total of the sales VAT per customer",
    "total VAT where the rate is 15",
    "sum of the VAT amount for invoices dated in March",
])
def test_a_method_carrying_a_condition_is_declined_not_flattened(sentence):
    """The most expensive possible failure: totalling the whole file and then calling the
    auditor's correct figure wrong. A clause it cannot express makes it decline outright."""
    read = calc_language.read_method(sentence, [vd.sales_listing(count=3)])
    assert read["checkable"] is False
    assert "condition" in read["understood"].lower(), read["understood"]


@pytest.mark.parametrize("sentence", [
    "please look at the sales file and tell me if it is fine",
    "the VAT on invoices over SAR 50,000",            # a condition, but no operation named
    "sales VAT per customer",
])
def test_a_sentence_with_no_recognisable_calculation_is_declined(sentence):
    """No operation named means no query. Guessing "they probably meant a total" is how a
    question about one thing gets answered with the total of another."""
    read = calc_language.read_method(sentence, [vd.sales_listing(count=3)])
    assert read["checkable"] is False


def test_a_column_the_document_does_not_have_is_never_named():
    """The cue table may suggest a column. It may not invent one."""
    bank = doc("Bank.xlsx", ["date", "narrative", "credit"], [["2025-01-05", "Deposit", 100.0]])
    read = calc_language.read_method("sum of the VAT column on the bank statement", [bank])
    assert read["checkable"] is False
    assert read["column"] == ""


def test_the_label_is_cut_at_a_word_and_not_mid_number():
    """A calculation the auditor did not name still goes in the case file under a readable name."""
    label = calc_language.label_for(
        "I summed the VAT column on the sales analysis and got 2,618,000 - can you check it?")
    assert label == "I summed the VAT column on the sales analysis"
    assert not label.endswith(" ")


def test_naming_no_document_among_several_asks_which_rather_than_guessing():
    """Answering a sales question off the purchase listing, silently, is the whole hazard."""
    docs = [vd.sales_listing(count=3), vd.purchase_listing(count=3)]
    read = calc_language.read_method("what is the total VAT amount", docs)
    assert read["document"] == "", "it must not pick one on the auditor's behalf"
    assert calc.pick_document(docs, read.get("document", "")) is None


# ======================================================================= arithmetic edges
def test_agreement_is_to_the_riyal_not_to_the_halala():
    """A taxpayer's sheet rounds per line; ours rounds once. One riyal is not a disagreement."""
    d = doc("Sales.xlsx", ["vat_amount"], [[10_000.40], [10_000.40], [10_000.40]])
    q = calc.CalcQuery(op="sum", column="vat_amount", document="Sales.xlsx")
    assert calc.verify(30_001.0, q, d).status == calc.AGREE
    assert calc.verify(30_500.0, q, d).status == calc.DISAGREE


def test_one_excess_stays_one_amount_however_many_statements_describe_it():
    """The regression that made `basis` exist, at its smallest."""
    listing = vd.sales_listing(count=20, vat_each=15_000.0)      # SAR 300,000
    c = ctx(sales_vat=100_000.0, documents=[listing])
    hyps = roster.propose(c)
    found = from_investigation(hyps, [adjudicate(h, c) for h in hyps])
    output = [f for f in found if f.effect == "increases-output"]
    assert len(output) > 1, "this excess should read more than one way"
    assert len({f.basis for f in output}) == 1, "and all of them rest on the same evidence"
    assert exposure(found)["increases_output"] == pytest.approx(200_000.0)


def test_two_genuinely_separate_documents_do_add_up():
    """The other half of the same rule — de-duplication must not become under-counting."""
    sales = vd.sales_listing(count=20, vat_each=15_000.0)
    purchases = vd.purchase_listing(count=3, vat_each=15_000.0, blocked_rows=(0, 1, 2))
    c = ctx(sales_vat=100_000.0, purchase_vat=150_000.0, documents=[sales, purchases])
    hyps = roster.propose(c)
    found = from_investigation(hyps, [adjudicate(h, c) for h in hyps])
    e = exposure(found)
    assert e["increases_output"] == pytest.approx(200_000.0)
    assert e["disallows_input"] > 0, "a blocked-input finding is a separate adjustment"
    assert e["total"] == pytest.approx(e["increases_output"] + e["disallows_input"])
