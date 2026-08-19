"""Draft the outbound letters: the information request, and the follow-up that chases gaps.

§8 named report preparation and taxpayer correspondence as the administrative burdens worth
automating, and §2 asked specifically for the follow-up to be drafted automatically from the
gaps found. Both are language work over facts the engine already established, which is exactly
where a model belongs and exactly where it must not be allowed to invent.

The rule is unchanged from the rest of the system, restated for prose that quotes documents
rather than reconciliation scalars: **the engine states every figure; Claude may repeat one it
was given and may not introduce one.** `verify_correspondence` enforces it by requiring every
numeric literal in the draft to appear in the facts block. On failure there is one corrective
retry, then the deterministic draft below — which is complete, sendable English, not a stub.

The follow-up lists *only* what is still outstanding. Re-asking for something already supplied
is the fastest way to lose an auditor's trust, and the gap list already knows the difference.
"""
from __future__ import annotations

from datetime import date

from ..llm.service import llm

REQUEST = "Request Drafter"
FOLLOWUP = "Follow-up Drafter"

SIGNOFF = ("Zakat, Tax and Customs Authority\nVAT Audit")


def _period(case) -> str:
    return f"{case.period_from:%d %B %Y} to {case.period_to:%d %B %Y}"


def _due(req) -> str:
    return f"{req.due_at:%d %B %Y}" if req.due_at else "20 days from the date of this letter"


# --------------------------------------------------------------------------- fact blocks
# Everything Claude is allowed to state. Engine-authored, so figures are permitted here.

def request_facts(case, taxpayer, req) -> str:
    lines = [
        f"Taxpayer: {taxpayer.name}",
        f"VAT registration number: {taxpayer.vat_registration_number}",
        f"Period under review: {_period(case)}",
        f"Response due: {_due(req)}",
        "Items requested:",
    ]
    for item in req.items:
        lines.append(f"  {item.seq}. {item.label} — {item.description}")
        if item.required_columns:
            lines.append(f"     Required columns: {', '.join(item.required_columns)}")
        if item.mandatory_columns:
            lines.append(f"     Must be populated on every row: "
                         f"{', '.join(item.mandatory_columns)}")
        if item.expected_format:
            lines.append(f"     Format: {item.expected_format}")
        if item.rationale:
            lines.append(f"     Purpose: {item.rationale}")
    return "\n".join(lines)


def followup_facts(case, taxpayer, req, gaps) -> str:
    lines = [
        f"Taxpayer: {taxpayer.name}",
        f"VAT registration number: {taxpayer.vat_registration_number}",
        f"Period under review: {_period(case)}",
        f"Round of correspondence: {req.seq}",
        f"Response due: {_due(req)}",
        "Outstanding items, grouped by what was requested:",
    ]
    for label, group in _grouped(gaps):
        lines.append(f"  {label}:")
        for g in group:
            cite = f" [{g.citation}]" if g.citation else ""
            lines.append(f"    - {g.detail}{cite}")
    return "\n".join(lines)


def _grouped(gaps) -> list[tuple[str, list]]:
    order: list[str] = []
    groups: dict[str, list] = {}
    for g in gaps:
        label = g.item_label or "Other"
        if label not in groups:
            groups[label] = []
            order.append(label)
        groups[label].append(g)
    return [(k, groups[k]) for k in order]


# --------------------------------------------------------------------------- deterministic

def fb_request(case, taxpayer, req) -> str:
    """The request letter, written deterministically. Complete English, not a placeholder."""
    body = [
        f"{taxpayer.name}",
        f"VAT registration number {taxpayer.vat_registration_number}",
        "",
        f"Subject: Information request — VAT period {_period(case)}",
        "",
        "Dear Sir or Madam,",
        "",
        "The Authority is reviewing the VAT return filed for the period "
        f"{_period(case)}. To complete that review we require the information listed below. "
        "Information already held by the Authority has not been requested.",
        "",
    ]
    for item in req.items:
        body.append(f"{item.seq}. {item.label}")
        if item.description:
            body.append(f"   {item.description}")
        if item.required_columns:
            body.append("   The analysis must contain the following columns: "
                        + ", ".join(item.required_columns) + ".")
        if item.mandatory_columns:
            body.append("   The following must be completed on every row: "
                        + ", ".join(item.mandatory_columns) + ".")
        if item.expected_format:
            body.append(f"   Please supply this in {item.expected_format} format.")
        body.append("")
    body += [
        f"Please provide the above by {_due(req)}. If any item cannot be provided in the form "
        "requested, please say so and explain why, rather than omitting it — an incomplete "
        "response will require a further request and will extend the review.",
        "",
        "Yours faithfully,",
        SIGNOFF,
    ]
    return "\n".join(body)


def fb_followup(case, taxpayer, req, gaps) -> str:
    """The chase letter. Lists only what is outstanding, item by item."""
    body = [
        f"{taxpayer.name}",
        f"VAT registration number {taxpayer.vat_registration_number}",
        "",
        f"Subject: Outstanding information — VAT period {_period(case)}",
        "",
        "Dear Sir or Madam,",
        "",
        "Thank you for the information supplied. On review, the following remains outstanding "
        "or does not meet the terms of the original request. Items already supplied in full "
        "are not repeated here.",
        "",
    ]
    for n, (label, group) in enumerate(_grouped(gaps), start=1):
        body.append(f"{n}. {label}")
        for g in group:
            cite = f" ({g.citation})" if g.citation else ""
            body.append(f"   - {g.detail}{cite}")
        body.append("")
    body += [
        f"Please supply the outstanding items by {_due(req)}.",
        "",
        "Yours faithfully,",
        SIGNOFF,
    ]
    return "\n".join(body)


# --------------------------------------------------------------------------- entry points

def draft_request(case, taxpayer, req) -> dict:
    """Draft the outbound request. Claude writes the language; the engine owns the facts."""
    facts = request_facts(case, taxpayer, req)
    return llm.draft_letter(kind="request", facts=facts,
                            fallback=lambda: fb_request(case, taxpayer, req))


def draft_followup(case, taxpayer, req, gaps) -> dict:
    """Draft the chase letter from the outstanding gaps only."""
    if not gaps:
        return {"text": "", "source": "none", "violations": [],
                "note": "Nothing outstanding — no follow-up is needed."}
    facts = followup_facts(case, taxpayer, req, gaps)
    return llm.draft_letter(kind="follow-up", facts=facts,
                            fallback=lambda: fb_followup(case, taxpayer, req, gaps))
