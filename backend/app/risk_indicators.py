"""The risk-engine indicator catalogue — what the upstream engine can say about a case.

The engine itself is out of scope: E-AUDIT begins *after* it has flagged a taxpayer + period.
What we need from it is a **structured** verdict, because the precedent agent's whole question
is "what happened the last N times the engine said *this*", and a free-text reason cannot be
grouped.

These six indicators are the risk areas the auditors named. The codes are ours — flagged as
placeholders in the code dictionary — and should be replaced with the engine's real emissions
before this is anything but a demo. Everything downstream keys on `code`, so swapping the
catalogue is a one-file change.

`evidence_hint` is the deterministic half of the planner: which of ZATCA's own sources bear on
this indicator, so the auditor is pointed at internal data before drafting any request.
"""
from __future__ import annotations

from typing import NamedTuple


class Indicator(NamedTuple):
    code: str
    label: str
    description: str
    # the boxes/directions a case of this kind usually turns on
    focus: tuple[str, ...]
    # internal sources to consult first (§1 — do not ask for what ZATCA already holds)
    evidence_hint: tuple[str, ...]


INDICATORS: tuple[Indicator, ...] = (
    Indicator(
        "SALES_UNDERREPORTED",
        "Potential underreporting of sales",
        "Declared output VAT looks low against the supplies the taxpayer's own e-invoices, "
        "POS activity or sector peers imply.",
        ("output",),
        ("e-invoices", "vat-returns", "financials", "pos"),
    ),
    Indicator(
        "PURCHASE_SALES_RATIO",
        "Unusual purchases-to-sales relationship",
        "Input VAT claimed is out of proportion to declared output — stock building, "
        "misclassification, or purchases that do not belong to the business.",
        ("input", "output"),
        ("e-invoices", "vat-returns", "financials", "customs"),
    ),
    Indicator(
        "FINANCIAL_DISCREPANCY",
        "Financial discrepancy",
        "Declared VAT turnover does not agree with the turnover in the financial information "
        "ZATCA already holds.",
        ("output",),
        ("vat-returns", "financials"),
    ),
    Indicator(
        "POS_RISK",
        "POS-related risk",
        "Point-of-sale activity is inconsistent with declared retail supplies — unregistered "
        "terminals, or settlement volumes above declared sales.",
        ("output",),
        ("pos", "vat-returns", "e-invoices"),
    ),
    Indicator(
        "FINANCIAL_STATUS",
        "Financial-status risk",
        "Solvency, arrears or collectability signals that change how urgently a case should be "
        "worked, independent of the size of any error.",
        (),
        ("financials", "payment-history", "prior-audits"),
    ),
    Indicator(
        "EINV_VS_RETURN",
        "E-invoicing versus VAT return difference",
        "The return does not agree with the cleared and reported e-invoice population once "
        "qualification rules are applied.",
        ("output", "input"),
        ("e-invoices", "vat-returns"),
    ),
)

BY_CODE = {i.code: i for i in INDICATORS}

# Sources the dossier can carry, and the label the UI shows for each.
SOURCES = {
    "vat-returns": "VAT returns",
    "e-invoices": "E-invoicing (FATOORA)",
    "customs": "Imports & exports",
    "financials": "Financial information",
    "prior-audits": "Previous audits",
    "payment-history": "Filing & payment history",
    "pos": "Point of sale",
    "risk-analysis": "Risk analysis",
}


def get(code: str) -> Indicator | None:
    return BY_CODE.get(code)


def label(code: str) -> str:
    ind = BY_CODE.get(code)
    return ind.label if ind else code


def evidence_hint(code: str) -> tuple[str, ...]:
    ind = BY_CODE.get(code)
    return ind.evidence_hint if ind else ()
