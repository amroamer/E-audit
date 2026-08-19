"""Assemble the case dossier: everything ZATCA already holds about this taxpayer and period.

The auditors described the first move on any case as investigating internal data — returns,
e-invoicing, imports/exports, history, prior audits, financials, the risk analysis itself — and
only then deciding what is genuinely missing. Today that means opening several systems; the
fragmentation is pain point 3. This module answers it with one call.

Two things make the dossier more than a screen of data:

* every block reports **whether it is held and as of when**, so the planner can drop a request
  item mechanically rather than relying on the auditor to remember what ZATCA has;
* nothing here interprets anything. It reads, counts and sums. Interpretation belongs to the
  agents, and the figures they cite still come from the engine.
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..models import (
    AuditCase, CustomsDeclaration, FinancialSummary, Invoice, InvoiceTaxSubtotal,
    RiskReferral, Taxpayer, VatReturn,
)
from ..risk_indicators import SOURCES, get as get_indicator


def _f(v: Any) -> float:
    return round(float(v or 0), 2)


def _years(start: date | None, end: date | None = None) -> float | None:
    if not start:
        return None
    return round(((end or date.today()) - start).days / 365.25, 1)


# --------------------------------------------------------------------------- taxpayer 360

def taxpayer_profile(db: Session, tp: Taxpayer) -> dict:
    """Who am I dealing with — the block an auditor would otherwise assemble by hand."""
    activities = list(tp.economic_activities or [])
    primary = next((a for a in activities if a.get("primary")), activities[0] if activities else {})
    prior = db.scalars(
        select(AuditCase).where(AuditCase.taxpayer_id == tp.id, AuditCase.status == "closed")
    ).all()
    findings = [c for c in prior if c.audit_result_type == "FINDING"]
    return {
        "id": tp.id,
        "name": tp.name,
        "vat_no": tp.vat_registration_number,
        "legal_form": tp.legal_form,
        "bp_type": tp.bp_type,
        "sector": tp.ind_sector,
        "size": tp.business_size,
        "primary_activity": primary,
        "activities": activities,
        "resident": tp.resident_flag,
        "vat_group_rep": tp.vat_group_rep_flag,
        "accounting_method": tp.accounting_method,
        "registered_from": tp.reg_from.isoformat() if tp.reg_from else None,
        "registered_years": _years(tp.reg_from),
        "deregistered": tp.reg_to.isoformat() if tp.reg_to else None,
        "einvoicing_onboarded": (tp.einvoicing_onboarded.isoformat()
                                 if tp.einvoicing_onboarded else None),
        "employees": tp.employee_count,
        "branches": tp.branch_count,
        "pos_registered": tp.pos_registered,
        "importer": tp.importer_flag,
        "exporter": tp.exporter_flag,
        "related_parties": list(tp.related_parties or []),
        "compliance": dict(tp.filing_compliance or {}),
        "audit_history": {
            "closed_cases": len(prior),
            "findings": len(findings),
            "total_assessed": _f(sum(float(c.diff_tax_amt or 0) for c in findings)),
            "last_outcome": (max(prior, key=lambda c: c.period_to).audit_result_type
                             if prior else None),
            "root_causes": sorted({c.root_cause_code for c in findings if c.root_cause_code}),
        },
    }


# --------------------------------------------------------------------------- blocks

def _referral_block(case: AuditCase) -> dict:
    r: RiskReferral | None = case.referral
    if r is None:
        # pre-referral-table cases still carry the flattened reason on the case row
        return {
            "held": bool(case.case_reason_code),
            "indicator_code": case.case_reason_code,
            "indicator_label": case.risk_category,
            "narrative": "", "score": None, "signals": [], "structured": False,
        }
    ind = get_indicator(r.indicator_code)
    return {
        "held": True,
        "structured": True,
        "indicator_code": r.indicator_code,
        "indicator_label": r.indicator_label or (ind.label if ind else r.indicator_code),
        "description": ind.description if ind else "",
        "narrative": r.narrative,
        "score": _f(r.score),
        "threshold": _f(r.threshold),
        "signals": list(r.signals or []),
        "model_version": r.model_version,
        "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        "consult_first": [SOURCES.get(s, s) for s in (ind.evidence_hint if ind else ())],
    }


def _returns_block(db: Session, case: AuditCase) -> dict:
    rows = db.scalars(
        select(VatReturn).where(VatReturn.taxpayer_id == case.taxpayer_id)
        .order_by(VatReturn.period_from)
    ).all()
    out = []
    for r in rows:
        out.append({
            "form_number": r.form_number,
            "period_from": r.period_from.isoformat(),
            "period_to": r.period_to.isoformat(),
            "in_scope": r.period_from == case.period_from and r.period_to == case.period_to,
            "version": r.data_version,
            "current": r.current_flag,
            "submitted": r.submission_date.isoformat() if r.submission_date else None,
            "deadline": r.filing_deadline.isoformat() if r.filing_deadline else None,
            "late": bool(r.submission_date and r.filing_deadline
                         and r.submission_date > r.filing_deadline),
            "total_vat_due": _f(r.total_vat_due),
            "net_due_vat": _f(r.net_due_vat),
            "paid": r.sadad_paid,
            "boxes": [
                {"box_code": b.box_code, "label": b.box_label, "direction": b.direction,
                 "category": b.category, "rate": b.rate,
                 "base": _f(b.base_amount), "vat": _f(b.vat_amount),
                 "adjustment": _f(b.adjustment)}
                for b in r.boxes
            ],
        })
    return {"held": bool(out), "count": len(out), "periods": out,
            "as_of": max((r["submitted"] for r in out if r["submitted"]), default=None)}


def _einvoice_block(db: Session, case: AuditCase) -> dict:
    """A count-and-sum summary only — the qualified reconstruction is the engine's job."""
    rows = db.execute(
        select(Invoice.direction, Invoice.invoice_type_code, Invoice.status_code,
               func.count(Invoice.id), func.coalesce(func.sum(InvoiceTaxSubtotal.taxable_amount), 0),
               func.coalesce(func.sum(InvoiceTaxSubtotal.tax_amount), 0))
        .join(InvoiceTaxSubtotal, InvoiceTaxSubtotal.invoice_id == Invoice.id)
        .where(Invoice.taxpayer_id == case.taxpayer_id,
               Invoice.issue_date >= case.period_from, Invoice.issue_date <= case.period_to)
        .group_by(Invoice.direction, Invoice.invoice_type_code, Invoice.status_code)
    ).all()
    groups = [
        {"direction": d, "type_code": tc, "status": st,
         "count": int(n), "base": _f(base), "vat": _f(vat)}
        for d, tc, st, n, base, vat in rows
    ]
    total = db.scalar(
        select(func.count()).select_from(Invoice)
        .where(Invoice.taxpayer_id == case.taxpayer_id,
               Invoice.issue_date >= case.period_from, Invoice.issue_date <= case.period_to)
    ) or 0
    return {"held": total > 0, "count": int(total), "groups": sorted(
        groups, key=lambda g: (g["direction"], g["type_code"], g["status"]))}


