"""Reconstruction + reconciliation bridge (deterministic core).

Rebuilds the **expected** VAT return from the taxpayer's e-invoices and compares it to the
declared boxes. Every number here is computed — no AI, no estimation.

The rules run *during* aggregation, not after it. Each tax-subtotal line is walked through
`app/pipeline` — population, status, tax point, category, adjustment — and only the lines
that survive are summed. That matters because a rule can do things a subtraction cannot:
move a supply to the next period (it must also *arrive* there), move a line between boxes,
and admit each line exactly once so two rules cannot double-count the same document.

The bridge is then *derived* from those line decisions rather than hand-wired, so a row can
never claim a movement the underlying lines do not support. `base + Σ rows == expected`
holds by construction.

Each bridge line carries a `detail` payload (the underlying invoices, the rule and the
computation) so the UI can open a drill-down for any figure.
"""
from __future__ import annotations

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .models import (
    AuditCase, VatReturn, Invoice, Rule,
    CaseRecon, RebuiltBox, BridgeLine, Residual, Conclusion, EventLog,
    TaxpayerResponse,
)
from .pipeline.rules import BOX_PURCHASE, BOX_SALES
from .pipeline.run import compose, deferred, qualify
from .rule_taxonomy import REASON_CODES

MATERIALITY_FLOOR = 1000.0   # SAR
MATERIALITY_PCT = 0.005      # 0.5% of the compared box

TYPE_LABEL = {388: "Tax invoice", 381: "Credit note", 383: "Debit note", 386: "Prepayment"}


def _box(ret: VatReturn | None, code: str, direction: str):
    if not ret:
        return None
    for b in ret.boxes:
        if b.box_code == code and b.direction == direction:
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


def _enabled_codes(db: Session) -> set[str]:
    from .pipeline.rules import coded_rules
    return {c for c in coded_rules() if _rule_on(db, c)}


def _line_records(invs: list[Invoice], period_from, period_to) -> list[dict]:
    """Flatten invoices into the tax-subtotal grain the pipeline qualifies."""
    rows: list[dict] = []
    for inv in invs:
        for st in inv.subtotals:
            rows.append({
                "invoice": inv,                      # kept for drill-down rendering
                "invoice_uuid": inv.uuid,
                "type_code": inv.invoice_type_code,
                "direction": inv.direction,
                "status": inv.status_code,
                "issue_date": inv.issue_date,
                "delivery_date": inv.delivery_date,
                "category": st.category,
                "rate": st.rate,
                "taxable_amount": float(st.taxable_amount),
                "tax_amount": float(st.tax_amount),
                "period_from": period_from,
                "period_to": period_to,
            })
    return rows


def _line_invoice_rows(lines) -> list[dict]:
    """Collapse qualified lines back to invoice rows for the drill-down tables."""
    seen: dict[str, dict] = {}
    for line in lines:
        inv = line.row["invoice"]
        if inv.uuid in seen:
            seen[inv.uuid]["tax_amount"] = round(seen[inv.uuid]["tax_amount"] + line.tax_amount, 2)
        else:
            seen[inv.uuid] = _inv_row(inv, line.tax_amount)
    return list(seen.values())


