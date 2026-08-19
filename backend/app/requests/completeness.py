"""Compare what was requested against what arrived.

This is the check the auditors described doing by hand on every response, and it is most of
pain point 2: time spent on structure, completeness, fields, calculations and formatting rather
than on tax. It is also the reason a case takes months — each round of "you left out two
columns" costs weeks.

**Deterministic first, model second.** Almost none of this needs judgement. Whether a column is
present, whether a mandatory field is blank, whether the rows cover the period asked for, and
whether a stated total equals the sum of its own column are all *checks*. They run here, with no
model, no credentials, and a reproducible answer. Only two questions genuinely need judgement —
whether a document addresses what was asked, and whether an explanation is specific enough — and
those belong to the document reviewer, which is allowed to be wrong and is checked afterwards.

Gaps are recomputed from scratch on every run. A resolved gap simply stops being produced, so
there is no reconciliation of gap state to get wrong.

The arithmetic check is the taxpayer half of §7's two error sources; the auditor half — did we
transcribe the taxpayer's own total correctly — is the `RecomputedTotal` test in the adjudicator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from ..pipeline.predicates import is_null
from .catalog import ITEM_BY_KEY
from .extract import display, normalise

TOLERANCE = 1.0          # SAR — the same one riyal the adjudicator works to
MAX_CITED_ROWS = 5       # enough for the auditor to find it; not a data dump
COVERAGE_SLACK = 3       # days: a period end a day or two short is not a gap worth a round trip

BLOCKING = "blocking"
ADVISORY = "advisory"


@dataclass
class Gap:
    kind: str
    detail: str
    severity: str = BLOCKING
    citation: str = ""
    item_label: str = ""
    request_item_id: int | None = None
    document_id: int | None = None
    source: str = "deterministic"

    def to_dict(self) -> dict:
        return {
            "kind": self.kind, "detail": self.detail, "severity": self.severity,
            "citation": self.citation, "item_label": self.item_label,
            "request_item_id": self.request_item_id, "document_id": self.document_id,
            "source": self.source,
        }


@dataclass
class Report:
    case_id: str
    round: int
    gaps: list[Gap] = field(default_factory=list)
    checked_items: int = 0
    checked_documents: int = 0

    @property
    def blocking(self) -> list[Gap]:
        return [g for g in self.gaps if g.severity == BLOCKING]

    @property
    def complete(self) -> bool:
        """The gate: the substantive review opens only when nothing blocking remains."""
        return not self.blocking

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id, "round": self.round,
            "complete": self.complete,
            "checked_items": self.checked_items,
            "checked_documents": self.checked_documents,
            "blocking": len(self.blocking),
            "advisory": len(self.gaps) - len(self.blocking),
            "gaps": [g.to_dict() for g in self.gaps],
        }


# --------------------------------------------------------------------------------- helpers

def _as_date(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def _num(v: Any) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    s = str(v or "").strip().replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _rows_as_dicts(content: dict) -> list[dict]:
    cols = content.get("columns") or []
    out = []
    for row in content.get("rows") or []:
        d = {c: (row[i] if i < len(row) else None) for i, c in enumerate(cols)}
        # normalise "" to None so `is_null` means "not populated", which is what was asked
        out.append({k: (None if (v is None or (isinstance(v, str) and not v.strip())) else v)
                    for k, v in d.items()})
    return out


def _best_catalog_match(columns: list[str]) -> tuple[str, float]:
    """Which catalogue item do these columns look most like? Used to spot a wrong document."""
    best, best_score = "", 0.0
    present = set(columns)
    for item in ITEM_BY_KEY.values():
        req = set(item.required_columns)
        if not req:
            continue
        score = len(req & present) / len(req)
        if score > best_score:
            best, best_score = item.key, score
    return best, round(best_score, 3)


# --------------------------------------------------------------------------------- the checks

def _check_columns(item, content: dict) -> list[Gap]:
    present = set(content.get("columns") or [])
    required = [normalise(c) for c in (item.required_columns or [])]
    gaps = []
    for col in required:
        if col not in present:
            gaps.append(Gap(kind="missing-column",
                            detail=f"The '{display(col)}' column was requested but is not in "
                                   f"the file.",
                            citation=f"header row of {content.get('format', 'file')}"))
    return gaps


def _check_mandatory(item, content: dict) -> list[Gap]:
    """Present-but-blank. Reuses the predicate algebra: `is_null(column)` over each row."""
    rows = _rows_as_dicts(content)
    if not rows:
        return []
    present = set(content.get("columns") or [])
    gaps = []
    for col in [normalise(c) for c in (item.mandatory_columns or [])]:
        if col not in present:
            continue                      # already reported as a missing column
        test = is_null(col)
        blank_rows = [i for i, r in enumerate(rows, start=1) if test.evaluate(r)]
        if blank_rows:
            cited = ", ".join(str(i) for i in blank_rows[:MAX_CITED_ROWS])
            more = f" (+{len(blank_rows) - MAX_CITED_ROWS} more)" \
                if len(blank_rows) > MAX_CITED_ROWS else ""
            gaps.append(Gap(
                kind="empty-mandatory-field",
                detail=f"'{display(col)}' must be completed on every row, but is empty "
                       f"in {len(blank_rows)} of {len(rows)} rows.",
                citation=f"rows {cited}{more}"))
    return gaps


def _check_period(item, content: dict, period_from: date, period_to: date) -> list[Gap]:
    pf, pt = _as_date(content.get("period_from")), _as_date(content.get("period_to"))
    want_from = item.period_from or period_from
    want_to = item.period_to or period_to
    if pf is None or pt is None:
        return []                          # no dated column — nothing to compare against
    gaps = []
    if (want_from - pf).days > COVERAGE_SLACK:
        gaps.append(Gap(kind="wrong-period", severity=ADVISORY,
                        detail=f"The file starts at {pf:%d %b %Y}, before the period requested "
                               f"({want_from:%d %b %Y}). Rows outside the period were supplied.",
                        citation="earliest dated row"))
    if (want_to - pt).days > COVERAGE_SLACK:
        gaps.append(Gap(kind="wrong-period",
                        detail=f"The file stops at {pt:%d %b %Y} but the period requested runs "
                               f"to {want_to:%d %b %Y} — "
                               f"{(want_to - pt).days} days are not covered.",
                        citation="latest dated row"))
    return gaps


def _check_footing(item, content: dict) -> list[Gap]:
    """Does the total the taxpayer states equal the sum of the column it claims to total?"""
    footed = list(item.footed_by or [])
    if len(footed) != 2:
        return []
    stated_key, column = normalise(footed[0]), normalise(footed[1])
    stated_totals = {normalise(k): v for k, v in (content.get("stated_totals") or {}).items()}
    stated = _num(stated_totals.get(stated_key, stated_totals.get(column)))
    if stated is None:
        return []                          # nothing stated to disagree with
    rows = _rows_as_dicts(content)
    values = [_num(r.get(column)) for r in rows]
    computed = round(sum(v for v in values if v is not None), 2)
    diff = round(stated - computed, 2)
    if abs(diff) <= TOLERANCE:
        return []
    return [Gap(kind="arithmetic-mismatch",
                detail=f"The stated total for '{display(column)}' is SAR {stated:,.2f}, but the "
                       f"rows sum to SAR {computed:,.2f} — a difference of SAR {diff:,.2f}.",
                citation=f"totals row vs {len(rows)} data rows")]


def _check_format(item, doc_format: str) -> list[Gap]:
    want = (item.expected_format or "").lower()
    got = (doc_format or "").lower()
    if not want or not got or want == got:
        return []
    tabular = {"xlsx", "xlsm", "csv"}
    if want in tabular and got in tabular:
        return []                          # a csv where we asked for xlsx is checkable anyway
    severity = BLOCKING if want in tabular else ADVISORY
    return [Gap(kind="wrong-format", severity=severity,
                detail=f"Supplied as {got}; a {want} was requested. "
                       + ("A tabular file is needed before the analysis can be checked."
                          if severity == BLOCKING else
                          "The content may still be usable."))]


def _check_is_right_document(item, content: dict) -> list[Gap]:
    """Did they send the thing we asked for, or something else that looks like a spreadsheet?"""
    required = [normalise(c) for c in (item.required_columns or [])]
    if not required or not content.get("columns"):
        return []
    present = set(content["columns"])
    overlap = len(set(required) & present) / len(required)
    if overlap >= 0.5:
        return []
    best, best_score = _best_catalog_match(content["columns"])
    looks_like = ITEM_BY_KEY[best].label if best and best_score > overlap else None
    detail = (f"Only {overlap:.0%} of the requested columns are present.")
    if looks_like:
        detail += f" The file looks more like a {looks_like.lower()}."
    return [Gap(kind="wrong-document", detail=detail, citation="header row")]


# --------------------------------------------------------------------------------- entry point

def check(*, case_id: str, round_: int, items: list, documents: list,
          period_from: date, period_to: date) -> Report:
    """Run every deterministic check for one round of correspondence.

    `items` are `models.RequestItem` rows (or anything with the same attributes) and
    `documents` are `models.ReceivedDocument` rows. Both are passed in rather than queried so
    the checker stays a pure function — which is what makes it testable against a fixture.
    """
    report = Report(case_id=case_id, round=round_,
                    checked_items=len(items), checked_documents=len(documents))
    by_item: dict[int, list] = {}
    for d in documents:
        by_item.setdefault(d.request_item_id, []).append(d)

    for item in items:
        if item.status == "waived":
            continue
        docs = by_item.get(item.id, [])
        if not docs:
            report.gaps.append(Gap(
                kind="missing-item", item_label=item.label, request_item_id=item.id,
                detail=f"Nothing was supplied for '{item.label}'."))
            continue
        for doc in docs:
            content = doc.content or {}
            found: list[Gap] = []
            found += _check_format(item, doc.file_format or content.get("format", ""))
            if content.get("columns"):
                found += _check_is_right_document(item, content)
                found += _check_columns(item, content)
                found += _check_mandatory(item, content)
                found += _check_period(item, content, period_from, period_to)
                found += _check_footing(item, content)
            elif item.kind == "analysis":
                found.append(Gap(
                    kind="wrong-format",
                    detail=f"'{item.label}' was requested as a tabular analysis, but the file "
                           f"supplied has no readable table."
                           + (f" {content['note']}" if content.get("note") else "")))
            for g in found:
                g.item_label = item.label
                g.request_item_id = item.id
                g.document_id = doc.id
            report.gaps.extend(found)

    for doc in by_item.get(None, []):
        report.gaps.append(Gap(
            kind="unrequested-document", severity=ADVISORY, document_id=doc.id,
            detail=f"'{doc.filename}' was supplied but does not answer any item on the request. "
                   f"It may be a misfiled response, or evidence worth reading anyway."))

    return report
