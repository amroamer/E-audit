"""Seed the demo database: schemas + tables, the rule library, assumptions, and demo cases.

Run:  python -m app.seed.seed
Re-runnable: drops and recreates all tables each time (demo convenience).
"""
from __future__ import annotations

from ..db import engine, create_schemas, SessionLocal, Base
from ..models import Rule, Assumption, CodeDictionary
from ..rule_taxonomy import REASON_CODES
from .rulebook_loader import parse_rules
from . import scenarios

ASSUMPTIONS = [
    ("return.total_is_netted", "true", "Declared Total is final; _Adjustment already included."),
    ("timing.tax_point", "issue_date", "Tax point = invoice IssueDate; delivery only for straddle tests."),
    ("version.selector", "as_filed_at_referral", "Reconcile the version filed at referral, not merely Current_Flag='Y'."),
    ("box14.sign_mode", "subtract", "Box16 = Box13 + Box14 - Box15 (sign decided analytically)."),
    ("materiality.floor_sar", "1000", "Residual flagged when |gap| > max(SAR 1000, 0.5% of box)."),
    ("materiality.rel_pct", "0.5", "Relative materiality (%) of the compared box."),
]

CODE_DICTIONARY = [
    ("invoice_type", "388", "Tax invoice", "Standard/simplified tax invoice", False),
    ("invoice_type", "381", "Credit note", "Reduces a prior invoice", False),
    ("invoice_type", "383", "Debit note", "Increases a prior invoice", False),
    ("invoice_type", "386", "Prepayment", "Advance-payment invoice", False),
    ("tax_category", "S", "Standard-rated", "15% (5% before 2020-07-01)", False),
    ("tax_category", "Z", "Zero-rated", "0% (exports, qualifying supplies)", False),
    ("tax_category", "E", "Exempt", "No VAT, no input recovery", False),
    ("tax_category", "O", "Out of scope", "Not subject to VAT", False),
    ("case_reason_code", "EINV_GT_RETURN", "E-invoices exceed return", "Reconstructed > declared", True),
    ("case_reason_code", "SECTOR_RATIO_OUTLIER", "Sector ratio outlier", "Placeholder — awaiting ZATCA list", True),
]


def run() -> None:
    create_schemas()
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    db = SessionLocal()
    try:
        rules = parse_rules()
        for r in rules:
            db.add(Rule(enabled=True, **r))

        for key, value, desc in ASSUMPTIONS:
            db.add(Assumption(key=key, value=value, description=desc))

        for cs, code, label, meaning, real in CODE_DICTIONARY:
            db.add(CodeDictionary(code_set=cs, code=code, label=label,
                                  meaning=meaning, is_placeholder=not real))

        # difference reason codes (timing / scope / document / accounting / risk).
        # Our reading of the difference taxonomy, not a published ZATCA code list.
        for code, (group, label) in REASON_CODES.items():
            db.add(CodeDictionary(code_set="reason_code", code=code, label=label,
                                  meaning=f"{group.capitalize()} difference", is_placeholder=True))

        scenarios.build_all(db)
        db.commit()
        print(f"Seeded {len(rules)} rules, {len(ASSUMPTIONS)} assumptions, "
              f"{len(CODE_DICTIONARY)} codes, {len(REASON_CODES)} reason codes, "
              f"and demo cases (finding + clean).")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    run()