def _reconstruct(db: Session, *, invs: list[Invoice], declared: float, direction: str,
                 box_code: str, box_label: str, box_title: str, period_from, period_to,
                 responses: list[TaxpayerResponse] | None = None,
                 ret: VatReturn | None = None, dbox=None,
                 invoices_considered: int, finding_sign: int) -> dict:
    """Qualify, sum, compare. Shared by the output and input boxes.

    `finding_sign` is +1 where an under-declaration is the revenue risk (output VAT) and
    -1 where an over-claim is (input VAT).
    """
    enabled = _enabled_codes(db)
    rows = _line_records(invs, period_from, period_to)
    lines = qualify(rows, enabled, direction)
    comp = compose(lines, enabled, direction)

    # legacy-compatible framing: the pre-qualification baseline and the gap it implies
    reconstructed_gross = comp.base_vat
    apparent_gap = round(reconstructed_gross - declared, 2)

    items: list[tuple[str, str, float]] = []
    explain_detail: dict[str, dict] = {}
    for r in comp.rows:
        items.append((r["rule"], r["label"], r["amount"]))
        explain_detail[r["rule"]] = {
            "type": "rule",
            "rule": _rinfo(db, r["rule"]),
            "reason_code": r["reason_code"],
            "reason_label": REASON_CODES.get(r["reason_code"], ("", ""))[1],
            "stage": r["stage"],
            "verdict": r["verdict"],
            "note": r["note"],
            "count": r["count"],
            "total": r["amount"],
            "invoices": _line_invoice_rows(r["lines"]),
        }

    # auditor-confirmed taxpayer evidence is not a line decision — it applies after
    # qualification, against the difference that survived
    for resp in (responses or []):
        amount = round(-abs(float(resp.amount)), 2)
        items.append((resp.code, resp.label, amount))
        explain_detail[resp.code] = {
            "type": "response", "label": resp.label, "doc_name": resp.doc_name,
            "count": 0, "total": amount, "invoices": [],
            "note": ("Evidence provided by the taxpayer"
                     + (f" — {resp.doc_name}" if resp.doc_name else "")
                     + ". The auditor confirmed the SAR amount it accounts for; this figure is "
                       "auditor-entered, not AI-generated."),
        }

    response_total = round(sum(a for c, _, a in items if c.startswith("RESP-")), 2)
    residual = round(comp.expected_vat + response_total - declared, 2)
    explained_total = round(apparent_gap - residual, 2)
    explained_pct = round(explained_total / apparent_gap, 4) if apparent_gap else None
    materiality = round(max(MATERIALITY_FLOOR, MATERIALITY_PCT * declared), 2)

    if abs(residual) <= materiality:
        band, state = ("noise" if abs(residual) <= 1 else "immaterial"), "supported"
    elif residual * finding_sign > 0:
        band, state = "material", "potential-finding"
    else:
        band, state = "material", "unresolved"

    recon_detail = {
        "type": "reconstruction",
        "formula": "Σ TAXSUBTOTAL (tax category S @ 15%) over qualified "
                   f"{'sale' if direction == 'sale' else 'purchase'} lines",
        "note": f"Standard-rated {'output' if direction == 'sale' else 'input'} VAT rebuilt "
                "line by line from the taxpayer's e-invoices. Each line was qualified before "
                "it was summed; the rows below are the lines that entered the baseline.",
        "count": len(comp.base_lines),
        "total": reconstructed_gross,
        "invoices": _line_invoice_rows(comp.base_lines),
    }
    declared_detail = {
        "type": "declared",
        "form_number": ret.form_number if ret else None,
        "data_version": ret.data_version if ret else None,
        "submission_date": ret.submission_date.isoformat() if ret and ret.submission_date else None,
        "box_code": box_code, "box_label": box_label,
        "base_amount": float(dbox.base_amount) if dbox else None,
        "vat_amount": declared,
        "adjustment": float(dbox.adjustment) if dbox else 0.0,
        "note": ("The output VAT the taxpayer declared for this box, from the current filed return."
                 if direction == "sale" else
                 "The input VAT the taxpayer claimed for this box, from the current filed return."),
    }
    if state == "potential-finding" and direction == "sale":
        res_note = ("Above the materiality threshold and unexplained by any rule — a potential "
                    "under-declaration of output VAT. Recommended next step: request the sales ledger "
                    "covering the residual to confirm.")
    elif state == "potential-finding":
        res_note = ("Declared input VAT exceeds what the qualified purchase e-invoices support — a "
                    "potential over-claim of recoverable input VAT. Recommended next step: request "
                    "the purchase ledger and tax invoices covering the residual.")
    elif state == "supported":
        res_note = ("Within the materiality threshold — the declared return is supported by the "
                    "qualified e-invoice evidence. No finding.")
    elif direction == "sale":
        res_note = "Material negative residual — the taxpayer may have over-declared; investigate."
    else:
        res_note = ("Declared input is below what the invoices support — the taxpayer may have "
                    "under-claimed recoverable input VAT; no revenue risk to the Authority.")
    residual_detail = {"type": "residual", "amount": residual, "materiality": materiality,
                       "band": band, "state": state, "note": res_note}

    anchor_label = "Declared (as filed)" if direction == "sale" else "Declared input (as filed)"
    gap_label = ("Reconstructed from e-invoices" if direction == "sale"
                 else "Reconstructed from purchase e-invoices")
    bridge = [{"seq": 0, "kind": "anchor", "rule": None, "label": anchor_label,
               "amount": declared, "running": declared, "detail": declared_detail}]
    running = round(declared + apparent_gap, 2)
    bridge.append({"seq": 1, "kind": "gap", "rule": None, "label": gap_label,
                   "amount": apparent_gap, "running": running, "detail": recon_detail})
    for seq, (rule, label, amount) in enumerate(items, start=2):
        running = round(running + amount, 2)
        bridge.append({"seq": seq, "kind": "explain", "rule": rule, "label": label,
                       "amount": amount, "running": running, "detail": explain_detail.get(rule)})
    bridge.append({"seq": len(items) + 2, "kind": "residual", "rule": None,
                   "label": "Unexplained residual", "amount": residual, "running": running,
                   "detail": residual_detail})

    out_lines = deferred(lines)
    return {
        "box": box_title,
        "declared": declared,
        "reconstructed_gross": reconstructed_gross,
        "apparent_gap": apparent_gap,
        "explained_total": explained_total,
        "explained_pct": explained_pct,
        "residual": residual,
        "materiality": materiality,
        "band": band,
        "state": state,
        "bridge": bridge,
        "invoices_considered": invoices_considered,
        "evidence_invoices": _line_invoice_rows(
            [l for l in lines if l.in_population]),
        # --- qualification-first additions
        "expected_vat": comp.expected_vat,
        "expected_base": comp.expected_base,
        "population_lines": comp.population,
        "counted_lines": comp.counted,
        "deferred_out": {"count": len(out_lines),
                         "amount": round(sum(l.tax_amount for l in out_lines), 2)},
    }


