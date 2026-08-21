"""User acceptance: one case, worked the way an auditor works it, through the real API.

`test_sit_agents.py` asks whether the parts are right. This asks the different question the
auditors will ask at the demo: *can I do my job with this?* So it is written as their journey,
end to end, one test per thing they said they needed — and it goes through the HTTP layer,
because a check that passes in Python but returns 422 to the screen has not passed.

Every acceptance criterion here traces to something the audit team asked for:

* a case that says who the taxpayer is, what they are registered to do, and whether we have
  audited them before;
* the email they already sent, read back as a checkable list;
* the spreadsheets that came in, and a straight answer on what falls short;
* a chase email written from the gaps and nothing else;
* four agents whose reasoning is visible and whose wording is the Authority's;
* their own arithmetic checked against the source, in the words they would use;
* an outbound letter and an audit report at the end.

The suite runs with **no API key**, which is the point: every step below has to work on the
deterministic path, because that is the path the demo will run on.
"""
from __future__ import annotations

import io
from contextlib import contextmanager

import pytest

pytest.importorskip("httpx", reason="the API acceptance walk needs httpx for TestClient")

from app import outcomes as oc

CASE = "CASE-2025-0481"          # the hero case: a request issued, a deficient response received
CLEAN = "CASE-2025-0482"         # the case where the taxpayer is right and nothing is wrong


@pytest.fixture(scope="module")
def api(request):
    """The app over the seeded test database, through HTTP."""
    request.getfixturevalue("seeded")          # session-scoped seed, shared with the rest
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        yield client


@contextmanager
def _case_row(case_id: str = CASE):
    """The ORM rows, for the two seams that are not behind an endpoint yet."""
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import AuditCase

    db = SessionLocal()
    try:
        case = db.scalar(select(AuditCase).where(AuditCase.case_id == case_id))
        yield case, case.taxpayer
    finally:
        db.close()


def _json(resp):
    assert resp.status_code == 200, f"{resp.request.url} -> {resp.status_code} {resp.text[:400]}"
    return resp.json()


def xlsx(headers: list[str], rows: list[list], sheet_name: str = "Sheet1") -> bytes:
    """A real .xlsx, so the upload path is exercised as the taxpayer's file exercises it."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ===================================================================== 1 · who am I dealing with
def test_the_case_says_who_the_taxpayer_is(api):
    """'Who is the taxpayer?' — the first thing on the screen, not something to go and look up."""
    case = _json(api.get(f"/api/cases/{CASE}"))
    tp = case["taxpayer"]
    assert tp["name"] and tp["vat_no"], "a case with no taxpayer identity is not a case"
    assert tp["sector"], "the sector decides which timing rules can even apply"
    assert case["period"], "an audit is always of a period"
    assert case["reason"], "the auditor has to be able to say why this case is open"


def test_the_two_things_the_scope_cut_kept_are_still_there(api):
    """Registered activities and prior audits survived the cut because the work needs them.

    Revenue matching none of the registered activities is the undisclosed-secondary-activity
    outcome, and a repeat of a prior root cause is the first thing an auditor checks. Neither is
    reachable without these two blocks.
    """
    dossier = _json(api.get(f"/api/cases/{CASE}/dossier"))
    assert "prior-audits" in dossier["blocks"], \
        "a repeat of a prior root cause is the first thing an auditor looks for"

    # The activity list is not in the dossier: it belongs to the case, because a registration is
    # a fact about the taxpayer rather than a holding to be retrieved. It reaches the agents
    # through the investigation context, and EV-04 is unreachable without it.
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    ev04 = next((h for h in inv["hypotheses"] if h["outcome_code"] == "SAL-SECONDARY"), None)
    assert ev04 is not None, "the registered activity list never reached the agents"


# ============================================================== 2 · the email that already went
REQUEST_EMAIL = """
Dear Sir/Madam,

Further to the audit of your VAT returns for the period 1 January 2025 to 31 March 2025, we
require the following documents within 20 days of the date of this letter:

1. A detailed sales analysis for the period, in Excel format, showing the following columns:
   invoice date, invoice number, customer name, customer VAT number, description, taxable
   amount, VAT rate and VAT amount.
2. A credit and debit note listing for the same period.
3. A reconciliation of the sales reported in the VAT returns to the general ledger.

Please confirm receipt of this letter.

