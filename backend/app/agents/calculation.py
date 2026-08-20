"""Answer the auditor's arithmetic, and check the arithmetic they did themselves.

The auditors asked for two things: help computing totals off the documents the taxpayer sent,
and a second pair of eyes on figures they worked out by hand. Both are the same machine here,
because both reduce to *recompute it from source and say what you get*.

**The model never does arithmetic.** It reads the auditor's description of what they did —
"I summed the VAT column for everything dated in the quarter" — and turns it into a `CalcQuery`,
a typed question from a closed algebra. Python executes that query over the uploaded rows and
produces the number. An arithmetic agent that could hallucinate a total would be worse than no
agent at all, so the model is kept strictly on the parsing side of the line, exactly as it is
everywhere else in this system.

The algebra is deliberately small. It covers what an auditor actually asks a spreadsheet —
totals, counts, distinct counts, averages, extremes, optionally filtered by date range, value
threshold, text match or blankness. Anything outside it comes back as *not checkable*, which is
an honest answer. A query language wide enough to express everything would also be wide enough
to express something nobody can review.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

TOLERANCE = 1.0        # SAR — the same one riyal the adjudicator and completeness work to

AGGREGATIONS = ("sum", "count", "count_distinct", "average", "max", "min")
FILTER_OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "between", "contains",
              "is_blank", "not_blank")

AGREE = "agree"
DISAGREE = "disagree"
NOT_CHECKABLE = "not-checkable"


# ------------------------------------------------------------------------ coercion
_NUM_CLEAN_RE = re.compile(r"[,\s ']")
_PAREN_NEG_RE = re.compile(r"^\((.*)\)$")


def as_number(v: Any) -> float | None:
    """A cell as a number, or None if it is not one.

    Spreadsheets from taxpayers carry thousands separators, stray currency codes and
    accounting-style parentheses for negatives. Treating those as unreadable would make the
    checker refuse most real files; guessing at them would be worse. This handles the
    conventions that are unambiguous and returns None for everything else.
    """
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    neg = False
    m = _PAREN_NEG_RE.match(s)
    if m:
        neg, s = True, m.group(1)
    s = _NUM_CLEAN_RE.sub("", s)
    s = re.sub(r"(?i)^(sar|sr|ريال)\s*", "", s).replace("%", "")
    if s.startswith("-"):
        neg, s = True, s[1:]
    if not re.fullmatch(r"\d*\.?\d+", s):
        return None
    return -float(s) if neg else float(s)


def as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v or "").strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d %B %Y", "%d %b %Y",
                "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:len(fmt) + 6], fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s[:19]).date()
    except ValueError:
        return None


# ------------------------------------------------------------------------- the query
@dataclass(frozen=True)
class Filter:
    column: str
    op: str
    value: Any = None

    def describe(self) -> str:
        if self.op in ("is_blank", "not_blank"):
            return f"{self.column} {self.op.replace('_', ' ')}"
        if self.op == "between" and isinstance(self.value, (list, tuple)):
            return f"{self.column} between {self.value[0]} and {self.value[1]}"
        return f"{self.column} {self.op} {self.value}"


@dataclass(frozen=True)
class CalcQuery:
    """A question the executor can settle without judgement."""
    op: str
    column: str = ""
    filters: tuple[Filter, ...] = ()
    document: str = ""            # filename to run against; "" = the only/first suitable one

    def describe(self) -> str:
        head = f"{self.op}({self.column})" if self.column else f"{self.op}()"
        where = " where " + " and ".join(f.describe() for f in self.filters) if self.filters else ""
        return head + where

    def valid(self) -> tuple[bool, str]:
        if self.op not in AGGREGATIONS:
            return False, f"'{self.op}' is not an aggregation this engine performs."
        if self.op != "count" and not self.column:
            return False, f"{self.op} needs a column to work on."
        for f in self.filters:
            if f.op not in FILTER_OPS:
                return False, f"'{f.op}' is not a filter this engine applies."
        return True, ""


@dataclass
class CalcResult:
    status: str                       # ok | not-checkable
    value: float | None = None
    matched: int = 0                  # rows the filters admitted
    scanned: int = 0                  # rows in the document
    column: str = ""
    document: str = ""
    query: str = ""
    rows: list[dict] = field(default_factory=list)   # a sample, for the auditor to click into
    note: str = ""

    def to_dict(self) -> dict:
        return {"status": self.status, "value": self.value, "matched": self.matched,
                "scanned": self.scanned, "column": self.column, "document": self.document,
                "query": self.query, "rows": self.rows, "note": self.note}


MAX_CITED_ROWS = 8


# ---------------------------------------------------------------------- execution
def _column_index(columns: list[str], name: str) -> int:
    try:
        return columns.index(name)
    except ValueError:
        return -1


def _passes(row: list, columns: list[str], f: Filter) -> bool:
    idx = _column_index(columns, f.column)
    if idx < 0 or idx >= len(row):
        return False
    cell = row[idx]
    blank = cell is None or str(cell).strip() == ""
    if f.op == "is_blank":
        return blank
    if f.op == "not_blank":
        return not blank
    if blank:
        return False

    # compare as dates when both sides look like dates, else as numbers, else as text
    d_cell = as_date(cell)
    if f.op == "between" and isinstance(f.value, (list, tuple)) and len(f.value) == 2:
        lo_d, hi_d = as_date(f.value[0]), as_date(f.value[1])
        if d_cell and lo_d and hi_d:
            return lo_d <= d_cell <= hi_d
        n, lo, hi = as_number(cell), as_number(f.value[0]), as_number(f.value[1])
        return n is not None and lo is not None and hi is not None and lo <= n <= hi
    if f.op == "contains":
        return str(f.value).strip().lower() in str(cell).strip().lower()

    d_val = as_date(f.value)
    if d_cell and d_val:
        left, right = d_cell, d_val
    else:
        n_cell, n_val = as_number(cell), as_number(f.value)
        if n_cell is not None and n_val is not None:
            left, right = n_cell, n_val
        else:
            left, right = str(cell).strip().lower(), str(f.value).strip().lower()

    return {"eq": left == right, "ne": left != right, "gt": left > right,
            "gte": left >= right, "lt": left < right, "lte": left <= right}[f.op]


def run(query: CalcQuery, doc: dict) -> CalcResult:
    """Execute a query over one extracted document. Pure arithmetic, no judgement."""
    ok, why = query.valid()
    if not ok:
        return CalcResult(status=NOT_CHECKABLE, note=why, query=query.describe())

    columns = list(doc.get("columns") or [])
    rows = list(doc.get("rows") or [])
    name = doc.get("filename", "") or query.document

    if query.column and _column_index(columns, query.column) < 0:
        return CalcResult(
            status=NOT_CHECKABLE, query=query.describe(), document=name, scanned=len(rows),
            note=f"'{query.column}' is not a column in {name or 'this document'}. "
                 f"Columns present: {', '.join(columns) or 'none'}.")
    for f in query.filters:
        if _column_index(columns, f.column) < 0:
            return CalcResult(
                status=NOT_CHECKABLE, query=query.describe(), document=name, scanned=len(rows),
                note=f"Cannot filter on '{f.column}' — it is not a column in "
                     f"{name or 'this document'}.")

    kept = [r for r in rows if all(_passes(r, columns, f) for f in query.filters)]
    idx = _column_index(columns, query.column) if query.column else -1

    if query.op == "count":
        value: float | None = float(len(kept))
    else:
        raw = [r[idx] for r in kept if idx < len(r)]
        if query.op == "count_distinct":
            value = float(len({str(v).strip().lower() for v in raw
                               if v is not None and str(v).strip()}))
        else:
            nums = [n for n in (as_number(v) for v in raw) if n is not None]
            if not nums:
                return CalcResult(
                    status=NOT_CHECKABLE, query=query.describe(), document=name,
                    column=query.column, matched=len(kept), scanned=len(rows),
                    note=f"No numeric values in '{query.column}' for the rows selected.")
            value = {"sum": sum(nums), "average": sum(nums) / len(nums),
                     "max": max(nums), "min": min(nums)}[query.op]

    cited = [{"row": rows.index(r) + 1,
              **{c: r[i] for i, c in enumerate(columns) if i < len(r)}}
             for r in kept[:MAX_CITED_ROWS]]

    return CalcResult(status="ok", value=round(float(value), 2), matched=len(kept),
                      scanned=len(rows), column=query.column, document=name,
                      query=query.describe(), rows=cited)


# ------------------------------------------------------------------------- verify
@dataclass
class Verification:
    status: str                     # agree | disagree | not-checkable
    stated: float
    computed: float | None
    delta: float
    result: CalcResult
    explanation: str = ""           # engine-authored, so real digits are allowed

    def to_dict(self) -> dict:
        return {"status": self.status, "stated": self.stated, "computed": self.computed,
                "delta": self.delta, "explanation": self.explanation,
                "detail": self.result.to_dict()}


def _sar(v: float) -> str:
    return f"SAR {abs(v):,.2f}".rstrip("0").rstrip(".") if v % 1 else f"SAR {abs(v):,.0f}"


def verify(stated: float, query: CalcQuery, doc: dict,
           tolerance: float = TOLERANCE) -> Verification:
    """Recompute what the auditor says they computed, and report the difference.

    A disagreement is not an accusation — the auditor may have filtered differently, or the
    document may be the wrong one. So the explanation always says *what was recomputed and
    over how many rows*, which is what lets the auditor see immediately whose assumption
    differs rather than just being told they are wrong.
    """
    res = run(query, doc)
    if res.status != "ok" or res.value is None:
        return Verification(status=NOT_CHECKABLE, stated=stated, computed=None, delta=0.0,
                            result=res,
                            explanation=res.note or "The stated method could not be reproduced.")

    delta = round(res.value - stated, 2)
    where = f" over {res.matched} of {res.scanned} rows" if res.matched != res.scanned \
        else f" over all {res.scanned} rows"
    if abs(delta) <= tolerance:
        return Verification(
            status=AGREE, stated=stated, computed=res.value, delta=delta, result=res,
            explanation=f"Recomputed {res.query}{where} in {res.document or 'the document'} "
                        f"and got {_sar(res.value)}, which agrees with the figure recorded.")
    return Verification(
        status=DISAGREE, stated=stated, computed=res.value, delta=delta, result=res,
        explanation=f"Recomputed {res.query}{where} in {res.document or 'the document'} and got "
                    f"{_sar(res.value)} against {_sar(stated)} recorded — a difference of "
                    f"{_sar(delta)}. Check whether the same rows and the same column were used.")


# --------------------------------------------------------------- parsing (the model half)
def query_from_dict(payload: dict) -> CalcQuery | None:
    """Build a query from a model's structured answer, rejecting anything outside the algebra.

    The model chooses from a closed set. A key it invents does not become a query — it becomes
    None, and the caller reports the question as not checkable.
    """
    if not isinstance(payload, dict):
        return None
    op = str(payload.get("op") or "").strip().lower()
    if op not in AGGREGATIONS:
        return None
    filters: list[Filter] = []
    for f in payload.get("filters") or []:
        if not isinstance(f, dict):
            continue
        fop = str(f.get("op") or "").strip().lower()
        col = str(f.get("column") or "").strip()
        if fop not in FILTER_OPS or not col:
            continue
        filters.append(Filter(column=col, op=fop, value=f.get("value")))
    return CalcQuery(op=op, column=str(payload.get("column") or "").strip(),
                     filters=tuple(filters), document=str(payload.get("document") or "").strip())


def pick_document(docs: list[dict], wanted: str) -> dict | None:
    """The document a query names, matched leniently on filename.

    Returns None when the choice is genuinely ambiguous — several tabular documents are on the
    case and the query named none of them. Falling back to "the biggest one" would mean a
    question about sales could be answered off the purchase listing, silently and with the
    engine's authority behind it. That is precisely the error this agent exists to catch, so it
    must not be the agent's own default. One tabular document is not ambiguous; use it.
    """
    if not docs:
        return None
    if wanted:
        low = wanted.strip().lower()
        for d in docs:
            if (d.get("filename") or "").strip().lower() == low:
                return d
        for d in docs:
            if low in (d.get("filename") or "").strip().lower():
                return d
        return None                      # named something that is not here — do not substitute
    tabular = [d for d in docs if d.get("rows")]
    if len(tabular) == 1:
        return tabular[0]
    if not tabular:
        return docs[0] if len(docs) == 1 else None
    return None                          # several candidates: the caller must ask which


def names(docs: list[dict]) -> str:
    return ", ".join((d.get("filename") or "?") for d in docs) or "none"
