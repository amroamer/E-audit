"""System integration tests: every agent, against the documents a VAT audit actually receives.

`test_roster.py` proves each check in isolation on a small fixture. This suite is the harder
question: given realistic Saudi VAT material — a return with the form's own boxes, sales and
purchase listings, credit notes, POS, bank statements, imports, exports, a trial balance —
does the right agent raise the right finding, and do the others stay quiet?

Two properties are tested throughout, and they matter more than any individual assertion:

* **No false positives.** An agent firing on a clean document is worse than one that misses,
  because the auditor stops trusting the panel. Every scenario asserts what must NOT be raised
  as well as what must.
* **Every figure is right.** The amounts are round on purpose. If an assertion fails, the
  logic is wrong — not the arithmetic in the fixture.
"""
import pytest

from app import outcomes as oc
from app.agents import roster
from app.agents.adjudicator import CaseContext, adjudicate
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


def ctx(*, sales_vat=2_000_000.0, purchase_vat=150_000.0, out_unexplained=0.0,
        in_unexplained=0.0, documents=(), activities=(), gaps=(), calculations=()) -> CaseContext:
    recon = {**box(sales_vat, out_unexplained),
             "purchase": box(purchase_vat, in_unexplained)}
    return CaseContext(recon=recon, documents=list(documents), cr_activities=list(activities),
                       gaps=list(gaps), calculations=list(calculations))


def settle(hyps, c):
    return {h.id: adjudicate(h, c) for h in hyps}


def findings_for(c):
    hyps = roster.propose(c)
    adjs = [adjudicate(h, c) for h in hyps]
    return from_investigation(hyps, adjs)


def codes(c) -> set[str]:
    return {f.code for f in findings_for(c)}


# =============================================================== the VAT return
def test_the_return_boxes_add_up_the_way_the_form_does():
    """If the fixture's own return is wrong, every comparison built on it is meaningless."""
    r = vd.vat_return(standard_sales_vat=2_000_000.0, standard_purchase_vat=150_000.0)
    assert r["total_output_vat"] == 2_000_000.0
    assert r["total_input_vat"] == 150_000.0
    assert r["net_vat_due"] == 1_850_000.0
    # the base is the VAT grossed back up at 15%
    assert r["boxes"]["standard_rated_sales"]["base"] == pytest.approx(13_333_333.33, abs=0.01)


def test_imports_and_corrections_move_the_net_the_way_the_form_does():
    r = vd.vat_return(standard_sales_vat=2_000_000.0, standard_purchase_vat=150_000.0,
                      imports_customs_vat=45_000.0, corrections=-5_000.0)
    assert r["total_input_vat"] == 195_000.0
    assert r["net_vat_due"] == 2_000_000.0 - 195_000.0 - 5_000.0