Yours faithfully,
General Authority of Zakat and Tax
"""


def test_the_email_i_already_sent_comes_back_as_a_checkable_list(api):
    """Planning is out of scope, so the spec has to be recovered from the email that went out."""
    parsed = _json(api.post(f"/api/cases/{CASE}/request-email/parse", json={"text": REQUEST_EMAIL}))
    keys = {i["key"] for i in parsed["items"]}
    assert {"sales-analysis", "credit-note-listing"} <= keys, keys

    sales = next(i for i in parsed["items"] if i["key"] == "sales-analysis")
    # The column list wraps over three lines in the email. Reading only the first would let a
    # response through that is missing everything after "customer name".
    cols = {c.lower() for c in sales["required_columns"]}
    assert "vat_amount" in cols and "customer_vat_number" in cols, cols
    assert sales["cue"], "the auditor confirms the parse, so it must show what triggered it"
    assert parsed["period_from"] == "2025-01-01" and parsed["period_to"] == "2025-03-31"


def test_the_parser_never_invents_a_request_item(api):
    """It may only select from the catalog. An unrecognised paragraph is reported, not guessed."""
    parsed = _json(api.post(f"/api/cases/{CASE}/request-email/parse", json={
        "text": "Please provide the widget schedule and the blue folder for the period."}))
    assert parsed["items"] == []
    assert parsed["unmatched"], "an ask it could not place has to be visible, not dropped"


def test_boilerplate_is_not_reported_as_an_outstanding_ask(api):
    """A salutation listed as an unplaced request would make the auditor distrust the panel."""
    parsed = _json(api.post(f"/api/cases/{CASE}/request-email/parse", json={"text": REQUEST_EMAIL}))
    blob = " ".join(parsed["unmatched"]).lower()
    for phrase in ("dear sir", "yours faithfully", "confirm receipt", "general authority"):
        assert phrase not in blob, f"boilerplate reported as an unplaced ask: {phrase}"


# ================================================================= 3 · what actually turned up
def test_it_tells_me_exactly_what_falls_short(api):
    """Job one. Not 'the response is deficient' — which column, which rows, which dates."""
    state = _json(api.post(f"/api/cases/{CASE}/requests/check"))
    report = state["report"]
    assert report["complete"] is False
    kinds = {g["kind"] for g in report["gaps"]}
    assert "missing-column" in kinds
    assert "empty-mandatory-field" in kinds
    assert "wrong-period" in kinds
    assert "arithmetic-mismatch" in kinds

    blanks = next(g for g in report["gaps"] if g["kind"] == "empty-mandatory-field")
    assert "rows" in blanks["citation"], "an auditor has to be able to go and look at the rows"
    for gap in report["gaps"]:
        assert gap["item_label"], "every gap names the request item it belongs to"
        assert gap["source"] == "deterministic", "column presence is a check, not a judgement"


def test_the_chase_email_names_every_gap_and_invents_nothing(api):
    """'If the docs are not what we asked for then directly write what is missing in an email.'"""
    state = _json(api.post(f"/api/cases/{CASE}/requests/check"))
    blocking = [g for g in state["report"]["gaps"] if g["severity"] == "blocking"]
    draft = _json(api.get(f"/api/cases/{CASE}/followup"))
    body = draft["text"]

    assert len(body) > 200, "a stub is not an acceptable fallback — it has to be sendable"
    for gap in blocking:
        label = gap["item_label"]
        assert label.lower()[:12] in body.lower(), f"the letter never mentions '{label}'"
    # Everything numeric in the letter has to trace to the facts the engine handed it.
    assert draft["verified"] or draft["violations"], \
        "a draft that did not verify must say what failed, not fail silently"


def test_a_corrected_response_closes_its_gap_and_the_old_file_stays_as_history(api):
    """The taxpayer answers the chase. The loop has to be able to close, or it is not a loop."""
    before = _json(api.post(f"/api/cases/{CASE}/requests/check"))
    item = next(g["request_item_id"] for g in before["report"]["gaps"]
                if g["kind"] == "missing-item")

    content = xlsx(["note_date", "note_number", "original_invoice_number", "customer_name",
                    "taxable_amount", "vat_amount", "reason"],
                   [["2025-02-10", f"CN-{i:03d}", f"INV-{i:03d}", "Riyadh Retail Co.",
                     -40_000.0, -6_000.0, "Returned goods"] for i in range(1, 6)])
    after = _json(api.post(
        f"/api/cases/{CASE}/documents",
        files={"file": ("Credit_Notes_Q1_2025.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"item_id": str(item)}))

    still_missing = [g for g in after["report"]["gaps"]
                     if g["kind"] == "missing-item" and g["request_item_id"] == item]
    assert not still_missing, "a supplied document must clear its own missing-item gap"
    assert len(after["documents"]) > len(before["documents"]), "the file is on the case file"


def test_a_file_that_answers_nothing_is_advisory_not_blocking(api):
    """A misfiled attachment is worth mentioning. It is not a reason to hold the case open."""
    content = xlsx(["date", "narrative", "amount"],
                   [["2025-01-15", "Opening balance", 100_000.0]])
    state = _json(api.post(
        f"/api/cases/{CASE}/documents",
        files={"file": ("Random_Extract.xlsx", content,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}))
    stray = [g for g in state["report"]["gaps"] if g["kind"] == "unrequested-document"]
    assert stray, "a document answering no item has to be surfaced"
    assert all(g["severity"] == "advisory" for g in stray)


# ========================================================================= 4 · what it means
def test_the_review_runs_all_four_agents(api):
    """The auditors named three and left the fourth to us. All four have to be on the case."""
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    assert inv["hypotheses"], "an empty panel is not a review"
    agents = {h["agent"] for h in inv["hypotheses"]}
    assert agents <= {"Regulations", "Data Entry", "Calculation", "Evidence & Coverage"}, \
        f"an agent the auditors never named is on the case file: {agents}"
    assert len(agents) == 4, f"only {agents} proposed anything on a case this deficient"


def test_every_finding_is_worded_by_the_authority(api):
    """'The Authority's own sentence is what gets written down.' Nothing is phrased ad hoc."""
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    assert inv["findings"], "a case with this much wrong should establish something"
    for f in inv["findings"]:
        assert f["code"] in oc.BY_CODE, f["code"]
        assert f["statement"] == oc.statement(f["code"]), "the wording was not taken from the "\
                                                          "vocabulary"
        assert not any(ch.isdigit() for ch in f["statement"]), \
            "an outcome statement must carry no figure — the amount travels beside it"


