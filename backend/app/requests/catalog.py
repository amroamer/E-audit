"""The catalogue of things an auditor can ask a taxpayer for.

Two design points carry most of the value here.

**`satisfied_by` is the "do not ask for what we hold" rule, made mechanical.** The auditors were
emphatic that they do not request information ZATCA already has. Leaving that to memory is what
makes it unreliable; naming the internal source that already answers an item lets the planner
drop it automatically and *show* why it was dropped.

**`required_columns` is what makes completeness checkable.** Their own example was a sales
analysis with eight specific columns; a request that says "a sales analysis" cannot be checked
against what arrives, and a request that names its columns can be — deterministically, with no
model involved. `mandatory_columns` are the subset that may not be blank once present.

The column names are ours. Replace them with the real request templates and the checker gets
sharper without any code change.
"""
from __future__ import annotations

from typing import Literal, NamedTuple

Kind = Literal["analysis", "document", "explanation"]

SALES_COLUMNS = (
    "invoice_date", "invoice_number", "customer_name", "customer_vat_number",
    "description", "taxable_amount", "vat_rate", "vat_amount",
)
PURCHASE_COLUMNS = (
    "invoice_date", "invoice_number", "supplier_name", "supplier_vat_number",
    "description", "taxable_amount", "vat_rate", "vat_amount",
)


class RequestItem(NamedTuple):
    key: str
    label: str
    kind: Kind
    description: str
    required_columns: tuple[str, ...] = ()
    mandatory_columns: tuple[str, ...] = ()      # must be present *and* populated
    expected_format: str = ""
    # internal source that already answers this — if held, do not ask for it (§1)
    satisfied_by: str = ""
    # reason codes / root causes this item bears on, used to pick items per hypothesis
    addresses: tuple[str, ...] = ()
    # a total the taxpayer states that we can recompute from the rows (§7 second line)
    footed_by: tuple[str, str] = ()              # (stated total field, column to sum)