def _customs_block(db: Session, case: AuditCase) -> dict:
    rows = db.scalars(
        select(CustomsDeclaration).where(CustomsDeclaration.taxpayer_id == case.taxpayer_id)
        .order_by(CustomsDeclaration.declaration_date)
    ).all()
    in_period = [d for d in rows
                 if case.period_from <= d.declaration_date <= case.period_to]
    return {
        "held": bool(rows),
        "count": len(rows),
        "in_period": len(in_period),
        "import_vat_in_period": _f(sum(float(d.vat_paid or 0) for d in in_period
                                       if d.direction == "import")),
        "export_value_in_period": _f(sum(float(d.customs_value or 0) for d in in_period
                                         if d.direction == "export")),
        "declarations": [
            {"declaration_no": d.declaration_no, "date": d.declaration_date.isoformat(),
             "direction": d.direction, "port": d.port, "hs_chapter": d.hs_chapter,
             "goods": d.goods_description, "customs_value": _f(d.customs_value),
             "vat_paid": _f(d.vat_paid), "vat_deferred": d.vat_deferred,
             "in_period": case.period_from <= d.declaration_date <= case.period_to}
            for d in rows
        ],
        "as_of": max((d.declaration_date for d in rows), default=None) and
                 max(d.declaration_date for d in rows).isoformat(),
    }


