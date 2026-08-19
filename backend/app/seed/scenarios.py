"""Demo scenarios — synthetic taxpayers whose data tells a clear story on screen.

Phase 0 seeds coherent declared returns + e-invoice evidence + a referred case.
The reconstruction/bridge that turns this into the on-screen narrative lands in a later phase.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..models import (
    Taxpayer, VatReturn, VatReturnBox, Invoice, InvoiceTaxSubtotal, AuditCase,
)

PERIOD_FROM = date(2025, 1, 1)
PERIOD_TO = date(2025, 3, 31)
DEADLINE = date(2025, 4, 30)


def _sale_invoice(tp: Taxpayer, seq: int, base: float, rate: int, issue: date,
                  type_code: int = 388, delivery: date | None = None,
                  status: str = "cleared") -> Invoice:
    vat = round(base * rate / 100, 2)
    inv = Invoice(
        uuid=f"{tp.vat_registration_number}-S-{seq:04d}",
        taxpayer_id=tp.id, invoice_type_code=type_code, type_flags="standard",
        direction="sale", issue_date=issue, delivery_date=delivery or issue,
        status_code=status, seller_vat=tp.vat_registration_number,
        tax_exclusive_amount=base, tax_amount=vat,
    )
    inv.subtotals.append(InvoiceTaxSubtotal(category="S", rate=rate,
                                            taxable_amount=base, tax_amount=vat))
    return inv


def _purchase_invoice(tp: Taxpayer, seq: int, base: float, rate: int, issue: date,
                      type_code: int = 388, delivery: date | None = None,
                      status: str = "cleared", supplier: str = "300099998800003") -> Invoice:
    """A cleared purchase e-invoice — the taxpayer is the buyer; feeds the input-VAT reconstruction."""
    vat = round(base * rate / 100, 2)
    inv = Invoice(
        uuid=f"{tp.vat_registration_number}-P-{seq:04d}",
        taxpayer_id=tp.id, invoice_type_code=type_code, type_flags="standard",
        direction="purchase", issue_date=issue, delivery_date=delivery or issue,
        status_code=status, buyer_vat=tp.vat_registration_number, seller_vat=supplier,
        tax_exclusive_amount=base, tax_amount=vat,
    )
    inv.subtotals.append(InvoiceTaxSubtotal(category="S", rate=rate,
                                            taxable_amount=base, tax_amount=vat))
    return inv


def _box(code: str, label: str, direction: str, base: float, vat: float,
         rate: int | None = None, category: str = "", adjustment: float = 0) -> VatReturnBox:
    return VatReturnBox(box_code=code, box_label=label, direction=direction,
                        category=category, rate=rate, base_amount=base,
                        vat_amount=vat, adjustment=adjustment)


def scenario_alfaisaliah(db: Session) -> None:
    """Hero case: SAR 480k apparent output-VAT gap that later dissolves to ~SAR 75k residual."""
    tp = Taxpayer(
        vat_registration_number="300012345600003", partner="BP100001",
        id_number="7001234567", name="Al-Faisaliah Trading Co.",
        ind_sector="Wholesale trade", business_size="large",
        accounting_method="accrual", resident_flag=True, bp_type="org",
        reg_from=date(2018, 1, 1),
    )
    db.add(tp); db.flush()

    # Declared return — standard-rated output VAT declared at SAR 2,000,000
    ret = VatReturn(
        form_number="VAT-2025Q1-AF", taxpayer_id=tp.id,
        period_from=PERIOD_FROM, period_to=PERIOD_TO, data_version=1, current_flag=True,
        submission_date=date(2025, 4, 28), filing_deadline=DEADLINE,
        sadad_bill_number="SADAD-AF-2025Q1", sadad_paid=True,
        total_vat_due=2_000_000, net_due_vat=1_850_000,
    )
    ret.boxes += [
        _box("standard_rate_sales", "Standard-rated sales", "sale",
             13_333_333.33, 2_000_000, rate=15, category="S"),
        _box("zero_rated_sales", "Zero-rated domestic sales", "sale", 900_000, 0, rate=0, category="Z"),
        _box("exports", "Exports", "sale", 1_500_000, 0, rate=0, category="Z"),
        _box("standard_rate_purchase", "Standard-rated purchases", "purchase",
             1_000_000, 150_000, rate=15, category="S"),
    ]
    db.add(ret)

    # Evidence — crafted so reconstruction tells the SAR 480k → 75k story:
    #   20 in-period tax invoices (388) @15% ......... VAT  2,380,000
    #    2 clearance-lag 388 (delivered in Q2) ........ VAT    100,000  → belong to next period
    #    5 credit notes (381) already in the return ... VAT   -305,000
    #   gross 388 = 2,480,000 vs declared 2,000,000  → apparent gap 480,000
    #   less credit notes 305,000 and timing 100,000  → true residual 75,000
    for i in range(20):
        db.add(_sale_invoice(tp, i + 1, 793_333.33, 15, date(2025, 1, 10)))          # VAT 119,000 ea
    for i in range(2):
        db.add(_sale_invoice(tp, 900 + i, 333_333.33, 15, date(2025, 3, 28),         # VAT 50,000 ea
                             delivery=date(2025, 4, 3)))
    for i in range(5):
        db.add(_sale_invoice(tp, 800 + i, -406_666.67, 15, date(2025, 2, 15),        # VAT -61,000 ea
                             type_code=381))

    # purchase e-invoices — input VAT ties to the declared SAR 150,000 (supported)
    for i in range(10):
        db.add(_purchase_invoice(tp, i + 1, 100_000, 15, date(2025, 1, 20)))          # VAT 15,000 ea

    db.add(AuditCase(
        case_id="CASE-2025-0481", taxpayer_id=tp.id, form_number=ret.form_number,
        period_from=PERIOD_FROM, period_to=PERIOD_TO,
        case_reason_code="EINV_VS_RETURN", risk_category="OUTPUT_UNDERDECLARED",
        vat_priority="HIGH", audit_type="desk", status="referred",
        referral_date=date.today() - timedelta(days=30),
        sla_due=date.today() + timedelta(days=12),          # urgent
        scenario_key="finding",
    ))
    # a prior, closed finding for this taxpayer — feeds the "history" priority signal
    db.add(AuditCase(
        case_id="CASE-2024-0310", taxpayer_id=tp.id, form_number="VAT-2024Q4-AF",
        period_from=date(2024, 10, 1), period_to=date(2024, 12, 31),
        case_reason_code="EINV_VS_RETURN", risk_category="OUTPUT_UNDERDECLARED",
        vat_priority="HIGH", audit_type="desk", status="closed",
        referral_date=date(2025, 2, 1), scenario_key="prior",
        action_taken="ASSESSMENT_RAISED", audit_result_type="FINDING", root_cause_code="OUT-01",
        old_tax_amt=1_500_000, new_tax_amt=1_620_000, diff_tax_amt=120_000, vat_amt=120_000,
    ))


def scenario_nael_clean(db: Session) -> None:
    """Clean case: declared return ties to e-invoices; the flag resolves with no finding."""
    tp = Taxpayer(
        vat_registration_number="300098765400003", partner="BP100002",
        id_number="7009876543", name="Nael Foodstuff Est.",
        ind_sector="Food retail", business_size="medium",
        accounting_method="accrual", resident_flag=True, bp_type="org",
        reg_from=date(2019, 6, 1),
    )
    db.add(tp); db.flush()

    ret = VatReturn(
        form_number="VAT-2025Q1-NL", taxpayer_id=tp.id,
        period_from=PERIOD_FROM, period_to=PERIOD_TO, data_version=1, current_flag=True,
        submission_date=date(2025, 4, 20), filing_deadline=DEADLINE,
        sadad_bill_number="SADAD-NL-2025Q1", sadad_paid=True,
        total_vat_due=600_000, net_due_vat=540_000,
    )
    ret.boxes += [
        _box("standard_rate_sales", "Standard-rated sales", "sale",
             4_000_000, 600_000, rate=15, category="S"),
        _box("standard_rate_purchase", "Standard-rated purchases", "purchase",
             400_000, 60_000, rate=15, category="S"),
    ]
    db.add(ret)

    n = 20
    per_base = round(4_000_000 / n, 2)              # ties exactly to declared 600k VAT
    for i in range(n):
        db.add(_sale_invoice(tp, i + 1, per_base, 15, date(2025, 2, 1)))

    # purchase e-invoices — input VAT ties to the declared SAR 60,000 (supported)
    for i in range(4):
        db.add(_purchase_invoice(tp, i + 1, 100_000, 15, date(2025, 2, 3)))           # VAT 15,000 ea

    db.add(AuditCase(
        case_id="CASE-2025-0482", taxpayer_id=tp.id, form_number=ret.form_number,
        period_from=PERIOD_FROM, period_to=PERIOD_TO,
        case_reason_code="PURCHASE_SALES_RATIO", risk_category="RATIO_ANOMALY",
        vat_priority="MEDIUM", audit_type="desk", status="referred",
        referral_date=date.today() - timedelta(days=20),
        sla_due=date.today() + timedelta(days=45),          # relaxed
        scenario_key="clean",
    ))


def scenario_rawabi_creditnotes(db: Session) -> None:
    """Credit-note story: a SAR 300k apparent gap is entirely credit notes already in the return → supported."""
    tp = Taxpayer(
        vat_registration_number="300055500100003", partner="BP100003",
        id_number="7005550001", name="Rawabi Construction Co.",
        ind_sector="Construction", business_size="large",
        accounting_method="accrual", resident_flag=True, bp_type="org",
        reg_from=date(2017, 3, 1),
    )
    db.add(tp); db.flush()

    ret = VatReturn(
        form_number="VAT-2025Q1-RW", taxpayer_id=tp.id,
        period_from=PERIOD_FROM, period_to=PERIOD_TO, data_version=1, current_flag=True,
        submission_date=date(2025, 4, 22), filing_deadline=DEADLINE,
        sadad_bill_number="SADAD-RW-2025Q1", sadad_paid=True,
        total_vat_due=1_200_000, net_due_vat=1_100_000,
    )
    ret.boxes += [
        _box("standard_rate_sales", "Standard-rated sales", "sale",
             8_000_000, 1_200_000, rate=15, category="S"),
        _box("standard_rate_purchase", "Standard-rated purchases", "purchase",
             700_000, 105_000, rate=15, category="S"),
    ]
    db.add(ret)

    # 20 tax invoices @15% (VAT 75,000 ea) → gross 1,500,000
    # 5 credit notes (381) @ VAT -60,000 ea → -300,000  (already reflected in the declared 1,200,000)
    #   apparent gap 300,000 → fully explained by COR-01 → residual 0
    for i in range(20):
        db.add(_sale_invoice(tp, i + 1, 500_000, 15, date(2025, 2, 5)))
    for i in range(5):
        db.add(_sale_invoice(tp, 800 + i, -400_000, 15, date(2025, 2, 20), type_code=381))

    # purchase e-invoices — input VAT ties to the declared SAR 105,000 (supported)
    for i in range(7):
        db.add(_purchase_invoice(tp, i + 1, 100_000, 15, date(2025, 2, 8)))           # VAT 15,000 ea

    db.add(AuditCase(
        case_id="CASE-2025-0483", taxpayer_id=tp.id, form_number=ret.form_number,
        period_from=PERIOD_FROM, period_to=PERIOD_TO,
        case_reason_code="EINV_VS_RETURN", risk_category="OUTPUT_UNDERDECLARED",
        vat_priority="MEDIUM", audit_type="desk", status="referred",
        referral_date=date.today() - timedelta(days=18),
        sla_due=date.today() + timedelta(days=30),
        scenario_key="creditnote",
    ))


def scenario_tabuk_timing(db: Session) -> None:
    """Timing story: a SAR 200k apparent gap is entirely clearance-lag (delivered next period) → supported."""
    tp = Taxpayer(
        vat_registration_number="300066600200003", partner="BP100004",
        id_number="7006660002", name="Tabuk Logistics Co.",
        ind_sector="Transport & logistics", business_size="medium",
        accounting_method="accrual", resident_flag=True, bp_type="org",
        reg_from=date(2020, 1, 1),
    )
    db.add(tp); db.flush()

    ret = VatReturn(
        form_number="VAT-2025Q1-TB", taxpayer_id=tp.id,
        period_from=PERIOD_FROM, period_to=PERIOD_TO, data_version=1, current_flag=True,
        submission_date=date(2025, 4, 18), filing_deadline=DEADLINE,
        sadad_bill_number="SADAD-TB-2025Q1", sadad_paid=True,
        total_vat_due=800_000, net_due_vat=740_000,
    )
    ret.boxes += [
        _box("standard_rate_sales", "Standard-rated sales", "sale",
             5_333_333.33, 800_000, rate=15, category="S"),
        _box("standard_rate_purchase", "Standard-rated purchases", "purchase",
             400_000, 60_000, rate=15, category="S"),
    ]
    db.add(ret)

    # 16 in-period invoices (VAT 50,000 ea) → 800,000 ties to the declared box
    # 4 issued in-period but delivered 2025-04-05 (VAT 50,000 ea) → 200,000 belong to next period
    #   apparent gap 200,000 → fully explained by OUT-07 (tax-point timing) → residual 0
    for i in range(16):
        db.add(_sale_invoice(tp, i + 1, 333_333.33, 15, date(2025, 3, 18)))
    for i in range(4):
        db.add(_sale_invoice(tp, 900 + i, 333_333.33, 15, date(2025, 3, 29),
                             delivery=date(2025, 4, 5)))

    # purchase e-invoices — input VAT ties to the declared SAR 60,000 (supported)
    for i in range(4):
        db.add(_purchase_invoice(tp, i + 1, 100_000, 15, date(2025, 3, 10)))          # VAT 15,000 ea

    db.add(AuditCase(
        case_id="CASE-2025-0484", taxpayer_id=tp.id, form_number=ret.form_number,
        period_from=PERIOD_FROM, period_to=PERIOD_TO,
        case_reason_code="EINV_VS_RETURN", risk_category="OUTPUT_UNDERDECLARED",
        vat_priority="MEDIUM", audit_type="desk", status="referred",
        referral_date=date.today() - timedelta(days=15),
        sla_due=date.today() + timedelta(days=50),
        scenario_key="timing",
    ))


def scenario_najd_underdeclared(db: Session) -> None:
    """Genuine under-declaration: reconstruction far exceeds the return and rules explain little → material finding."""
    tp = Taxpayer(
        vat_registration_number="300077700300003", partner="BP100005",
        id_number="7007770003", name="Najd Electronics Trading",
        ind_sector="Retail trade", business_size="medium",
        accounting_method="accrual", resident_flag=True, bp_type="org",
        reg_from=date(2021, 9, 1),
    )
    db.add(tp); db.flush()

    ret = VatReturn(
        form_number="VAT-2025Q1-NJ", taxpayer_id=tp.id,
        period_from=PERIOD_FROM, period_to=PERIOD_TO, data_version=1, current_flag=True,
        submission_date=date(2025, 4, 29), filing_deadline=DEADLINE,
        sadad_bill_number="SADAD-NJ-2025Q1", sadad_paid=True,
        total_vat_due=1_000_000, net_due_vat=940_000,
    )
    ret.boxes += [
        _box("standard_rate_sales", "Standard-rated sales", "sale",
             6_666_666.67, 1_000_000, rate=15, category="S"),
        _box("standard_rate_purchase", "Standard-rated purchases", "purchase",
             400_000, 60_000, rate=15, category="S"),
    ]
    db.add(ret)

    # 16 tax invoices (VAT 100,000 ea) → gross 1,600,000 vs declared 1,000,000
    # 1 credit note (VAT -50,000) → only ~8% of the 600,000 gap is explained → residual 550,000 (finding)
    for i in range(16):
        db.add(_sale_invoice(tp, i + 1, 666_666.67, 15, date(2025, 2, 12)))
    db.add(_sale_invoice(tp, 800, -333_333.33, 15, date(2025, 2, 25), type_code=381))

    # input VAT: only SAR 20,000 of purchase invoices support the declared SAR 60,000 → over-claim 40,000
    for i in range(2):
        db.add(_purchase_invoice(tp, i + 1, 66_666.67, 15, date(2025, 2, 14)))        # VAT 10,000 ea

    db.add(AuditCase(
        case_id="CASE-2025-0485", taxpayer_id=tp.id, form_number=ret.form_number,
        period_from=PERIOD_FROM, period_to=PERIOD_TO,
        case_reason_code="SALES_UNDERREPORTED", risk_category="OUTPUT_UNDERDECLARED",
        vat_priority="HIGH", audit_type="desk", status="referred",
        referral_date=date.today() - timedelta(days=28),
        sla_due=date.today() + timedelta(days=25),
        scenario_key="underdeclared",
    ))


def scenario_yanbu_overdeclared(db: Session) -> None:
    """Over-declaration: the return exceeds what e-invoices support → negative residual, unresolved (taxpayer-favourable)."""
    tp = Taxpayer(
        vat_registration_number="300088800400003", partner="BP100006",
        id_number="7008880004", name="Yanbu Petrochem Supplies",
        ind_sector="Manufacturing", business_size="large",
        accounting_method="accrual", resident_flag=True, bp_type="org",
        reg_from=date(2016, 5, 1),
    )
    db.add(tp); db.flush()

    ret = VatReturn(
        form_number="VAT-2025Q1-YN", taxpayer_id=tp.id,
        period_from=PERIOD_FROM, period_to=PERIOD_TO, data_version=1, current_flag=True,
        submission_date=date(2025, 4, 26), filing_deadline=DEADLINE,
        sadad_bill_number="SADAD-YN-2025Q1", sadad_paid=True,
        total_vat_due=900_000, net_due_vat=820_000,
    )
    ret.boxes += [
        _box("standard_rate_sales", "Standard-rated sales", "sale",
             6_000_000, 900_000, rate=15, category="S"),
        _box("standard_rate_purchase", "Standard-rated purchases", "purchase",
             500_000, 75_000, rate=15, category="S"),
    ]
    db.add(ret)

    # 15 tax invoices (VAT 50,000 ea) → gross 750,000 vs declared 900,000
    #   negative residual -150,000 → the taxpayer appears to have over-declared → unresolved
    for i in range(15):
        db.add(_sale_invoice(tp, i + 1, 333_333.33, 15, date(2025, 2, 18)))

    # purchase e-invoices — input VAT ties to the declared SAR 75,000 (supported)
    for i in range(5):
        db.add(_purchase_invoice(tp, i + 1, 100_000, 15, date(2025, 2, 20)))          # VAT 15,000 ea

    db.add(AuditCase(
        case_id="CASE-2025-0486", taxpayer_id=tp.id, form_number=ret.form_number,
        period_from=PERIOD_FROM, period_to=PERIOD_TO,
        case_reason_code="EINV_VS_RETURN", risk_category="OUTPUT_OVERDECLARED",
        vat_priority="MEDIUM", audit_type="desk", status="referred",
        referral_date=date.today() - timedelta(days=22),
        sla_due=date.today() + timedelta(days=40),
        scenario_key="overdeclared",
    ))


def scenario_hail_manual_entry(db: Session) -> None:
    """Keying error: the declared box is the expected figure with the decimal point moved.

    This is the case the investigation layer exists for. The e-invoices support SAR 520,000
    of output VAT; the return says SAR 52,000. Every prior period this taxpayer filed sits
    around half a million, so the figure is out of character for the business as well as for
    the invoices — a slipped decimal, not unreported trade. The right next action is to ask
    the taxpayer to confirm the box, not to raise an assessment.
    """
    tp = Taxpayer(
        vat_registration_number="300033300500003", partner="BP100007",
        id_number="7003330005", name="Hail Medical Supplies Co.",
        ind_sector="Medical equipment", business_size="medium",
        accounting_method="accrual", resident_flag=True, bp_type="org",
        reg_from=date(2019, 2, 1),
    )
    db.add(tp); db.flush()

    # three prior quarters, all filed around SAR 500k — the taxpayer's own baseline
    for i, (pf, pt, vat) in enumerate([
        (date(2024, 4, 1), date(2024, 6, 30), 498_000),
        (date(2024, 7, 1), date(2024, 9, 30), 515_000),
        (date(2024, 10, 1), date(2024, 12, 31), 527_000),
    ]):
        prior = VatReturn(
            form_number=f"VAT-2024Q{i + 2}-HL", taxpayer_id=tp.id,
            period_from=pf, period_to=pt, data_version=1, current_flag=True,
            submission_date=pt + timedelta(days=20), filing_deadline=pt + timedelta(days=30),
            total_vat_due=vat, net_due_vat=vat,
        )
        prior.boxes += [
            _box("standard_rate_sales", "Standard-rated sales", "sale",
                 round(vat / 0.15, 2), vat, rate=15, category="S"),
        ]
        db.add(prior)

    # the period under audit — SAR 52,000 declared where SAR 520,000 is supported
    ret = VatReturn(
        form_number="VAT-2025Q1-HL", taxpayer_id=tp.id,
        period_from=PERIOD_FROM, period_to=PERIOD_TO, data_version=1, current_flag=True,
        submission_date=date(2025, 4, 24), filing_deadline=DEADLINE,
        sadad_bill_number="SADAD-HL-2025Q1", sadad_paid=True,
        total_vat_due=52_000, net_due_vat=7_000,
    )
    ret.boxes += [
        _box("standard_rate_sales", "Standard-rated sales", "sale",
             346_666.67, 52_000, rate=15, category="S"),
        _box("standard_rate_purchase", "Standard-rated purchases", "purchase",
             300_000, 45_000, rate=15, category="S"),
    ]
    db.add(ret)

    # 20 cleared sale invoices @ VAT 26,000 => 520,000 = declared 52,000 x 10 exactly
    for i in range(20):
        db.add(_sale_invoice(tp, i + 1, 173_333.33, 15, date(2025, 2, 10)))
    # purchases tie to the declared input, so only the output box is in question
    for i in range(3):
        db.add(_purchase_invoice(tp, i + 1, 100_000, 15, date(2025, 2, 12)))

    db.add(AuditCase(
        case_id="CASE-2025-0487", taxpayer_id=tp.id, form_number=ret.form_number,
        period_from=PERIOD_FROM, period_to=PERIOD_TO,
        case_reason_code="FINANCIAL_DISCREPANCY", risk_category="OUTPUT_UNDERDECLARED",
        vat_priority="HIGH", audit_type="desk", status="referred",
        referral_date=date.today() - timedelta(days=10),
        sla_due=date.today() + timedelta(days=20),
        scenario_key="manual-entry",
    ))


def build_all(db: Session) -> None:
    scenario_alfaisaliah(db)
    scenario_nael_clean(db)
    scenario_rawabi_creditnotes(db)
    scenario_tabuk_timing(db)
    scenario_najd_underdeclared(db)
    scenario_yanbu_overdeclared(db)
    scenario_hail_manual_entry(db)
