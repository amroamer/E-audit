"""Turn the email the auditor actually sent into a spec the completeness checker can enforce.

Planning is out of scope: the request already went out, in the auditor's own words, before this
PoC sees the case. So the spec cannot come from a planner — it has to be **recovered from the
email**, and everything downstream (what is missing, what to chase, whether the response closes
the case) rests on getting that recovery right.

Two rules make that safe.

**The catalog is a closed set.** Parsing may only ever *select* items from `catalog.CATALOG`.
It cannot invent a request item, and it cannot invent a required column — those come from the
catalog entry, or from a column list written out in the email and read off deterministically.
An unrecognised paragraph is reported as unmatched, never guessed into an item.

**The auditor confirms before it binds.** Reading an email is judgement work and will sometimes
be wrong. A silently-wrong parse would make every gap report downstream wrong too, so the parse
is a *proposal*: it is shown, with the phrase that triggered each match, for the auditor to
accept, drop or add to. Only the confirmed spec is stored. Same shape as the taxpayer-letter
reader, and for the same reason.

Deterministic first, model second: keyword matching handles the items an auditor phrases
conventionally, and only what is left over is put to a model — which answers with catalog keys,
never with prose that becomes a requirement.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

from .catalog import CATALOG, ITEM_BY_KEY, RequestItem
from .extract import normalise

# ---------------------------------------------------------------- deterministic matching
# Phrases that identify a catalog item when an auditor writes the request conventionally.
# Deliberately specific: a loose pattern that fires on "sales" would match almost any request
# email and produce a spec the taxpayer was never actually asked for.
CUES: dict[str, tuple[str, ...]] = {
    "sales-analysis": ("sales analysis", "analysis of sales", "sales listing", "sales ledger",
                       "detailed sales", "list of sales invoices", "sales invoices issued",
                       "schedule of sales"),
    "purchase-analysis": ("purchase analysis", "analysis of purchases", "purchase listing",
                          "purchases ledger", "detailed purchases", "input vat schedule",
                          "list of purchase invoices", "schedule of purchases"),
    "credit-note-listing": ("credit note", "credit notes", "debit note", "debit notes",
                            "credit and debit note"),
    "trial-balance": ("trial balance", "tb as at", "trial balances"),
    "financial-statements": ("financial statements", "audited accounts", "annual accounts",
                             "income statement", "profit and loss"),
    "general-ledger": ("general ledger", "gl extract", "ledger extract", "vat account",
                       "vat control account"),
    "bank-statements": ("bank statement", "bank statements", "bank account statement"),
    "contracts": ("contract", "contracts", "agreement", "agreements", "signed contract"),
    "customs-declarations": ("customs declaration", "import declaration", "bayan",
                             "customs declarations"),
    "invoice-copies": ("copies of invoices", "copy of the invoice", "invoice copies",
                       "sample invoices", "supporting invoices", "copies of the tax invoices"),
    "vat-return-copies": ("vat return", "vat returns", "copy of the return", "returns filed",
                          "filed returns"),
    "reconciliation": ("reconciliation", "reconcile the return", "reconciling"),
    "explanation-difference": ("explanation of the difference", "explain the difference",
                               "written explanation", "reason for the difference"),
    "explanation-activity": ("business use", "explanation of business use", "nature of the expense",
                             "purpose of the purchase"),
    "pos-report": ("point of sale", "point-of-sale", "pos report", "pos settlement",
                   "pos records", "cash register"),
    "fixed-asset-register": ("fixed asset register", "asset register", "fixed assets"),
}

# "the following columns: a, b, c" / "including: a, b and c" — an explicit column spec.
_COLSPEC_RE = re.compile(
    r"(?:following|these|below|with the)\s+(?:columns?|fields?|headings?|headers?)\s*[:\-—]\s*"
    r"(?P<body>[^\n]{3,400})", re.I)
# a bulleted or numbered column list on its own lines, introduced by a colon
_COL_SPLIT_RE = re.compile(r"[,;]|\band\b|\|", re.I)

_DATE_PATTERNS = (
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "%Y-%m-%d"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b"), "%d/%m/%Y"),
    (re.compile(r"\b(\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4})\b"), "%d %B %Y"),
)

_QUARTER_RE = re.compile(r"\bQ([1-4])\s*[/-]?\s*(\d{4})\b", re.I)
_DUE_RE = re.compile(
    r"(?:within|no later than|by|due(?:\s+(?:on|by))?)\s+(?P<v>\d{1,2}\s+[A-Za-z]{3,9}\s+\d{4}"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}\s+(?:working\s+)?days)", re.I)


@dataclass
class ParsedItem:
    key: str
    label: str
    required_columns: tuple[str, ...]
    mandatory_columns: tuple[str, ...]
    cue: str                      # the phrase in the email that matched — shown to the auditor
    source: str = "keyword"       # keyword | model | auditor
    confidence: str = "high"

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label,
                "required_columns": list(self.required_columns),
                "mandatory_columns": list(self.mandatory_columns),
                "cue": self.cue, "source": self.source, "confidence": self.confidence}


@dataclass
class ParsedRequest:
    """A *proposal*. Nothing here binds until the auditor confirms it."""
    items: list[ParsedItem] = field(default_factory=list)
    period_from: date | None = None
    period_to: date | None = None
    due_phrase: str = ""
    columns_stated: dict[str, tuple[str, ...]] = field(default_factory=dict)
    unmatched: list[str] = field(default_factory=list)
    source: str = "deterministic"

    def to_dict(self) -> dict:
        return {
            "items": [i.to_dict() for i in self.items],
            "period_from": self.period_from.isoformat() if self.period_from else None,
            "period_to": self.period_to.isoformat() if self.period_to else None,
            "due_phrase": self.due_phrase,
            "columns_stated": {k: list(v) for k, v in self.columns_stated.items()},
            "unmatched": self.unmatched,
            "source": self.source,
            "needs_confirmation": True,
        }


# ------------------------------------------------------------------------------ helpers
# a line that opens a new numbered or bulleted ask, rather than continuing the previous one
_ITEM_START_RE = re.compile(r"^\s*(?:[-*•–—]|\(?\d{1,2}[.)])\s+")

# Letter furniture. Not asks, and leaving them in means the auditor reviews the parse by
# reading past their own salutation every time.
_BOILERPLATE_RE = re.compile(
    r"^\s*(dear\b|to whom it may concern|yours (faithfully|sincerely)|kind regards|"
    r"regards\b|best regards|sincerely\b|thank you|many thanks|"
    r"zakat, tax and customs authority|vat audit\b|"
    r"(this|the) (e-?mail|message)\b|sent from\b)", re.I)
# "…please provide the following:" — a lead-in to the list, not an ask in itself
_LEADIN_RE = re.compile(r":\s*$")


def _sentences(text: str) -> list[str]:
    """Split into the units an auditor actually writes requests in: bullets and sentences.

    Wrapped lines are rejoined first. An emailed request item routinely runs over three lines,
    and a column list is exactly the thing that wraps — splitting on the newline would cut
    "with the following columns: invoice date," off from the rest and silently shrink the
    requirement to whatever fitted on the first line.
    """
    logical: list[str] = []
    for raw in re.split(r"[\n\r]+", text):
        stripped = raw.strip()
        if not stripped:
            logical.append("")                      # a blank line always ends an item
            continue
        if _BOILERPLATE_RE.match(stripped):
            logical.append("")                      # furniture also ends the ask above it
            continue
        if _ITEM_START_RE.match(raw) or not logical or not logical[-1]:
            logical.append(stripped)
        else:
            logical[-1] = f"{logical[-1]} {stripped}"   # a continuation of the ask above

    out: list[str] = []
    for line in logical:
        line = _ITEM_START_RE.sub("", line).strip(" \t.")
        if not line:
            continue
        # a long line may still hold several asks
        parts = re.split(r"(?<=[.;])\s+(?=[A-Z])", line) if len(line) > 160 else [line]
        out.extend(p.strip() for p in parts if p.strip())
    return out


def _find_dates(text: str) -> list[date]:
    found: list[date] = []
    for rx, fmt in _DATE_PATTERNS:
        for m in rx.finditer(text):
            raw = m.group(0)
            for f in (fmt, "%d %b %Y"):
                try:
                    found.append(datetime.strptime(raw, f).date())
                    break
                except ValueError:
                    continue
    return sorted(set(found))


def _quarter(text: str) -> tuple[date, date] | None:
    m = _QUARTER_RE.search(text)
    if not m:
        return None
    q, year = int(m.group(1)), int(m.group(2))
    start_month = 3 * (q - 1) + 1
    end_month = start_month + 2
    last = {1: 31, 2: 28, 3: 31, 4: 30, 5: 31, 6: 30,
            7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31}[end_month]
    if end_month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        last = 29
    return date(year, start_month, 1), date(year, end_month, last)


def _stated_columns(sentence: str) -> tuple[str, ...]:
    """Columns written out in the email, read off literally.

    This is the one place a required column may come from outside the catalog — because the
    auditor wrote it down, not because anything inferred it.
    """
    m = _COLSPEC_RE.search(sentence)
    if not m:
        return ()
    body = m.group("body")
    parts = [p.strip(" .;:-\t'\"()") for p in _COL_SPLIT_RE.split(body)]
    cols = tuple(normalise(p) for p in parts if 1 < len(p.strip()) < 60)
    return tuple(dict.fromkeys(c for c in cols if c))


def _match_item(sentence: str) -> tuple[str, str] | None:
    """(catalog key, matched phrase) for the most specific cue present in the sentence."""
    low = sentence.lower()
    best: tuple[str, str] | None = None
    for key, cues in CUES.items():
        for cue in cues:
            if cue in low and (best is None or len(cue) > len(best[1])):
                best = (key, cue)
    return best


def _as_parsed(item: RequestItem, cue: str, stated: tuple[str, ...],
               source: str, confidence: str) -> ParsedItem:
    # stated columns win — the auditor asked for those in writing, whatever the catalog says
    required = stated or item.required_columns
    mandatory = tuple(c for c in item.mandatory_columns if c in required) or item.mandatory_columns
    return ParsedItem(key=item.key, label=item.label, required_columns=required,
                      mandatory_columns=mandatory, cue=cue, source=source, confidence=confidence)


# -------------------------------------------------------------------------- the parse
def parse_email(text: str) -> ParsedRequest:
    """Deterministic pass. Everything it is sure of, with the evidence for each match."""
    out = ParsedRequest()
    body = (text or "").strip()
    if not body:
        return out

    q = _quarter(body)
    if q:
        out.period_from, out.period_to = q
    else:
        dates = _find_dates(body)
        if len(dates) >= 2:
            out.period_from, out.period_to = dates[0], dates[-1]

    due = _DUE_RE.search(body)
    if due:
        out.due_phrase = due.group("v").strip()

    seen: set[str] = set()
    for sentence in _sentences(body):
        hit = _match_item(sentence)
        stated = _stated_columns(sentence)
        if not hit:
            # An ask we could not place is the auditor's to resolve — but a lead-in ("please
            # provide the following:") introduces the list rather than asking for anything, and
            # reporting it as unplaced would be noise on every single email.
            if (len(sentence) > 25 and not _LEADIN_RE.search(sentence)
                    and re.search(r"\b(provide|submit|send|furnish|attach|share)\b",
                                  sentence, re.I)):
                out.unmatched.append(sentence[:240])
            continue
        key, cue = hit
        if stated:
            out.columns_stated[key] = stated
        if key in seen:
            continue
        item = ITEM_BY_KEY.get(key)
        if not item:
            continue
        seen.add(key)
        out.items.append(_as_parsed(item, cue, stated, "keyword", "high"))
    return out


def apply_model_matches(parsed: ParsedRequest, keys_by_line: dict[str, str]) -> ParsedRequest:
    """Fold the model's suggestions in — as *low-confidence* items the auditor must accept.

    `keys_by_line` maps an unmatched sentence to a catalog key. Anything that is not a real
    catalog key is dropped on the floor: the model selects from a closed set, it does not get
    to define one.
    """
    have = {i.key for i in parsed.items}
    still: list[str] = []
    for line in parsed.unmatched:
        key = keys_by_line.get(line, "")
        item = ITEM_BY_KEY.get(key)
        if not item or key in have:
            still.append(line)
            continue
        have.add(key)
        parsed.items.append(_as_parsed(item, line[:120], _stated_columns(line),
                                       "model", "low"))
    parsed.unmatched = still
    parsed.source = "mixed" if any(i.source == "model" for i in parsed.items) else parsed.source
    return parsed


def confirm(parsed: ParsedRequest, keep: list[str],
            add: list[str] | None = None) -> list[ParsedItem]:
    """The auditor's decision, applied. Only what comes out of here becomes the spec.

    `keep` are the proposed keys the auditor accepted; `add` are catalog keys they added by
    hand. Anything proposed but not kept is discarded — a parse the auditor rejected must not
    survive into the completeness check.
    """
    keep_set = set(keep)
    out = [i for i in parsed.items if i.key in keep_set]
    for key in add or []:
        if key in {i.key for i in out}:
            continue
        item = ITEM_BY_KEY.get(key)
        if item:
            out.append(_as_parsed(item, "added by the auditor",
                                  parsed.columns_stated.get(key, ()), "auditor", "high"))
    return out


def catalog_choices() -> list[dict]:
    """Everything the auditor may add by hand, for the confirm screen."""
    return [{"key": i.key, "label": i.label, "kind": i.kind,
             "description": i.description,
             "required_columns": list(i.required_columns)} for i in CATALOG]
