"""Build the taxpayer's (deficient) response as a real spreadsheet.

The auditors' example was a sales analysis with eight named columns, answered with something
that omits columns, leaves mandatory fields blank and covers the wrong period. Seeding a
hand-written dict of "extracted" content would demonstrate the checker against its own
assumptions; generating an actual .xlsx and running the real extractor over it demonstrates the
path a real response takes.

The file is deliberately imperfect in five different ways at once, because that is what arrives:

* two requested columns are simply absent (customer VAT number, description);
* the columns that are present use the taxpayer's own names ("Invoice No.", "Net Amount"),
  which are correct information under a spelling the request did not use;
* the invoice number is blank on three rows;
* the rows stop a month short of the period requested;
* the total row states a figure one row larger than the rows beneath it.

Only the first, third, fourth and fifth are gaps. The second must NOT be — reporting a column
missing because the taxpayer called it something reasonable would destroy trust faster than
missing it entirely.
"""
from __future__ import annotations

import io
from datetime import date, timedelta

SALES_HEADERS = ("Invoice Date", "Invoice No.", "Customer", "Net Amount", "Rate", "VAT")

ROW_VAT = 119_000.0
ROW_BASE = 793_333.33
N_ROWS = 22
BLANK_INVOICE_ROWS = (7, 13, 18)          # 1-based, as the checker cites them
OVERSTATED_BY = ROW_VAT                   # the total claims one row that is not listed

CUSTOMERS = (
    "Gulf Retail Partners", "Coastal Distribution Est.", "Northern Supply Co.",
    "Central Markets LLC", "Peninsula Wholesale", "Eastern Trading House",
)


def sales_analysis_rows() -> list[list]:
    """22 rows spanning 6 January to 27 February — a month short of a Q1 request."""
    start = date(2025, 1, 6)
    rows: list[list] = []
    for i in range(1, N_ROWS + 1):
        d = start + timedelta(days=(i - 1) * 2 + (i // 6))
        number = "" if i in BLANK_INVOICE_ROWS else f"INV-2025-{1000 + i}"
        rows.append([d.isoformat(), number, CUSTOMERS[i % len(CUSTOMERS)],
                     ROW_BASE, "15%", ROW_VAT])
    return rows


def stated_total() -> float:
    return round(N_ROWS * ROW_VAT + OVERSTATED_BY, 2)


def sales_analysis_xlsx() -> bytes:
    """The response as the taxpayer would actually send it."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Sales Analysis — Q1 2025"])          # a title row above the header, as they do
    ws.append([])
    ws.append(list(SALES_HEADERS))
    for row in sales_analysis_rows():
        ws.append(row)
    ws.append(["Total", "", "", "", "", stated_total()])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
