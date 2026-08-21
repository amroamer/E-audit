"""Deterministic guards + placeholder rendering + fallbacks. Pure stdlib."""
from __future__ import annotations

import re
from decimal import Decimal

# ---- placeholder identity: the ONLY way an engine number may appear in Claude prose.
# The vocabulary is the engine's, and it is deliberately short: rules decide which documents
# qualify, so there is no pre-qualification total and no "explained by rules" share to name.
_SCALAR_KEYS = ("declared", "expected", "difference", "evidence_total", "unexplained",
                "materiality", "invoices_considered", "qualifying_count", "population_count")

# ---- literals Claude is allowed to write verbatim (NOT figures): rule + doc codes, VAT rate
_RULECODE_RE = re.compile(r"\b[A-Z]{2,4}-\d{2,3}\b")          # COR-01, TIM-04
_DOC_CODES = {"381", "388", "383", "386"}                    # e-invoice document type codes
_STATUTORY = {"15", "5"}                                     # VAT rates, may appear as "15%"
_ALLOWED_LITERALS = _DOC_CODES | _STATUTORY

# ---- Arabic-Indic normalization (F12): fold digits, drop AR grouping
_AR = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789", "٬")

# ---- token scanners
_PLH_RE = re.compile(r"\{\{([a-zA-Z0-9_.\-]+)\}\}")
_NUM_RE = re.compile(r"(?<![A-Za-z])\d[\d,]*(?:\.\d+)?")      # any numeric literal
_MAGNITUDE_RE = re.compile(
    r"\b(thousand|million|billion|hundred)\b|"
    r"\b(a third|two[- ]thirds|half|quarter|double|twice)\b", re.I)

# ---- conclusion guards (F1)
_FINDING_WORDS = re.compile(
    r"\b(finding|assessment|penalt(?:y|ies)|evasion|non-?compliance|"
    r"under-?declar\w*|shortfall|liab\w*|adjustment required)\b", re.I)
_CLEARED_WORDS = re.compile(
    r"\b(no (?:issue|finding|adjustment|further action|discrepancy)|"
    r"fully (?:explained|reconciled)|case closed|100%\s*explained|nothing to pursue)\b", re.I)


# =========================================================== rendering
def _sar(v) -> str:
    return "SAR " + f"{abs(Decimal(str(v))):,.0f}"


def placeholder_values(recon: dict) -> dict:
    vals = {
        "declared": _sar(recon["declared"]),
        "expected": _sar(recon["expected_vat"]),
        "difference": _sar(recon["difference"]),
        "evidence_total": _sar(recon.get("evidence_total", 0.0)),
        "unexplained": _sar(recon["unexplained"]),
        "materiality": _sar(recon["materiality"]),
        "invoices_considered": f"{int(recon['invoices_considered'])}",
        "qualifying_count": f"{int(recon.get('counted_lines', 0))}",
        "population_count": f"{int(recon.get('population_lines', 0))}",
    }
    # one token per rule that removed documents, so prose can name what a step did without
    # implying it subtracted anything from a total
    for step in recon.get("funnel", []):
        if step.get("rule"):
            vals[f"step.{step['rule']}"] = _sar(step["amount"])
            vals[f"step.{step['rule']}.count"] = f"{int(step['count'])}"
    for ev in recon.get("evidence", []):
        vals[f"evidence.{ev['code']}"] = _sar(ev["amount"])
    return vals


def render_placeholders(text: str, recon: dict) -> str:
    vals = placeholder_values(recon)
    return _PLH_RE.sub(lambda m: vals.get(m.group(1), m.group(0)), text)


# =========================================================== verify_claims
def verify_claims(text: str, recon: dict | None, *, figure_free: bool = False) -> dict:
    """Rejects any figure Claude fabricated. Under the placeholder model this means:
       every {{token}} must be a known placeholder, and NO bare numeric literal may
       appear except whitelisted rule/doc codes and the statutory rate.
       figure_free=True (taxpayer summary): reject ALL numeric literals, no recon needed."""
    text = (text or "").translate(_AR).replace("٪", "%")
    violations: list[str] = []
    known = set(placeholder_values(recon)) if recon is not None else set()

    for name in _PLH_RE.findall(text):
        if figure_free or name not in known:
            violations.append(f"unknown/forbidden placeholder {{{{{name}}}}}")
    stripped = _PLH_RE.sub(" ", text)          # engine values enter ONLY via placeholders
    stripped = _RULECODE_RE.sub(" ", stripped)  # rule codes are language, not figures

    for tok in _NUM_RE.findall(stripped):
        norm = tok.replace(",", "")
        if norm in _ALLOWED_LITERALS:
            continue
        violations.append(f"fabricated figure “{tok}” (Claude must use a placeholder)")

    for m in _MAGNITUDE_RE.finditer(stripped):
        violations.append(f"magnitude/ratio in prose: “{m.group(0)}”")

    seen, out = set(), []
    for v in violations:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return {"ok": not out, "violations": out}