# ================================================== 1 · REGULATIONS AGENT
class TestRegulationsAgent:
    def test_every_tax_invoice_condition_is_caught(self):
        """One row per condition, each broken in turn. All five must be found."""
        c = ctx(documents=[vd.defective_tax_invoices()])
        h = next(x for x in roster.regulations(c) if x.test.kind == "invoice-conditions")
        a = adjudicate(h, c)
        assert a.status == "confirmed"
        assert a.detail["rows_failing"] == 5          # the complete row is left alone
        assert a.detail["rows_tested"] == 6
        broken = {m for ex in a.detail["examples"] for m in ex["missing"]}
        assert {"invoice_date", "invoice_number", "customer_name",
                "taxable_amount", "vat_amount"} <= broken

    def test_a_clean_sales_listing_raises_nothing(self):
        c = ctx(documents=[vd.sales_listing()])
        h = next(x for x in roster.regulations(c) if x.test.kind == "invoice-conditions")
        assert adjudicate(h, c).status == "refuted"

    def test_blocked_input_categories_are_flagged_with_the_right_amount(self):
        doc = vd.purchase_listing(count=10, vat_each=15_000.0, blocked_rows=(1, 3, 5))
        c = ctx(documents=[doc])
        h = next(x for x in roster.regulations(c) if x.test.kind == "blocked-input")
        a = adjudicate(h, c)
        assert a.status == "confirmed"
        assert a.detail["rows_matched"] == 3
        assert a.amount == 45_000.0                   # 3 x 15,000
        assert "review" in a.explanation.lower()      # flagged, never concluded

    def test_an_ordinary_purchase_ledger_is_not_flagged_as_blocked(self):
        c = ctx(documents=[vd.purchase_listing(count=10)])
        h = next(x for x in roster.regulations(c) if x.test.kind == "blocked-input")
        assert adjudicate(h, c).status == "refuted"

    def test_a_credit_note_with_no_reference_fails_its_conditions(self):
        doc = vd.credit_note_listing(count=5, missing_original_ref_rows=(0, 2))
        c = ctx(documents=[doc])
        h = next(x for x in roster.regulations(c) if x.test.kind == "credit-note-conditions")
        a = adjudicate(h, c)
        assert a.status == "confirmed" and a.detail["rows_failing"] == 2
        assert a.amount == -12_000.0                  # notes carry negative VAT

    def test_valid_credit_notes_are_left_alone(self):
        c = ctx(documents=[vd.credit_note_listing(count=5)])
        h = next(x for x in roster.regulations(c) if x.test.kind == "credit-note-conditions")
        assert adjudicate(h, c).status == "refuted"

    def test_a_note_listing_missing_the_reference_column_entirely_is_still_a_finding(self):
        """The column is not there at all — the condition cannot be evidenced from the file."""
        doc = vd.credit_note_listing(count=5, missing_columns=("original_invoice_number",))
        c = ctx(documents=[doc])
        h = next(x for x in roster.regulations(c) if x.test.kind == "credit-note-conditions")
        a = adjudicate(h, c)
        assert a.status == "confirmed"
        assert "original_invoice_number" in a.detail["columns_absent"]


# ==================================================== 2 · DATA ENTRY AGENT
class TestDataEntryAgent:
    def test_a_decimal_slip_is_identified_rather_than_treated_as_evasion(self):
        """The audit team's own example: SAR 10,000 keyed where the records say 1,000."""
        c = ctx(sales_vat=200_000.0, out_unexplained=1_800_000.0)   # expected 2,000,000
        h = next(x for x in roster.data_entry(c) if x.test.kind == "decimal-shift")
        a = adjudicate(h, c)
        assert a.status == "confirmed"
        assert a.detail["factor"] == 10
        assert "decimal point" in a.explanation

    def test_a_transposition_is_identified(self):
        # declared 1,900,000 against expected 9,100,000 — same digits, different order
        c = ctx(sales_vat=1_900_000.0, out_unexplained=7_200_000.0)
        h = next(x for x in roster.data_entry(c) if x.test.kind == "digit-transposition")
        assert adjudicate(h, c).status == "confirmed"

    def test_an_ordinary_difference_is_not_blamed_on_keying(self):
        c = ctx(sales_vat=2_000_000.0, out_unexplained=618_000.0)
        verdicts = settle(roster.data_entry(c), c)
        assert verdicts["DE-01"].status == "refuted"
        assert verdicts["DE-02"].status == "refuted"

    def test_the_agent_stays_silent_when_nothing_is_out(self):
        assert roster.data_entry(ctx()) == []

    def test_a_keying_finding_never_becomes_a_letter_line(self):
        """A decimal slip explains a difference; it is not something the Authority states."""
        c = ctx(sales_vat=200_000.0, out_unexplained=1_800_000.0)
        assert not any(f.code for f in findings_for(c) if f.hypothesis_id.startswith("DE-"))


