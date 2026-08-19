"""The labelled closed-case corpus the precedent agent retrieves over.

The auditors' fourth pain point is that regulatory interpretation, sector knowledge and lessons
learned live in individual auditors rather than anywhere a system can reach. The answer is not a
trained model — it is a *population*: when the risk engine raises this indicator, on a taxpayer
of this sector and size, what did comparable cases turn out to be, what was requested, and which
of those requests actually closed them?

That question needs a few hundred closed cases with honest labels. This module generates them.

Three properties matter more than realism:

* **Deterministic.** One fixed seed, so the demo, the tests and the parity harness all see the
  same corpus. A precedent panel that changes between runs is not evidence of anything.
* **Signal-carrying.** The outcome mix, root causes and decisive-evidence weights differ by
  indicator, because that difference *is* what precedent has to teach. A uniform corpus would
  retrieve perfectly and say nothing.
* **Separate from the demo taxpayers.** Corpus taxpayers are their own population, so the seven
  hand-built scenarios keep exactly the reconciliation figures, priorities and history they had.

These are closed historical cases, so they carry no returns or e-invoices — only the referral,
the outcome and the record of how the case ran. Everything here is synthetic.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

from sqlalchemy.orm import Session

from ..models import AuditCase, RiskReferral, Taxpayer
from ..requests.catalog import BY_INDICATOR
from ..risk_indicators import INDICATORS, label as indicator_label

SEED = 20250819
N_CASES = 200
N_TAXPAYERS = 72

# --------------------------------------------------------------------------------- population

SECTORS: tuple[tuple[str, str, str], ...] = (
    ("Wholesale trade", "4690", "Non-specialised wholesale trade"),
    ("Retail trade", "4711", "Retail sale in non-specialised stores"),
    ("Construction", "4100", "Construction of buildings"),
    ("Transport & logistics", "4923", "Freight transport by road"),
    ("Manufacturing", "2011", "Manufacture of basic chemicals"),
    ("Food retail", "4721", "Retail sale of food in specialised stores"),
    ("Professional services", "6920", "Accounting, bookkeeping and auditing"),
    ("Medical equipment", "4649", "Wholesale of other household goods"),
    ("Telecommunications", "6110", "Wired telecommunications activities"),
    ("Hospitality", "5610", "Restaurants and mobile food service activities"),
    ("Real estate", "6810", "Real estate activities with own or leased property"),
    ("Information technology", "6201", "Computer programming activities"),
)

NAME_A = ("Al-Rajhi", "Al-Nahda", "Al-Waha", "Riyadh", "Jeddah", "Dammam", "Qassim", "Asir",
          "Madinah", "Taif", "Khobar", "Buraidah", "Najran", "Jazan", "Sakaka", "Arar",
          "Al-Bahah", "Unaizah", "Hafar", "Yanbu", "Rabigh", "Dhahran")
NAME_B = ("Trading", "Industrial", "Commercial", "Development", "Services", "Enterprises",
          "Group", "Holding", "Contracting", "Supplies", "Systems", "Solutions")
NAME_C = ("Co.", "Est.", "LLC", "Company", "Group")

SIZE_BANDS = ("micro", "small", "medium", "large")
SIZE_WEIGHTS = (0.14, 0.31, 0.34, 0.21)
# rough turnover ceiling per band, used to scale exposure
SIZE_SCALE = {"micro": 40_000, "small": 140_000, "medium": 520_000, "large": 2_400_000}

# ------------------------------------------------------------------------------- outcome model
# Per indicator: how cases of this kind actually turn out, and why. These distributions are the
# corpus's only real content — everything the precedent agent reports is a tally over them.
#
#   outcomes     : (result, weight) — NO_FINDING means the flag was explained away
#   explained_by : root causes behind a NO_FINDING (qualification rules — legitimate reasons)
#   caused_by    : root causes behind a FINDING (mistakes)
#   decisive     : how often each requested item is the one that closed the case
#   rounds       : (weight per 1..4 rounds of correspondence)
PROFILE: dict[str, dict] = {
    "EINV_VS_RETURN": {
        "outcomes": (("NO_FINDING", 0.61), ("FINDING", 0.39)),
        "explained_by": (("COR-01", 0.38), ("OUT-07", 0.31), ("COR-02", 0.17), ("INP-09", 0.14)),
        "caused_by": (("OUT-01", 0.44), ("DAT-01", 0.25), ("OUT-03", 0.17), ("DAT-12", 0.14)),
        "decisive": {"sales-analysis": 0.44, "credit-note-listing": 0.31,
                     "reconciliation": 0.19, "explanation-difference": 0.06},
        "rounds": (0.34, 0.38, 0.20, 0.08),
    },
    "SALES_UNDERREPORTED": {
        "outcomes": (("FINDING", 0.68), ("NO_FINDING", 0.32)),
        "explained_by": (("OUT-07", 0.42), ("COR-01", 0.33), ("T-AMEND", 0.25)),
        "caused_by": (("OUT-01", 0.51), ("DAT-01", 0.21), ("OUT-03", 0.15), ("CMP-06", 0.13)),
        "decisive": {"sales-analysis": 0.57, "trial-balance": 0.21,
                     "bank-statements": 0.14, "explanation-difference": 0.08},
        "rounds": (0.18, 0.32, 0.31, 0.19),
    },
    "PURCHASE_SALES_RATIO": {
        "outcomes": (("NO_FINDING", 0.54), ("FINDING", 0.46)),
        "explained_by": (("INP-09", 0.35), ("S-STOCK", 0.34), ("COR-02", 0.31)),
        "caused_by": (("INP-02", 0.37), ("INP-01", 0.29), ("INP-04", 0.20), ("DAT-05", 0.14)),
        "decisive": {"purchase-analysis": 0.52, "explanation-activity": 0.26,
                     "sales-analysis": 0.15, "customs-declarations": 0.07},
        "rounds": (0.22, 0.35, 0.28, 0.15),
    },
    "FINANCIAL_DISCREPANCY": {
        "outcomes": (("NO_FINDING", 0.49), ("FINDING", 0.51)),
        "explained_by": (("A-YEAREND", 0.41), ("OUT-07", 0.32), ("COR-01", 0.27)),
        "caused_by": (("DAT-12", 0.43), ("OUT-01", 0.28), ("DAT-01", 0.17), ("CMP-05", 0.12)),
        "decisive": {"reconciliation": 0.48, "trial-balance": 0.27,
                     "financial-statements": 0.16, "explanation-difference": 0.09},
        "rounds": (0.29, 0.36, 0.24, 0.11),
    },
    "POS_RISK": {
        "outcomes": (("FINDING", 0.57), ("NO_FINDING", 0.43)),
        "explained_by": (("S-EXEMPT", 0.38), ("OUT-07", 0.34), ("COR-01", 0.28)),
        "caused_by": (("OUT-01", 0.48), ("DAT-02", 0.24), ("CMP-09", 0.16), ("DAT-12", 0.12)),
        "decisive": {"pos-report": 0.61, "sales-analysis": 0.24, "bank-statements": 0.15},
        "rounds": (0.31, 0.37, 0.21, 0.11),
    },
    "FINANCIAL_STATUS": {
        # a prioritisation signal, not an error signal — it rarely produces a finding of its own
        "outcomes": (("NO_FINDING", 0.78), ("FINDING", 0.22)),
        "explained_by": (("R-SOLVENCY", 0.56), ("CMP-01", 0.24), ("A-YEAREND", 0.20)),
        "caused_by": (("CMP-01", 0.44), ("OUT-01", 0.32), ("CMP-05", 0.24)),
        "decisive": {"financial-statements": 0.66, "bank-statements": 0.34},
        "rounds": (0.52, 0.31, 0.12, 0.05),
    },
}

ACTION = {"FINDING": "ASSESSMENT_RAISED", "NO_FINDING": "CASE_CLOSED_NO_ACTION"}

CONCLUSION = {
    "NO_FINDING": (
        "The taxpayer's analysis reconciled the difference to {cause}; no adjustment required.",
        "Evidence supplied accounted for the flagged difference ({cause}). Case closed without "
        "assessment.",
        "The difference was explained by {cause} and traced to the documents supplied.",
    ),
    "FINDING": (
        "Assessment raised. Root cause recorded as {cause}.",
        "The difference was not supported by the evidence supplied; {cause} confirmed and "
        "assessed.",
        "Findings confirmed against the documents supplied. Root cause {cause}.",
    ),
}


def _pick(rng: random.Random, weighted) -> str:
    """One weighted draw from ((value, weight), ...)."""
    values = [v for v, _ in weighted]
    weights = [w for _, w in weighted]
    return rng.choices(values, weights=weights, k=1)[0]


def _quarter(rng: random.Random) -> tuple[date, date]:
    """A closed quarter between 2023-Q1 and 2024-Q4."""
    year = rng.choice((2023, 2023, 2024, 2024, 2024))
    q = rng.randint(1, 4)
    start = date(year, 3 * q - 2, 1)
    end = date(year + (q == 4), 1 if q == 4 else 3 * q + 1, 1) - timedelta(days=1)
    return start, end


def _taxpayers(rng: random.Random, db: Session) -> list[Taxpayer]:
    """A population of historical taxpayers, disjoint from the seven demo scenarios."""
    out: list[Taxpayer] = []
    used: set[str] = set()
    for i in range(N_TAXPAYERS):
        sector, isic, isic_desc = rng.choice(SECTORS)
        for _ in range(20):
            name = f"{rng.choice(NAME_A)} {rng.choice(NAME_B)} {rng.choice(NAME_C)}"
            if name not in used:
                break
        used.add(name)
        size = rng.choices(SIZE_BANDS, weights=SIZE_WEIGHTS, k=1)[0]
        reg = date(rng.randint(2018, 2022), rng.randint(1, 12), 1)
        due = 12
        late = rng.choices((0, 1, 2, 4), weights=(0.55, 0.24, 0.14, 0.07), k=1)[0]
        tp = Taxpayer(
            # 3009xxxxxxx00003 — a distinct block from the demo taxpayers
            vat_registration_number=f"3009{9000 + i:04d}00{i % 10}0003"[:15],
            partner=f"BP2{i:05d}", id_number=f"71{i:08d}", name=name,
            ind_sector=sector, business_size=size, accounting_method="accrual",
            resident_flag=True, bp_type="org", reg_from=reg,
            legal_form=rng.choice(("LLC", "Establishment", "JSC")),
            economic_activities=[{"isic": isic, "description": isic_desc, "primary": True}],
            related_parties=[],
            employee_count={"micro": 6, "small": 34, "medium": 180, "large": 900}[size],
            branch_count=rng.randint(1, 6),
            pos_registered=sector in ("Retail trade", "Food retail", "Hospitality"),
            importer_flag=rng.random() < 0.45, exporter_flag=rng.random() < 0.18,
            einvoicing_onboarded=date(rng.choice((2022, 2023)), 1, 1),
            filing_compliance={"returns_due": due, "returns_filed": due,
                               "filed_late": late, "avg_days_late": late * 3,
                               "payments_late": max(0, late - 1),
                               "outstanding_balance": 0.0},
        )
        db.add(tp)
        out.append(tp)
    db.flush()
    return out


def build(db: Session) -> int:
    """Generate the closed-case corpus. Returns the number of cases created."""
    rng = random.Random(SEED)
    pool = _taxpayers(rng, db)
    indicators = [i.code for i in INDICATORS]
    # weighted so the indicators the auditors described as common actually are
    ind_weights = {"EINV_VS_RETURN": 0.28, "SALES_UNDERREPORTED": 0.24,
                   "PURCHASE_SALES_RATIO": 0.18, "FINANCIAL_DISCREPANCY": 0.14,
                   "POS_RISK": 0.10, "FINANCIAL_STATUS": 0.06}

    made = 0
    for n in range(N_CASES):
        indicator = rng.choices(indicators,
                                weights=[ind_weights.get(c, 0.05) for c in indicators], k=1)[0]
        prof = PROFILE[indicator]
        tp = rng.choice(pool)
        period_from, period_to = _quarter(rng)

        result = _pick(rng, prof["outcomes"])
        cause = _pick(rng, prof["explained_by"] if result == "NO_FINDING" else prof["caused_by"])

        rounds = rng.choices((1, 2, 3, 4), weights=prof["rounds"], k=1)[0]
        # each round of correspondence is the months-long wait the auditors described
        days = rounds * rng.randint(28, 52) + rng.randint(5, 25)

        scale = SIZE_SCALE[tp.business_size]
        assessed = (round(rng.uniform(0.05, 1.6) * scale, 2) if result == "FINDING" else 0.0)

        candidates = list(BY_INDICATOR.get(indicator, ("sales-analysis",)))
        n_req = min(len(candidates), rng.randint(2, 4))
        requested = rng.sample(candidates, n_req)
        decisive_weights = [prof["decisive"].get(k, 0.02) for k in requested]
        decisive = ([rng.choices(requested, weights=decisive_weights, k=1)[0]]
                    if result != "NO_FINDING" or rng.random() < 0.88 else [])

        referral_date = period_to + timedelta(days=rng.randint(40, 120))
        closed = referral_date + timedelta(days=days)
        case = AuditCase(
            case_id=f"CASE-H{period_from.year}-{2000 + n:04d}",
            taxpayer_id=tp.id, form_number=f"VAT-{period_from.year}Q{(period_from.month + 2) // 3}"
                                          f"-{tp.partner}",
            period_from=period_from, period_to=period_to,
            case_reason_code=indicator,
            risk_category=indicator_label(indicator)[:30],
            vat_priority=rng.choice(("HIGH", "MEDIUM", "MEDIUM", "LOW")),
            audit_type=rng.choices(("desk", "field"), weights=(0.82, 0.18), k=1)[0],
            status="closed", referral_date=referral_date,
            sla_due=referral_date + timedelta(days=90), scenario_key="corpus",
            action_taken=ACTION[result], audit_result_type=result, root_cause_code=cause,
            old_tax_amt=0, new_tax_amt=0, diff_tax_amt=assessed, vat_amt=assessed,
            closed_date=closed, rounds_of_correspondence=rounds, days_to_close=days,
            evidence_used={"requested": requested, "decisive": decisive},
            conclusion_note=rng.choice(CONCLUSION[result]).format(cause=cause),
        )
        db.add(case)
        db.flush()

        db.add(RiskReferral(
            case_ref=case.id, indicator_code=indicator,
            indicator_label=indicator_label(indicator),
            narrative="", score=round(rng.uniform(35, 95), 1), threshold=60.0,
            signals=[], model_version="risk-engine-2023.2",
            generated_at=referral_date,
        ))
        made += 1

    db.flush()
    return made