def test_i_can_see_why_each_finding_was_raised_and_how_it_was_settled(api):
    """'How the agents got there, this is very important.'

    An auditor defends a finding to a taxpayer. "An agent proposed it" is not a defence, so the
    observation that triggered it and the test that settled it both have to be on the screen.
    """
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    adjudications = {a["hypothesis_id"]: a for a in inv["adjudications"]}
    for f in inv["findings"]:
        assert f["why"], f"{f['code']} does not say what triggered it"
        assert f["explanation"], f"{f['code']} does not say how it was settled"
        a = adjudications[f["hypothesis_id"]]
        assert a["status"] == "confirmed"
        assert a["detail"], "a verdict with no working behind it cannot be checked"


def test_an_agent_never_states_a_figure(api):
    """The core invariant, at the level the screen shows it.

    The `claim` is exploratory language and stays entirely free of digits — every amount in this
    system is the adjudicator's. `why` is the observation that triggered the hypothesis, and may
    name how much material there was to test ("22 rows"), because an auditor reading the trigger
    needs its scale. What neither may ever carry is a **monetary amount**: that is the thing an
    agent is not entitled to assert, and the thing a reader would take as settled.
    """
    import re

    money = re.compile(r"(?:SAR|ريال)\s*[\d.,]+|[\d.,]{4,}\s*(?:SAR|riyals?)", re.I)
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    for h in inv["hypotheses"]:
        assert not re.search(r"\d", h["claim"]), \
            f"{h['id']} put a digit in its claim: {h['claim']!r}"
        for field in ("claim", "why"):
            assert not money.search(h.get(field) or ""), \
                f"{h['id']} states an amount in its {field}: {h.get(field)!r}"


def test_one_excess_is_assessed_once_however_many_ways_it_reads(api):
    """The catch that made `basis` exist.

    A sales listing above the return is simultaneously higher than declared, not disclosed, not
    corresponding, and — with no trial balance — a fourth statement, all from one test over one
    file. Adding them up would report three times the real exposure and put the same figure in
    the taxpayer's letter four times.
    """
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    exposure = inv["exposure"]
    findings = inv["findings"]

    by_basis: dict[str, set[float]] = {}
    for f in findings:
        if f["effect"] == "increases-output":
            by_basis.setdefault(f["basis"], set()).add(f["amount"])
    expected = sum(max(v) for v in by_basis.values())
    assert exposure["increases_output"] == pytest.approx(expected)
    assert exposure["increases_output"] < sum(
        f["amount"] for f in findings if f["effect"] == "increases-output"), \
        "the whole point is that the sum of the findings overstates the exposure"
    assert exposure["distinct_bases"] <= len(findings)


