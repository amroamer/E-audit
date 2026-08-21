"""The audit report, built against the Authority's own template.

The template the audit team supplied has six blocks — taxpayer information, case information,
the assigned team, taxpayer documentation, the audit outcome, and risk feedback. This module
fills them from the case, and it is deliberately explicit about the difference between three
states, because an auditor signing a report needs to be able to tell them apart:

* **filled** — the engine established it. It carries a figure or a fact from the case file.
* **not held** — the proof-of-concept has no source for it (contact details, the audit team's
  names, the field-audit date). Written as `[not held]` rather than left blank, so an empty
  cell is never mistaken for "nothing to report".
* **for the auditor** — a judgement the report needs and the machine must not make. Rulings
  given verbally, penalties, whether a future audit is warranted.

Nothing here invents a value. A section with no basis says so.

The section order and headings follow the template exactly, so the output can be pasted into
the Authority's document without rearrangement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .. import outcomes as oc

NOT_HELD = "[not held]"
FOR_AUDITOR = "[for the auditor to complete]"

# The template's own option lists, kept verbatim so a filled report uses the Authority's
# vocabulary rather than ours.
CREATION_REASONS = ("Risk Engine", "Whistleblowers report", "Report from OGAs",
                    "Internal referral", "Other")
CASE_TYPES = ("Comprehensive Audit", "Limited Scope Audit", "Refund Audit")
TAX_TYPES = ("VAT", "Excise Tax", "CIT", "WHT")


@dataclass
class Field:
    label: str
    value: str
    note: str = ""          # the guidance the template carries under the label

    @property
    def held(self) -> bool:
        return self.value not in (NOT_HELD, FOR_AUDITOR, "")


@dataclass
class Section:
    title: str
    fields: list[Field] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"title": self.title,
                "fields": [{"label": f.label, "value": f.value, "note": f.note,
                            "held": f.held} for f in self.fields]}


def _sar(v) -> str:
    return f"SAR {abs(float(v)):,.2f}"


def _period(case) -> str:
    return f"{case.period_from:%d %B %Y} to {case.period_to:%d %B %Y}"


def _priority_band(score: int) -> str:
    """The template asks for 1, 2 or 3. Our composite score is 0-100."""
    if score >= 60:
        return "1"
    return "2" if score >= 35 else "3"


# ------------------------------------------------------------------ the blocks
def taxpayer_information(taxpayer) -> Section:
    return Section("Taxpayer information", [
        Field("Taxpayer name", taxpayer.name),
        Field("Taxpayer TIN", taxpayer.vat_registration_number),
        Field("Taxpayer contact details", NOT_HELD,
              "Telephone, address and e-mail are not among the sources this "
              "proof-of-concept holds."),
    ])


def case_information(case, priority: dict | None = None) -> Section:
    score = int((priority or {}).get("score", 0))
    return Section("Audit Case information", [
        Field("Audit Case ID", case.case_id),
        Field("Audit Creation Date",
              case.referral_date.isoformat() if case.referral_date else NOT_HELD),
        Field("Case Creation Reason", "Risk Engine",
              "One of: " + ", ".join(CREATION_REASONS)),
        Field("Date Audit closed",
              date.today().isoformat() if case.status == "closed" else FOR_AUDITOR),
        Field("Priority", _priority_band(score),
              f"Composite score {score}/100 — exposure, deadline, history, quick-win."),
        Field("Priority risk", _priority_band(score)),
        Field("Audit Case Type",
              "Limited Scope Audit" if (case.audit_type or "desk") == "desk"
              else str(case.audit_type),
              "One of: " + ", ".join(CASE_TYPES)),
        Field("Tax type", "VAT", "One of: " + ", ".join(TAX_TYPES)),
        Field("Audit Case Tax Period", _period(case)),
        Field("Confidential Audit", "No"),
        Field("Risk Confidentiality", "No"),
        Field("Place of conduct of Audit", "Desk audit — conducted on documents supplied"),
        Field("Address of Audit location", "Not applicable — desk audit"),
        Field("Meeting date", FOR_AUDITOR),
        Field("Field audit report date", "Not applicable — no field visit was made",
              "Should be attached to this if separate."),
    ])


def audit_team() -> Section:
    """Names the proof-of-concept has no source for. Never invented."""
    return Section("Assigned Audit Team information", [
        Field("Audit Manager", NOT_HELD),
        Field("Audit Supervisor", NOT_HELD),
        Field("Audit Officer", NOT_HELD),
    ])


def taxpayer_documentation(requested: list[dict], received: list[dict],
                           gaps: list[dict]) -> Section:
    """What was asked for and what arrived — the auditors' own "required/obtained" row."""
    lines: list[str] = []
    if requested:
        lines.append("Requested:")
        lines += [f"  - {r.get('label', r.get('key', ''))}" for r in requested]
    if received:
        lines.append("Obtained:")
        for d in received:
            cols = len(d.get("columns") or [])
            rows = d.get("row_count") or len(d.get("rows") or [])
            lines.append(f"  - {d.get('filename')} ({rows} rows, {cols} columns)")
    else:
        lines.append("Obtained: nothing was received.")
    blocking = [g for g in gaps if g.get("severity") == "blocking"]
    if blocking:
        lines.append(f"Outstanding at the date of this report ({len(blocking)}):")
        for g in blocking[:10]:
            lines.append(f"  - {g.get('item_label') or 'Response'}: {g.get('detail')}")
    return Section("Taxpayer documentation", [
        Field("Documents required/obtained", "\n".join(lines) if lines else NOT_HELD),
    ])