# =========================================================== verify_correspondence
def verify_correspondence(text: str, facts: str) -> dict:
    """Guard for outbound letters, where the placeholder model does not fit.

    A request or follow-up quotes engine-authored facts — "the column 'description' is missing",
    "the rows sum to SAR 468,000" — rather than reconciliation scalars, so there is no fixed
    placeholder vocabulary to check against. The rule is the same in substance: **Claude may
    repeat a figure that the engine put in front of it, and may not introduce one.**

    So every numeric literal in the draft must already appear in `facts` (the gap details, the
    item descriptions, the period). Anything else is a fabrication, whether it is a plausible
    total or a deadline nobody set.
    """
    text = (text or "").translate(_AR).replace("٪", "%")
    facts = (facts or "").translate(_AR).replace("٪", "%")
    supplied = {t.replace(",", "") for t in _NUM_RE.findall(facts)}
    stripped = _RULECODE_RE.sub(" ", text)

    violations: list[str] = []
    for tok in _NUM_RE.findall(stripped):
        norm = tok.replace(",", "")
        if norm in supplied or norm in _ALLOWED_LITERALS:
            continue
        violations.append(f"figure “{tok}” does not appear in the facts supplied")
    for m in _MAGNITUDE_RE.finditer(stripped):
        violations.append(f"magnitude/ratio in prose: “{m.group(0)}”")

    seen, out = set(), []
    for v in violations:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return {"ok": not out, "violations": out}


# =========================================================== verify_conclusion (F1)
def verify_conclusion(text: str, recon: dict) -> list:
    """A wrong VERDICT passes every figure check. Guard the words that flip the outcome."""
    text = text or ""
    state = recon.get("state")
    left, mat = abs(float(recon["unexplained"])), abs(float(recon["materiality"]))
    out: list[str] = []
    if state == "supported":
        out += [f"finding-language on a SUPPORTED case: “{m.group(0)}”"
                for m in _FINDING_WORDS.finditer(text)]
    if state == "potential-finding" and left > mat:
        out += [f"clearance-language on an OPEN finding: “{m.group(0)}”"
                for m in _CLEARED_WORDS.finditer(text)]
    return out


# =========================================================== streaming guard
class StreamGuard:
    """Verify + substitute per whole segment; never flush mid-placeholder (F8).
    `unmask` restores the pseudonymized taxpayer name (F7) after substitution."""

    _BOUND = re.compile(r"(?<!\d)[.!?](?=\s|$)|\n|##")

    def __init__(self, recon: dict, unmask=lambda s: s):
        self.recon, self.unmask, self.buf, self.tripped = recon, unmask, "", False

    def feed(self, chunk: str) -> str:
        self.buf += chunk
        out = ""
        while True:
            if re.search(r"\{\{[^}]*$", self.buf):     # ends mid-placeholder → wait
                break
            m = self._BOUND.search(self.buf)
            if not m:
                break
            seg, self.buf = self.buf[:m.end()], self.buf[m.end():]
            if not self._ok(seg):
                return out
            out += self.unmask(render_placeholders(seg, self.recon))
        return out

    def finish(self) -> str:
        if self.tripped or not self._ok(self.buf):
            return ""
        tail, self.buf = self.buf, ""
        return self.unmask(render_placeholders(tail, self.recon))

    def _ok(self, seg: str) -> bool:
        v = verify_claims(seg, self.recon)
        if not v["ok"] or verify_conclusion(seg, self.recon):
            self.tripped = True
            return False
        return True


