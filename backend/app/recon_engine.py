"""Reconstruction and comparison (deterministic core).

Rebuilds the **expected** VAT return from the taxpayer's e-invoices and compares it to the
declared boxes. Every number here is computed — no AI, no estimation.

The rules run *during* aggregation, never after it. Each tax-subtotal line is walked through
`app/pipeline` — status, tax point, category, adjustment — and only the lines that survive
are summed. A rule can therefore do things a subtraction cannot: move a supply to the next
period (where it must also *arrive*), move a line between boxes, and admit each line exactly
once so two rules cannot double-count the same document.

That order rules out a whole class of misleading output, and the shape of this module
reflects it. There is **no pre-qualification total**. Such a figure would have to include
documents the rules put in another period and exclude documents the rules admit, purely so a
waterfall could be drawn from it — it would correspond to nothing, and every "explained by
rules" percentage derived from it would be one artifact over another. A rule that fires has
already changed which documents count; there is nothing left for it to explain.

What the module publishes instead is the narrowing itself — `funnel`, an ordered account of
how the population became the qualifying set, straight from the line decisions — and then a
plain comparison:

    expected − declared            = difference
    difference − taxpayer evidence = unexplained

Every funnel step carries a `detail` payload (the underlying invoices, the rule and the
computation) so the UI can open a drill-down for any figure.
"""
from __future__ import annotations