def _reconstruct_input(db: Session, tp, ret: VatReturn | None, period_from, period_to) -> dict:
    """Input VAT (standard-rated purchases) — the mirror of the output box.

    Here an *over-claim* (declared input exceeding what the qualified purchase e-invoices
    support, i.e. a negative residual) is the revenue risk.
    """
    pbox = _box(ret, BOX_PURCHASE, "purchase")
    declared = round(float(pbox.vat_amount) if pbox else 0.0, 2)
    invs = db.scalars(
        select(Invoice).where(Invoice.taxpayer_id == tp.id, Invoice.direction == "purchase")
    ).all()
    considered = len([i for i in invs if i.status_code in ("cleared", "reported")])
    return _reconstruct(
        db, invs=list(invs), declared=declared, direction="purchase",
        box_code=BOX_PURCHASE, box_label="Standard-rated purchases",
        box_title="Standard-rated purchases (input VAT)",
        period_from=period_from, period_to=period_to, ret=ret, dbox=pbox,
        invoices_considered=considered, finding_sign=-1,
    )


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
    dbox = _box(ret, BOX_SALES, "sale")
    declared = round(float(dbox.vat_amount) if dbox else 0.0, 2)

    invs = db.scalars(
        select(Invoice).where(Invoice.taxpayer_id == tp.id, Invoice.direction == "sale")
    ).all()
    responses = db.scalars(
        select(TaxpayerResponse)
        .where(TaxpayerResponse.case_id == case_id)
        .order_by(TaxpayerResponse.seq)
    ).all()

    result = _reconstruct(
        db, invs=list(invs), declared=declared, direction="sale",
        box_code=BOX_SALES, box_label="Standard-rated sales",
        box_title="Standard-rated sales VAT",
        period_from=case.period_from, period_to=case.period_to,
        responses=list(responses), ret=ret, dbox=dbox,
        invoices_considered=len(invs), finding_sign=1,
    )
    residual, state = result["residual"], result["state"]
    band, materiality = result["band"], result["materiality"]
    apparent_gap, explained_total = result["apparent_gap"], result["explained_total"]
    explained_pct = result["explained_pct"]

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
            case_id=case_id, declared_total=declared, rebuilt_total=result["reconstructed_gross"],
            apparent_gap=apparent_gap, explained_total=explained_total,
            residual=residual, explained_pct=explained_pct, status=state,
        )
        db.add(cr)
        db.flush()
        db.add(RebuiltBox(
            case_recon_id=cr.id, box_code=BOX_SALES, direction="sale",
            rebuilt_base=result["expected_base"], rebuilt_vat=result["expected_vat"],
            declared_vat=declared, gap_vat=apparent_gap,
        ))
        for seq, b in enumerate([x for x in result["bridge"] if x["kind"] == "explain"], start=1):
            db.add(BridgeLine(case_recon_id=cr.id, seq=seq, rule_code=b["rule"],
                              label=b["label"], side="rebuilt-side", amount=b["amount"]))
        db.add(Residual(case_recon_id=cr.id, box_code=BOX_SALES,
                        amount=residual, band=band, state=state))
        db.add(Conclusion(case_recon_id=cr.id, state=state,
                          financial_impact=max(residual, 0.0), narrative=""))
        db.add(EventLog(case_id=case_id, actor="engine", action="reconcile",
                        payload={"apparent_gap": apparent_gap, "residual": residual, "state": state}))
        case.status = "reconciled"
        db.commit()

    # case-level view across BOTH boxes: an input over-claim is a finding too, so the case's
    # exposure and headline state must combine output + input (not just the output box)
    purchase = _reconstruct_input(db, tp, ret, case.period_from, case.period_to)
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
        **result,
        "purchase": purchase,
        "combined": combined,
    }
