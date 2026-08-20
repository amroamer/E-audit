"""The request spec is recovered from the auditor's own email, so these guards matter.

Everything downstream — what is missing, what to chase, whether the case can close — rests on
this parse. The two properties worth protecting are that it never invents a requirement, and
that nothing binds until the auditor has confirmed it.
"""
from datetime import date

from app.requests import from_email as fe

EMAIL = """
Dear Sir/Madam,

Further to our review of your VAT position for Q1 2025, please provide the following
within 20 working days:

1. A detailed sales analysis for the period, with the following columns: invoice date,
   invoice number, customer name, customer VAT number, description, taxable amount,
   VAT rate and VAT amount.
2. A detailed purchases analysis on which input VAT was claimed.
3. The trial balance as at 31 March 2025.
4. Copies of the tax invoices for the ten largest purchases.
5. Please also furnish a summary of your warehousing arrangements in Dammam.

Yours faithfully,
Zakat, Tax and Customs Authority
"""


def test_conventional_items_are_recovered_with_their_cue():
    p = fe.parse_email(EMAIL)
    keys = {i.key for i in p.items}
    assert {"sales-analysis", "purchase-analysis", "trial-balance", "invoice-copies"} <= keys
    # every match carries the phrase that produced it, so the auditor can check the parse
    for item in p.items:
        assert item.cue


def test_period_and_due_date_are_read():
    p = fe.parse_email(EMAIL)
    assert p.period_from == date(2025, 1, 1) and p.period_to == date(2025, 3, 31)
    assert "20" in p.due_phrase


def test_columns_written_out_in_the_email_win_over_the_catalog():
    """The auditor asked for those columns in writing — that is the requirement."""
    p = fe.parse_email(EMAIL)
    sales = next(i for i in p.items if i.key == "sales-analysis")
    assert "customer_vat_number" in sales.required_columns
    assert "invoice_date" in sales.required_columns


def test_unrecognised_asks_are_reported_not_guessed():
    p = fe.parse_email(EMAIL)
    assert any("warehousing" in u for u in p.unmatched)
    assert not any("warehous" in i.label.lower() for i in p.items)


def test_model_may_only_choose_catalog_keys():
    """A hallucinated key is dropped; the line stays unmatched for the auditor to see."""
    p = fe.parse_email(EMAIL)
    line = next(u for u in p.unmatched if "warehousing" in u)
    fe.apply_model_matches(p, {line: "not-a-real-item"})
    assert any("warehousing" in u for u in p.unmatched)
    assert all(i.key in {c["key"] for c in fe.catalog_choices()} for i in p.items)


def test_model_match_is_low_confidence_and_needs_the_auditor():
    p = fe.parse_email(EMAIL)
    line = next(u for u in p.unmatched if "warehousing" in u)
    fe.apply_model_matches(p, {line: "contracts"})
    added = next(i for i in p.items if i.key == "contracts")
    assert added.source == "model" and added.confidence == "low"


def test_nothing_binds_until_confirmed():
    p = fe.parse_email(EMAIL)
    assert p.to_dict()["needs_confirmation"] is True
    # the auditor keeps two and adds one; the rejected proposals do not survive
    spec = fe.confirm(p, keep=["sales-analysis", "trial-balance"], add=["pos-report"])
    assert {i.key for i in spec} == {"sales-analysis", "trial-balance", "pos-report"}
    assert next(i for i in spec if i.key == "pos-report").source == "auditor"


def test_empty_email_is_an_empty_proposal_not_a_crash():
    p = fe.parse_email("")
    assert p.items == [] and p.unmatched == []


def test_a_bare_mention_does_not_become_a_request():
    """'sales' appears in almost every audit email; only a real cue may match."""
    p = fe.parse_email("We have reviewed your sales position and will be in touch.")
    assert p.items == []


def test_letter_furniture_is_not_reported_as_an_unplaced_ask():
    """The auditor should review a short list of genuine leftovers, not their own salutation
    and sign-off. Exactly one ask in the sample cannot be placed."""
    p = fe.parse_email(EMAIL)
    assert len(p.unmatched) == 1
    assert "warehousing" in p.unmatched[0]
    joined = " ".join(p.unmatched).lower()
    assert "dear sir" not in joined and "yours faithfully" not in joined


def test_a_leadin_is_not_an_ask():
    p = fe.parse_email("Please provide the following documents within 20 days:")
    assert p.unmatched == []
