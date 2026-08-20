"""Findings are the only bridge from an agent to something a taxpayer reads.

The properties worth protecting: a finding is worded by the Authority's vocabulary and not by
the agent, its amount comes from the adjudicator, and a confirmed hypothesis that names no
outcome never becomes a line in a letter.
"""
from app import outcomes as oc
from app.agents.contracts import Adjudication, Hypothesis, TestSpec
from app.agents.findings import exposure, from_investigation, grouped_by_basis


def hyp(hid, code, claim="A claim written to be tested."):
    return Hypothesis(id=hid, agent="Evidence & Coverage", claim=claim, outcome_code=code,
                      why="something on the case file", test=TestSpec(kind="missing-support"))


def adj(hid, status, amount=0.0, explanation="engine said so"):
    return Adjudication(hypothesis_id=hid, status=status, amount=amount,
                        explanation=explanation)


def test_a_confirmed_hypothesis_is_worded_by_the_vocabulary_not_the_agent():
    h = hyp("EV-01", "PUR-NODOC", claim="Agent phrasing that must not be sent.")
    out = from_investigation([h], [adj("EV-01", "confirmed", 10500.0)])
    assert len(out) == 1
    assert out[0].statement == oc.statement("PUR-NODOC")
    assert "Agent phrasing" not in out[0].statement


def test_the_amount_comes_from_the_adjudicator():
    out = from_investigation([hyp("EV-01", "PUR-NODOC")],
                             [adj("EV-01", "confirmed", 10500.0)])
    assert out[0].amount == 10500.0


def test_a_refuted_hypothesis_is_not_a_finding():
    assert from_investigation([hyp("EV-01", "PUR-NODOC")],
                              [adj("EV-01", "refuted", 10500.0)]) == []


def test_insufficient_evidence_is_not_a_finding():
    assert from_investigation([hyp("EV-01", "PUR-NODOC")],
                              [adj("EV-01", "insufficient-evidence")]) == []


def test_a_confirmed_hypothesis_with_no_outcome_never_goes_outbound():
    """A decimal slip explains a difference; it is not a finding the Authority states."""
    h = Hypothesis(id="DE-01", agent="Data Entry", claim="A keying slip.",
                   test=TestSpec(kind="decimal-shift"))
    assert from_investigation([h], [adj("DE-01", "confirmed", 75000.0)]) == []


def test_an_unknown_outcome_code_is_dropped_not_invented():
    h = hyp("EV-99", "NOT-A-CODE")
    assert from_investigation([h], [adj("EV-99", "confirmed", 100.0)]) == []


def test_findings_are_ordered_by_what_is_at_stake():
    hyps = [hyp("A", "PUR-NODOC"), hyp("B", "SAL-HIGHER"), hyp("C", "PUR-BLOCKED")]
    adjs = [adj("A", "confirmed", 1_000.0), adj("B", "confirmed", 90_000.0),
            adj("C", "confirmed", 5_000.0)]
    assert [f.hypothesis_id for f in from_investigation(hyps, adjs)] == ["B", "C", "A"]


def test_exposure_keeps_output_and_input_apart():
    """Both are revenue, but they are different adjustments and must not be added blind.

    Three separate pieces of evidence, so nothing here collapses onto a shared basis.
    """
    hyps = [hyp("A", "SAL-HIGHER"), hyp("B", "PUR-BLOCKED"), hyp("C", "DOC-INVOICE")]
    adjs = [Adjudication(hypothesis_id="A", status="confirmed", amount=90_000.0,
                         detail={"basis": "excess|output|sales.xlsx"}),
            Adjudication(hypothesis_id="B", status="confirmed", amount=3_000.0,
                         detail={"basis": "blocked|input|purchases.xlsx"}),
            Adjudication(hypothesis_id="C", status="confirmed", amount=15_000.0,
                         detail={"basis": "conditions|output|sales.xlsx"})]
    e = exposure(from_investigation(hyps, adjs))
    assert e["increases_output"] == 90_000.0
    assert e["disallows_input"] == 3_000.0
    assert e["documentation_at_risk"] == 15_000.0
    assert e["total"] == 93_000.0          # documentation is not an assessment
    assert e["count"] == 3


def test_the_finding_carries_the_trigger_and_the_engine_explanation():
    out = from_investigation([hyp("EV-01", "PUR-NODOC")],
                             [adj("EV-01", "confirmed", 1.0, "3 lines carry no invoice number")])
    assert out[0].why == "something on the case file"
    assert "3 lines" in out[0].explanation


# ------------------------------------------------------------- shared evidence
def hyp_with(hid, code, kind, doc="sales.xlsx", box="output"):
    return Hypothesis(id=hid, agent="Calculation", claim="A claim.", outcome_code=code,
                      why="because", test=TestSpec(kind=kind, box=box,
                                                   params={"document": doc}))


