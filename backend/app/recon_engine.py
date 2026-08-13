"""Phase 1 — reconstruction + reconciliation bridge (deterministic core).

Rebuilds the expected standard-rated output VAT from the taxpayer's cleared e-invoices
(aggregating InvoiceTaxSubtotal), compares it to the declared box, explains the gap with
deterministic rules (credit notes already in the return, clearance-lag timing), and isolates
the true unexplained residual. Every number here is computed — no AI, no estimation.

Each bridge line also carries a `detail` payload (the underlying invoices, the rule, and the
computation) so the UI can open a drill-down popup for any figure.
"""
from __future__ import annotations

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .models import (
    AuditCase, VatReturn, Invoice, Rule,
    CaseRecon, RebuiltBox, BridgeLine, Residual, Conclusion, EventLog,
    TaxpayerResponse,
)

MATERIALITY_FLOOR = 1000.0   # SAR
MATERIALITY_PCT = 0.005      # 0.5% of the compared box

TYPE_LABEL = {388: "Tax invoice", 381: "Credit note", 383: "Debit note", 386: "Prepayment"}


def _declared_box(ret: VatReturn | None):
    if not ret:
        return None
    for b in ret.boxes:
        if b.box_code == "standard_rate_sales" and b.direction == "sale":
            return b
    return None


def _inv_row(inv: Invoice, s_tax: float) -> dict:
    base = sum(float(st.taxable_amount) for st in inv.subtotals if st.category == "S" and st.rate == 15)
    return {
        "uuid": inv.uuid,
        "type_code": inv.invoice_type_code,
        "type": TYPE_LABEL.get(inv.invoice_type_code, str(inv.invoice_type_code)),
        "issue_date": inv.issue_date.isoformat(),
        "delivery_date": inv.delivery_date.isoformat() if inv.delivery_date else None,
        "status": inv.status_code,
        "base": round(base, 2),
        "tax_amount": round(s_tax, 2),
    }


def _rule_on(db: Session, code: str) -> bool:
    r = db.get(Rule, code)
    return bool(r and r.enabled)


def _rinfo(db: Session, code: str) -> dict:
    r = db.get(Rule, code)
    if not r:
        return {"code": code}
    return {"code": r.code, "family": r.family, "title": r.title,
            "explains_gap": r.explains_gap, "severity": r.severity}


def _purchase_box(ret: VatReturn | None):
    if not ret:
        return None
    for b in ret.boxes:
        if b.box_code == "standard_rate_purchase" and b.direction == "purchase":
            return b
    return None


