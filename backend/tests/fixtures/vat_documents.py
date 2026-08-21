"""Test data shaped like the documents a Saudi VAT audit actually receives.

Built to exercise the agents against realistic material rather than convenient material. The
VAT return follows the KSA form's own box structure, and each document type carries the
defects auditors actually meet: a listing that does not foot, a purchase ledger with blocked
categories, a credit note with no reference to the invoice it corrects, POS takings above the
declared box.

Every generator returns the same shape the extractor produces from a real upload —
`{filename, columns, rows, row_count, stated_totals}` — so a test can feed one straight to an
agent without a file ever touching disk.

The figures are deliberately round. A test that fails should fail because the logic is wrong,
not because someone has to check arithmetic by hand to find out.
"""
from __future__ import annotations

from datetime import date, timedelta

# --------------------------------------------------------------- the VAT return
# The KSA VAT return's own boxes. Kept in the Authority's order and wording, because a
# reconciliation that quietly renames a box is a reconciliation nobody can check.
VAT_RETURN_BOXES = (
    ("standard_rated_sales", "Standard rated sales", "sale", 15),
    ("private_healthcare_education", "Private healthcare / private education", "sale", 0),
    ("zero_rated_domestic", "Zero rated domestic sales", "sale", 0),
    ("exports", "Exports", "sale", 0),
    ("exempt_sales", "Exempt sales", "sale", 0),
    ("standard_rated_purchases", "Standard rated domestic purchases", "purchase", 15),
    ("imports_vat_paid_customs", "Imports subject to VAT paid at customs", "purchase", 15),
    ("imports_reverse_charge", "Imports subject to VAT under reverse charge", "purchase", 15),
    ("zero_rated_purchases", "Zero rated purchases", "purchase", 0),
    ("exempt_purchases", "Exempt purchases", "purchase", 0),
)

PERIOD_FROM = date(2025, 1, 1)
PERIOD_TO = date(2025, 3, 31)


def vat_return(*, standard_sales_vat: float = 2_000_000.0,
               standard_purchase_vat: float = 150_000.0,
               exports: float = 0.0, zero_rated: float = 0.0, exempt: float = 0.0,
               imports_customs_vat: float = 0.0,
               corrections: float = 0.0) -> dict:
    """A filed return, as the boxes the auditor compares against.

    `net_vat_due` is computed the way the form computes it, so a test that changes one box
    sees the total move exactly as it would on a real return.
    """
    boxes = {
        "standard_rated_sales": {"base": round(standard_sales_vat / 0.15, 2),
                                 "vat": standard_sales_vat},
        "private_healthcare_education": {"base": 0.0, "vat": 0.0},
        "zero_rated_domestic": {"base": zero_rated, "vat": 0.0},
        "exports": {"base": exports, "vat": 0.0},
        "exempt_sales": {"base": exempt, "vat": 0.0},
        "standard_rated_purchases": {"base": round(standard_purchase_vat / 0.15, 2),
                                     "vat": standard_purchase_vat},
        "imports_vat_paid_customs": {"base": round(imports_customs_vat / 0.15, 2) if imports_customs_vat else 0.0,
                                     "vat": imports_customs_vat},
        "imports_reverse_charge": {"base": 0.0, "vat": 0.0},
        "zero_rated_purchases": {"base": 0.0, "vat": 0.0},
        "exempt_purchases": {"base": 0.0, "vat": 0.0},
    }
    output_vat = sum(b["vat"] for k, b in boxes.items()
                     if any(k == code and d == "sale" for code, _, d, _ in VAT_RETURN_BOXES))
    input_vat = sum(b["vat"] for k, b in boxes.items()
                    if any(k == code and d == "purchase" for code, _, d, _ in VAT_RETURN_BOXES))
    return {
        "period_from": PERIOD_FROM.isoformat(),
        "period_to": PERIOD_TO.isoformat(),
        "boxes": boxes,
        "total_output_vat": round(output_vat, 2),
        "total_input_vat": round(input_vat, 2),
        "corrections_previous_period": corrections,
        "net_vat_due": round(output_vat - input_vat + corrections, 2),
    }


# ------------------------------------------------------------------- helpers
def _doc(filename: str, columns: list[str], rows: list[list],
         stated_totals: dict | None = None) -> dict:
    return {"filename": filename, "columns": columns, "rows": rows,
            "row_count": len(rows), "stated_totals": stated_totals or {}}


def _dates(n: int, start: date = PERIOD_FROM, step: int = 3) -> list[str]:
    return [(start + timedelta(days=i * step)).isoformat() for i in range(n)]


# ------------------------------------------------------------ sales listings
SALES_COLUMNS = ["invoice_date", "invoice_number", "customer_name", "customer_vat_number",
                 "description", "taxable_amount", "vat_rate", "vat_amount"]


