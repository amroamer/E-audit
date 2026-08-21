"""Adjudicating the document tests — the ones that read the taxpayer's uploaded rows.

These settle the hypotheses the post-receipt roster raises. Every one is arithmetic, date logic
or field presence over the extracted rows: nothing here exercises judgement, which is why an
agent is allowed to *propose* a finding but never to reach one.

Two conventions carried over from the original tests, because they are what make the verdicts
usable:

* **"Confirmed" means the defect exists.** These hypotheses assert a problem, so confirming one
  is a finding. A refutation is the good outcome for the taxpayer.
* **Insufficient evidence is a real verdict**, not a failure. A column that is not there cannot
  be tested, and saying so is more useful than a confident answer computed from nothing.

`amount` is the SAR at stake, computed here. The agent that proposed the test never sees it.
"""
from __future__ import annotations

def _plural(n: int, word: str, plural: str = "") -> str:
    """'1 line' / '3 lines'. These sentences reach a report and a taxpayer letter, and "line(s)"
    reads as a note the author never finished."""
    return f"{n} {word if n == 1 else (plural or word + 's')}"

from datetime import date

from .calculation import as_date, as_number
from .contracts import Adjudication, Hypothesis

MAX_CITED = 6

# The conditions a tax invoice must satisfy for the deduction to stand. Field presence only —
# the substantive questions (is the supply real, is the supplier registered) are not answerable
# from a spreadsheet, and pretending otherwise would be the worst kind of false confidence.
INVOICE_CONDITIONS = {
    "sale": ("invoice_date", "invoice_number", "customer_name", "taxable_amount", "vat_amount"),
    "purchase": ("invoice_date", "invoice_number", "supplier_name", "supplier_vat_number",
                 "taxable_amount", "vat_amount"),
}
CREDIT_NOTE_CONDITIONS = ("note_date", "note_number", "original_invoice_number")

# Expense categories on which input VAT is not recoverable. Deliberately a small, explicit list:
# it is the placeholder for the article corpus the auditors are supplying, and naming it here
# keeps the shape honest — when the real articles land, this becomes a lookup against them.
BLOCKED_TERMS = (
    "entertainment", "hospitality", "catering", "restaurant", "hotel accommodation",
    "passenger vehicle", "private car", "employee benefit", "staff welfare", "gift",
    "club membership", "recreation",
)


def _doc(ctx, name: str) -> dict | None:
    if not name:
        return None
    low = name.strip().lower()
    for d in ctx.documents:
        if (d.get("filename") or "").strip().lower() == low:
            return d
    return None


def _idx(columns: list[str], name: str) -> int:
    try:
        return columns.index(name)
    except ValueError:
        return -1


def _cell(row: list, i: int):
    return row[i] if 0 <= i < len(row) else None


def _blank(v) -> bool:
    return v is None or str(v).strip() == ""


def _cite(rows: list[dict]) -> list[dict]:
    return rows[:MAX_CITED]


def _no_doc(h: Hypothesis, name: str) -> Adjudication:
    return Adjudication(
        hypothesis_id=h.id, status="insufficient-evidence",
        explanation=f"{name or 'The document'} is not among the files received, so the test "
                    f"could not be run.")


# ------------------------------------------------------------- document conditions
def _conditions(h: Hypothesis, ctx, required: tuple[str, ...], label: str) -> Adjudication:
    name = h.test.params.get("document", "")
    doc = _doc(ctx, name)
    if doc is None:
        return _no_doc(h, name)
    columns = list(doc.get("columns") or [])
    rows = list(doc.get("rows") or [])

    absent = [c for c in required if _idx(columns, c) < 0]
    present = [c for c in required if _idx(columns, c) >= 0]
    if not present:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            detail={"filename": name, "missing_columns": absent},
            explanation=f"{name} carries none of the fields a {label} must show, so individual "
                        f"rows cannot be tested. The document itself is the problem.")

    failing, amount = [], 0.0
    for n, row in enumerate(rows, start=1):
        missing = [c for c in present if _blank(_cell(row, _idx(columns, c)))]
        if not missing:
            continue
        vat = as_number(_cell(row, _idx(columns, "vat_amount"))) or 0.0
        amount += vat
        failing.append({"row": n, "missing": missing,
                        "invoice_number": _cell(row, _idx(columns, "invoice_number")),
                        "note_number": _cell(row, _idx(columns, "note_number")),
                        "vat_amount": vat})

    detail = {"basis": f"conditions|{h.test.box}|{name}",
              "filename": name, "rows_tested": len(rows), "rows_failing": len(failing),
              "columns_absent": absent, "conditions_checked": present,
              "examples": _cite(failing)}
    if not failing and not absent:
        return Adjudication(
            hypothesis_id=h.id, status="refuted", detail=detail,
            explanation=f"All {len(rows)} rows in {name} carry every field a {label} must show.")
    if not failing:
        return Adjudication(
            hypothesis_id=h.id, status="confirmed", amount=0.0, detail=detail,
            explanation=(f"{name} does not carry {', '.join(absent)}, so the {label} conditions "
                         f"cannot be evidenced from it even though the rows present are "
                         f"complete."))
    return Adjudication(
        hypothesis_id=h.id, status="confirmed", amount=round(amount, 2), detail=detail,
        explanation=(f"{len(failing)} of {len(rows)} rows in {name} are missing "
                     f"{', '.join(sorted({m for f in failing for m in f['missing']}))}, "
                     f"carrying SAR {abs(amount):,.2f} of VAT between them."))