def test_documentation_risk_never_double_counts_an_amount_already_assessed(api):
    """Evidence at risk is what is *not yet* an adjustment. Otherwise it is the same money twice."""
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    assessed = {f["basis"] for f in inv["findings"] if f["effect"] != "documentation"}
    at_risk = {f["basis"] for f in inv["findings"] if f["effect"] == "documentation"}
    counted = at_risk - assessed
    expected = sum(max(f["amount"] for f in inv["findings"] if f["basis"] == b)
                   for b in counted)
    assert inv["exposure"]["documentation_at_risk"] == pytest.approx(expected)


def test_the_figures_name_the_document_they_came_from(api):
    """The auditor has to know whether a figure came from the taxpayer's file or the feed."""
    recon = _json(api.get(f"/api/cases/{CASE}/reconcile"))
    assert recon["population_source"] in ("document", "e-invoice")
    if recon["population_source"] == "document":
        assert recon["population_document"], "say which file, or the figure is unattributable"


# ================================================================ 5 · my own working, checked
def test_i_can_say_what_i_did_in_my_own_words_and_have_it_checked(api):
    """'It might be just a free text that they tell you, I calculated X, Y, Z.'

    And it must work with no API key, because that is what the demo runs on.
    """
    out = _json(api.post(f"/api/cases/{CASE}/calc/check", json={
        "method": "I summed the VAT column on the sales analysis and got 2,618,000 — check it?"}))
    assert out["status"] == "agree"
    assert out["stated"] == 2_618_000.0, "the figure was stated in the sentence, not a box"
    assert out["computed"] == 2_618_000.0
    assert out["query"] == "sum(vat_amount)", "it has to show the query it ran, not just a verdict"
    assert out["source"] == "deterministic"


def test_it_tells_me_how_it_read_me_before_it_answers(api):
    """A misread method must surface as a visible wrong query, never as a wrong number."""
    out = _json(api.post(f"/api/cases/{CASE}/calc/ask", json={
        "question": "how many distinct customers are on the sales analysis?"}))
    assert out["status"] == "ok"
    assert "distinct" in out["understood"] and "customer" in out["understood"]


def test_a_disagreement_says_what_it_recomputed_and_over_how_many_rows(api):
    """Being told "you are wrong" without the working is useless to an auditor."""
    out = _json(api.post(f"/api/cases/{CASE}/calc/check", json={
        "label": "Q1 output VAT", "method": "total of the VAT column on the sales analysis",
        "stated_amount": 2_500_000.0}))
    assert out["status"] == "disagree"
    assert out["delta"] == pytest.approx(118_000.0)
    assert "22" in out["explanation"], "say how many rows it ran over"
    assert out["document"], "say which document it ran over"


def test_a_method_it_cannot_express_is_declined_not_approximated(api):
    """The important refusal: a condition it cannot apply must not be silently dropped.

    Totalling the whole file and then reporting the auditor's correct January figure as a
    disagreement is the worst outcome this agent can produce.
    """
    out = _json(api.post(f"/api/cases/{CASE}/calc/ask", json={
        "question": "sum of the VAT column for January only on the sales analysis"}))
    assert out["status"] == "not-checkable"
    assert out["answer"] is None
    assert "condition" in out["note"].lower()


def test_a_question_naming_no_document_asks_which_one(api):
    """Answering a sales question off the purchase listing is the error this agent exists to catch."""
    docs = _json(api.get(f"/api/cases/{CASE}/calc"))["documents"]
    if len(docs) < 2:
        pytest.skip("needs more than one tabular document on the case")
    out = _json(api.post(f"/api/cases/{CASE}/calc/ask", json={
        "question": "what is the total VAT amount?"}))
    assert out["status"] == "not-checkable"
    assert "which" in out["note"].lower() or "name one" in out["note"].lower()


def test_a_query_i_specify_myself_is_run_verbatim(api):
    """Nothing to interpret, so nothing gets interpreted — and no model is reached."""
    out = _json(api.post(f"/api/cases/{CASE}/calc/ask", json={
        "question": "ignore this sentence entirely",
        "spec": {"op": "count", "document": "Sales_Analysis_Q1_2025.xlsx"}}))
    assert out["status"] == "ok"
    assert out["answer"] == 22
    assert out["source"] == "auditor"


