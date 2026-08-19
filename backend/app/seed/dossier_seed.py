"""Enrich the seeded demo taxpayers with everything ZATCA would already hold.

`scenarios.py` builds the declared position and the e-invoice evidence — the story each case
tells on screen. This module adds the surrounding context an auditor consults *before* writing
to anyone: what the business actually does, what it imports, what its financials say, how it has
filed, and the structured risk-engine referral that started the case.

It runs as a post-pass keyed on VAT number so the seven scenario functions stay readable.

Everything here is synthetic. The referral signals in particular are *inputs* — the risk engine
is upstream and out of scope, so its figures are authored here rather than computed, and they
are deliberately the engine's own crude numbers, not the qualified reconstruction.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditCase, CustomsDeclaration, FinancialSummary, RiskReferral, Taxpayer
from ..risk_indicators import label as indicator_label

MODEL_VERSION = "risk-engine-2024.4"

# --------------------------------------------------------------------------------- profiles
# vat_no -> the profile block. ISIC codes are real ISIC Rev.4 classes; the businesses are not.
PROFILES: dict[str, dict] = {
    "300012345600003": {  # Al-Faisaliah Trading Co. — the hero case
        "legal_form": "LLC",
        "economic_activities": [
            {"isic": "4690", "description": "Non-specialised wholesale trade", "primary": True},
            {"isic": "4652", "description": "Wholesale of electronic and telecommunications "
                                            "equipment and parts", "primary": False},
        ],
        "related_parties": [
            {"name": "Al-Faisaliah Logistics Est.", "vat_no": "300012345600004",
             "relation": "common-owner"},
        ],
        "employee_count": 240, "branch_count": 4, "pos_registered": False,
        "importer_flag": True, "exporter_flag": True,
        "einvoicing_onboarded": date(2022, 1, 1),
        "filing_compliance": {"returns_due": 12, "returns_filed": 12, "filed_late": 1,
                              "avg_days_late": 3, "payments_late": 1, "outstanding_balance": 0.0},
        "financials": [
            (2023, 48_000_000, 31_000_000, 17_000_000, 6_100_000, 62_000_000),
            (2024, 53_500_000, 35_800_000, 17_700_000, 6_400_000, 66_500_000),
        ],
        "customs": [
            ("IM-2025-004412", date(2025, 1, 18), "import", "Jeddah Islamic Port", "8517",
             "Telephone sets and parts", 2_400_000, 120_000, 360_000, False),
            ("IM-2025-005108", date(2025, 2, 22), "import", "Jeddah Islamic Port", "8471",
             "Automatic data-processing machines", 1_650_000, 82_500, 247_500, False),
            ("EX-2025-001902", date(2025, 3, 11), "export", "King Abdulaziz Port", "8544",
             "Insulated wire and cable", 1_500_000, 0, 0, False),
        ],
    },
    "300098765400003": {  # Nael Foodstuff Est. — the clean case
        "legal_form": "Establishment",
        "economic_activities": [
            {"isic": "4711", "description": "Retail sale in non-specialised stores with food, "
                                            "beverages or tobacco predominating", "primary": True},
        ],
        "related_parties": [],
        "employee_count": 65, "branch_count": 7, "pos_registered": True,
        "importer_flag": True, "exporter_flag": False,
        "einvoicing_onboarded": date(2023, 1, 1),
        "filing_compliance": {"returns_due": 12, "returns_filed": 12, "filed_late": 0,
                              "avg_days_late": 0, "payments_late": 0, "outstanding_balance": 0.0},
        "financials": [
            (2023, 14_800_000, 11_100_000, 3_700_000, 980_000, 9_200_000),
            (2024, 16_200_000, 12_150_000, 4_050_000, 1_120_000, 9_900_000),
        ],
        # a purchases-to-sales case on an importer: the one open case where the planner can
        # visibly drop a request because ZATCA holds the answer already (§1)
        "customs": [
            ("IM-2025-002145", date(2025, 1, 22), "import", "Jeddah Islamic Port", "0402",
             "Milk and cream, concentrated", 780_000, 39_000, 117_000, False),
            ("IM-2025-002877", date(2025, 2, 19), "import", "Jeddah Islamic Port", "1006",
             "Rice", 640_000, 32_000, 96_000, False),
        ],
    },
    "300055500100003": {  # Rawabi Construction Co. — credit notes
        "legal_form": "LLC",
        "economic_activities": [
            {"isic": "4100", "description": "Construction of buildings", "primary": True},
            {"isic": "4290", "description": "Construction of other civil engineering projects",
             "primary": False},
        ],
        "related_parties": [
            {"name": "Rawabi Ready-Mix Co.", "vat_no": "300055500100004", "relation": "subsidiary"},
        ],
        "employee_count": 850, "branch_count": 3, "pos_registered": False,
        "importer_flag": True, "exporter_flag": False,
        "einvoicing_onboarded": date(2022, 4, 1),
        "filing_compliance": {"returns_due": 12, "returns_filed": 12, "filed_late": 2,
                              "avg_days_late": 6, "payments_late": 0, "outstanding_balance": 0.0},
        "financials": [
            (2023, 31_500_000, 24_200_000, 7_300_000, 1_900_000, 44_000_000),
            (2024, 33_800_000, 26_400_000, 7_400_000, 1_750_000, 46_500_000),
        ],
        "customs": [
            ("IM-2025-003301", date(2025, 2, 4), "import", "Jubail Commercial Port", "7308",
             "Structures and parts of structures, of iron or steel", 3_200_000, 160_000,
             480_000, True),
        ],
    },
    "300066600200003": {  # Tabuk Logistics Co. — clearance-lag timing
        "legal_form": "LLC",
        "economic_activities": [
            {"isic": "4923", "description": "Freight transport by road", "primary": True},
            {"isic": "5229", "description": "Other transportation support activities",
             "primary": False},
        ],
        "related_parties": [],
        "employee_count": 310, "branch_count": 5, "pos_registered": False,
        "importer_flag": False, "exporter_flag": False,
        "einvoicing_onboarded": date(2023, 1, 1),
        "filing_compliance": {"returns_due": 12, "returns_filed": 12, "filed_late": 0,
                              "avg_days_late": 0, "payments_late": 0, "outstanding_balance": 0.0},
        "financials": [
            (2023, 19_400_000, 13_100_000, 6_300_000, 2_050_000, 28_700_000),
            (2024, 21_100_000, 14_400_000, 6_700_000, 2_180_000, 30_200_000),
        ],
        "customs": [],
    },
    "300077700300003": {  # Najd Electronics Trading — genuine under-declaration
        "legal_form": "LLC",
        "economic_activities": [
            {"isic": "4741", "description": "Retail sale of computers, peripheral units, "
                                            "software and telecommunications equipment",
             "primary": True},
        ],
        "related_parties": [],
        "employee_count": 48, "branch_count": 2, "pos_registered": True,
        "importer_flag": True, "exporter_flag": False,
        "einvoicing_onboarded": date(2023, 7, 1),
        "filing_compliance": {"returns_due": 12, "returns_filed": 11, "filed_late": 4,
                              "avg_days_late": 14, "payments_late": 3,
                              "outstanding_balance": 62_400.0},
        "financials": [
            (2023, 22_900_000, 18_600_000, 4_300_000, 640_000, 11_400_000),
            (2024, 27_600_000, 23_100_000, 4_500_000, 520_000, 12_100_000),
        ],
        "customs": [
            ("IM-2025-006677", date(2025, 1, 29), "import", "Riyadh Dry Port", "8471",
             "Automatic data-processing machines", 4_100_000, 205_000, 615_000, False),
            ("IM-2025-007240", date(2025, 3, 6), "import", "Riyadh Dry Port", "8517",
             "Telephone sets and parts", 2_850_000, 142_500, 427_500, False),
        ],
    },
    "300088800400003": {  # Yanbu Petrochem Supplies — over-declaration
        "legal_form": "JSC",
        "economic_activities": [
            {"isic": "2011", "description": "Manufacture of basic chemicals", "primary": True},
            {"isic": "4669", "description": "Wholesale of waste and scrap and other products "
                                            "n.e.c.", "primary": False},
        ],
        "related_parties": [
            {"name": "Yanbu Industrial Services Co.", "vat_no": "300088800400005",
             "relation": "subsidiary"},
        ],
        "employee_count": 1_240, "branch_count": 2, "pos_registered": False,
        "importer_flag": True, "exporter_flag": True,
        "einvoicing_onboarded": date(2022, 1, 1),
        "filing_compliance": {"returns_due": 12, "returns_filed": 12, "filed_late": 0,
                              "avg_days_late": 0, "payments_late": 0, "outstanding_balance": 0.0},
        "financials": [
            (2023, 88_400_000, 61_900_000, 26_500_000, 11_200_000, 210_000_000),
            (2024, 91_700_000, 64_800_000, 26_900_000, 10_800_000, 216_500_000),
        ],
        "customs": [
            ("EX-2025-002455", date(2025, 1, 14), "export", "King Fahd Industrial Port", "2902",
             "Cyclic hydrocarbons", 6_800_000, 0, 0, False),
            ("EX-2025-002881", date(2025, 3, 2), "export", "King Fahd Industrial Port", "3902",
             "Polymers of propylene", 5_450_000, 0, 0, False),
        ],
    },
    "300033300500003": {  # Hail Medical Supplies Co. — the slipped decimal
        "legal_form": "LLC",
        "economic_activities": [
            {"isic": "4649", "description": "Wholesale of other household goods", "primary": True},
            {"isic": "4772", "description": "Retail sale of pharmaceutical and medical goods",
             "primary": False},
        ],
        "related_parties": [],
        "employee_count": 92, "branch_count": 3, "pos_registered": False,
        "importer_flag": True, "exporter_flag": False,
        "einvoicing_onboarded": date(2023, 1, 1),
        "filing_compliance": {"returns_due": 12, "returns_filed": 12, "filed_late": 0,
                              "avg_days_late": 0, "payments_late": 0, "outstanding_balance": 0.0},
        "financials": [
            (2023, 12_600_000, 8_900_000, 3_700_000, 1_140_000, 8_800_000),
            (2024, 13_900_000, 9_800_000, 4_100_000, 1_260_000, 9_400_000),
        ],
        "customs": [
            ("IM-2025-008120", date(2025, 2, 8), "import", "Dammam Port", "9018",
             "Instruments and appliances used in medical sciences", 1_900_000, 0, 285_000, False),
        ],
    },
}

# ---------------------------------------------------------------------------- referrals
# case_id -> (score, threshold, narrative, [signals]). The *indicator* is not repeated here:
# it lives on the case in `scenarios.py` and is read from there, so there is one vocabulary.
# These are the *engine's* figures: crude comparisons, before any qualification rule runs.
REFERRALS: dict[str, tuple] = {
    "CASE-2025-0481": (
        78.0, 60.0,
        "Cleared and reported e-invoices for the period carry materially more output VAT than "
        "the return declares. The gap exceeds both the absolute and relative thresholds.",
        [{"code": "EINV_OUTPUT_DELTA", "label": "E-invoice vs declared output VAT",
          "value": 480_000.0, "weight": 0.55},
         {"code": "PRIOR_FINDING", "label": "Prior audit finding on the same indicator",
          "value": 1.0, "weight": 0.25},
         {"code": "DELTA_PCT_OF_BOX", "label": "Gap as % of declared box",
          "value": 24.0, "weight": 0.20}],
    ),
    "CASE-2025-0482": (
        41.0, 35.0,
        "Input-to-output ratio sits outside the sector band for food retail of this size. No "
        "e-invoicing difference was detected.",
        [{"code": "INPUT_OUTPUT_RATIO", "label": "Input VAT as % of output VAT",
          "value": 10.0, "weight": 0.60},
         {"code": "SECTOR_BAND_DEVIATION", "label": "Deviation from sector median",
          "value": 2.1, "weight": 0.40}],
    ),
    "CASE-2025-0483": (
        55.0, 60.0,
        "Gross e-invoice output VAT exceeds the declared box. Credit notes are present in the "
        "population but are not netted by this comparison.",
        [{"code": "EINV_OUTPUT_DELTA", "label": "E-invoice vs declared output VAT",
          "value": 300_000.0, "weight": 0.70},
         {"code": "CREDIT_NOTE_VOLUME", "label": "Credit notes in period", "value": 5.0,
          "weight": 0.30}],
    ),
    "CASE-2025-0484": (
        52.0, 60.0,
        "Gross e-invoice output VAT exceeds the declared box. A share of the population was "
        "cleared near the period boundary.",
        [{"code": "EINV_OUTPUT_DELTA", "label": "E-invoice vs declared output VAT",
          "value": 200_000.0, "weight": 0.65},
         {"code": "BOUNDARY_CLEARANCE", "label": "Invoices cleared in the final 5 days",
          "value": 4.0, "weight": 0.35}],
    ),
    "CASE-2025-0485": (
        84.0, 60.0,
        "Declared output VAT is well below the level implied by the taxpayer's own e-invoices "
        "and by imports cleared in the period. Filing history is irregular.",
        [{"code": "EINV_OUTPUT_DELTA", "label": "E-invoice vs declared output VAT",
          "value": 600_000.0, "weight": 0.45},
         {"code": "IMPORT_VS_SALES", "label": "Import value against declared sales",
          "value": 6_950_000.0, "weight": 0.30},
         {"code": "LATE_FILING_RATE", "label": "Returns filed late (last 12)",
          "value": 4.0, "weight": 0.25}],
    ),
    "CASE-2025-0486": (
        46.0, 60.0,
        "The declared output box exceeds the e-invoice population — the difference favours the "
        "Authority, which is unusual and may indicate a reporting or clearance problem.",
        [{"code": "EINV_OUTPUT_DELTA", "label": "E-invoice vs declared output VAT",
          "value": -150_000.0, "weight": 0.75},
         {"code": "NEGATIVE_DELTA_FLAG", "label": "Declared exceeds evidence", "value": 1.0,
          "weight": 0.25}],
    ),
    "CASE-2025-0487": (
        91.0, 60.0,
        "Declared output VAT is an order of magnitude below both the e-invoice population for "
        "the period and the taxpayer's own three preceding quarters.",
        [{"code": "EINV_OUTPUT_DELTA", "label": "E-invoice vs declared output VAT",
          "value": 468_000.0, "weight": 0.40},
         {"code": "OWN_HISTORY_DEVIATION", "label": "Deviation from own trailing average",
          "value": -89.7, "weight": 0.45},
         {"code": "MAGNITUDE_ORDER", "label": "Order-of-magnitude step change", "value": 1.0,
          "weight": 0.15}],
    ),
    "CASE-2024-0310": (
        71.0, 60.0,
        "Cleared e-invoices exceeded the declared output box for the quarter.",
        [{"code": "EINV_OUTPUT_DELTA", "label": "E-invoice vs declared output VAT",
          "value": 120_000.0, "weight": 1.0}],
    ),
}

# Closure record for the one hand-built prior audit, so the history block has real depth.
PRIOR_CLOSURES: dict[str, dict] = {
    "CASE-2024-0310": {
        "closed_date": date(2025, 3, 14),
        "rounds_of_correspondence": 2,
        "days_to_close": 41,
        "evidence_used": {"requested": ["sales-analysis", "credit-note-listing"],
                          "decisive": ["sales-analysis"]},
        "conclusion_note": "Sales analysis showed invoices issued in the quarter but omitted "
                           "from the return. Assessment raised and settled.",
    },
}


def enrich_all(db: Session) -> None:
    """Attach profiles, financials, customs and structured referrals to the seeded demo."""
    by_vat = {t.vat_registration_number: t for t in db.scalars(select(Taxpayer)).all()}

    for vat_no, profile in PROFILES.items():
        tp = by_vat.get(vat_no)
        if tp is None:
            continue
        for field in ("legal_form", "economic_activities", "related_parties", "employee_count",
                      "branch_count", "pos_registered", "importer_flag", "exporter_flag",
                      "einvoicing_onboarded", "filing_compliance"):
            setattr(tp, field, profile[field])

        for year, turnover, purchases, gross, net, assets in profile["financials"]:
            db.add(FinancialSummary(
                taxpayer_id=tp.id, fiscal_year=year, turnover=turnover, purchases=purchases,
                gross_profit=gross, net_profit=net, total_assets=assets,
                source="zakat-return", as_of=date(year + 1, 4, 30),
            ))

        for (no, dt, direction, port, hs, goods, value, duty, vat, deferred) in profile["customs"]:
            db.add(CustomsDeclaration(
                taxpayer_id=tp.id, declaration_no=no, declaration_date=dt, direction=direction,
                port=port, hs_chapter=hs, goods_description=goods, customs_value=value,
                duty_paid=duty, vat_paid=vat, vat_deferred=deferred, status="cleared",
            ))

    db.flush()

    for case in db.scalars(select(AuditCase)).all():
        spec = REFERRALS.get(case.case_id)
        if spec is not None:
            score, threshold, narrative, signals = spec
            db.add(RiskReferral(
                case_ref=case.id,
                indicator_code=case.case_reason_code,   # the case carries the vocabulary
                indicator_label=indicator_label(case.case_reason_code),
                narrative=narrative, score=score, threshold=threshold,
                signals=signals, model_version=MODEL_VERSION,
                generated_at=case.referral_date or (case.period_to + timedelta(days=45)),
            ))
        closure = PRIOR_CLOSURES.get(case.case_id)
        if closure is not None:
            for k, v in closure.items():
                setattr(case, k, v)

    db.flush()
