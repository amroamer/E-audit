from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func, delete
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (
    Taxpayer, VatReturn, Invoice, AuditCase, Rule, TaxpayerResponse, EventLog, GapFinding,
)
from ..requests import service as req_service
from ..agents.correspondence import draft_followup, draft_request
from ..recon_engine import reconcile_case
from ..priority import score_case
from ..pipeline.rules import coded_rules as wired_codes
from ..rule_taxonomy import REASON_CODES, STAGES, KINDS
from ..scope import scope_card
from ..dossier import collect as collect_dossier
from ..llm.service import llm
from ..config import settings

router = APIRouter(prefix="/api")


def _rule_rows(db: Session) -> list[dict]:
    return [
        {"code": r.code, "family": r.family, "title": r.title,
         "explains_gap": r.explains_gap, "severity": r.severity}
        for r in db.scalars(select(Rule).order_by(Rule.code)).all()
    ]


@router.get("/health")
def health(db: Session = Depends(get_db)):
    return {
        "status": "ok",
        "taxpayers": db.scalar(select(func.count()).select_from(Taxpayer)),
        "cases": db.scalar(select(func.count()).select_from(AuditCase)),
        "rules": db.scalar(select(func.count()).select_from(Rule)),
    }


@router.get("/rules")
def list_rules(db: Session = Depends(get_db)):
    """The rule library, each row carrying its taxonomy and whether the engine can fire it.

    `wired` comes from the reconciling-item registry rather than a hard-coded list in the
    UI, so a rule added to the registry is badged live without a frontend change.
    """
    wired = wired_codes()
    rows = db.scalars(select(Rule).order_by(Rule.code)).all()
    return [
        {
            "code": r.code, "family": r.family, "title": r.title,
            "explains_gap": r.explains_gap, "gap_band": r.gap_band,
            "severity": r.severity, "severity_band": r.severity_band,
            "root_cause_code": r.root_cause_code, "enabled": r.enabled,
            "rule_kind": r.rule_kind, "stage": r.stage,
            "reason_code": r.reason_code,
            "reason_label": REASON_CODES.get(r.reason_code, ("", ""))[1],
            "wired": r.code in wired,
        }
        for r in rows
    ]


@router.get("/reason-codes")
def list_reason_codes():
    """The difference taxonomy: why a return may legitimately differ from the e-invoices."""
    return {
        "kinds": list(KINDS),
        "stages": list(STAGES),
        "codes": [
            {"code": code, "group": group, "label": label}
            for code, (group, label) in REASON_CODES.items()
        ],
    }


@router.get("/scope")
def scope():
    """What this PoC reconciles, and what it deliberately leaves out."""
    return scope_card()


@router.get("/cases/{case_id}/dossier")
def case_dossier(case_id: str, db: Session = Depends(get_db)):
    """Everything ZATCA already holds on this taxpayer and period, in one call.

    The auditors start a case by investigating internal data — returns, e-invoicing, imports and
    exports, history, prior audits, financials — and only then decide what is genuinely missing.
    Doing that today means opening several systems. This is that step, assembled.
    """
    try:
        return collect_dossier(db, case_id)
    except LookupError:
        raise HTTPException(404, "case not found")


@router.get("/cases/{case_id}/precedent")
def case_precedent(case_id: str, db: Session = Depends(get_db)):
    """What comparable closed cases turned out to be, and which evidence actually closed them.

    Deterministic retrieval over labelled closed cases — no model, no embeddings. Every figure
    is a count or a median taken here, which is what makes the ranked list reproducible.
    """
    from ..agents.precedent_analyst import brief

    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    return brief(db, c).to_dict()