from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from .models import (
    AuditCase, VatReturn, Invoice, Rule,
    CaseRecon, BoxOutcome, QualificationStep, Unexplained, Conclusion, EventLog,
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


def _line_records(invs: list[Invoice], period_from, period_to, sector: str = "") -> list[dict]:
    """Flatten invoices into the tax-subtotal grain the pipeline qualifies.

    `sector` and the counterparty columns are carried on every line so a qualification rule
    can be scoped to them — the auditors were clear that the expected relationship is not
    the same for a government supply as for a commercial one.
    """
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
                "approval_date": inv.approval_date,
                "counterparty_class": inv.counterparty_class,
                "sector": sector,
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
                 ret: VatReturn | None = None, dbox=None, sector: str = "",
                 invoices_considered: int, finding_sign: int) -> dict:
    """Qualify, sum, compare. Shared by the output and input boxes.

    The order is the whole point and there is no step before it. Rules decide which lines
    belong in this box for this period; the qualifying lines are summed; that sum is what the
    return should have said. Nothing is summed and then adjusted, so there is no
    pre-qualification total, no "apparent gap" and nothing for a rule to "explain" — a rule
    that fires has already changed which documents count.

    What is left is a straight comparison:

        expected − declared            = difference
        difference − taxpayer evidence = unexplained

    `finding_sign` is +1 where an under-declaration is the revenue risk (output VAT) and
    -1 where an over-claim is (input VAT).
    """
    enabled = _enabled_codes(db)
    rows = _line_records(invs, period_from, period_to, sector)
    lines = qualify(rows, enabled, direction)
    comp = compose(lines, enabled, direction)

    # ---- how the population narrowed, step by step -----------------------------------
    funnel = [{
        "seq": 0, "kind": "population", "rule": None, "stage": "",
        "label": ("Sale e-invoices on file" if direction == "sale"
                  else "Purchase e-invoices on file"),
        "count": comp.population, "amount": round(sum(l.tax_amount for l in lines), 2),
        "detail": {
            "type": "population",
            "note": ("Every e-invoice line held for this taxpayer in this direction, before "
                     "any rule is applied. It is a starting point, not a figure with meaning "
                     "— the rules below decide which of these lines belong in this box."),
            "count": comp.population,
            "invoices": _line_invoice_rows(list(lines)),
        },
    }]
    for seq, g in enumerate(comp.funnel, start=1):
        rule_code = g["rule"]
        funnel.append({
            "seq": seq,
            "kind": "defer" if g["verdict"] == "deferred-next" else "exclude",
            "rule": rule_code,
            "stage": g["stage"],
            "reason_code": g["reason_code"],
            "label": g["label"],
            "count": g["count"],
            "amount": g["amount"],
            "detail": {
                "type": "rule" if rule_code else "structural",
                "rule": _rinfo(db, rule_code) if rule_code else None,
                "reason_code": g["reason_code"],
                "reason_label": REASON_CODES.get(g["reason_code"], ("", ""))[1],
                "stage": g["stage"],
                "verdict": g["verdict"],
                "note": g["note"],
                "count": g["count"],
                "total": g["amount"],
                "invoices": _line_invoice_rows(g["lines"]),
            },
        })
    funnel.append({
        "seq": len(funnel), "kind": "qualified", "rule": None, "stage": "",
        "label": f"Qualify for {period_from:%b %Y} – {period_to:%b %Y}",
        "count": comp.counted, "amount": comp.expected_vat,
        "detail": {
            "type": "qualified",
            "formula": "Σ TAXSUBTOTAL (tax category S @ 15%) over the lines that qualified",
            "note": ("The lines that survived every rule, summed. This is what the return "
                     "should have declared for this box."),
            "count": comp.counted,
            "total": comp.expected_vat,
            "invoices": _line_invoice_rows(comp.counted_lines),
        },
    })

    composition = [{
        "type_code": c["type_code"], "label": c["label"], "count": c["count"],
        "amount": c["amount"],
        "detail": {"type": "composition", "label": c["label"], "count": c["count"],
                   "total": c["amount"],
                   "note": f"{c['label']} among the lines that qualified for this box.",
                   "invoices": _line_invoice_rows(c["lines"])},
    } for c in comp.composition]

    # ---- compare ---------------------------------------------------------------------
    difference = round(comp.expected_vat - declared, 2)

    # Taxpayer evidence is the one thing that can account for a difference *after* the fact:
    # it arrives later, and the auditor confirms the amount by hand. It is not a rule and is
    # never mixed in with one.
    evidence = []
    evidence_total = 0.0
    for resp in (responses or []):
        amount = round(abs(float(resp.amount)), 2)
        evidence_total = round(evidence_total + amount, 2)
        evidence.append({
            "code": resp.code, "label": resp.label, "amount": amount,
            "doc_name": resp.doc_name,
            "detail": {
                "type": "response", "label": resp.label, "doc_name": resp.doc_name,
                "count": 0, "total": amount, "invoices": [],
                "note": ("Evidence provided by the taxpayer"
                         + (f" — {resp.doc_name}" if resp.doc_name else "")
                         + ". The auditor confirmed the SAR amount it accounts for; this "
                           "figure is auditor-entered, not AI-generated."),
            },
        })

    # evidence eats into the difference from whichever side it sits
    unexplained = round(difference - evidence_total * (1 if difference >= 0 else -1), 2)
    if evidence_total and abs(unexplained) > abs(difference):
        unexplained = 0.0                       # evidence cannot make a difference larger
    materiality = round(max(MATERIALITY_FLOOR, MATERIALITY_PCT * declared), 2)

    if abs(unexplained) <= materiality:
        band, state = ("noise" if abs(unexplained) <= 1 else "immaterial"), "supported"
    elif unexplained * finding_sign > 0:
        band, state = "material", "potential-finding"
    else:
        band, state = "material", "unresolved"

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
        diff_note = ("Above the materiality threshold — more output VAT qualifies for this "
                     "period than the return declares, which is a potential under-declaration. "
                     "Recommended next step: request the sales ledger covering the difference.")
    elif state == "potential-finding":
        diff_note = ("Declared input VAT exceeds what the qualifying purchase e-invoices "
                     "support — a potential over-claim of recoverable input VAT. Recommended "
                     "next step: request the purchase ledger and tax invoices.")
    elif state == "supported":
        diff_note = ("Within the materiality threshold — the declared figure agrees with what "
                     "qualifies for this period. No finding.")
    elif direction == "sale":
        diff_note = ("The return declares more output VAT than qualifies for the period — the "
                     "taxpayer may have over-declared; investigate.")
    else:
        diff_note = ("Declared input is below what the qualifying invoices support — the "
                     "taxpayer may have under-claimed; no revenue risk to the Authority.")
    difference_detail = {"type": "difference", "expected": comp.expected_vat,
                         "declared": declared, "difference": difference,
                         "evidence_total": evidence_total, "unexplained": unexplained,
                         "materiality": materiality, "band": band, "state": state,
                         "note": diff_note}

    out_lines = deferred(lines)
    return {
        "box": box_title,
        "box_code": box_code,
        "declared": declared,
        "expected_vat": comp.expected_vat,
        "expected_base": comp.expected_base,
        "difference": difference,
        "evidence_total": evidence_total,
        "evidence": evidence,
        "unexplained": unexplained,
        "materiality": materiality,
        "band": band,
        "state": state,
        "funnel": funnel,
        "composition": composition,
        "declared_detail": declared_detail,
        "difference_detail": difference_detail,
        "invoices_considered": invoices_considered,
        "evidence_invoices": _line_invoice_rows(
            [l for l in lines if l.in_population]),
        "population_lines": comp.population,
        "counted_lines": comp.counted,
        "deferred_out": {"count": len(out_lines),
                         "amount": round(sum(l.tax_amount for l in out_lines), 2)},
    }