def adj_basis(hid, amount, basis):
    return Adjudication(hypothesis_id=hid, status="confirmed", amount=amount,
                        detail={"basis": basis}, explanation="engine said so")


def test_one_excess_read_four_ways_is_counted_once():
    """A listing above the return supports several statements at once. They are readings of a
    single excess — adding them would assess the same riyals four times in a letter."""
    hyps = [hyp_with("CA-01", "SAL-HIGHER", "listing-vs-declared"),
            hyp_with("CA-02", "SAL-UNDISCLOSED", "listing-vs-declared"),
            hyp_with("EV-03", "SAL-NOTB", "trial-balance-absent")]
    basis = "excess|output|sales.xlsx"
    adjs = [adj_basis("CA-01", 618_000.0, basis),
            adj_basis("CA-02", 618_000.0, basis),
            adj_basis("EV-03", 618_000.0, basis)]      # delegates, so same basis
    found = from_investigation(hyps, adjs)
    assert len(found) == 3                              # all three still reported
    e = exposure(found)
    assert e["increases_output"] == 618_000.0           # but assessed once
    assert e["distinct_bases"] == 1


def test_different_evidence_still_adds_up():
    hyps = [hyp_with("CA-01", "SAL-HIGHER", "listing-vs-declared"),
            hyp_with("CA-03", "SAL-POS", "listing-vs-declared", doc="pos.xlsx")]
    adjs = [adj_basis("CA-01", 100_000.0, "excess|output|sales.xlsx"),
            adj_basis("CA-03", 40_000.0, "excess|output|pos.xlsx")]
    assert exposure(from_investigation(hyps, adjs))["increases_output"] == 140_000.0


def test_documentation_risk_excludes_evidence_already_assessed():
    """The same excess read as 'documents do not correspond' is not further money at risk."""
    basis = "excess|output|sales.xlsx"
    hyps = [hyp_with("CA-01", "SAL-HIGHER", "listing-vs-declared"),
            hyp_with("EV-02", "SAL-MISMATCH", "listing-vs-declared"),
            hyp_with("RG-S1", "DOC-INVOICE", "invoice-conditions")]
    adjs = [adj_basis("CA-01", 618_000.0, basis),
            adj_basis("EV-02", 618_000.0, basis),
            adj_basis("RG-S1", 357_000.0, "conditions|output|sales.xlsx")]
    e = exposure(from_investigation(hyps, adjs))
    assert e["increases_output"] == 618_000.0
    assert e["documentation_at_risk"] == 357_000.0      # not 975,000
    assert e["total"] == 618_000.0


def test_grouped_by_basis_clusters_the_alternative_readings():
    basis = "excess|output|sales.xlsx"
    hyps = [hyp_with("CA-01", "SAL-HIGHER", "listing-vs-declared"),
            hyp_with("CA-02", "SAL-UNDISCLOSED", "listing-vs-declared"),
            hyp_with("RG-S1", "DOC-INVOICE", "invoice-conditions")]
    adjs = [adj_basis("CA-01", 618_000.0, basis), adj_basis("CA-02", 618_000.0, basis),
            adj_basis("RG-S1", 357_000.0, "conditions|output|sales.xlsx")]
    groups = grouped_by_basis(from_investigation(hyps, adjs))
    assert len(groups) == 2
    assert groups[0]["amount"] == 618_000.0 and len(groups[0]["findings"]) == 2


# ---------------------------------------------------------------- in the letter
def test_the_letter_states_each_amount_once_per_basis():
    """Four statements about one excess must not read as four debts to the taxpayer."""
    from app.agents.correspondence import _finding_lines

    basis = "excess|output|sales.xlsx"
    hyps = [hyp_with("CA-01", "SAL-HIGHER", "listing-vs-declared"),
            hyp_with("CA-02", "SAL-UNDISCLOSED", "listing-vs-declared"),
            hyp_with("EV-02", "SAL-MISMATCH", "listing-vs-declared"),
            hyp_with("RG-S1", "DOC-INVOICE", "invoice-conditions")]
    adjs = [adj_basis("CA-01", 618_000.0, basis), adj_basis("CA-02", 618_000.0, basis),
            adj_basis("EV-02", 618_000.0, basis),
            adj_basis("RG-S1", 357_000.0, "conditions|output|sales.xlsx")]
    lines = _finding_lines([f.to_dict() for f in from_investigation(hyps, adjs)])
    assert sum("618,000" in ln for ln in lines) == 1
    assert sum("357,000" in ln for ln in lines) == 1
    # the alternative readings are still on the page, just without the money
    assert sum("Also characterised as" in ln for ln in lines) == 2


def test_finding_lines_accepts_findings_or_dicts():
    out = from_investigation([hyp("EV-01", "PUR-NODOC")], [adj("EV-01", "confirmed", 10.0)])
    from app.agents.correspondence import _finding_lines
    assert _finding_lines(out) == _finding_lines([f.to_dict() for f in out])