@router.get("/cases/{case_id}/investigate")
def investigate_case(case_id: str, db: Session = Depends(get_db)):
    """Run the multi-agent investigation over the reconciled case.

    Evidence agents propose typed hypotheses; a deterministic adjudicator settles each one
    against the engine's figures. No model is involved in any number here, and the whole
    loop runs without credentials — the agents are pattern detectors, not writers.
    """
    from ..agents.orchestrator import investigate

    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    recon = reconcile_case(db, case_id, persist=False)

    prior_returns = [
        {"form_number": r.form_number,
         "period_from": r.period_from.isoformat(), "period_to": r.period_to.isoformat(),
         "vat_amount": next((float(b.vat_amount) for b in r.boxes
                             if b.box_code == "standard_rate_sales" and b.direction == "sale"), 0.0)}
        for r in db.scalars(
            select(VatReturn).where(VatReturn.taxpayer_id == c.taxpayer_id,
                                    VatReturn.period_from < c.period_from)
            .order_by(VatReturn.period_from)).all()
    ]
    prior_cases = [
        {"case_id": pc.case_id, "root_cause_code": pc.root_cause_code,
         "result": pc.audit_result_type, "action": pc.action_taken}
        for pc in db.scalars(
            select(AuditCase).where(AuditCase.taxpayer_id == c.taxpayer_id,
                                    AuditCase.case_id != case_id,
                                    AuditCase.scenario_key != "corpus")).all()
    ]
    # §7's second line: whatever the taxpayer supplied, and whatever figure an auditor keyed in
    # against it, so the adjudicator can re-add the source and check our own arithmetic.
    docs = [
        {"id": d.id, "filename": d.filename,
         "columns": (d.content or {}).get("columns", []),
         "rows": (d.content or {}).get("rows", [])}
        for d in req_service.documents(db, case_id)
    ]
    recorded = [
        {"seq": r.seq, "label": r.label, "amount": float(r.amount), "doc_name": r.doc_name}
        for r in db.scalars(
            select(TaxpayerResponse).where(TaxpayerResponse.case_id == case_id)
            .order_by(TaxpayerResponse.seq)).all()
    ]
    return investigate(recon, prior_returns=prior_returns, prior_cases=prior_cases,
                       documents=docs, recorded=recorded).model_dump()


class RulePatch(BaseModel):
    enabled: bool


@router.patch("/rules/{code}")
def update_rule(code: str, body: RulePatch, db: Session = Depends(get_db)):
    """Enable/disable a detection rule. Disabling a wired rule (e.g. COR-01) removes it from the bridge."""
    r = db.get(Rule, code)
    if not r:
        raise HTTPException(404, "rule not found")
    r.enabled = body.enabled
    db.commit()
    return {"code": r.code, "enabled": r.enabled}


@router.delete("/rules/{code}")
def delete_rule(code: str, db: Session = Depends(get_db)):
    r = db.get(Rule, code)
    if not r:
        raise HTTPException(404, "rule not found")
    db.delete(r)
    db.commit()
    return {"status": "deleted", "code": code}


@router.get("/cases")
def list_cases(db: Session = Depends(get_db)):
    """Open cases, each scored by the composite priority engine, sorted most-urgent first."""
    cases = db.scalars(
        select(AuditCase).where(AuditCase.status != "closed").order_by(AuditCase.case_id)
    ).all()
    rows = [
        {
            "case_id": c.case_id,
            "taxpayer": c.taxpayer.name,
            "vat_no": c.taxpayer.vat_registration_number,
            "sector": c.taxpayer.ind_sector,
            "period": f"{c.period_from:%Y-%m-%d} → {c.period_to:%Y-%m-%d}",
            "reason": c.case_reason_code,
            "risk": c.risk_category,
            "referral_priority": c.vat_priority,
            "status": c.status,
            "scenario": c.scenario_key,
            "priority": score_case(db, c),
        }
        for c in cases
    ]
    rows.sort(key=lambda r: r["priority"]["score"], reverse=True)
    return rows