def sales_listing(*, count: int = 20, vat_each: float = 15_000.0,
                  filename: str = "sales_analysis.xlsx",
                  missing_columns: tuple[str, ...] = (),
                  blank_invoice_rows: tuple[int, ...] = (),
                  overstated_total_by: float = 0.0,
                  stops_early_days: int = 0,
                  descriptions: list[str] | None = None) -> dict:
    """A sales analysis, optionally carrying the defects auditors actually meet.

    Every knob here corresponds to a real complaint: a column that was asked for and not
    supplied, a mandatory field left blank, a stated total that does not foot, a file that
    stops short of the period.
    """
    columns = [c for c in SALES_COLUMNS if c not in missing_columns]
    step = 3 if not stops_early_days else max(1, (90 - stops_early_days) // max(count, 1))
    days = _dates(count, step=step)
    rows = []
    for i in range(count):
        base = round(vat_each / 0.15, 2)
        cells = {
            "invoice_date": days[i],
            "invoice_number": "" if i in blank_invoice_rows else f"INV-2025-{1000 + i}",
            "customer_name": f"Customer {chr(65 + i % 26)} Est.",
            "customer_vat_number": f"3001111111000{i % 10:02d}",
            "description": (descriptions[i % len(descriptions)] if descriptions
                            else "wholesale foodstuff supply"),
            "taxable_amount": base,
            "vat_rate": "15%",
            "vat_amount": vat_each,
        }
        rows.append([cells[c] for c in columns])
    totals = {}
    if overstated_total_by:
        totals = {"vat_amount": round(vat_each * count + overstated_total_by, 2)}
    return _doc(filename, columns, rows, totals)


# --------------------------------------------------------- purchase listings
PURCHASE_COLUMNS = ["invoice_date", "invoice_number", "supplier_name", "supplier_vat_number",
                    "description", "taxable_amount", "vat_rate", "vat_amount"]

BLOCKED_DESCRIPTIONS = ["staff entertainment dinner", "hotel accommodation for directors",
                        "passenger vehicle lease", "client hospitality", "employee benefit gift"]
ALLOWED_DESCRIPTIONS = ["packaging materials", "warehouse rent", "freight and logistics",
                        "raw materials", "office supplies"]


def purchase_listing(*, count: int = 10, vat_each: float = 15_000.0,
                     filename: str = "purchase_analysis.xlsx",
                     blocked_rows: tuple[int, ...] = (),
                     missing_supplier_vat_rows: tuple[int, ...] = (),
                     blank_invoice_rows: tuple[int, ...] = ()) -> dict:
    """A purchase analysis. `blocked_rows` carry descriptions input VAT cannot be recovered on."""
    days = _dates(count)
    rows = []
    for i in range(count):
        base = round(vat_each / 0.15, 2)
        desc = (BLOCKED_DESCRIPTIONS[i % len(BLOCKED_DESCRIPTIONS)] if i in blocked_rows
                else ALLOWED_DESCRIPTIONS[i % len(ALLOWED_DESCRIPTIONS)])
        rows.append([
            days[i],
            "" if i in blank_invoice_rows else f"PUR-2025-{2000 + i}",
            f"Supplier {chr(65 + i % 26)} Co.",
            "" if i in missing_supplier_vat_rows else f"3009999999000{i % 10:02d}",
            desc, base, "15%", vat_each,
        ])
    return _doc(filename, PURCHASE_COLUMNS, rows)


# -------------------------------------------------------------- credit notes
NOTE_COLUMNS = ["note_date", "note_number", "original_invoice_number", "customer_name",
                "reason", "taxable_amount", "vat_rate", "vat_amount"]


def credit_note_listing(*, count: int = 5, vat_each: float = -6_000.0,
                        filename: str = "credit_notes.xlsx",
                        missing_original_ref_rows: tuple[int, ...] = (),
                        missing_columns: tuple[str, ...] = ()) -> dict:
    """Credit notes. A note with no reference to the invoice it corrects fails its conditions."""
    columns = [c for c in NOTE_COLUMNS if c not in missing_columns]
    days = _dates(count, start=date(2025, 2, 1))
    rows = []
    for i in range(count):
        cells = {
            "note_date": days[i],
            "note_number": f"CN-2025-{300 + i}",
            "original_invoice_number": ("" if i in missing_original_ref_rows
                                        else f"INV-2025-{1000 + i}"),
            "customer_name": f"Customer {chr(65 + i % 26)} Est.",
            "reason": "goods returned",
            "taxable_amount": round(vat_each / 0.15, 2),
            "vat_rate": "15%",
            "vat_amount": vat_each,
        }
        rows.append([cells[c] for c in columns])
    return _doc(filename, columns, rows)


# ------------------------------------------------------------------ POS / bank
def pos_report(*, days: int = 90, gross_per_day: float = 40_250.0,
               filename: str = "pos_settlement.xlsx") -> dict:
    """Point-of-sale settlement. VAT is the 15% inside a gross take."""
    rows = []
    for i in range(days):
        gross = gross_per_day
        net = round(gross / 1.15, 2)
        rows.append([(PERIOD_FROM + timedelta(days=i)).isoformat(), f"TERM-{i % 4 + 1:02d}",
                     40 + i % 15, gross, net, round(gross - net, 2)])
    return _doc(filename,
                ["invoice_date", "terminal_id", "transactions", "gross_amount",
                 "taxable_amount", "vat_amount"], rows)


def bank_statement(*, count: int = 30, credit_each: float = 100_000.0,
                   filename: str = "bank_statement.csv") -> dict:
    """A bank statement. No VAT column — which is the point: it cannot be totalled as VAT,
    and an agent that tries must report that honestly."""
    rows = []
    for i in range(count):
        rows.append([(PERIOD_FROM + timedelta(days=i * 3)).isoformat(),
                     f"Deposit from Customer {chr(65 + i % 26)}", credit_each, 0.0,
                     round(500_000 + credit_each * i, 2)])
    return _doc(filename, ["invoice_date", "description", "credit", "debit", "balance"], rows)


# ------------------------------------------------------------ imports / exports
def import_declarations(*, count: int = 6, customs_vat_each: float = 22_500.0,
                        filename: str = "import_declarations.xlsx") -> dict:
    """Customs declarations. Import VAT is paid at the border, so it belongs to a box the
    e-invoice population cannot evidence at all."""
    rows = []
    for i in range(count):
        base = round(customs_vat_each / 0.15, 2)
        rows.append([(PERIOD_FROM + timedelta(days=i * 12)).isoformat(),
                     f"DEC-2025-{5000 + i}", f"HS-{8400 + i}", "Import",
                     f"Overseas Supplier {chr(65 + i)} Ltd", base, "15%", customs_vat_each])
    return _doc(filename,
                ["invoice_date", "declaration_number", "hs_code", "direction",
                 "supplier_name", "taxable_amount", "vat_rate", "vat_amount"], rows)


def export_documentation(*, count: int = 4, value_each: float = 300_000.0,
                         filename: str = "export_evidence.xlsx",
                         missing_proof_rows: tuple[int, ...] = ()) -> dict:
    """Exports are zero-rated only where the proof of export exists. A row without it is
    standard-rated until the taxpayer produces one."""
    rows = []
    for i in range(count):
        rows.append([(PERIOD_FROM + timedelta(days=i * 18)).isoformat(),
                     f"EXP-2025-{700 + i}", f"Overseas Buyer {chr(65 + i)}",
                     "" if i in missing_proof_rows else f"BOL-{9000 + i}",
                     "export of goods", value_each, "0%", 0.0])
    return _doc(filename,
                ["invoice_date", "invoice_number", "customer_name", "proof_of_export",
                 "description", "taxable_amount", "vat_rate", "vat_amount"], rows)


# ------------------------------------------------------------- trial balance
def trial_balance(*, sales_credit: float = 17_453_333.33,
                  output_vat_credit: float = 2_618_000.0,
                  filename: str = "trial_balance.xlsx") -> dict:
    """A trial balance, which is what lets an excess be traced into the accounts."""
    rows = [
        ["4000", "Sales — standard rated", 0.0, sales_credit],
        ["4100", "Sales — exports", 0.0, 0.0],
        ["2100", "Output VAT payable", 0.0, output_vat_credit],
        ["1200", "Input VAT recoverable", 150_000.0, 0.0],
        ["1000", "Trade receivables", round(sales_credit * 0.4, 2), 0.0],
        ["5000", "Cost of sales", round(sales_credit * 0.6, 2), 0.0],
    ]
    return _doc(filename, ["account_code", "account_name", "debit", "credit"], rows)


# ------------------------------------------- tax-invoice condition violations
def defective_tax_invoices(*, filename: str = "sales_analysis.xlsx") -> dict:
    """One row per condition an Article-53 tax invoice must satisfy, each broken in turn.

    Used to prove the Regulations agent catches every condition it claims to test, and that
    a complete row is left alone.
    """
    columns = SALES_COLUMNS
    good = ["2025-01-10", "INV-2025-1001", "Complete Customer Est.", "300111111100003",
            "wholesale foodstuff supply", 100_000.0, "15%", 15_000.0]
    rows = [list(good)]
    for i, col in enumerate(("invoice_date", "invoice_number", "customer_name",
                             "taxable_amount", "vat_amount")):
        row = list(good)
        row[columns.index(col)] = ""
        row[columns.index("invoice_number")] = (
            row[columns.index("invoice_number")] or f"INV-BROKEN-{i}")
        if col == "invoice_number":
            row[columns.index("invoice_number")] = ""
        rows.append(row)
    return _doc(filename, columns, rows)


# --------------------------------------------------------------- CR activities
WHOLESALE_FOOD = [{"isic": "4630", "description": "Wholesale of food, beverages and tobacco",
                   "primary": True}]
WHOLESALE_PLUS_LEASING = WHOLESALE_FOOD + [
    {"isic": "7730", "description": "Renting and leasing of other machinery and equipment",
     "primary": False}]