# =================================================== 3 · CALCULATION AGENT
class TestCalculationAgent:
    def test_a_listing_above_the_return_is_found_with_the_right_excess(self):
        doc = vd.sales_listing(count=20, vat_each=130_900.0)     # totals 2,618,000
        c = ctx(sales_vat=2_000_000.0, documents=[doc])
        h = next(x for x in roster.calculation(c) if x.id == "CA-01")
        a = adjudicate(h, c)
        assert a.status == "confirmed"
        assert a.detail["listing_total"] == 2_618_000.0
        assert a.amount == 618_000.0

    def test_a_listing_that_agrees_with_the_return_raises_nothing(self):
        doc = vd.sales_listing(count=20, vat_each=100_000.0)      # totals 2,000,000
        c = ctx(sales_vat=2_000_000.0, documents=[doc])
        assert adjudicate(next(x for x in roster.calculation(c) if x.id == "CA-01"),
                         c).status == "refuted"

    def test_a_listing_below_the_return_is_not_an_understatement(self):
        doc = vd.sales_listing(count=10, vat_each=100_000.0)      # totals 1,000,000
        c = ctx(sales_vat=2_000_000.0, documents=[doc])
        a = adjudicate(next(x for x in roster.calculation(c) if x.id == "CA-01"), c)
        assert a.status == "refuted"
        assert "not understated" in a.explanation

    def test_pos_takings_above_the_declared_box_are_found(self):
        """A quarter of POS at 40,250 gross/day carries 5,250 VAT/day = 472,500."""
        pos = vd.pos_report(days=90, gross_per_day=40_250.0)
        c = ctx(sales_vat=300_000.0, documents=[pos])
        h = next(x for x in roster.calculation(c) if x.id == "CA-03")
        a = adjudicate(h, c)
        assert a.status == "confirmed"
        assert a.detail["listing_total"] == pytest.approx(472_500.0, abs=1.0)
        assert a.amount == pytest.approx(172_500.0, abs=1.0)

    def test_a_bank_statement_has_no_vat_to_total_and_says_so(self):
        """It is evidence of receipts, not of VAT. Inventing a total from it would be wrong."""
        c = ctx(sales_vat=2_000_000.0, documents=[vd.bank_statement()])
        h = next(x for x in roster.calculation(c) if x.id == "CA-03")
        a = adjudicate(h, c)
        assert a.status == "insufficient-evidence"
        assert "no VAT amount column" in a.explanation

    def test_an_unreproducible_auditor_figure_is_reported(self):
        c = ctx(sales_vat=2_000_000.0, documents=[vd.sales_listing()], calculations=[
            {"status": "agree", "label": "row count", "stated": 20.0, "computed": 20.0,
             "delta": 0.0},
            {"status": "disagree", "label": "Q1 output VAT", "stated": 300_000.0,
             "computed": 290_000.0, "delta": -10_000.0},
        ])
        h = next(x for x in roster.calculation(c) if x.test.kind == "auditor-figure")
        a = adjudicate(h, c)
        assert a.status == "confirmed" and a.amount == 10_000.0
        assert "Q1 output VAT" in a.explanation