def invoice_conditions(h: Hypothesis, ctx) -> Adjudication:
    direction = "purchase" if h.test.box == "input" else "sale"
    return _conditions(h, ctx, INVOICE_CONDITIONS[direction], "valid tax invoice")


def credit_note_conditions(h: Hypothesis, ctx) -> Adjudication:
    return _conditions(h, ctx, CREDIT_NOTE_CONDITIONS, "valid credit note")


# ------------------------------------------------------------------- blocked input
def blocked_input(h: Hypothesis, ctx) -> Adjudication:
    """Input VAT claimed on categories it cannot be recovered on.

    Matching is on the description the taxpayer wrote, which is evidence of what was bought and
    nothing more. The verdict therefore says *these lines need review against the article*, and
    the citation is the row — the auditor decides, which is where §6 puts it.
    """
    name = h.test.params.get("document", "")
    doc = _doc(ctx, name)
    if doc is None:
        return _no_doc(h, name)
    columns = list(doc.get("columns") or [])
    d_idx = _idx(columns, "description")
    if d_idx < 0:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            detail={"filename": name, "columns": columns},
            explanation=f"{name} has no description column, so what was purchased cannot be "
                        f"tested against the blocked categories.")

    v_idx = _idx(columns, "vat_amount")
    hits, amount = [], 0.0
    for n, row in enumerate(doc.get("rows") or [], start=1):
        text = str(_cell(row, d_idx) or "").lower()
        term = next((t for t in BLOCKED_TERMS if t in text), "")
        if not term:
            continue
        vat = as_number(_cell(row, v_idx)) or 0.0
        amount += vat
        hits.append({"row": n, "term": term, "description": _cell(row, d_idx),
                     "vat_amount": vat})

    detail = {"basis": f"blocked|{h.test.box}|{name}",
              "filename": name, "rows_matched": len(hits), "examples": _cite(hits),
              "terms": sorted({h_["term"] for h_ in hits})}
    if not hits:
        return Adjudication(
            hypothesis_id=h.id, status="refuted", detail=detail,
            explanation=f"No line in {name} describes a purchase in a category on which input "
                        f"VAT is blocked.")
    return Adjudication(
        hypothesis_id=h.id, status="confirmed", amount=round(amount, 2), detail=detail,
        explanation=(f"{_plural(len(hits), 'line')} in {name} describe purchases in blocked categories "
                     f"({', '.join(detail['terms'])}), carrying SAR {abs(amount):,.2f} of input "
                     f"VAT. Each needs review against the article before the claim is allowed."))


# ----------------------------------------------------------------- missing support
def missing_support(h: Hypothesis, ctx) -> Adjudication:
    """Claimed lines with no document reference or no supplier identity behind them."""
    name = h.test.params.get("document", "")
    doc = _doc(ctx, name)
    if doc is None:
        return _no_doc(h, name)
    columns = list(doc.get("columns") or [])
    keys = [c for c in ("invoice_number", "supplier_vat_number") if _idx(columns, c) >= 0]
    if not keys:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            detail={"filename": name, "columns": columns},
            explanation=f"{name} identifies neither the invoice nor the supplier, so no line in "
                        f"it can be traced to a supporting document.")

    v_idx = _idx(columns, "vat_amount")
    unsupported, amount = [], 0.0
    for n, row in enumerate(doc.get("rows") or [], start=1):
        missing = [k for k in keys if _blank(_cell(row, _idx(columns, k)))]
        if not missing:
            continue
        vat = as_number(_cell(row, v_idx)) or 0.0
        amount += vat
        unsupported.append({"row": n, "missing": missing, "vat_amount": vat})

    detail = {"basis": f"support|{h.test.box}|{name}",
              "filename": name, "rows_unsupported": len(unsupported),
              "identifiers_checked": keys, "examples": _cite(unsupported)}
    if not unsupported:
        return Adjudication(
            hypothesis_id=h.id, status="refuted", detail=detail,
            explanation=f"Every line in {name} identifies the invoice and supplier behind it.")
    return Adjudication(
        hypothesis_id=h.id, status="confirmed", amount=round(amount, 2), detail=detail,
        explanation=(f"{_plural(len(unsupported), 'line')} in {name} carry no "
                     f"{' or '.join(sorted({m for u in unsupported for m in u['missing']}))}, "
                     f"so SAR {abs(amount):,.2f} of input VAT has nothing behind it."))