@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Executive tiles — aggregated live across every open case's deterministic reconciliation."""
    cases = db.scalars(select(AuditCase).where(AuditCase.status != "closed")).all()
    exposure = explained = apparent = 0.0
    supported = findings = review = 0
    for c in cases:
        try:
            r = reconcile_case(db, c.case_id, persist=False)
        except Exception:
            continue
        combined = r.get("combined") or {}
        apparent += abs(r["apparent_gap"])
        explained += max(r["explained_total"], 0.0)
        state = combined.get("state", r["state"])          # worst of output + input boxes
        if state == "potential-finding":
            exposure += float(combined.get("total_exposure", max(r["residual"], 0.0)))
            findings += 1
        elif state == "unresolved":
            review += 1
        elif state == "supported":
            supported += 1
    n = len(cases)
    return {
        "open_cases": n,
        "exposure_total": round(exposure, 2),
        "explained_total": round(explained, 2),
        "apparent_gap_total": round(apparent, 2),
        "auto_clearable": supported,
        "auto_clearable_pct": round(supported / n, 4) if n else 0.0,
        "needs_action": findings + review,
        "findings": findings,
        "to_review": review,
    }


@router.post("/admin/reseed")
def reseed_demo():
    """Restore the demo database to its seeded state. Synthetic data only — drops and rebuilds all tables."""
    if not settings.data_is_synthetic:
        raise HTTPException(403, "reseed is disabled unless the data is synthetic")
    from ..seed.seed import run as _run
    _run()
    return {"status": "ok", "message": "Demo data restored"}


@router.get("/cases/{case_id}")
def get_case(case_id: str, db: Session = Depends(get_db)):
    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    tp = c.taxpayer
    vret = db.scalar(
        select(VatReturn).where(
            VatReturn.taxpayer_id == tp.id,
            VatReturn.period_from == c.period_from,
            VatReturn.current_flag.is_(True),
        )
    )
    n_inv = db.scalar(
        select(func.count()).select_from(Invoice).where(Invoice.taxpayer_id == tp.id)
    )
    return {
        "case_id": c.case_id,
        "status": c.status,
        "reason": c.case_reason_code,
        "risk": c.risk_category,
        "priority": c.vat_priority,
        "scenario": c.scenario_key,
        "period": f"{c.period_from:%Y-%m-%d} → {c.period_to:%Y-%m-%d}",
        "taxpayer": {
            "name": tp.name, "vat_no": tp.vat_registration_number,
            "sector": tp.ind_sector, "size": tp.business_size,
            "accounting_method": tp.accounting_method, "resident": tp.resident_flag,
            "vat_group": tp.vat_group_rep_flag,
        },
        "return": None if not vret else {
            "form_number": vret.form_number,
            "data_version": vret.data_version,
            "submission_date": vret.submission_date and vret.submission_date.isoformat(),
            "filing_deadline": vret.filing_deadline and vret.filing_deadline.isoformat(),
            "total_vat_due": float(vret.total_vat_due),
            "net_due_vat": float(vret.net_due_vat),
            "boxes": [
                {
                    "box_code": b.box_code, "label": b.box_label, "direction": b.direction,
                    "category": b.category, "rate": b.rate,
                    "base_amount": float(b.base_amount), "vat_amount": float(b.vat_amount),
                    "adjustment": float(b.adjustment),
                }
                for b in vret.boxes
            ],
        },
        "invoice_count": n_inv,
    }


@router.get("/cases/{case_id}/reconcile")
def reconcile(case_id: str, db: Session = Depends(get_db)):
    """Run the deterministic reconstruction + bridge and return the residual + waterfall."""
    try:
        return reconcile_case(db, case_id)
    except ValueError as e:
        raise HTTPException(404, str(e))


# ---------------------------------------------------------------- taxpayer response loop
class ResponseIn(BaseModel):
    label: str
    amount: float           # SAR the evidence accounts for (auditor-confirmed)
    doc_name: str = ""


@router.get("/cases/{case_id}/responses")
def list_responses(case_id: str, db: Session = Depends(get_db)):
    rows = db.scalars(
        select(TaxpayerResponse).where(TaxpayerResponse.case_id == case_id)
        .order_by(TaxpayerResponse.seq)
    ).all()
    return [{"seq": r.seq, "code": r.code, "label": r.label,
             "amount": float(r.amount), "doc_name": r.doc_name} for r in rows]


