"""Load the VAT Mistakes Rulebook summary table into core.rule_library."""
from __future__ import annotations

import re
from pathlib import Path

from ..rule_taxonomy import classify

RULEBOOK = Path(__file__).resolve().parents[3] / "docs" / "VAT-Mistakes-Rulebook.md"


def _sev_band(s: str) -> str:
    t = re.split(r"[ (/–—-]", s.strip(), 1)[0].lower()
    return t if t in ("high", "medium", "low") else "medium"


def _gap_band(g: str) -> str:
    gl = g.strip().lower()
    if gl.startswith("yes"):
        return "yes"
    if gl.startswith("partial"):
        return "partial"
    return "no"


def parse_rules(path: Path = RULEBOOK) -> list[dict]:
    md = path.read_text(encoding="utf-8")
    rules: list[dict] = []
    in_tbl = False
    for ln in md.splitlines():
        if ln.strip().startswith("## Summary table"):
            in_tbl = True
            continue
        if in_tbl:
            if ln.strip().startswith("## ") or ln.strip() == "---":
                if rules:
                    break
                continue
            if ln.strip().startswith("|"):
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if len(cells) < 5:
                    continue
                code = cells[0]
                if not re.match(r"^[A-Z]{2,4}-\d", code):
                    continue
                family, gap_band = cells[2], _gap_band(cells[3])
                rules.append({
                    "code": code,
                    "title": cells[1],
                    "family": family,
                    "explains_gap": cells[3].replace("->", "→"),
                    "gap_band": gap_band,
                    "severity": cells[4],
                    "severity_band": _sev_band(cells[4]),
                    "root_cause_code": code,  # placeholder until ZATCA code list arrives
                    # explanation / mistake / risk, plus precedence stage and difference class
                    **classify(code, family, gap_band),
                })
    return rules