# ============================================ 4 · EVIDENCE & COVERAGE AGENT
class TestEvidenceAgent:
    def test_purchase_lines_with_no_identity_behind_them_are_found(self):
        doc = vd.purchase_listing(count=10, vat_each=15_000.0,
                                  missing_supplier_vat_rows=(0, 1),
                                  blank_invoice_rows=(4,))
        c = ctx(documents=[doc])
        h = next(x for x in roster.evidence(c) if x.test.kind == "missing-support")
        a = adjudicate(h, c)
        assert a.status == "confirmed"
        assert a.detail["rows_unsupported"] == 3
        assert a.amount == 45_000.0

    def test_a_fully_identified_purchase_ledger_raises_nothing(self):
        c = ctx(documents=[vd.purchase_listing(count=10)])
        h = next(x for x in roster.evidence(c) if x.test.kind == "missing-support")
        assert adjudicate(h, c).status == "refuted"

    def test_revenue_outside_the_registered_activities_is_flagged(self):
        doc = vd.sales_listing(count=10, vat_each=30_000.0, descriptions=[
            "wholesale foodstuff supply", "wholesale foodstuff supply",
            "wholesale foodstuff supply", "wholesale foodstuff supply",
            "equipment leasing income"])
        c = ctx(sales_vat=300_000.0, documents=[doc], activities=vd.WHOLESALE_FOOD)
        h = next(x for x in roster.evidence(c) if x.test.kind == "secondary-activity")
        a = adjudicate(h, c)
        assert a.status == "confirmed"
        assert a.detail["rows_outside"] == 2          # rows 5 and 10 of 10
        assert a.amount == 60_000.0

    def test_the_same_revenue_is_clean_once_the_activity_is_registered(self):
        """The finding is about disclosure, not about the trade itself."""
        doc = vd.sales_listing(count=10, vat_each=30_000.0, descriptions=[
            "wholesale foodstuff supply", "equipment leasing income"])
        c = ctx(sales_vat=300_000.0, documents=[doc],
                activities=vd.WHOLESALE_PLUS_LEASING)
        h = next(x for x in roster.evidence(c) if x.test.kind == "secondary-activity")
        assert adjudicate(h, c).status == "refuted"

    def test_no_trial_balance_is_only_a_finding_alongside_an_excess(self):
        over = vd.sales_listing(count=20, vat_each=130_900.0)     # 2,618,000
        c = ctx(sales_vat=2_000_000.0, documents=[over])
        h = next(x for x in roster.evidence(c) if x.test.kind == "trial-balance-absent")
        assert adjudicate(h, c).status == "confirmed"

        under = vd.sales_listing(count=10, vat_each=100_000.0)    # 1,000,000
        c2 = ctx(sales_vat=2_000_000.0, documents=[under])
        h2 = next(x for x in roster.evidence(c2) if x.test.kind == "trial-balance-absent")
        a2 = adjudicate(h2, c2)
        assert a2.status == "refuted" and "nothing to substantiate" in a2.explanation

    def test_supplying_the_trial_balance_removes_the_hypothesis_entirely(self):
        over = vd.sales_listing(count=20, vat_each=130_900.0)
        c = ctx(sales_vat=2_000_000.0, documents=[over, vd.trial_balance()])
        assert not [x for x in roster.evidence(c) if x.test.kind == "trial-balance-absent"]

    def test_outstanding_requests_become_a_non_cooperation_finding(self):
        c = ctx(documents=[vd.sales_listing()], gaps=[
            {"kind": "missing-item", "item_label": "Trial balance", "severity": "blocking"},
            {"kind": "missing-column", "item_label": "Sales analysis", "severity": "blocking"},
        ])
        h = next(x for x in roster.evidence(c) if x.test.kind == "non-cooperation")
        a = adjudicate(h, c)
        assert a.status == "confirmed"
        assert a.detail["outstanding"] == 1           # only a missing ITEM counts
        assert "Trial balance" in a.explanation


# ================================================= imports, exports, coverage
class TestOtherDocumentTypes:
    def test_import_declarations_are_read_as_a_purchase_population(self):
        """Import VAT is paid at customs, so it is evidence for the input box."""
        doc = vd.import_declarations(count=6, customs_vat_each=22_500.0,
                                     filename="import_declarations.xlsx")
        c = ctx(purchase_vat=100_000.0, documents=[doc])
        h = next((x for x in roster.evidence(c) if x.test.kind == "missing-support"), None)
        assert h is None or adjudicate(h, c).status in ("refuted", "insufficient-evidence")

    def test_exports_without_proof_are_visible_in_the_document(self):
        """Zero-rating stands on the proof of export. The column is what an auditor checks."""
        doc = vd.export_documentation(count=4, missing_proof_rows=(1, 3))
        blanks = sum(1 for r in doc["rows"] if not str(r[doc["columns"].index("proof_of_export")]).strip())
        assert blanks == 2

    def test_a_trial_balance_is_not_mistaken_for_a_sales_listing(self):
        """It has no VAT amount column, so nothing should try to total it as one."""
        c = ctx(sales_vat=2_000_000.0, documents=[vd.trial_balance()])
        assert not [x for x in roster.calculation(c) if x.id == "CA-01"]