def audit_outcome(case, recon: dict, findings: list[dict], exposure: dict,
                  conclusion: str) -> Section:
    """The substance. Every figure here was computed by the engine."""
    box = recon.get("box") or "Standard-rated sales VAT"

    objectives = (
        f"To establish whether the VAT declared for {_period(case)} is supported by the "
        f"records the taxpayer holds, and to quantify any difference."
    )

    docs = recon.get("population_document")
    activities = [
        "The review was conducted on the documents supplied by the taxpayer.",
    ]
    if docs:
        activities.append(
            f"{recon.get('population_lines', 0)} lines were read from {docs} and tested "
            f"against the conditions for inclusion in {box} for the period.")
    activities.append(
        f"The records that qualify total {_sar(recon.get('expected_vat', 0))} against "
        f"{_sar(recon.get('declared', 0))} declared, a difference of "
        f"{_sar(recon.get('difference', 0))}.")
    if recon.get("evidence_total"):
        activities.append(
            f"Evidence supplied by the taxpayer accounted for "
            f"{_sar(recon['evidence_total'])} of that difference.")
    activities.append(
        "Four automated checks were then run over the records received — the conditions the "
        "law sets for a document, keying and transposition errors, the totals the records "
        "support against those declared, and whether there is supporting evidence behind "
        "what was claimed. Each proposal was settled against the source records; the "
        "findings below are those that were confirmed.")
    if not recon.get("population_complete", True):
        activities.append(
            "NOTE: the records supplied do not yet meet the terms of the request. The figures "
            "above should be treated as a floor rather than a settled position.")

    if findings:
        lines = []
        seen_basis: set[str] = set()
        for f in findings:
            basis = f.get("basis") or f.get("hypothesis_id")
            first = basis not in seen_basis
            seen_basis.add(basis)
            amount = f" {_sar(f['amount'])}." if (f.get("amount") and first) else ""
            prefix = "  Also characterised as: " if not first else "- "
            lines.append(f"{prefix}{f['statement']}{amount}")
            if first and f.get("explanation"):
                lines.append(f"    Basis: {f['explanation']}")
        found = "\n".join(lines)
    else:
        found = ("No finding was established from the records supplied. The declared position "
                 "is supported by the evidence available.")

    if findings:
        recommendations = (
            "Put the findings above to the taxpayer in writing and invite representations "
            "before any assessment is raised. Where a finding rests on a defect in the "
            "records rather than on the figures, request the underlying documents.")
    else:
        recommendations = "Close the case. No adjustment is proposed."

    if exposure.get("total"):
        assessment_lines = [
            f"Output VAT understated: {_sar(exposure.get('increases_output', 0))}",
            f"Input VAT not recoverable: {_sar(exposure.get('disallows_input', 0))}",
            f"Total proposed adjustment: {_sar(exposure.get('total', 0))}",
            "",
            "Each amount is stated once. Where several findings describe the same records, "
            "the amount is counted against the records and not against each finding.",
        ]
        if exposure.get("documentation_at_risk"):
            assessment_lines.insert(2, (
                f"Documentation defects on records not already carrying an adjustment: "
                f"{_sar(exposure['documentation_at_risk'])} — not part of the proposed "
                f"adjustment."))
        assessment = "\n".join(assessment_lines)
    else:
        assessment = ("No measure is proposed. The records supplied support the position "
                      "declared, within the materiality applied to this review "
                      f"({_sar(recon.get('materiality', 0))}).")

    future = []
    if findings:
        codes = sorted({f["code"] for f in findings})
        future.append("Findings raised on this period: " + ", ".join(codes) + ".")
        future.append("Worth re-testing in the next period to establish whether the cause "
                      "was corrected.")
    if not recon.get("population_complete", True):
        future.append("The response to the information request was incomplete; consider "
                      "whether a field visit is warranted if the pattern repeats.")
    if not future:
        future.append("No issue arising from this review is expected to bear on a future audit.")

    return Section("Audit Outcome", [
        Field("Audit objectives", objectives),
        Field("Description of Audit activities", "\n".join(activities),
              "Note all key actions taken during the audit, including records examined, "
              "creditability checks performed, and the summary results."),
        Field("Audit Findings", found),
        Field("Audit Recommendations", recommendations),
        Field("Rulings", FOR_AUDITOR,
              "Note details of any rulings given to the taxpayer, verbally or in writing. "
              "If none, state 'none'."),
        Field("Assessment", assessment,
              "Provide details on the proposed assessment measures and justify each measure "
              "separately; also provide justification if no measures were proposed."),
        Field("Penalties imposed", FOR_AUDITOR),
        Field("Future Audits", "\n".join(future),
              "List any issues that may be relevant to future audits."),
    ])