# =========================================================== deterministic fallbacks
# ENGINE-AUTHORED trusted text — real digits are fine here and NOT passed through verify.
def fb_narration(recon: dict) -> str:
    """The engine's own account of the box. Qualification first, then the comparison."""
    funnel = recon.get("funnel", [])
    steps = [s for s in funnel if s["kind"] in ("exclude", "defer")]
    source = next((s["label"].lower() for s in funnel if s["kind"] == "population"),
                  "e-invoice lines on file")
    removed = "; ".join(
        f"{s['count']} for {s['label'].lower()}" + (f" ({s['rule']})" if s.get("rule") else "")
        for s in steps)
    narrowing = (f"the rules set aside {removed}, leaving "
                 f"{int(recon.get('counted_lines', 0))} that qualify for this period"
                 if steps else
                 f"every one qualifies for this period")
    ev = recon.get("evidence_total") or 0.0
    if recon["state"] == "supported" and not ev:
        tail = "The two agree within materiality."
    elif ev:
        tail = (f"Taxpayer evidence accounts for {_sar(ev)} of it, leaving "
                f"{_sar(recon['unexplained'])} ({recon['band']}).")
    else:
        tail = f"Nothing on file accounts for it ({recon['band']})."
    return (f"Of {int(recon.get('population_lines', 0))} {source}, {narrowing}, "
            f"totalling {_sar(recon['expected_vat'])}. The return declares "
            f"{_sar(recon['declared'])}, a difference of {_sar(recon['difference'])}. {tail}")


def fb_nba(recon: dict):
    from .schemas import NextBestAction
    if recon["state"] == "supported" or abs(recon["unexplained"]) <= recon["materiality"]:
        return NextBestAction(
            action_type="no-action",
            document_requested="None — the difference is within materiality.",
            addressed_to="internal-review",
            rationale="What qualifies for this period agrees with the declared box.",
            expected_yield="Case can be closed as supported.", minimises_contact=True)
    return NextBestAction(
        action_type="request-explanation",
        document_requested="A written reconciliation of the difference for the period.",
        addressed_to="taxpayer",
        rationale="The qualifying e-invoices and the declared box do not agree, and nothing on "
                  "file accounts for the difference.",
        expected_yield="Confirms or clears the {{unexplained}} still unaccounted for.",
        minimises_contact=False)


def fb_summary(profile: dict, prior_returns: list, prior_cases: list) -> dict:
    amended = [r for r in prior_returns if not r.get("current")]
    pts = [f"Sector: {profile.get('sector', 'n/a')}; size: {profile.get('size', 'n/a')}; "
           f"accounting basis: {profile.get('accounting_method', 'n/a')}."]
    if amended:
        pts.append(f"{len(amended)} amended return{'' if len(amended) == 1 else 's'} on file.")
    if prior_cases:
        pts.append(f"{len(prior_cases)} prior audit case{'' if len(prior_cases) == 1 else 's'} for this taxpayer.")
    while len(pts) < 2:
        pts.append("Limited prior history available.")
    return {"headline": "Auditor brief assembled from profile and prior filings (deterministic).",
            "points": pts[:5],
            "risk_flags": (["Repeated amendments"] if len(amended) > 1 else []),
            "prior_pattern": ("Recurring adjustments across periods." if prior_cases
                              else "No prior audit findings recorded.")}


def fb_report(recon: dict) -> str:
    """The audit report, written by the engine. Qualification, then comparison — in that order."""
    concl = ("What qualifies for this period agrees with the declared box within materiality; "
             "the case is **supported** with no further action."
             if recon["state"] == "supported"
             else f"{_sar(recon['unexplained'])} ({recon['band']}) is still unaccounted for; "
                  f"the case is a **potential finding** pending evidence.")
    steps = "\n".join(
        f"- {s['label']}: {s['count']} "
        f"document{'' if s['count'] == 1 else 's'}, {_sar(s['amount'])}"
        + (f" [{s['rule']}]" if s.get("rule") else "")
        for s in recon.get("funnel", []) if s["kind"] in ("exclude", "defer")) \
        or "- No rule removed any document from the population."
    ev = "\n".join(f"- {e['label']}: {_sar(e['amount'])}"
                   for e in recon.get("evidence", []))
    return (f"## Case summary\n"
            f"{int(recon.get('counted_lines', 0))} of "
            f"{int(recon.get('population_lines', 0))} documents qualify for {recon['box']} in "
            f"this period, totalling {_sar(recon['expected_vat'])}. The return declares "
            f"{_sar(recon['declared'])}.\n\n"
            f"## Which documents qualify\n{steps}\n\n"
            f"## Comparison\n"
            f"- Expected (qualifying e-invoices): {_sar(recon['expected_vat'])}\n"
            f"- Declared (as filed): {_sar(recon['declared'])}\n"
            f"- Difference: {_sar(recon['difference'])}\n"
            + (f"\n### Accounted for by taxpayer evidence\n{ev}\n" if ev else "")
            + f"\n## Conclusion\n{concl}\n\n"
            f"## Recommended next action\n"
            + ("Close as supported." if recon["state"] == "supported"
               else "Request a written reconciliation of the difference from the taxpayer."))
