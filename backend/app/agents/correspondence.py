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
VERDICT = "Verdict Drafter"

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


# --------------------------------------------------------------------------- closure (§8)

VERDICT_HEAD = {
    "supported": "No adjustment is proposed",
    "potential-finding": "A difference remains unexplained",
    "unresolved": "A difference remains unresolved",
}


def verdict_facts(case, taxpayer, recon, investigation=None) -> str:
    """The engine's conclusion, as the only things the letter may state."""
    lines = [
        f"Taxpayer: {taxpayer.name}",
        f"VAT registration number: {taxpayer.vat_registration_number}",
        f"Period reviewed: {_period(case)}",
        f"Box reviewed: {recon.get('box_title') or recon.get('box')}",
        f"Outcome: {VERDICT_HEAD.get(recon['state'], recon['state'])}",
        f"Declared: SAR {recon['declared']:,.2f}",
        f"Qualifying e-invoices for the period total: SAR {recon['expected_vat']:,.2f}",
        f"Difference: SAR {abs(recon['difference']):,.2f}",
        f"Still unaccounted for: SAR {abs(recon['unexplained']):,.2f}",
        f"Materiality applied: SAR {recon['materiality']:,.2f}",
        "Documents the rules placed outside this return:",
    ]
    steps = [f for f in recon.get("funnel", []) if f.get("rule")]
    for f in steps:
        lines.append(f"  - {f['rule']}: {f['label']} — {f['count']} document(s), "
                     f"SAR {abs(f['amount']):,.2f}")
    if not steps:
        lines.append("  - none")
    if recon.get("evidence"):
        lines.append("Accounted for by evidence you supplied:")
        for e in recon["evidence"]:
            lines.append(f"  - {e['label']} — SAR {e['amount']:,.2f}")
    if investigation and investigation.get("conclusion"):
        lines.append(f"Reviewer's conclusion: {investigation['conclusion']}")
    return "\n".join(lines)


def fb_verdict(case, taxpayer, recon, investigation=None) -> str:
    """The verdict letter, written deterministically."""
    unexplained = abs(float(recon["unexplained"]))
    state = recon["state"]
    body = [
        f"{taxpayer.name}",
        f"VAT registration number {taxpayer.vat_registration_number}",
        "",
        f"Subject: Outcome of the VAT review — period {_period(case)}",
        "",
        "Dear Sir or Madam,",
        "",
        f"The Authority has completed its review of the VAT return filed for the period "
        f"{_period(case)}. This letter sets out the outcome.",
        "",
    ]
    steps = [f for f in recon.get("funnel", []) if f.get("rule")]
    if steps:
        body.append("In arriving at that view, the following documents were treated as falling "
                    "outside this return:")
        for f in steps:
            body.append(f"  - {f['label']}: {f['count']} document(s), "
                        f"SAR {abs(f['amount']):,.2f}")
        body.append("")
    if recon.get("evidence"):
        body.append("The evidence you supplied accounted for:")
        for e in recon["evidence"]:
            body.append(f"  - {e['label']} (SAR {e['amount']:,.2f})")
        body.append("")

    if state == "supported":
        body += [
            "On that basis the declared figures are supported by the evidence available, and "
            "no adjustment is proposed. No further action is required from you in respect of "
            "this period.",
        ]
    elif state == "unresolved":
        body += [
            f"A difference of SAR {unexplained:,.2f} remains, and on the evidence available it "
            f"appears to be in your favour. Before the review can be closed, please confirm "
            f"the figures declared for the period, or provide the further explanation set out "
            f"in any accompanying request.",
        ]
    else:
        body += [
            f"A difference of SAR {unexplained:,.2f} remains unexplained, against a materiality "
            f"threshold of SAR {float(recon['materiality']):,.2f}. This is a proposed position "
            f"and not an assessment.",
            "",
            "If you consider the difference to be explained, please respond with the "
            "supporting documentation. If no response is received, the Authority will proceed "
            "on the basis set out above.",
        ]
    body += ["", "Yours faithfully,", SIGNOFF]
    return "\n".join(body)


def draft_verdict(case, taxpayer, recon, investigation=None) -> dict:
    """Draft the taxpayer letter that reports the outcome. §8's second administrative burden.

    Same guard as the request letters, and the same reason for it: the letter states the
    Authority's position, so every figure in it has to be one the engine computed.
    """
    facts = verdict_facts(case, taxpayer, recon, investigation)
    return llm.draft_letter(kind="verdict", facts=facts,
                            fallback=lambda: fb_verdict(case, taxpayer, recon, investigation))