@router.post("/cases/{case_id}/responses")
def add_response(case_id: str, body: ResponseIn, db: Session = Depends(get_db)):
    """Record evidence the taxpayer supplied, then regenerate the whole reconciliation."""
    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    if not body.label.strip() or abs(body.amount) < 0.005:
        raise HTTPException(422, "a description and a non-zero amount are required")
    n = db.scalar(select(func.count()).select_from(TaxpayerResponse)
                  .where(TaxpayerResponse.case_id == case_id)) or 0
    seq = n + 1
    db.add(TaxpayerResponse(
        case_id=case_id, seq=seq, code=f"RESP-{seq:02d}",
        label=body.label.strip(), amount=abs(body.amount), doc_name=body.doc_name.strip(),
    ))
    db.add(EventLog(case_id=case_id, actor="auditor", action="taxpayer-response",
                    payload={"seq": seq, "amount": abs(body.amount), "doc": body.doc_name}))
    db.commit()
    return reconcile_case(db, case_id)


@router.delete("/cases/{case_id}/responses/{seq}")
def delete_response(case_id: str, seq: int, db: Session = Depends(get_db)):
    db.execute(delete(TaxpayerResponse).where(
        TaxpayerResponse.case_id == case_id, TaxpayerResponse.seq == seq))
    db.add(EventLog(case_id=case_id, actor="auditor", action="taxpayer-response-removed",
                    payload={"seq": seq}))
    db.commit()
    return reconcile_case(db, case_id)


# ------------------------------------------------- information request / response loop
def _case_or_404(db: Session, case_id: str) -> AuditCase:
    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    return c


@router.get("/cases/{case_id}/plan")
def request_plan(case_id: str, db: Session = Depends(get_db)):
    """What to ask the taxpayer for — and what was dropped because ZATCA already holds it."""
    from ..requests.planner import plan

    return plan(db, _case_or_404(db, case_id)).to_dict()


@router.get("/cases/{case_id}/requests")
def request_loop(case_id: str, db: Session = Depends(get_db)):
    """Every round of correspondence on this case: items, documents received, and gaps."""
    return req_service.state(db, _case_or_404(db, case_id))


@router.post("/cases/{case_id}/requests")
def open_round(case_id: str, db: Session = Depends(get_db)):
    """Open the next round from the current plan, as a draft the auditor approves."""
    case = _case_or_404(db, case_id)
    current = req_service.current_request(db, case_id)
    if current is not None and current.status not in ("satisfied",):
        raise HTTPException(409, f"round {current.seq} is still {current.status}")
    req = req_service.open_request(db, case)
    drafted = draft_request(case, case.taxpayer, req)
    req.body, req.body_source = drafted["text"], drafted["source"]
    db.add(EventLog(case_id=case_id, actor="auditor", action="request-drafted",
                    payload={"round": req.seq, "items": len(req.items)}))
    db.commit()
    return {**req_service.state(db, case), "draft": drafted}


@router.post("/cases/{case_id}/requests/{seq}/issue")
def issue_round(case_id: str, seq: int, db: Session = Depends(get_db)):
    case = _case_or_404(db, case_id)
    req = next((r for r in req_service.rounds(db, case_id) if r.seq == seq), None)
    if req is None:
        raise HTTPException(404, "round not found")
    req_service.issue(db, req)
    db.add(EventLog(case_id=case_id, actor="auditor", action="request-issued",
                    payload={"round": seq}))
    db.commit()
    return req_service.state(db, case)


@router.post("/cases/{case_id}/documents")
async def upload_document(case_id: str, file: UploadFile = File(...),
                          item_id: int | None = Form(None),
                          db: Session = Depends(get_db)):
    """Record a file the taxpayer sent, extract it, and re-run the completeness checks."""
    case = _case_or_404(db, case_id)
    req = req_service.current_request(db, case_id)
    if req is None:
        raise HTTPException(409, "no information request has been issued on this case")
    data = await file.read()
    if len(data) > 8_000_000:
        raise HTTPException(413, "file too large for the demo (8 MB limit)")
    doc = req_service.record_document(
        db, case=case, req=req, item_id=item_id, filename=file.filename or "response",
        data=data, file_format=(file.filename or "").rsplit(".", 1)[-1].lower())
    report = req_service.run_checks(db, case)
    db.add(EventLog(case_id=case_id, actor="taxpayer", action="document-received",
                    payload={"round": req.seq, "file": doc.filename,
                             "gaps": len(report.gaps)}))
    db.commit()
    return {**req_service.state(db, case), "report": report.to_dict()}