CATALOG: tuple[RequestItem, ...] = (
    RequestItem(
        "sales-analysis", "Detailed sales analysis", "analysis",
        "A line-by-line analysis of all sales in the period, one row per invoice.",
        required_columns=SALES_COLUMNS,
        mandatory_columns=("invoice_date", "invoice_number", "taxable_amount", "vat_amount"),
        expected_format="xlsx",
        addresses=("OUT-01", "OUT-03", "DAT-01", "T-LATE"),
        footed_by=("total_vat_amount", "vat_amount"),
    ),
    RequestItem(
        "purchase-analysis", "Detailed purchases analysis", "analysis",
        "A line-by-line analysis of all purchases on which input VAT was claimed.",
        required_columns=PURCHASE_COLUMNS,
        mandatory_columns=("invoice_date", "invoice_number", "supplier_vat_number",
                           "taxable_amount", "vat_amount"),
        expected_format="xlsx",
        addresses=("INP-01", "INP-02", "INP-09", "DAT-05"),
        footed_by=("total_vat_amount", "vat_amount"),
    ),
    RequestItem(
        "credit-note-listing", "Credit and debit note listing", "analysis",
        "All credit (381) and debit (383) notes issued or received in the period, with the "
        "original invoice each one adjusts.",
        required_columns=("note_date", "note_number", "note_type", "original_invoice_number",
                          "taxable_amount", "vat_amount", "reason"),
        mandatory_columns=("note_number", "original_invoice_number", "vat_amount"),
        expected_format="xlsx",
        addresses=("COR-01", "COR-02", "COR-03"),
    ),
    RequestItem(
        "trial-balance", "Trial balance", "document",
        "The trial balance covering the period under audit.",
        required_columns=("account_code", "account_name", "debit", "credit"),
        mandatory_columns=("account_code", "debit", "credit"),
        expected_format="xlsx",
        addresses=("OUT-01", "CMP-05"),
    ),
    RequestItem(
        "financial-statements", "Audited financial statements", "document",
        "Signed financial statements for the financial year covering the period.",
        expected_format="pdf",
        satisfied_by="financials",
        addresses=("OUT-01",),
    ),
    RequestItem(
        "general-ledger", "General ledger extract — VAT accounts", "analysis",
        "Ledger movements on the output and input VAT control accounts for the period.",
        required_columns=("posting_date", "account_code", "reference", "description",
                          "debit", "credit"),
        mandatory_columns=("posting_date", "account_code"),
        expected_format="xlsx",
        addresses=("DAT-12", "COR-01"),
    ),
    RequestItem(
        "bank-statements", "Bank statements", "document",
        "Statements for all business accounts covering the period.",
        expected_format="pdf",
        addresses=("OUT-01", "POS"),
    ),
    RequestItem(
        "contracts", "Contracts and agreements", "document",
        "Signed contracts for the transactions under review, including any variation orders.",
        expected_format="pdf",
        addresses=("OUT-05", "T-TAXPOINT", "RCM-01"),
    ),
    RequestItem(
        "customs-declarations", "Import declarations", "document",
        "Customs declarations for goods imported in the period.",
        expected_format="pdf",
        satisfied_by="customs",             # ZATCA holds these — never ask
        addresses=("RCM-02", "INP-05"),
    ),
    RequestItem(
        "invoice-copies", "Copies of specific invoices", "document",
        "Copies of the invoices listed, with all mandatory fields visible.",
        expected_format="pdf",
        satisfied_by="e-invoices",          # held for anything cleared or reported
        addresses=("INP-01", "DAT-05", "DAT-02"),
    ),
    RequestItem(
        "vat-return-copies", "Copies of VAT returns filed", "document",
        "The returns as filed for the period and the two preceding periods.",
        expected_format="pdf",
        satisfied_by="vat-returns",         # held
        addresses=("CMP-01",),
    ),
    RequestItem(
        "reconciliation", "Reconciliation of the return to the ledger", "analysis",
        "A reconciliation between the VAT declared in the return and the VAT control account, "
        "with each reconciling item explained.",
        required_columns=("item", "amount", "explanation", "supporting_reference"),
        mandatory_columns=("item", "amount", "explanation"),
        expected_format="xlsx",
        addresses=("DAT-12", "OUT-01", "COR-01"),
        footed_by=("declared_vat", "amount"),
    ),
    RequestItem(
        "explanation-difference", "Written explanation of the difference", "explanation",
        "A written explanation of why the declared figure differs from the invoices issued in "
        "the period, referring to specific transactions.",
        expected_format="letter",
        addresses=("OUT-01", "DAT-12", "T-LATE"),
    ),
    RequestItem(
        "explanation-activity", "Explanation of business use", "explanation",
        "An explanation of how the listed purchases relate to the registered economic activity.",
        expected_format="letter",
        addresses=("INP-02", "INP-04"),
    ),
    RequestItem(
        "pos-report", "Point-of-sale settlement report", "analysis",
        "Daily settlement totals from every POS terminal operated in the period.",
        required_columns=("date", "terminal_id", "transactions", "gross_amount", "vat_amount"),
        mandatory_columns=("date", "terminal_id", "gross_amount"),
        expected_format="xlsx",
        addresses=("OUT-01", "POS"),
        footed_by=("total_gross", "gross_amount"),
    ),
    RequestItem(
        "fixed-asset-register", "Fixed asset register", "analysis",
        "Additions and disposals in the period, with the input VAT claimed on each.",
        required_columns=("asset_code", "description", "acquisition_date", "cost",
                          "vat_claimed", "disposal_date"),
        mandatory_columns=("asset_code", "acquisition_date", "cost"),
        expected_format="xlsx",
        addresses=("INP-02", "INP-06", "OUT-06"),
    ),
)

ITEM_BY_KEY = {i.key: i for i in CATALOG}

# Which items an auditor typically opens with, per risk indicator. The planner starts here and
# then subtracts anything the dossier already holds.
BY_INDICATOR: dict[str, tuple[str, ...]] = {
    "SALES_UNDERREPORTED": ("sales-analysis", "explanation-difference", "trial-balance",
                            "bank-statements"),
    "PURCHASE_SALES_RATIO": ("purchase-analysis", "sales-analysis", "explanation-activity",
                             "customs-declarations"),
    "FINANCIAL_DISCREPANCY": ("reconciliation", "trial-balance", "financial-statements",
                              "explanation-difference"),
    "POS_RISK": ("pos-report", "sales-analysis", "bank-statements"),
    "FINANCIAL_STATUS": ("financial-statements", "bank-statements"),
    "EINV_VS_RETURN": ("sales-analysis", "credit-note-listing", "reconciliation",
                       "explanation-difference"),
}


def items_for_indicator(code: str) -> tuple[RequestItem, ...]:
    return tuple(ITEM_BY_KEY[k] for k in BY_INDICATOR.get(code, ()) if k in ITEM_BY_KEY)