# =========================================================== the whole picture
class TestWholeCase:
    def test_a_clean_case_raises_no_finding_at_all(self):
        """The most important negative test in the suite. A compliant taxpayer with complete
        records must come back with nothing to answer."""
        c = ctx(sales_vat=2_000_000.0, purchase_vat=150_000.0, documents=[
            vd.sales_listing(count=20, vat_each=100_000.0),
            vd.purchase_listing(count=10, vat_each=15_000.0),
            vd.credit_note_listing(count=3, vat_each=0.0),
            vd.trial_balance(),
        ], activities=vd.WHOLESALE_FOOD)
        assert codes(c) == set()

    def test_a_dirty_case_raises_exactly_the_expected_findings(self):
        c = ctx(sales_vat=2_000_000.0, purchase_vat=150_000.0, documents=[
            vd.sales_listing(count=20, vat_each=130_900.0, blank_invoice_rows=(3, 7)),
            vd.purchase_listing(count=10, vat_each=15_000.0, blocked_rows=(1,),
                                missing_supplier_vat_rows=(2,)),
        ], activities=vd.WHOLESALE_FOOD,
            gaps=[{"kind": "missing-item", "item_label": "Trial balance",
                   "severity": "blocking"}])
        found = codes(c)
        assert "SAL-HIGHER" in found            # listing exceeds the return
        assert "DOC-INVOICE" in found           # two rows with no invoice number
        assert "PUR-BLOCKED" in found           # an entertainment line
        assert "PUR-NODOC" in found             # a line with no supplier VAT number
        assert "SAL-NOTB" in found              # excess with no trial balance
        assert "PUR-NOCOOP" in found            # the trial balance never arrived

    def test_one_excess_is_never_assessed_twice(self):
        """Four statements can be true of one listing. The assessment counts it once."""
        c = ctx(sales_vat=2_000_000.0, documents=[
            vd.sales_listing(count=20, vat_each=130_900.0)])
        found = findings_for(c)
        sales = [f for f in found if f.effect == oc.INCREASES_OUTPUT]
        assert len(sales) > 1                    # several statements
        assert len({f.basis for f in sales}) == 1    # one piece of evidence
        assert exposure(found)["increases_output"] == 618_000.0

    def test_two_separate_documents_do_add_up(self):
        """The opposite guard: distinct evidence must not be collapsed."""
        c = ctx(sales_vat=300_000.0, documents=[
            vd.sales_listing(count=10, vat_each=40_000.0),        # 400,000 -> +100,000
            vd.pos_report(days=90, gross_per_day=40_250.0),       # 472,500 -> +172,500
        ])
        e = exposure(findings_for(c))
        assert e["increases_output"] == pytest.approx(272_500.0, abs=1.0)

    def test_no_agent_states_a_figure_on_any_scenario(self):
        """The invariant the whole design rests on, re-checked over realistic material."""
        import re
        scenarios = [
            ctx(documents=[vd.sales_listing(blank_invoice_rows=(1,))]),
            ctx(documents=[vd.purchase_listing(blocked_rows=(0,))]),
            ctx(documents=[vd.pos_report()], sales_vat=100_000.0),
            ctx(documents=[vd.credit_note_listing(missing_original_ref_rows=(0,))]),
            ctx(sales_vat=200_000.0, out_unexplained=1_800_000.0),
            ctx(documents=[vd.import_declarations(), vd.export_documentation()]),
        ]
        for c in scenarios:
            for h in roster.propose(c):
                assert not re.search(r"\d", h.claim), f"{h.id} states a figure"

    def test_every_finding_is_worded_by_the_authoritys_vocabulary(self):
        c = ctx(sales_vat=2_000_000.0, documents=[
            vd.sales_listing(count=20, vat_each=130_900.0, blank_invoice_rows=(1,)),
            vd.purchase_listing(count=6, blocked_rows=(0,)),
        ], activities=vd.WHOLESALE_FOOD)
        for f in findings_for(c):
            assert f.statement == oc.statement(f.code)
            assert f.statement
