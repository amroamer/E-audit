"""Seed one full round trip on the hero case, so the loop has something to show on load.

The demo needs to open on the state auditors actually spend their time in: a request already
issued, a response already received, and the response not quite right. Building it here — by
running the real planner, the real extractor and the real checker rather than writing the
outcome down — means the seeded state is a genuine product of the pipeline, and any drift in
the pipeline shows up immediately as different seeded gaps.

Only the hero case is seeded this far. The others open at the planning stage, which is where a
new case starts.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..agents.correspondence import draft_request
from ..models import AuditCase, Taxpayer
from ..requests import service
from . import demo_files

HERO = "CASE-2025-0481"


def build(db: Session) -> dict:
    """Issue round 1 on the hero case and record the taxpayer's deficient response."""
    case = db.scalar(select(AuditCase).where(AuditCase.case_id == HERO))
    if case is None:
        return {"seeded": False}
    taxpayer = db.get(Taxpayer, case.taxpayer_id)

    req = service.open_request(db, case)
    if not req.items:
        return {"seeded": False, "reason": "planner produced no items"}

    issued = (case.referral_date or date.today()) + timedelta(days=4)
    drafted = draft_request(case, taxpayer, req)
    service.issue(db, req, body=drafted["text"], source=drafted["source"], when=issued)

    # the taxpayer answers the sales analysis — late, and not quite as asked
    sales_item = next((i for i in req.items if i.catalog_key == "sales-analysis"), req.items[0])
    service.record_document(
        db, case=case, req=req, item_id=sales_item.id,
        filename="Sales_Analysis_Q1_2025.xlsx",
        data=demo_files.sales_analysis_xlsx(),
        file_format="xlsx",
        received=issued + timedelta(days=34),      # the months-long wait, in miniature
    )

    report = service.run_checks(db, case)
    return {"seeded": True, "case_id": HERO, "round": req.seq,
            "items": len(req.items), "gaps": len(report.gaps),
            "blocking": len(report.blocking)}