def _reconstruct_input(db: Session, tp, ret: VatReturn | None, period_to) -> dict:
    """Input-VAT (standard-rated purchases) reconstruction — the mirror of the output box.

    For input VAT the revenue risk is the opposite sign: an *over-claim* (declared input exceeds
    what cleared purchase e-invoices support → negative residual) is the finding.
    """
    pbox = _purchase_box(ret)
    declared = round(float(pbox.vat_amount) if pbox else 0.0, 2)

    invs = db.scalars(
        select(Invoice).where(Invoice.taxpayer_id == tp.id, Invoice.direction == "purchase")
    ).all()
    gross = credit_notes = timing = 0.0
    gross_rows: list[dict] = []
    cn_rows: list[dict] = []
    timing_rows: list[dict] = []
    for inv in invs:
        if inv.status_code not in ("cleared", "reported"):
            continue
        s_tax = sum(float(st.tax_amount) for st in inv.subtotals if st.category == "S" and st.rate == 15)
        row = _inv_row(inv, s_tax)
        if inv.invoice_type_code == 381:
            credit_notes += s_tax
            cn_rows.append(row)
        else:
            gross += s_tax
            gross_rows.append(row)
            if inv.delivery_date and inv.delivery_date > period_to:
                timing += s_tax
                timing_rows.append(row)
    gross = round(gross, 2)
    credit_notes = round(credit_notes, 2)
    timing = round(timing, 2)
    apparent_gap = round(gross - declared, 2)

    items: list[tuple[str, str, float]] = []
    if abs(credit_notes) > 0.005 and _rule_on(db, "COR-02"):
        items.append(("COR-02", "Supplier credit notes (381) reducing recoverable input", credit_notes))
    if abs(timing) > 0.005 and _rule_on(db, "INP-09"):
        items.append(("INP-09", "Input claimed in the wrong / a late period", round(-timing, 2)))

    explained_signed = round(sum(a for _, _, a in items), 2)
    adjusted = round(gross + explained_signed, 2)
    residual = round(adjusted - declared, 2)
    explained_total = round(apparent_gap - residual, 2)
    explained_pct = round(explained_total / apparent_gap, 4) if apparent_gap else None
    materiality = round(max(MATERIALITY_FLOOR, MATERIALITY_PCT * declared), 2)

    if abs(residual) <= materiality:
        band, state = ("noise" if abs(residual) <= 1 else "immaterial"), "supported"
    elif residual < 0:
        band, state = "material", "potential-finding"      # over-claimed input (declared > supported)
    else:
        band, state = "material", "unresolved"             # under-claimed input (taxpayer-favourable)

    recon_detail = {
        "type": "reconstruction",
        "formula": "Σ TAXSUBTOTAL (tax category S @ 15%) over cleared purchase tax invoices",
        "note": "Standard-rated input VAT rebuilt from the taxpayer's cleared purchase e-invoices.",
        "count": len(gross_rows), "total": gross, "invoices": gross_rows,
    }
    explain_detail = {
        "COR-02": {
            "type": "rule", "rule": _rinfo(db, "COR-02"),
            "note": "Supplier credit notes (type 381) reduce recoverable input VAT and are already "
                    "reflected in the declared figure.",
            "count": len(cn_rows), "total": credit_notes, "invoices": cn_rows,
        },
        "INP-09": {
            "type": "rule", "rule": _rinfo(db, "INP-09"),
            "note": "Purchase invoices delivered in the next period — the input belongs to the "
                    "following return.",
            "count": len(timing_rows), "total": round(-timing, 2), "invoices": timing_rows,
        },
    }
    declared_detail = {
        "type": "declared", "box_code": "standard_rate_purchase", "box_label": "Standard-rated purchases",
        "form_number": ret.form_number if ret else None,
        "data_version": ret.data_version if ret else None,
        "submission_date": ret.submission_date.isoformat() if ret and ret.submission_date else None,
        "base_amount": float(pbox.base_amount) if pbox else None,
        "vat_amount": declared, "adjustment": float(pbox.adjustment) if pbox else 0.0,
        "note": "The input VAT the taxpayer claimed for this box, from the current filed return.",
    }
    if state == "potential-finding":
        res_note = ("Declared input VAT exceeds what the cleared purchase e-invoices support — a potential "
                    "over-claim of recoverable input VAT. Recommended next step: request the purchase ledger "
                    "and tax invoices covering the residual.")
    elif state == "supported":
        res_note = ("Within the materiality threshold — the declared input VAT is supported by the purchase "
                    "e-invoice evidence. No finding.")
    else:
        res_note = ("Declared input is below what the invoices support — the taxpayer may have under-claimed "
                    "recoverable input VAT; no revenue risk to the Authority.")
    residual_detail = {"type": "residual", "amount": residual, "materiality": materiality,
                       "band": band, "state": state, "note": res_note}

    bridge = [{"seq": 0, "kind": "anchor", "rule": None, "label": "Declared input (as filed)",
               "amount": declared, "running": declared, "detail": declared_detail}]
    running = round(declared + apparent_gap, 2)
    bridge.append({"seq": 1, "kind": "gap", "rule": None, "label": "Reconstructed from purchase e-invoices",
                   "amount": apparent_gap, "running": running, "detail": recon_detail})
    for seq, (rule, label, amount) in enumerate(items, start=2):
        running = round(running + amount, 2)
        bridge.append({"seq": seq, "kind": "explain", "rule": rule, "label": label,
                       "amount": amount, "running": running, "detail": explain_detail.get(rule)})
    bridge.append({"seq": len(items) + 2, "kind": "residual", "rule": None,
                   "label": "Unexplained residual", "amount": residual, "running": running,
                   "detail": residual_detail})

    considered = len([i for i in invs if i.status_code in ("cleared", "reported")])
    return {
        "box": "Standard-rated purchases (input VAT)",
        "declared": declared, "reconstructed_gross": gross, "apparent_gap": apparent_gap,
        "explained_total": explained_total, "explained_pct": explained_pct,
        "residual": residual, "materiality": materiality, "band": band, "state": state,
        "bridge": bridge, "invoices_considered": considered,
        "evidence_invoices": gross_rows + cn_rows,
    }