# ------------------------------------------------------------ listing vs declared
def listing_vs_declared(h: Hypothesis, ctx) -> Adjudication:
    """Total the taxpayer's own document and set it against the box they declared."""
    name = h.test.params.get("document", "")
    doc = _doc(ctx, name)
    if doc is None:
        return _no_doc(h, name)
    columns = list(doc.get("columns") or [])
    v_idx = _idx(columns, "vat_amount")
    if v_idx < 0:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            detail={"filename": name, "columns": columns},
            explanation=f"{name} has no VAT amount column, so it cannot be totalled against the "
                        f"declared box.")

    box = ctx.box(h.test.box)
    declared = float(box["declared"])
    rows = doc.get("rows") or []
    nums = [n for n in (as_number(_cell(r, v_idx)) for r in rows) if n is not None]
    if not nums:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            detail={"filename": name},
            explanation=f"No numeric VAT values could be read from {name}.")

    total = round(sum(nums), 2)
    excess = round(total - declared, 2)
    # Every finding that rests on "this document totals more than the box" shares one basis,
    # whichever test surfaced it — they are readings of a single excess, not separate money.
    detail = {"basis": f"excess|{h.test.box}|{name}",
              "filename": name, "listing_total": total, "declared": declared,
              "excess": excess, "rows": len(nums), "materiality": box["materiality"]}

    if excess > box["materiality"]:
        return Adjudication(
            hypothesis_id=h.id, status="confirmed", amount=excess, detail=detail,
            explanation=(f"{name} totals SAR {total:,.2f} across {len(nums)} rows against SAR "
                         f"{declared:,.2f} declared — SAR {abs(excess):,.2f} more than the "
                         f"return reports."))
    if excess < -box["materiality"]:
        return Adjudication(
            hypothesis_id=h.id, status="refuted", detail=detail,
            explanation=(f"{name} totals SAR {total:,.2f}, which is less than the SAR "
                         f"{declared:,.2f} declared. The return is not understated on this "
                         f"document."))
    return Adjudication(
        hypothesis_id=h.id, status="refuted", detail=detail,
        explanation=(f"{name} totals SAR {total:,.2f} against SAR {declared:,.2f} declared — "
                     f"they agree within materiality."))


# --------------------------------------------------------------- trial balance
def trial_balance_absent(h: Hypothesis, ctx) -> Adjudication:
    """The listing exceeds the return *and* nothing was supplied to substantiate it.

    Two conditions, and both matter. A missing trial balance is not itself a finding — it only
    becomes one when there is an excess that cannot be traced into the accounts without it.
    """
    if ctx.has_document_like("trial", "balance"):
        return Adjudication(hypothesis_id=h.id, status="refuted",
                            explanation="A trial balance was supplied.")
    inner = listing_vs_declared(h, ctx)
    if inner.status != "confirmed":
        return Adjudication(
            hypothesis_id=h.id, status="refuted", detail=inner.detail,
            explanation="No trial balance was supplied, but the records submitted do not exceed "
                        "the declared sales, so there is nothing to substantiate.")
    return Adjudication(
        hypothesis_id=h.id, status="confirmed", amount=inner.amount,
        detail={**inner.detail, "trial_balance": "not supplied"},
        explanation=inner.explanation + " No trial balance was supplied to substantiate it.")