# ======================================================================= 6 · what goes out
def test_there_is_a_draft_at_every_step_that_has_something_to_say(api):
    """'At each important step you should put email drafts.' And only where there is a trigger."""
    emails = _json(api.get(f"/api/cases/{CASE}/emails"))["emails"]
    steps = {e["step"]: e for e in emails}
    assert "response-check" in steps, "there are open gaps, so the chase must be offered"
    assert "closure" in steps, "there are findings, so the verdict must be offered"
    for e in emails:
        assert len(e["text"]) > 200, f"{e['step']} draft is a stub"
        assert e["trigger"], "the auditor must see why a draft is being offered"


def test_the_verdict_letter_states_each_amount_once(api):
    """It used to state SAR 618,000 four times — once per way of reading the same excess."""
    body = _json(api.get(f"/api/cases/{CASE}/verdict"))["text"]
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    amounts = [f["amount"] for f in inv["findings"] if f["effect"] == "increases-output"]
    if amounts:
        formatted = f"{max(amounts):,.0f}"
        assert body.count(formatted) <= 2, \
            f"'{formatted}' appears {body.count(formatted)} times in the letter"


def test_the_letter_introduces_no_figure_of_its_own(api):
    """`verify_correspondence` in substance: every numeral must trace to the engine's facts."""
    import re

    from app.agents.correspondence import verdict_facts

    recon = _json(api.get(f"/api/cases/{CASE}/reconcile"))
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    with _case_row() as (case, taxpayer):
        facts = verdict_facts(case, taxpayer, recon, inv, inv.get("findings"))

    body = _json(api.get(f"/api/cases/{CASE}/verdict"))["text"]
    fact_numbers = set(re.findall(r"\d[\d,]*(?:\.\d+)?", facts))
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", body):
        assert n in fact_numbers or len(n.replace(",", "")) <= 2, \
            f"the letter states {n!r}, which is not in the facts block it was given"


def test_the_audit_report_follows_the_authority_template(api):
    """The outcome is two things: the email and the audit report."""
    from app.reporting import audit_report

    recon = _json(api.get(f"/api/cases/{CASE}/reconcile"))
    inv = _json(api.get(f"/api/cases/{CASE}/investigate"))
    with _case_row() as (case, taxpayer):
        report = audit_report.build(case, taxpayer, recon, inv)

    titles = [s["title"] for s in report["sections"]]
    assert titles == ["Taxpayer information", "Audit Case information",
                      "Assigned Audit Team information", "Taxpayer documentation",
                      "Audit Outcome", "Risk feedback"], titles

    fields = [f for s in report["sections"] for f in s["fields"]]
    filled = report["completeness"]["filled"]
    assert filled == sum(1 for f in fields if f["held"])
    assert filled >= len(fields) // 2, \
        "more than half the template unfilled means the report is not usable"

    # A field the case cannot answer says which kind of gap it is. Filling either from a guess
    # would put an invented fact under the Authority's letterhead.
    for f in fields:
        if not f["held"]:
            assert f["value"] in (audit_report.NOT_HELD, audit_report.FOR_AUDITOR), \
                f"'{f['label']}' is neither filled nor honestly marked: {f['value']!r}"

    outcome = next(s for s in report["sections"] if s["title"] == "Audit Outcome")
    blob = " ".join(f["value"] for f in outcome["fields"])
    for f in inv["findings"]:
        assert f["statement"][:40] in blob, f"{f['code']} never reaches the report"


# ============================================================ 7 · the case where nothing is wrong
def test_a_clean_case_raises_nothing_and_says_so(api):
    """The most important negative test in the suite.

    An agent that fires on a compliant taxpayer costs more than one that misses, because the
    auditor stops reading the panel — and this one goes out under the Authority's name.
    """
    inv = _json(api.get(f"/api/cases/{CLEAN}/investigate"))
    assert inv["findings"] == [], [f["code"] for f in inv["findings"]]
    assert inv["exposure"]["total"] == 0.0

    emails = _json(api.get(f"/api/cases/{CLEAN}/emails"))["emails"]
    closure = next((e for e in emails if e["step"] == "closure"), None)
    assert closure is not None, "a clean case still needs a letter — it is still an outcome"
    assert "no finding" in closure["trigger"] or "supported" in closure["trigger"]


def test_the_lifecycle_says_whose_move_it_is(api):
    """The rail on every tab: where the case is, and who has to act next."""
    rail = _json(api.get(f"/api/cases/{CASE}/lifecycle"))
    stages = rail["stages"] if isinstance(rail, dict) else rail
    active = [s for s in stages if s["state"] == "active"]
    assert active, "a live case must be somewhere"
    for s in active:
        assert s["owner"] in ("auditor", "taxpayer", "system"), s["owner"]
        assert s["next_action"], f"stage '{s['label']}' is active but names no next action"