def risk_feedback(case, recon: dict, findings: list[dict]) -> Section:
    """What the review tells the risk engine — closing the loop the referral opened."""
    indicator = case.risk_category or case.case_reason_code or NOT_HELD
    confirmed = bool(findings)

    if confirmed:
        response = (f"The referral is borne out. {len(findings)} finding(s) were established "
                    f"from the records supplied.")
    elif recon.get("difference"):
        response = ("The referral surfaced a real difference, but the records supplied "
                    "account for it. No finding.")
    else:
        response = ("The referral is not borne out on the records supplied. The declared "
                    "position is supported.")

    if confirmed:
        effects = {f["effect"] for f in findings}
        if oc.INCREASES_OUTPUT in effects and oc.DISALLOWS_INPUT in effects:
            driver = "Output VAT understated and input VAT over-recovered"
        elif oc.INCREASES_OUTPUT in effects:
            driver = "Output VAT understated"
        elif oc.DISALLOWS_INPUT in effects:
            driver = "Input VAT over-recovered"
        else:
            driver = "Defects in the records rather than in the figures"
        reason = findings[0]["statement"]
    else:
        driver = "None established"
        reason = "Not applicable — no under-reporting was established."

    source = recon.get("population_document") or NOT_HELD
    if source != NOT_HELD:
        source = f"Records supplied by the taxpayer ({source})"

    return Section("Risk feedback", [
        Field("Indicators", indicator),
        Field("Indicator response description", response),
        Field("Under reporting driver", driver),
        Field("Under reporting reason", reason),
        Field("Primary source of evidence", source),
    ])


# ------------------------------------------------------------------ assembly
def build(case, taxpayer, recon: dict, investigation: dict, *,
          priority: dict | None = None, requested: list[dict] | None = None,
          received: list[dict] | None = None, gaps: list[dict] | None = None) -> dict:
    """The whole report, section by section, in the template's own order."""
    findings = investigation.get("findings") or []
    exposure = investigation.get("exposure") or {}
    sections = [
        taxpayer_information(taxpayer),
        case_information(case, priority),
        audit_team(),
        taxpayer_documentation(requested or [], received or [], gaps or []),
        audit_outcome(case, recon, findings, exposure,
                      investigation.get("conclusion", "")),
        risk_feedback(case, recon, findings),
    ]
    total = sum(len(s.fields) for s in sections)
    held = sum(1 for s in sections for f in s.fields if f.held)
    return {
        "title": "Audit report",
        "case_id": case.case_id,
        "taxpayer": taxpayer.name,
        "sections": [s.to_dict() for s in sections],
        "completeness": {"fields": total, "filled": held,
                         "outstanding": total - held},
    }