def _reconstruct_input(db: Session, tp, ret: VatReturn | None, period_from, period_to) -> dict:
    """Input VAT (standard-rated purchases) — the mirror of the output box.

    Here an *over-claim* (declared input exceeding what the qualified purchase e-invoices
    support, i.e. a negative difference) is the revenue risk.
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
        sector=tp.ind_sector, invoices_considered=considered, finding_sign=-1,
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
        responses=list(responses), ret=ret, dbox=dbox, sector=tp.ind_sector,
        invoices_considered=len(invs), finding_sign=1,
    )
    unexplained, state = result["unexplained"], result["state"]
    band, difference = result["band"], result["difference"]

    # --- persist (idempotent: clear any prior recon for this case) --------------------
    # Only the /reconcile endpoint persists; the AI endpoints call with persist=False
    # (read-only) so their concurrent fan-out can't race on the recon tables.
    if persist:
        for p in db.scalars(select(CaseRecon).where(CaseRecon.case_id == case_id)).all():
            for tbl in (QualificationStep, BoxOutcome, Unexplained, Conclusion):
                db.execute(delete(tbl).where(tbl.case_recon_id == p.id))
        db.execute(delete(CaseRecon).where(CaseRecon.case_id == case_id))
        db.flush()

        cr = CaseRecon(
            case_id=case_id, declared_total=declared, expected_total=result["expected_vat"],
            difference=difference, evidence_total=result["evidence_total"],
            unexplained=unexplained, status=state,
        )
        db.add(cr)
        db.flush()
        db.add(BoxOutcome(
            case_recon_id=cr.id, box_code=BOX_SALES, direction="sale",
            expected_base=result["expected_base"], expected_vat=result["expected_vat"],
            declared_vat=declared, difference=difference,
        ))
        # the audit trail of the narrowing: one row per rule that removed documents
        for seq, f in enumerate([x for x in result["funnel"]
                                 if x["kind"] in ("exclude", "defer")], start=1):
            db.add(QualificationStep(
                case_recon_id=cr.id, seq=seq, stage=f["stage"], rule_code=f["rule"] or "",
                verdict=f["kind"], label=f["label"],
                line_count=f["count"], amount=f["amount"]))
        db.add(Unexplained(case_recon_id=cr.id, box_code=BOX_SALES,
                           amount=unexplained, band=band, state=state))
        db.add(Conclusion(case_recon_id=cr.id, state=state,
                          financial_impact=max(unexplained, 0.0), narrative=""))
        db.add(EventLog(case_id=case_id, actor="engine", action="reconcile",
                        payload={"expected": result["expected_vat"], "difference": difference,
                                 "unexplained": unexplained, "state": state}))
        case.status = "reconciled"
        db.commit()

    # case-level view across BOTH boxes: an input over-claim is a finding too, so the case's
    # exposure and headline state must combine output + input (not just the output box)
    purchase = _reconstruct_input(db, tp, ret, case.period_from, case.period_to)
    _order = {"potential-finding": 3, "unresolved": 2, "supported": 1}
    out_finding = unexplained if state == "potential-finding" else 0.0
    in_finding = abs(purchase["unexplained"]) if purchase["state"] == "potential-finding" else 0.0
    combined = {
        # revenue at risk to the Authority — findings only (drives the overview "exposure" tile)
        "total_exposure": round(out_finding + in_finding, 2),
        # ranking magnitude — any output anomaly (under- or over-declaration) + input over-claims
        "priority_exposure": round(abs(unexplained) + in_finding, 2),
        "state": state if _order.get(state, 0) >= _order.get(purchase["state"], 0) else purchase["state"],
        "output_state": state,
        "input_state": purchase["state"],
        "output_unexplained": unexplained,
        "input_unexplained": purchase["unexplained"],
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