def reconcile_case(db: Session, case_id: str, *, persist: bool = True) -> dict:
    case = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
    if not case:
        raise ValueError("case not found")
    tp = case.taxpayer
    ret = db.scalar(
        select(VatReturn).where(
            VatReturn.taxpayer_id == tp.id,
            VatReturn.period_from == case.period_from,
            VatReturn.current_flag.is_(True),
        )
    )
    dbox = _declared_box(ret)
    declared = round(float(dbox.vat_amount) if dbox else 0.0, 2)

    def rinfo(code: str):
        r = db.get(Rule, code)
        if not r:
            return {"code": code}
        return {"code": r.code, "family": r.family, "title": r.title,
                "explains_gap": r.explains_gap, "severity": r.severity}

    def _enabled(code: str) -> bool:
        # a rule only fires if it exists in the library and is enabled (deleted/disabled → skipped)
        r = db.get(Rule, code)
        return bool(r and r.enabled)

    # --- reconstruct standard-rated output VAT from cleared sale e-invoices ----------
    invs = db.scalars(
        select(Invoice).where(Invoice.taxpayer_id == tp.id, Invoice.direction == "sale")
    ).all()
    gross_pos = credit_notes = timing = 0.0
    gross_rows: list[dict] = []
    cn_rows: list[dict] = []
    timing_rows: list[dict] = []
    for inv in invs:
        if inv.status_code not in ("cleared", "reported"):
            continue
        s_tax = sum(float(st.tax_amount) for st in inv.subtotals if st.category == "S" and st.rate == 15)
        row = _inv_row(inv, s_tax)
        if inv.invoice_type_code == 381:          # credit note
            credit_notes += s_tax                 # negative
            cn_rows.append(row)
        else:                                     # tax invoice (388) etc.
            gross_pos += s_tax
            gross_rows.append(row)
            if inv.delivery_date and inv.delivery_date > case.period_to:
                timing += s_tax                   # supplied in the next period
                timing_rows.append(row)
    gross_pos = round(gross_pos, 2)
    credit_notes = round(credit_notes, 2)
    timing = round(timing, 2)
    apparent_gap = round(gross_pos - declared, 2)

    # --- bridge: reconciling items that move the reconstruction toward the return -----
    items: list[tuple[str, str, float]] = []
    if abs(credit_notes) > 0.005 and _enabled("COR-01"):
        items.append(("COR-01", "Credit notes (381) already applied in the return", credit_notes))
    if abs(timing) > 0.005 and _enabled("OUT-07"):
        items.append(("OUT-07", "Clearance lag — invoices delivered in the next period", round(-timing, 2)))

    # taxpayer-supplied evidence (auditor-confirmed SAR amounts) folds in as RESP-xx lines
    responses = db.scalars(
        select(TaxpayerResponse)
        .where(TaxpayerResponse.case_id == case_id)
        .order_by(TaxpayerResponse.seq)
    ).all()
    for r in responses:
        items.append((r.code, r.label, round(-abs(float(r.amount)), 2)))

    explained_signed = round(sum(a for _, _, a in items), 2)
    adjusted = round(gross_pos + explained_signed, 2)
    residual = round(adjusted - declared, 2)
    explained_total = round(apparent_gap - residual, 2)
    explained_pct = round(explained_total / apparent_gap, 4) if apparent_gap else None

    materiality = round(max(MATERIALITY_FLOOR, MATERIALITY_PCT * declared), 2)
    if abs(residual) <= materiality:
        band, state = ("noise" if abs(residual) <= 1 else "immaterial"), "supported"
    elif residual > 0:
        band, state = "material", "potential-finding"
    else:
        band, state = "material", "unresolved"

    # --- per-line drill-down detail --------------------------------------------------
    recon_detail = {
        "type": "reconstruction",
        "formula": "Σ TAXSUBTOTAL (tax category S @ 15%) over cleared sale tax invoices",
        "note": "Standard-rated output VAT rebuilt from the taxpayer's cleared e-invoices.",
        "count": len(gross_rows), "total": gross_pos, "invoices": gross_rows,
    }
    explain_detail = {
        "COR-01": {
            "type": "rule", "rule": rinfo("COR-01"),
            "note": "These credit notes (type 381) are already reflected in the taxpayer's declared "
                    "figure, so they are removed from the reconstructed total to avoid double-counting.",
            "count": len(cn_rows), "total": credit_notes, "invoices": cn_rows,
        },
        "OUT-07": {
            "type": "rule", "rule": rinfo("OUT-07"),
            "note": "Issued within the period but delivered in the next period (tax-point / clearance "
                    "lag) — the supply belongs to the following return.",
            "count": len(timing_rows), "total": round(-timing, 2), "invoices": timing_rows,
        },
    }
    for r in responses:
        explain_detail[r.code] = {
            "type": "response",
            "label": r.label,
            "doc_name": r.doc_name,
            "count": 0,
            "total": round(-abs(float(r.amount)), 2),
            "invoices": [],
            "note": ("Evidence provided by the taxpayer"
                     + (f" — {r.doc_name}" if r.doc_name else "")
                     + ". The auditor confirmed the SAR amount it accounts for; this figure is "
                       "auditor-entered, not AI-generated."),
        }
    declared_detail = {
        "type": "declared",
        "form_number": ret.form_number if ret else None,
        "data_version": ret.data_version if ret else None,
        "submission_date": ret.submission_date.isoformat() if ret and ret.submission_date else None,
        "box_code": "standard_rate_sales", "box_label": "Standard-rated sales",
        "base_amount": float(dbox.base_amount) if dbox else None,
        "vat_amount": declared,
        "adjustment": float(dbox.adjustment) if dbox else 0.0,
        "note": "The output VAT the taxpayer declared for this box, from the current filed return.",
    }
    if state == "potential-finding":
        res_note = ("Above the materiality threshold and unexplained by any rule — a potential "
                    "under-declaration of output VAT. Recommended next step: request the sales ledger "
                    "covering the residual to confirm.")
    elif state == "supported":
        res_note = ("Within the materiality threshold — the declared return is supported by the "
                    "e-invoice evidence. No finding.")
    else:
        res_note = "Material negative residual — the taxpayer may have over-declared; investigate."
    residual_detail = {
        "type": "residual", "amount": residual, "materiality": materiality,
        "band": band, "state": state, "note": res_note,
    }

    # --- persist (idempotent: clear any prior recon for this case) --------------------
    # Only the /reconcile endpoint persists; the AI endpoints call with persist=False
    # (read-only) so their concurrent fan-out can't race on the recon tables.
    if persist:
        for p in db.scalars(select(CaseRecon).where(CaseRecon.case_id == case_id)).all():
            for tbl in (BridgeLine, RebuiltBox, Residual, Conclusion):
                db.execute(delete(tbl).where(tbl.case_recon_id == p.id))
        db.execute(delete(CaseRecon).where(CaseRecon.case_id == case_id))
        db.flush()

        cr = CaseRecon(
            case_id=case_id, declared_total=declared, rebuilt_total=gross_pos,
            apparent_gap=apparent_gap, explained_total=explained_total,
            residual=residual, explained_pct=explained_pct, status=state,
        )
        db.add(cr)
        db.flush()
        db.add(RebuiltBox(
            case_recon_id=cr.id, box_code="standard_rate_sales", direction="sale",
            rebuilt_base=round(gross_pos / 0.15, 2), rebuilt_vat=gross_pos,
            declared_vat=declared, gap_vat=apparent_gap,
        ))
        for seq, (rule, label, amount) in enumerate(items, start=1):
            db.add(BridgeLine(case_recon_id=cr.id, seq=seq, rule_code=rule,
                              label=label, side="rebuilt-side", amount=amount))
        db.add(Residual(case_recon_id=cr.id, box_code="standard_rate_sales",
                        amount=residual, band=band, state=state))
        db.add(Conclusion(case_recon_id=cr.id, state=state,
                          financial_impact=max(residual, 0.0), narrative=""))
        db.add(EventLog(case_id=case_id, actor="engine", action="reconcile",
                        payload={"apparent_gap": apparent_gap, "residual": residual, "state": state}))
        case.status = "reconciled"
        db.commit()

    # --- waterfall for the UI (each step carries its drill-down detail) ---------------
    bridge = [{"seq": 0, "kind": "anchor", "rule": None, "label": "Declared (as filed)",
               "amount": declared, "running": declared, "detail": declared_detail}]
    running = round(declared + apparent_gap, 2)
    bridge.append({"seq": 1, "kind": "gap", "rule": None, "label": "Reconstructed from e-invoices",
                   "amount": apparent_gap, "running": running, "detail": recon_detail})
    for seq, (rule, label, amount) in enumerate(items, start=2):
        running = round(running + amount, 2)
        bridge.append({"seq": seq, "kind": "explain", "rule": rule, "label": label,
                       "amount": amount, "running": running, "detail": explain_detail.get(rule)})
    bridge.append({"seq": len(items) + 2, "kind": "residual", "rule": None,
                   "label": "Unexplained residual", "amount": residual, "running": running,
                   "detail": residual_detail})

    # case-level view across BOTH boxes: an input over-claim is a finding too, so the case's
    # exposure and headline state must combine output + input (not just the output box)
    purchase = _reconstruct_input(db, tp, ret, case.period_to)
    _order = {"potential-finding": 3, "unresolved": 2, "supported": 1}
    out_finding = residual if state == "potential-finding" else 0.0
    in_finding = abs(purchase["residual"]) if purchase["state"] == "potential-finding" else 0.0
    combined = {
        # revenue at risk to the Authority — findings only (drives the overview "exposure" tile)
        "total_exposure": round(out_finding + in_finding, 2),
        # ranking magnitude — any output anomaly (under- or over-declaration) + input over-claims
        "priority_exposure": round(abs(residual) + in_finding, 2),
        "state": state if _order.get(state, 0) >= _order.get(purchase["state"], 0) else purchase["state"],
        "output_state": state,
        "input_state": purchase["state"],
        "output_residual": residual,
        "input_residual": purchase["residual"],
        "finding_boxes": [b for b, st in (("output", state), ("input", purchase["state"]))
                          if st == "potential-finding"],
    }

    return {
        "case_id": case_id,
        "taxpayer": tp.name,
        "box": "Standard-rated sales VAT",
        "declared": declared,
        "reconstructed_gross": gross_pos,
        "apparent_gap": apparent_gap,
        "explained_total": explained_total,
        "explained_pct": explained_pct,
        "residual": residual,
        "materiality": materiality,
        "band": band,
        "state": state,
        "bridge": bridge,
        "invoices_considered": len(invs),
        "evidence_invoices": gross_rows + cn_rows,
        "purchase": purchase,
        "combined": combined,
    }