@router.post("/cases/{case_id}/requests/check")
def recheck(case_id: str, db: Session = Depends(get_db)):
    """Re-run the deterministic completeness checks over what has been received."""
    case = _case_or_404(db, case_id)
    report = req_service.run_checks(db, case)
    db.commit()
    return {**req_service.state(db, case), "report": report.to_dict()}


@router.get("/cases/{case_id}/followup")
def followup(case_id: str, db: Session = Depends(get_db)):
    """Draft the chase letter from the outstanding gaps only."""
    case = _case_or_404(db, case_id)
    req = req_service.current_request(db, case_id)
    if req is None:
        raise HTTPException(409, "no information request has been issued on this case")
    gaps = db.scalars(
        select(GapFinding).where(GapFinding.case_id == case_id, GapFinding.round == req.seq,
                                 GapFinding.severity == "blocking")
        .order_by(GapFinding.id)).all()
    return draft_followup(case, case.taxpayer, req, list(gaps))


@router.get("/demo/response-file")
def demo_response_file():
    """The taxpayer's deficient sales analysis, so the upload path can be demonstrated live."""
    from ..seed.demo_files import sales_analysis_xlsx

    return Response(
        content=sales_analysis_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="Sales_Analysis_Q1_2025.xlsx"'},
    )


# ---------------------------------------------------------------- AI layer (Phase 2)
@router.get("/cases/{case_id}/narrate")           # FEATURE 1 — bridge narration (verified prose)
def narrate(case_id: str, db: Session = Depends(get_db)):
    recon = reconcile_case(db, case_id, persist=False)
    return llm.narrate(recon, _rule_rows(db))


@router.get("/cases/{case_id}/nba")               # FEATURE 2 — next best action (structured)
def nba(case_id: str, db: Session = Depends(get_db)):
    recon = reconcile_case(db, case_id, persist=False)
    return llm.next_best_action(recon, _rule_rows(db))


@router.get("/cases/{case_id}/summary")           # FEATURE 3 — taxpayer brief (figure-free)
def summary(case_id: str, db: Session = Depends(get_db)):
    c = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not c:
        raise HTTPException(404, "case not found")
    tp = c.taxpayer
    profile = {"name": tp.name, "sector": tp.ind_sector, "size": tp.business_size,
               "accounting_method": tp.accounting_method, "resident": tp.resident_flag,
               "vat_group": tp.vat_group_rep_flag}
    prior_returns = [
        {"data_version": r.data_version, "current": r.current_flag,
         "reason_for_amendment": r.reason_for_amendment,
         "submitted": r.submission_date and r.submission_date.isoformat()}
        for r in db.scalars(select(VatReturn).where(VatReturn.taxpayer_id == tp.id)
                            .order_by(VatReturn.data_version)).all()
    ]
    prior_cases = [
        {"case_id": pc.case_id, "reason": pc.case_reason_code, "risk": pc.risk_category,
         "result": pc.audit_result_type, "root_cause": pc.root_cause_code, "action": pc.action_taken}
        for pc in db.scalars(select(AuditCase).where(
            AuditCase.taxpayer_id == tp.id, AuditCase.case_id != case_id)).all()
    ]
    return llm.summarise_history(profile, prior_returns, prior_cases)


class LetterIn(BaseModel):
    text: str


@router.post("/cases/{case_id}/read-letter")     # FEATURE 5 — read a taxpayer letter (draft extraction)
def read_letter(case_id: str, body: LetterIn, db: Session = Depends(get_db)):
    recon = reconcile_case(db, case_id, persist=False)
    return llm.read_letter(recon, body.text)


@router.get("/cases/{case_id}/report")            # FEATURE 4 — AI-drafted report (streamed SSE)
def report(case_id: str, db: Session = Depends(get_db)):
    recon = reconcile_case(db, case_id)
    return StreamingResponse(llm.stream_report(recon, _rule_rows(db)),
                             media_type="text/event-stream")