def _financials_block(db: Session, case: AuditCase) -> dict:
    rows = db.scalars(
        select(FinancialSummary).where(FinancialSummary.taxpayer_id == case.taxpayer_id)
        .order_by(FinancialSummary.fiscal_year)
    ).all()
    years = [
        {"fiscal_year": f.fiscal_year, "turnover": _f(f.turnover),
         "purchases": _f(f.purchases), "gross_profit": _f(f.gross_profit),
         "net_profit": _f(f.net_profit), "total_assets": _f(f.total_assets),
         "gross_margin_pct": f.gross_margin_pct,
         "purchase_ratio_pct": (round(float(f.purchases) / float(f.turnover) * 100, 2)
                                if float(f.turnover or 0) else None),
         "source": f.source}
        for f in rows
    ]
    return {"held": bool(years), "count": len(years), "years": years,
            "as_of": max((f.as_of for f in rows if f.as_of), default=None) and
                     max(f.as_of for f in rows if f.as_of).isoformat()}


def _prior_audits_block(db: Session, case: AuditCase) -> dict:
    rows = db.scalars(
        select(AuditCase).where(AuditCase.taxpayer_id == case.taxpayer_id,
                                AuditCase.case_id != case.case_id,
                                AuditCase.status == "closed")
        .order_by(AuditCase.period_from)
    ).all()
    return {
        "held": bool(rows),
        "count": len(rows),
        "audits": [
            {"case_id": c.case_id,
             "period_from": c.period_from.isoformat(), "period_to": c.period_to.isoformat(),
             "indicator": c.case_reason_code, "risk_category": c.risk_category,
             "result": c.audit_result_type, "root_cause": c.root_cause_code,
             "action": c.action_taken, "assessed": _f(c.diff_tax_amt),
             "rounds": c.rounds_of_correspondence, "days_to_close": c.days_to_close,
             "closed": c.closed_date.isoformat() if c.closed_date else None,
             "note": c.conclusion_note}
            for c in rows
        ],
    }


# --------------------------------------------------------------------------- assembly

def collect(db: Session, case_id: str) -> dict:
    """Everything ZATCA holds that bears on this case, in one object."""
    case = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if case is None:
        raise LookupError(f"case not found: {case_id}")
    tp = db.get(Taxpayer, case.taxpayer_id)

    blocks = {
        "vat-returns": _returns_block(db, case),
        "e-invoices": _einvoice_block(db, case),
        "customs": _customs_block(db, case),
        "financials": _financials_block(db, case),
        "prior-audits": _prior_audits_block(db, case),
    }
    referral = _referral_block(case)
    blocks["risk-analysis"] = {"held": referral["held"], "count": 1 if referral["held"] else 0}
    compliance = dict(tp.filing_compliance or {})
    blocks["payment-history"] = {"held": bool(compliance), **compliance}
    blocks["pos"] = {"held": bool(tp.pos_registered), "registered": tp.pos_registered}

    sources = [
        {"key": key, "label": SOURCES.get(key, key), "held": bool(b.get("held")),
         "count": b.get("count"), "as_of": b.get("as_of")}
        for key, b in blocks.items()
    ]
    sources.sort(key=lambda s: (not s["held"], s["label"]))

    return {
        "case_id": case.case_id,
        "period_from": case.period_from.isoformat(),
        "period_to": case.period_to.isoformat(),
        "status": case.status,
        "audit_type": case.audit_type,
        "sla_due": case.sla_due.isoformat() if case.sla_due else None,
        "taxpayer": taxpayer_profile(db, tp),
        "referral": referral,
        "sources": sources,
        "blocks": blocks,
    }


def held_sources(dossier: dict) -> set[str]:
    """The source keys this case actually has data for — the planner's "do not ask" set."""
    return {s["key"] for s in dossier["sources"] if s["held"]}