# ------------------------------------------------------------ secondary activity
def secondary_activity(h: Hypothesis, ctx) -> Adjudication:
    """Revenue described in terms that match none of the registered activities.

    This is the outcome that needs the CR: without the registered activity list there is nothing
    to be outside of. It flags for review rather than concluding — a description is weak evidence
    of an activity, and the auditor is the one who decides.
    """
    if not ctx.cr_activities:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            explanation="The registration's economic activities are not on file, so revenue "
                        "cannot be tested against them.")
    name = h.test.params.get("document", "")
    doc = _doc(ctx, name)
    if doc is None:
        return _no_doc(h, name)
    columns = list(doc.get("columns") or [])
    d_idx = _idx(columns, "description")
    if d_idx < 0:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            detail={"filename": name},
            explanation=f"{name} has no description column, so supplies cannot be matched to the "
                        f"registered activities.")

    # the vocabulary of what this taxpayer is registered to do
    words: set[str] = set()
    for a in ctx.cr_activities:
        for w in str(a.get("description", "")).lower().replace(",", " ").split():
            if len(w) > 4:
                words.add(w.strip("()-"))
    if not words:
        return Adjudication(
            hypothesis_id=h.id, status="insufficient-evidence",
            explanation="The registered activities carry no descriptions to match against.")

    v_idx = _idx(columns, "vat_amount")
    outside, amount = [], 0.0
    for n, row in enumerate(doc.get("rows") or [], start=1):
        text = str(_cell(row, d_idx) or "").lower()
        if not text.strip():
            continue
        if any(w in text for w in words):
            continue
        vat = as_number(_cell(row, v_idx)) or 0.0
        amount += vat
        outside.append({"row": n, "description": _cell(row, d_idx), "vat_amount": vat})

    detail = {"basis": f"activity|{h.test.box}|{name}",
              "filename": name, "rows_outside": len(outside),
              "activities": [a.get("description") for a in ctx.cr_activities],
              "examples": _cite(outside)}
    if not outside:
        return Adjudication(
            hypothesis_id=h.id, status="refuted", detail=detail,
            explanation="Every supply described in the listing matches a registered activity.")
    return Adjudication(
        hypothesis_id=h.id, status="confirmed", amount=round(amount, 2), detail=detail,
        explanation=(f"{_plural(len(outside), 'line')} in {name} describe supplies that match none of the "
                     f"registered activities, carrying SAR {abs(amount):,.2f} of VAT. Review "
                     f"whether they belong to an activity the return does not disclose."))


# -------------------------------------------------------------- non-cooperation
def non_cooperation(h: Hypothesis, ctx) -> Adjudication:
    outstanding = [g for g in ctx.gaps if g.get("kind") == "missing-item"]
    if not outstanding:
        return Adjudication(hypothesis_id=h.id, status="refuted",
                            explanation="Everything requested has been supplied.")
    labels = sorted({g.get("item_label", "") for g in outstanding if g.get("item_label")})
    return Adjudication(
        hypothesis_id=h.id, status="confirmed", amount=0.0,
        detail={"basis": "non-cooperation", "outstanding": len(outstanding), "items": labels},
        explanation=(f"{_plural(len(outstanding), 'requested item')} {'remains' if len(outstanding) == 1 else 'remain'} outstanding"
                     + (f" — {', '.join(labels)}" if labels else "")
                     + ". Claims that depend on them cannot be substantiated."))


# --------------------------------------------------------------- auditor figure
def auditor_figure(h: Hypothesis, ctx) -> Adjudication:
    """Figures recorded during the review that the engine could not reproduce.

    Confirming this is a finding against our own working, not the taxpayer's — which is exactly
    why the auditors asked for it.
    """
    bad = [c for c in ctx.calculations if c.get("status") == "disagree"]
    if not bad:
        checked = len(ctx.calculations)
        return Adjudication(
            hypothesis_id=h.id, status="refuted", detail={"checked": checked},
            explanation=(f"All {_plural(checked, 'recorded figure')} were reproduced from the documents "
                         f"they were taken from." if checked else
                         "No figures have been recorded on this case to check."))
    worst = max(bad, key=lambda c: abs(float(c.get("delta") or 0)))
    return Adjudication(
        hypothesis_id=h.id, status="confirmed",
        amount=round(abs(float(worst.get("delta") or 0)), 2),
        detail={"disagreements": len(bad),
                "items": [{"label": c.get("label"), "stated": c.get("stated"),
                           "computed": c.get("computed"), "delta": c.get("delta")}
                          for c in bad[:MAX_CITED]]},
        explanation=(f"{_plural(len(bad), 'recorded figure')} could not be reproduced. The largest, "
                     f"'{worst.get('label')}', was recorded as SAR "
                     f"{abs(float(worst.get('stated') or 0)):,.2f} against SAR "
                     f"{abs(float(worst.get('computed') or 0)):,.2f} recomputed."))


TESTS = {
    "invoice-conditions": invoice_conditions,
    "credit-note-conditions": credit_note_conditions,
    "blocked-input": blocked_input,
    "missing-support": missing_support,
    "listing-vs-declared": listing_vs_declared,
    "trial-balance-absent": trial_balance_absent,
    "secondary-activity": secondary_activity,
    "non-cooperation": non_cooperation,
    "auditor-figure": auditor_figure,
}
