"""Deterministic guards + placeholder rendering + fallbacks. Pure stdlib."""
from __future__ import annotations

import re
from decimal import Decimal

# ---- placeholder identity: the ONLY way an engine number may appear in Claude prose
_SCALAR_KEYS = ("declared", "reconstructed_gross", "apparent_gap", "explained_total",
                "explained_pct", "residual", "materiality", "invoices_considered")

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
    vals = {k: _sar(recon[k]) for k in
            ("declared", "reconstructed_gross", "apparent_gap",
             "explained_total", "residual", "materiality")}
    vals["invoices_considered"] = f"{int(recon['invoices_considered'])}"
    ep = recon.get("explained_pct")
    vals["explained_pct"] = "—" if ep is None else f"{round(float(ep) * 100)}%"
    for b in recon["bridge"]:
        if b.get("rule"):
            vals[f"bridge.{b['rule']}"] = _sar(b["amount"])
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


# =========================================================== verify_conclusion (F1)
def verify_conclusion(text: str, recon: dict) -> list:
    """A wrong VERDICT passes every figure check. Guard the words that flip the outcome."""
    text = text or ""
    state = recon.get("state")
    resid, mat = abs(float(recon["residual"])), abs(float(recon["materiality"]))
    out: list[str] = []
    if state == "supported":
        out += [f"finding-language on a SUPPORTED case: “{m.group(0)}”"
                for m in _FINDING_WORDS.finditer(text)]
    if state == "potential-finding" and resid > mat:
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
    expl = "; ".join(
        f"{b['rule']} {b['label'].lower()} ({_sar(b['amount'])})"
        for b in recon["bridge"] if b["kind"] == "explain") or "no reconciling items"
    tail = ("leaving no material residual." if recon["state"] == "supported"
            else f"leaving an unexplained residual of {_sar(recon['residual'])} ({recon['band']}).")
    return (f"Reconstructing {recon['box'].lower()} from {int(recon['invoices_considered'])} "
            f"cleared e-invoices gives {_sar(recon['reconstructed_gross'])} against "
            f"{_sar(recon['declared'])} declared — an apparent gap of "
            f"{_sar(recon['apparent_gap'])}. The bridge explains it via {expl}, {tail}")


def fb_nba(recon: dict):
    from .schemas import NextBestAction
    if recon["state"] == "supported" or abs(recon["residual"]) <= recon["materiality"]:
        return NextBestAction(
            action_type="no-action",
            document_requested="None — residual within materiality.",
            addressed_to="internal-review",
            rationale="The reconstructed position reconciles to the declared box within materiality.",
            expected_yield="Case can be closed as supported.", minimises_contact=True)
    return NextBestAction(
        action_type="request-explanation",
        document_requested="A written reconciliation of the unexplained residual for the period.",
        addressed_to="taxpayer",
        rationale="The bridge closes the known reconciling items; only the residual remains.",
        expected_yield="Confirms or clears the residual of {{residual}}.", minimises_contact=False)


def fb_summary(profile: dict, prior_returns: list, prior_cases: list) -> dict:
    amended = [r for r in prior_returns if not r.get("current")]
    pts = [f"Sector: {profile.get('sector', 'n/a')}; size: {profile.get('size', 'n/a')}; "
           f"accounting basis: {profile.get('accounting_method', 'n/a')}."]
    if amended:
        pts.append(f"{len(amended)} amended return(s) on file.")
    if prior_cases:
        pts.append(f"{len(prior_cases)} prior audit case(s) for this taxpayer.")
    while len(pts) < 2:
        pts.append("Limited prior history available.")
    return {"headline": "Auditor brief assembled from profile and prior filings (deterministic).",
            "points": pts[:5],
            "risk_flags": (["Repeated amendments"] if len(amended) > 1 else []),
            "prior_pattern": ("Recurring adjustments across periods." if prior_cases
                              else "No prior audit findings recorded.")}


def fb_report(recon: dict) -> str:
    concl = ("The reconstructed position reconciles to the declared box within materiality; "
             "the case is **supported** with no further action."
             if recon["state"] == "supported"
             else f"An unexplained residual of {_sar(recon['residual'])} ({recon['band']}) "
                  f"remains after the bridge; the case is a **potential finding** pending evidence.")
    lines = "\n".join(f"- {b['label']}: {_sar(b['amount'])} (running {_sar(b['running'])})"
                      for b in recon["bridge"])
    return (f"## Case summary\nDeclared {_sar(recon['declared'])} for {recon['box']}; "
            f"reconstructed {_sar(recon['reconstructed_gross'])} from "
            f"{int(recon['invoices_considered'])} cleared e-invoices.\n\n"
            f"## Reconstruction & bridge\n{lines}\n\n"
            f"## Residual & conclusion\n{concl}\n\n"
            f"## Recommended next action\n"
            + ("Close as supported." if recon["state"] == "supported"
               else "Request a written reconciliation of the residual from the taxpayer."))
