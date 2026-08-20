"""The case lifecycle: one bounded stage machine from referral to conclusion.

The auditors described the job as two phases — planning, then execution and closure — and the
PoC had been implementing a slice in the middle of it. This is the whole run:

    1 · Intake              the referral is parsed and the dossier assembled
    2 · Planning            hypotheses formed, gaps identified, a request drafted
    3 · Request / response  issued, answered, and checked until nothing is missing
    4 · Substantive review  hypotheses adjudicated against the evidence
    5 · Closure             report and taxpayer letter drafted for approval

Three things make this a state machine rather than a workflow engine.

**It is derived, never stored.** Every stage's state is computed from the case's own data —
whether a request exists, whether gaps remain, whether the reconciliation is material. There
is no status column to fall out of step with reality, and no migration when a rule changes.

**Every gate is a human decision.** §6 is explicit that materiality, hypothesis validation and
the final conclusion are human-led. The machine reports where the case is and what it is
waiting for; it never advances a stage by itself.

**Waiting is a first-class state.** Pain point one is that responses take months. A stage
blocked on the taxpayer is not the same as one blocked on the auditor, and a queue that
cannot tell them apart cannot be prioritised.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditCase, TaxpayerResponse
from ..requests import service as requests_service

# state vocabulary, in the order a stage moves through it
DONE = "done"           # its gate has been passed
ACTIVE = "active"       # the case is here now, and the next move is the auditor's
WAITING = "waiting"     # here, but blocked on someone outside ZATCA
PENDING = "pending"     # not reached yet
SKIPPED = "skipped"     # not needed — the case resolved without it

# a stage that still needs someone to act
OPEN = (ACTIVE, WAITING)

STAGES = ("intake", "planning", "correspondence", "review", "closure")

LABELS = {
    "intake": "Intake",
    "planning": "Planning",
    "correspondence": "Request & response",
    "review": "Substantive review",
    "closure": "Closure",
}
OWNERS = {
    "intake": "system",
    "planning": "auditor",
    "correspondence": "taxpayer",
    "review": "auditor",
    "closure": "auditor",
}


@dataclass
class Stage:
    key: str
    label: str
    state: str
    owner: str
    summary: str
    next_action: str = ""
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"key": self.key, "label": self.label, "state": self.state, "owner": self.owner,
                "summary": self.summary, "next_action": self.next_action, "detail": self.detail}


def _sar(v: float) -> str:
    return f"SAR {abs(v):,.0f}"


def status(db: Session, case: AuditCase, *, recon: dict | None = None,
           investigation: dict | None = None) -> dict:
    """Where this case is, what it is waiting for, and whose move it is.

    `recon` and `investigation` are passed in when the caller already has them, so the rail
    can render without recomputing a reconciliation the page is about to show anyway.
    """
    stages: list[Stage] = []

    # The reconciliation runs on internal data alone, so it is known before any request goes
    # out — which is what lets a case be cleared without contacting the taxpayer at all. That
    # is the minimise-contact principle from §1, and it has to be visible on the rail rather
    # than showing a request the auditor never needs to send.
    if recon is None:
        from ..recon_engine import reconcile_case
        try:
            recon = reconcile_case(db, case.case_id, persist=False)
        except Exception:                       # noqa: BLE001 — a case may have no return
            recon = None
    settled = (recon is not None
               and abs(float(recon["unexplained"])) <= float(recon["materiality"])
               and recon.get("purchase", {}).get("state") != "potential-finding")

    # ---- 1 · intake -------------------------------------------------------------------
    from ..dossier import collect, held_sources

    dossier = collect(db, case.case_id)
    held = held_sources(dossier)
    stages.append(Stage(
        key="intake", label=LABELS["intake"], state=DONE, owner=OWNERS["intake"],
        summary=(f"{len(held)} of {len(dossier['sources'])} internal sources on file. "
                 f"Referred as {dossier['referral']['indicator_label']}."),
        detail={"sources_held": sorted(held),
                "indicator": dossier["referral"]["indicator_code"]}))

    # ---- 2 · planning -----------------------------------------------------------------
    rounds = requests_service.rounds(db, case.case_id)
    if not rounds and settled:
        stages.append(Stage(
            key="planning", label=LABELS["planning"], state=SKIPPED, owner=OWNERS["planning"],
            summary="Not needed — the internal evidence settles the case, so nothing was "
                    "requested from the taxpayer."))
    elif not rounds:
        stages.append(Stage(
            key="planning", label=LABELS["planning"], state=ACTIVE, owner=OWNERS["planning"],
            summary="No information request has been drafted yet.",
            next_action="Review the plan and draft the request."))
    else:
        first = rounds[0]
        stages.append(Stage(
            key="planning", label=LABELS["planning"], state=DONE, owner=OWNERS["planning"],
            summary=f"{len(first.items)} items requested in round 1.",
            detail={"items": [i.label for i in first.items]}))

    # ---- 3 · request / response -------------------------------------------------------
    if not rounds:
        stages.append(Stage(
            key="correspondence", label=LABELS["correspondence"],
            state=SKIPPED if settled else PENDING, owner=OWNERS["correspondence"],
            summary=("Not needed — the taxpayer was never contacted." if settled
                     else "Not started.")))
        loop_complete = settled
    else:
        loop = requests_service.state(db, case)
        loop_complete = loop["complete"]
        current = rounds[-1]
        if loop_complete:
            stages.append(Stage(
                key="correspondence", label=LABELS["correspondence"], state=DONE,
                owner=OWNERS["correspondence"],
                summary=(f"Satisfied after {loop['round']} round"
                         f"{'' if loop['round'] == 1 else 's'} of correspondence."),
                detail={"rounds": loop["round"]}))
        elif current.status == "draft":
            stages.append(Stage(
                key="correspondence", label=LABELS["correspondence"], state=ACTIVE,
                owner="auditor",
                summary=f"Round {current.seq} is drafted but not issued.",
                next_action="Approve and issue the request."))
        elif current.status == "issued":
            overdue = bool(current.due_at and current.due_at < date.today())
            stages.append(Stage(
                key="correspondence", label=LABELS["correspondence"], state=WAITING,
                owner=OWNERS["correspondence"],
                summary=(f"Round {current.seq} issued "
                         f"{current.issued_at:%d %b %Y}; "
                         + ("response overdue." if overdue
                            else f"due {current.due_at:%d %b %Y}.")),
                next_action="Waiting on the taxpayer.",
                detail={"overdue": overdue}))
        else:
            stages.append(Stage(
                key="correspondence", label=LABELS["correspondence"], state=ACTIVE,
                owner="auditor",
                summary=(f"Round {current.seq} answered, but {loop['blocking']} item"
                         f"{'' if loop['blocking'] == 1 else 's'} still fall short of the "
                         f"request."),
                next_action="Send the drafted follow-up, or waive what is not needed.",
                detail={"blocking": loop["blocking"], "round": current.seq}))

    # ---- 4 · substantive review -------------------------------------------------------
    # The review opens on internal data, but it cannot *conclude* while requested evidence
    # is still outstanding — so an unsettled case reads as provisional until the loop closes.
    if recon is None:
        stages.append(Stage(key="review", label=LABELS["review"], state=PENDING,
                            owner=OWNERS["review"], summary="No return on file to reconcile."))
    else:
        unexplained = float(recon["unexplained"])
        leading = (investigation or {}).get("conclusion", "")
        if settled:
            stages.append(Stage(
                key="review", label=LABELS["review"], state=DONE, owner=OWNERS["review"],
                summary="The declared return is supported by the qualified evidence within "
                        "materiality.",
                detail={"unexplained": unexplained, "state": recon["state"]}))
        elif loop_complete:
            stages.append(Stage(
                key="review", label=LABELS["review"], state=ACTIVE, owner=OWNERS["review"],
                summary=(f"{_sar(unexplained)} unexplained with the evidence complete."
                         + (f" {leading}" if leading else "")),
                next_action="Validate the leading hypothesis and reach a conclusion.",
                detail={"unexplained": unexplained, "state": recon["state"]}))
        else:
            stages.append(Stage(
                key="review", label=LABELS["review"], state=ACTIVE, owner=OWNERS["review"],
                summary=(f"{_sar(unexplained)} unexplained on internal data. The evidence "
                         f"requested is not yet complete, so this is provisional."),
                next_action="Continue the review; do not conclude until the response is "
                            "complete.",
                detail={"unexplained": unexplained, "state": recon["state"], "provisional": True}))

    # ---- 5 · closure ------------------------------------------------------------------
    responses = db.scalars(
        select(TaxpayerResponse).where(TaxpayerResponse.case_id == case.case_id)).all()
    if case.status == "closed":
        stages.append(Stage(
            key="closure", label=LABELS["closure"], state=DONE, owner=OWNERS["closure"],
            summary=f"Closed as {case.audit_result_type or 'concluded'}."))
    elif settled or (loop_complete and recon is not None):
        stages.append(Stage(
            key="closure", label=LABELS["closure"], state=ACTIVE, owner=OWNERS["closure"],
            summary="Ready to draft the audit report and the taxpayer letter.",
            next_action="Review the drafts and approve.",
            detail={"evidence_recorded": len(responses)}))
    else:
        stages.append(Stage(
            key="closure", label=LABELS["closure"], state=PENDING, owner=OWNERS["closure"],
            summary="Opens once the review can conclude."))

    current = next((s for s in stages if s.state in OPEN), stages[-1])
    return {
        "case_id": case.case_id,
        "stages": [s.to_dict() for s in stages],
        "current": current.key,
        "current_label": current.label,
        "waiting_on": current.owner if current.state in OPEN else "",
        "next_action": current.next_action,
        "complete": all(s.state in (DONE, SKIPPED) for s in stages),
        # the auto-clear claim, stated plainly: this case needed no contact with the taxpayer
        "no_contact_needed": any(s.key == "correspondence" and s.state == SKIPPED
                                 for s in stages),
    }
