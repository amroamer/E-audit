"""Composite case prioritization.

score = 40% exposure + 30% deadline/SLA + 20% taxpayer history + 10% quick-win
Each signal is normalised to 0–1, blended, and reported as a 0–100 score, a
High/Medium/Low band, and the single top driver (for the queue chip).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from .models import AuditCase, VatReturn
from .recon_engine import reconcile_case

WEIGHTS = {"exposure": 0.40, "deadline": 0.30, "history": 0.20, "quickwin": 0.10}
EXPOSURE_CEILING = 100_000.0   # SAR residual that scores a full 1.0 on exposure
SLA_WINDOW = 90                # days; urgency ramps across this window


def _band(score: int) -> str:
    return "high" if score >= 60 else ("medium" if score >= 35 else "low")


def score_case(db: Session, case: AuditCase) -> dict:
    # exposure + quick-win come from a (non-persisting) reconstruction.
    # exposure spans BOTH boxes: output under-declaration + input over-claim (combined.total_exposure)
    try:
        recon = reconcile_case(db, case.case_id, persist=False)
        combined = recon.get("combined") or {}
        residual = float(combined.get("priority_exposure", abs(float(recon["residual"]))))
        explained = float(recon["explained_pct"] or 0.0)
    except Exception:
        residual, explained = 0.0, 0.0
    exposure = min(residual / EXPOSURE_CEILING, 1.0)
    quickwin = explained                                   # more explained → less effort left

    # deadline/SLA — urgency rises as the due date approaches (and past it)
    days = None
    deadline = 0.0
    if case.sla_due:
        days = (case.sla_due - date.today()).days
        deadline = max(0.0, min(1.0, 1.0 - days / SLA_WINDOW))

    # taxpayer history — prior findings and amended returns for this taxpayer
    prior_findings = db.scalar(
        select(func.count()).select_from(AuditCase).where(
            AuditCase.taxpayer_id == case.taxpayer_id,
            AuditCase.case_id != case.case_id,
            AuditCase.diff_tax_amt > 0,
        )
    ) or 0
    amended = db.scalar(
        select(func.count()).select_from(VatReturn).where(
            VatReturn.taxpayer_id == case.taxpayer_id,
            VatReturn.current_flag.is_(False),
        )
    ) or 0
    history = min(prior_findings * 0.5 + amended * 0.25, 1.0)

    parts = {"exposure": exposure, "deadline": deadline, "history": history, "quickwin": quickwin}
    score = round(sum(WEIGHTS[k] * parts[k] for k in WEIGHTS) * 100)

    contrib = {k: WEIGHTS[k] * parts[k] for k in WEIGHTS}
    top = max(contrib, key=contrib.get)
    drivers = {
        "exposure": f"SAR {int(residual):,} at stake",
        "deadline": ("past SLA deadline" if days is not None and days < 0
                     else (f"due in {days} days" if days is not None else "no deadline")),
        "history": (f"{int(prior_findings)} prior finding(s)" if prior_findings else "clean history"),
        "quickwin": f"{round(explained * 100)}% already explained",
    }

    return {
        "score": score,
        "band": _band(score),
        "driver": drivers[top],
        "signals": {
            "exposure": round(exposure, 3), "deadline": round(deadline, 3),
            "history": round(history, 3), "quickwin": round(quickwin, 3),
        },
        "residual": round(residual, 2),
        "deadline_days": days,
        "prior_findings": int(prior_findings),
    }
