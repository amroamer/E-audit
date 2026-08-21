"""Render the audit report as something an auditor can file: a Word document or a printed page.

The auditors asked for the report as a download, in Word or PDF. Both come from one HTML render
rather than two layout engines, for the same reason the numbers come from one place: a Word
export and a PDF export that were built separately would drift, and the auditor would have two
documents that disagree about a case.

* **Word** — HTML served as `application/msword`. Word opens it, keeps the headings, tables and
  page break, and the auditor can edit it. No third-party dependency, which matters because this
  has to work in the standalone portal too, where there is no Python at all.
* **PDF** — the same HTML with a print stylesheet. The browser's own print-to-PDF is the
  renderer. Shipping a PDF engine to produce a document the browser already produces would be
  weight for nothing.

The `[not held]` and `[for the auditor to complete]` markers are styled rather than hidden. A
report that quietly dropped its unanswered fields would look finished when it is not, and the
auditor would find out at the wrong moment.
"""
from __future__ import annotations

import html
import re
from datetime import date

# Word reads a subset of CSS, and only from an inline <style> block in the head. Print rules are
# ignored by Word and used by the browser, so one document serves both.
_STYLE = """
@page { size: A4; margin: 2cm; }
body { font-family: "Segoe UI", Calibri, Arial, sans-serif; font-size: 11pt; color: #14202b;
       line-height: 1.45; }
h1 { font-size: 20pt; margin: 0 0 2pt; color: #0f5c4a; }
h2 { font-size: 13pt; margin: 22pt 0 6pt; color: #0f5c4a;
     border-bottom: 1pt solid #0f5c4a; padding-bottom: 3pt; }
.sub { color: #5a6b78; font-size: 10pt; margin: 0 0 4pt; }
table { border-collapse: collapse; width: 100%; margin: 0 0 6pt; }
td { border: 0.75pt solid #c9d4dc; padding: 6pt 8pt; vertical-align: top; }
td.k { width: 30%; background: #f2f6f8; font-weight: 600; }
td.v { white-space: pre-wrap; }
.note { display: block; color: #5a6b78; font-size: 8.5pt; font-style: italic; margin-top: 3pt; }
.gap { color: #9a6b00; font-weight: 600; }
.foot { margin-top: 24pt; padding-top: 8pt; border-top: 0.75pt solid #c9d4dc;
        color: #5a6b78; font-size: 9pt; }
@media print { .noprint { display: none; } h2 { page-break-after: avoid; }
               tr { page-break-inside: avoid; } }
"""

_MARKERS = ("[not held]", "[for the auditor to complete]")


def _value(text: str) -> str:
    """Escape the value, then mark the two "we do not have this" tokens so they read as gaps."""
    out = html.escape(str(text or ""))
    for marker in _MARKERS:
        out = out.replace(html.escape(marker), f'<span class="gap">{html.escape(marker)}</span>')
    return out


def to_html(report: dict, *, for_word: bool = False) -> str:
    """The whole report as one self-contained HTML document."""
    rows: list[str] = []
    for section in report.get("sections") or []:
        rows.append(f"<h2>{html.escape(section['title'])}</h2><table>")
        for f in section.get("fields") or []:
            note = (f'<span class="note">{html.escape(f["note"])}</span>'
                    if f.get("note") else "")
            rows.append(f'<tr><td class="k">{html.escape(f["label"])}</td>'
                        f'<td class="v">{_value(f["value"])}{note}</td></tr>')
        rows.append("</table>")

    completeness = report.get("completeness") or {}
    outstanding = completeness.get("outstanding", 0)
    filled = completeness.get("filled", 0)
    fields = completeness.get("fields", 0)
    banner = (f"{filled} of {fields} fields are answered from the case. "
              f"{outstanding} still need the auditor or another ZATCA system.")

    # Word ignores the print button; the browser hides it when printing.
    button = "" if for_word else (
        '<p class="noprint"><button onclick="window.print()" '
        'style="font:inherit;padding:6pt 14pt;border:1px solid #0f5c4a;background:#0f5c4a;'
        'color:#fff;border-radius:4px;cursor:pointer">Print / Save as PDF</button></p>')

    return (
        "<!DOCTYPE html>\n"
        '<html><head><meta charset="utf-8">'
        f"<title>{html.escape(report.get('title', 'Audit report'))} — "
        f"{html.escape(report.get('case_id', ''))}</title>"
        f"<style>{_STYLE}</style></head><body>"
        f"<h1>{html.escape(report.get('title', 'Audit report'))}</h1>"
        f'<p class="sub">{html.escape(report.get("taxpayer", ""))} · '
        f'{html.escape(report.get("case_id", ""))} · '
        f'prepared {date.today().strftime("%d %B %Y")}</p>'
        f'<p class="sub">{html.escape(banner)}</p>'
        f"{button}"
        + "".join(rows)
        + '<p class="foot">Every figure in this report was computed by the audit engine from '
          'the documents on the case file. Fields marked as outstanding were left for a person '
          'to complete rather than filled from an assumption.</p>'
          "</body></html>"
    )


def filename_for(report: dict, extension: str) -> str:
    """A filename an auditor can find again: the case, the taxpayer, the date."""
    stem = f"Audit_report_{report.get('case_id', 'case')}_" \
           f"{re.sub(r'[^A-Za-z0-9]+', '_', report.get('taxpayer', '')).strip('_')}"
    return f"{stem[:90]}_{date.today().isoformat()}.{extension}"
