"""Read the auditor's stated method deterministically, before any model is asked.

The auditors described this step in their own words: *"it might be just a free text that they
tell you, I calculated X, Y, Z. This is what I got. Can you check it for me?"* So the input is a
sentence, not a form — and a sentence has to be interpreted before Python can recompute anything.

Interpretation is judgement work, which is why `llm.parse_calculation` exists. But the plainest
sentences are not judgement work at all: *"I summed the VAT column on the sales analysis"* names
an operation and a column, and reading it needs a cue table rather than a model. Sending it to
one anyway would mean the whole feature dies the moment there is no API key — and everything
else in this system stays usable without one.

So this is the first pass. It answers the sentences it is sure of and declines the rest, and the
model picks up whatever it declines. Deterministic first, model second, exactly as elsewhere.

**The decisive rule is what it refuses.** A method that carries a *condition* — "for January
only", "excluding the credit notes", "over SAR 50,000" — is not a bare aggregation, and reading
it as one would total the whole file and then report the auditor's correct figure as a
disagreement. Being wrongly told they have made an error is far more expensive to an auditor
than being told the sentence needs a model, so a condition this pass cannot express makes it
decline outright. It never silently drops a clause.
"""
from __future__ import annotations

import re

from . import calculation as calc

# The operation. Ordered: "how many distinct customers" must read as count_distinct, so the
# distinct cue is tested before the count cue.
OP_CUES: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"\b(distinct|unique|different)\b", re.I), "count_distinct"),
    (re.compile(r"\b(sum|summed|summing|total(?:led|ed|ling|ing)?|totals|added up|add up|"
                r"adding up|footed)\b", re.I), "sum"),
    (re.compile(r"\b(how many|count(?:ed|ing)?|number of)\b", re.I), "count"),
    (re.compile(r"\b(average|avg|mean)\b", re.I), "average"),
    (re.compile(r"\b(largest|highest|max(?:imum)?|biggest|greatest)\b", re.I), "max"),
    (re.compile(r"\b(smallest|lowest|min(?:imum)?)\b", re.I), "min"),
)

# The column, when the auditor names it the way an auditor talks rather than the way the
# spreadsheet's header row spells it. Only ever used to select a column the document actually
# has — this table can suggest a name, never invent one.
COLUMN_CUES: tuple[tuple[re.Pattern, tuple[str, ...]], ...] = (
    (re.compile(r"\b(vat|tax)\s*(amount|column|figures?)?\b", re.I),
     ("vat_amount", "tax_amount", "vat", "input_vat", "output_vat", "customs_vat")),
    (re.compile(r"\b(taxable|net|base|excluding vat|ex-vat|pre-vat)\b", re.I),
     ("taxable_amount", "net_amount", "base_amount", "amount")),
    (re.compile(r"\b(gross|inclusive|including vat|total amount)\b", re.I),
     ("gross_amount", "total_amount", "amount_including_vat")),
    (re.compile(r"\b(customer|client|buyer)s?\b", re.I), ("customer_name", "customer")),
    (re.compile(r"\b(supplier|vendor|seller)s?\b", re.I), ("supplier_name", "supplier")),
    (re.compile(r"\b(invoices?|invoice numbers?)\b", re.I), ("invoice_number",)),
    (re.compile(r"\brates?\b", re.I), ("vat_rate", "rate")),
)

# A clause this pass cannot turn into a filter. Its presence means the sentence is *not* a bare
# aggregation, so the deterministic reading is wrong even when the operation and column are
# obvious. See the module docstring: declining costs a model call, misreading costs the
# auditor's trust.
CONDITION_RE = re.compile(
    r"\b(only|just the|where|excluding|except|apart from|other than|without the|"
    r"greater than|more than|over|above|less than|below|under|between|at least|"
    r"before|after|up to|from the \w+ to|dated|during|in january|in february|in march|"
    r"in april|in may|in june|in july|in august|in september|in october|in november|"
    r"in december|first (?:month|quarter|half)|second (?:month|quarter|half)|"
    r"per (?:month|customer|supplier)|by (?:month|customer|supplier)|blank|missing|empty)\b",
    re.I)

# "and got 2,618,000" / "= SAR 2618000" / "I make it 2,618,000" — the figure the auditor says
# they arrived at, when they put it in the same sentence as the method.
_STATED_RES = (
    re.compile(r"\b(?:got|get|make it|makes it|comes to|came to|arrived at|totall?ing|"
               r"which is|equals?|=)\s*(?:sar|ريال)?\s*([\d][\d,\s]*(?:\.\d+)?)", re.I),
    re.compile(r"\bsar\s*([\d][\d,\s]*(?:\.\d+)?)", re.I),
    re.compile(r"\b(\d{1,3}(?:,\d{3})+(?:\.\d+)?)\b"),
)


