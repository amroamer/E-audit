"""Where the lines the engine qualifies come from.

The PoC now starts when the taxpayer's documents arrive, so the population under review is the
**listing they sent**, not a store of cleared e-invoices the Authority holds. This module builds
the same line grain `pipeline.run.qualify()` consumes, from an uploaded spreadsheet instead.

The important thing is what a spreadsheet **cannot** tell you, and saying so rather than filling
the gap with an assumption:

* **No clearance status.** A listing is the taxpayer's own account of what they issued. There is
  no `STATUSCODE` behind it, so every row is taken at face value as reported. That is not the
  same claim as "cleared", and the status rule cannot do its usual work of setting rejected or
  cancelled documents aside — nothing in the file distinguishes them.
* **Usually no delivery date.** Tax-point straddle rules (OUT-07, INP-09) need one. A listing
  that carries a delivery column gets the rule; one that does not simply does not fire it. The
  rule is not "assumed satisfied" — it never matches, and the funnel shows no step for it,
  which is the honest reading: nothing in the evidence places those supplies in another period.
* **No counterparty classification.** The government-platform rule (OUT-11) is scoped by
  counterparty class, which a spreadsheet does not carry, so it cannot fire either.

The consequence is deliberate and worth stating plainly: **fewer rules can fire on an uploaded
listing than on an e-invoice feed**, so the expected figure is closer to the raw total. That is
a property of the evidence, not a weakening of the engine, and it is why the qualification
funnel still earns its place — it shows exactly which rules had something to act on.

A row is read as a credit note when the document number says so or the amount is negative,
because that is the only signal a listing gives.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from ..agents.calculation import as_date, as_number

TAX_INVOICE = 388
CREDIT_NOTE = 381

# what a listing must carry before any line can be built from it
ESSENTIAL = ("vat_amount",)

# columns whose presence unlocks a rule that would otherwise never match
OPTIONAL_SIGNALS = ("delivery_date", "counterparty_class", "status")

_NOTE_HINTS = ("cn-", "cr-", "credit", "note")


def _idx(columns: list[str], name: str) -> int:
    try:
        return columns.index(name)
    except ValueError:
        return -1


def _cell(row: list, i: int) -> Any:
    return row[i] if 0 <= i < len(row) else None


def _looks_like_a_note(number: Any, tax: float, doc_type: Any) -> bool:
    """A listing gives three hints and no document-type code, so all three are used."""
    if doc_type is not None and str(doc_type).strip() in (str(CREDIT_NOTE), "credit note"):
        return True
    text = str(number or "").strip().lower()
    if any(h in text for h in _NOTE_HINTS):
        return True
    return tax < 0


def capability(columns: list[str]) -> dict:
    """What this document lets the engine do — reported so the funnel can be read honestly."""
    present = [c for c in OPTIONAL_SIGNALS if c in columns]
    return {
        "has_delivery_date": "delivery_date" in columns,
        "has_status": "status" in columns,
        "has_counterparty_class": "counterparty_class" in columns,
        "signals_present": present,
        "note": ("Tax-point and status rules can act on this document."
                 if present else
                 "This listing carries no delivery date, clearance status or counterparty "
                 "class, so timing and status rules have nothing to act on. Every row is "
                 "taken as reported."),
    }


def lines_from_document(doc: dict, *, direction: str, period_from: date, period_to: date,
                        sector: str = "", default_rate: int = 15) -> list[dict]:
    """Build qualification lines from one uploaded listing.

    Rows that carry no readable VAT amount are skipped rather than counted as zero — a blank
    or unreadable cell is a completeness problem, and the completeness checker already reports
    it. Summing it as nothing here would quietly shrink the expected figure instead.
    """
    columns = list(doc.get("columns") or [])
    if not all(c in columns for c in ESSENTIAL):
        return []

    i_vat = _idx(columns, "vat_amount")
    i_base = _idx(columns, "taxable_amount")
    i_rate = _idx(columns, "vat_rate")
    i_date = _idx(columns, "invoice_date")
    i_note_date = _idx(columns, "note_date")
    i_num = _idx(columns, "invoice_number")
    i_note_num = _idx(columns, "note_number")
    i_delivery = _idx(columns, "delivery_date")
    i_status = _idx(columns, "status")
    i_cp = _idx(columns, "counterparty_class")
    i_type = _idx(columns, "document_type")

    filename = doc.get("filename", "")
    out: list[dict] = []
    for n, row in enumerate(doc.get("rows") or [], start=1):
        tax = as_number(_cell(row, i_vat))
        if tax is None:
            continue
        base = as_number(_cell(row, i_base))
        raw_rate = as_number(_cell(row, i_rate))
        if raw_rate is None:
            rate = default_rate
        elif 0 < raw_rate < 1:
            rate = round(raw_rate * 100)   # 0.15 is 15% written another way
        else:
            rate = int(raw_rate)

        number = _cell(row, i_num) or _cell(row, i_note_num)
        is_note = _looks_like_a_note(number, tax, _cell(row, i_type))
        issued = as_date(_cell(row, i_date)) or as_date(_cell(row, i_note_date))

        out.append({
            # provenance, so a drill-down can point at the row the auditor can open
            "source": "document",
            "document": filename,
            "row_number": n,
            "invoice_uuid": str(number or f"{filename}#{n}"),
            "type_code": CREDIT_NOTE if is_note else TAX_INVOICE,
            "direction": direction,
            # A listing is what the taxpayer says they issued. There is no clearance behind it,
            # so "reported" is the truthful status — never "cleared", which would assert
            # something the document does not evidence.
            "status": str(_cell(row, i_status) or "reported").strip().lower() or "reported",
            "issue_date": issued,
            "delivery_date": as_date(_cell(row, i_delivery)) if i_delivery >= 0 else None,
            "approval_date": None,
            "counterparty_class": str(_cell(row, i_cp) or "").strip().lower(),
            "sector": sector,
            "category": "S" if rate == 15 else ("Z" if rate == 0 else "S"),
            "rate": rate,
            "taxable_amount": float(base) if base is not None else round(tax / (rate / 100), 2)
            if rate else 0.0,
            "tax_amount": float(tax),
            "period_from": period_from,
            "period_to": period_to,
        })
    return out


def pick_listing(documents: list[dict], direction: str) -> dict | None:
    """The uploaded listing for a direction, chosen by filename then by column shape.

    Name first because auditors name these files clearly and a name is a stated intention.
    Shape second: a listing with a supplier column is a purchase listing whatever it is called.
    """
    hints = {"sale": ("sales", "revenue", "output", "sale"),
             "purchase": ("purchase", "input", "expense", "supplier")}[direction]
    for d in documents:
        if any(h in (d.get("filename") or "").lower() for h in hints):
            return d
    marker = "customer_name" if direction == "sale" else "supplier_name"
    alt = "customer_vat_number" if direction == "sale" else "supplier_vat_number"
    for d in documents:
        cols = d.get("columns") or []
        if "vat_amount" in cols and (marker in cols or alt in cols):
            return d
    return None


def document_rows(documents: list[dict], *, direction: str, period_from: date, period_to: date,
                  sector: str = "") -> tuple[list[dict], dict | None]:
    """The lines for a direction, and the document they came from (None if there is none)."""
    doc = pick_listing(documents, direction)
    if doc is None:
        return [], None
    return lines_from_document(doc, direction=direction, period_from=period_from,
                               period_to=period_to, sector=sector), doc