def stated_amount_in(text: str) -> float | None:
    """The figure the sentence claims, if it states one.

    An auditor writing freely puts the answer in the same breath as the method. Making them
    retype it into a separate box is the kind of friction that gets a feature ignored, so it is
    read out of the sentence when it is unambiguous — and left to the form when it is not.
    """
    t = (text or "").strip()
    if not t:
        return None
    for pattern in _STATED_RES:
        m = pattern.search(t)
        if m:
            v = calc.as_number(m.group(1))
            if v is not None:
                return v
    return None


def label_for(text: str, limit: int = 72) -> str:
    """A short name for a calculation the auditor did not bother to name.

    The method sentence usually carries its own heading — everything before the auditor states
    what they got. Cutting mid-word instead would put "…and got 2,618,000 - can you check " in
    the case file as the name of the check.
    """
    t = " ".join((text or "").split())
    if not t:
        return ""
    t = re.split(r"\s+(?:and\s+)?(?:got|get|make it|makes it|comes to|came to|arrived at)\b|"
                 r"\s+[-—–]\s+|[?]", t, maxsplit=1, flags=re.I)[0].strip(" .,:;")
    if len(t) <= limit:
        return t
    cut = t[:limit].rsplit(" ", 1)[0]
    return (cut or t[:limit]).rstrip(" .,:;") + "…"


def _document(text: str, docs: list[dict]) -> dict | None:
    """The document the sentence names — by filename, by its stem, or by being the only one."""
    low = (text or "").lower()
    for d in docs:
        name = (d.get("filename") or "").strip().lower()
        if name and name in low:
            return d
    for d in docs:
        stem = re.split(r"[._\-]", (d.get("filename") or "").strip().lower())[0]
        if len(stem) > 3 and stem in low:
            return d
    # "the sales analysis", "the purchase listing" — the words an auditor uses for the file.
    for word, fragments in (("sales", ("sales",)), ("purchase", ("purchase", "input")),
                            ("credit", ("credit", "note")), ("bank", ("bank",)),
                            ("pos", ("pos", "point of sale")), ("trial", ("trial", "balance")),
                            ("import", ("import", "customs")), ("export", ("export",))):
        if re.search(rf"\b{word}", low):
            hits = [d for d in docs
                    if any(f in (d.get("filename") or "").lower() for f in fragments)]
            if len(hits) == 1:
                return hits[0]
    return docs[0] if len(docs) == 1 else None


def _column(text: str, columns: list[str]) -> str:
    """The column the sentence means, chosen only from the ones the document has."""
    low = (text or "").lower()
    cols = [c for c in columns if c]
    for c in sorted(cols, key=len, reverse=True):
        spaced = c.replace("_", " ").lower()
        if len(spaced) > 2 and (spaced in low or c.lower() in low):
            return c
    lookup = {c.lower(): c for c in cols}
    for pattern, candidates in COLUMN_CUES:
        if pattern.search(text or ""):
            for cand in candidates:
                if cand in lookup:
                    return lookup[cand]
    return ""


def read_method(text: str, docs: list[dict]) -> dict:
    """Turn a stated method into a query payload, or say why it cannot.

    The payload is the same shape `llm.parse_calculation` returns, so `_resolve` can use either
    without caring which produced it — and `calculation.query_from_dict` re-validates it against
    the closed algebra either way.
    """
    t = (text or "").strip()
    blank = {"op": "", "column": "", "filters": [], "document": "", "checkable": False,
             "source": "deterministic"}
    if not t:
        return {**blank, "understood": "Describe how the figure was calculated."}

    op = next((name for pattern, name in OP_CUES if pattern.search(t)), "")
    if not op:
        return {**blank, "understood": "No calculation was recognised in that description — "
                                       "say whether it was a total, a count or an average."}

    doc = _document(t, docs)
    columns = list(doc.get("columns") or []) if doc else sorted(
        {c for d in docs for c in (d.get("columns") or [])})
    # A plain count is over rows, and the executor ignores the column for it. Carrying one
    # anyway would have the query describe itself as "count(invoice_number)", which reads as a
    # count of the invoice numbers present — a different question, and one with a different
    # answer as soon as a row has none.
    column = "" if op == "count" else _column(t, columns)

    if op != "count" and not column:
        return {**blank, "op": op,
                "understood": f"Read as a {op.replace('_', ' ')}, but no column in the "
                              f"documents on file matches the description."}

    if CONDITION_RE.search(t):
        # Deliberate: the sentence narrows the rows, and dropping the clause would total the
        # whole file and then call the auditor's correct figure wrong.
        return {**blank, "op": op, "column": column,
                "document": (doc or {}).get("filename", ""),
                "understood": "That method sets a condition on which rows to include, which "
                              "this reading cannot apply on its own."}

    said = ("count the rows" if op == "count"
            else f"{op.replace('_', ' ')} of {column}")
    where = f" in {doc['filename']}" if doc else ""
    return {"op": op, "column": column, "filters": [],
            "document": (doc or {}).get("filename", ""),
            "understood": said + where, "checkable": True, "source": "deterministic"}
