"""The case lead — a bounded state machine, deliberately not a model.

Free-form agent chat is unauditable and unbounded, so nothing here is a conversation. The
agents read and append typed entries on a shared case file, in fixed rounds:

    0  facts        the engine publishes what it computed
    1  hypotheses   evidence agents propose, in parallel
    2  adjudication the deterministic adjudicator settles every one
    3  objection    the challenger attacks the leading hypothesis
    4  conclusion   the case lead ranks, and states what remains unexplained

It stops when the confirmed hypotheses account for the difference, or it escalates the
ranked list to the auditor rather than guessing. Every conclusion traces back to an
adjudicated test over engine data.
"""
from __future__ import annotations

from .adjudicator import CaseContext, adjudicate
from .contracts import Adjudication, Entry, Hypothesis, Investigation
from .detectors import propose as propose_recon, recomputation
from .roster import propose as propose_documents
from .findings import from_investigation, exposure

CASE_LEAD = "Case Lead"
CHALLENGER = "Challenger"

CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def _sar(v: float) -> str:
    return f"SAR {abs(v):,.0f}"


def investigate(recon: dict, *, prior_returns: list[dict] | None = None,
                prior_cases: list[dict] | None = None,
                documents: list[dict] | None = None,
                recorded: list[dict] | None = None,
                cr_activities: list[dict] | None = None,
                calculations: list[dict] | None = None,
                gaps: list[dict] | None = None,
                requested: list[dict] | None = None) -> Investigation:
    ctx = CaseContext(recon=recon, prior_returns=prior_returns or [],
                      prior_cases=prior_cases or [],
                      documents=documents or [], recorded=recorded or [],
                      cr_activities=cr_activities or [], calculations=calculations or [],
                      gaps=gaps or [], requested=requested or [])
    entries: list[Entry] = []
    seq = 0

    def add(round_: int, kind: str, agent: str, payload: dict) -> None:
        nonlocal seq
        seq += 1
        entries.append(Entry(seq=seq, round=round_, kind=kind, agent=agent, payload=payload))

    # ---- round 0: the engine publishes the facts the agents may reason over
    difference = recon["unexplained"]   # what the investigation has to account for
    add(0, "fact", "Engine", {
        "declared": recon["declared"], "expected": recon["expected_vat"],
        "difference": difference, "materiality": recon["materiality"],
        "state": recon["state"],
        "input_unexplained": recon["purchase"]["unexplained"],
        "deferred_out": recon.get("deferred_out", {}),
    })

    # A supported case has nothing to investigate. Saying so plainly beats running the
    # machinery and reporting that no pattern explains a difference that does not exist.
    #
    # One exception: the auditor-error recomputation (§7) is a check on our own working, and a
    # case that looks supported *because* a figure was transcribed wrongly is exactly the case
    # that must not be waved through. If there is anything to recompute, the machinery runs.
    if (abs(difference) <= recon["materiality"]
            and recon["purchase"]["state"] != "potential-finding"
            and not recomputation(ctx)
            and not propose_documents(ctx)):
        conclusion = ("The declared return is supported by the qualified e-invoice evidence "
                      "within materiality. There is no difference to investigate.")
        add(4, "conclusion", CASE_LEAD,
            {"leading": None, "explained": 0.0, "unexplained": 0.0, "conclusion": conclusion})
        return Investigation(case_id=recon["case_id"], rounds=1, entries=entries,
                             hypotheses=[], adjudications=[], leading=None,
                             conclusion=conclusion, unexplained=0.0, source="deterministic",
                             findings=[], exposure=exposure([]))

    # ---- round 1: evidence agents propose (parallel fan-out; no interdependence)
    #
    # Which roster is live depends on where the population came from. The four named agents read
    # the taxpayer's uploaded documents and are the whole roster under the current scope. The
    # reconstruction and historical-pattern detectors reason about the e-invoice feed and the
    # return history — the planning-era inputs — so on a case built from an uploaded listing they
    # have nothing to say, and a confirmed hypothesis that can never carry an outcome code is
    # precisely the noise the roster design exists to avoid. They stay live on the feed path,
    # which is why they are gated rather than deleted.
    #
    # The recomputation control runs on both paths regardless: it checks OUR arithmetic, and a
    # case that looks settled because a figure was transcribed wrongly must not be waved through.
    from_documents = recon.get("population_source") == "document"
    hypotheses = (recomputation(ctx) if from_documents else propose_recon(ctx)) \
        + propose_documents(ctx)
    for h in hypotheses:
        add(1, "hypothesis", h.agent,
            {"id": h.id, "claim": h.claim, "why": h.why, "test": h.test.describe(),
             "confidence": h.confidence, "outcome_code": h.outcome_code})

    # ---- round 2: the adjudicator settles each one against engine data
    adjudications: list[Adjudication] = []
    for h in hypotheses:
        a = adjudicate(h, ctx)
        adjudications.append(a)
        add(2, "adjudication", "Adjudicator",
            {"id": h.id, "status": a.status, "amount": a.amount,
             "explanation": a.explanation, "detail": a.detail})

    by_id = {h.id: h for h in hypotheses}
    confirmed = [a for a in adjudications if a.status == "confirmed"]

    # A confirmed recomputation is a defect in OUR working, not an explanation of the
    # taxpayer's difference. It carries an amount, so without this it would out-rank the real
    # hypotheses and "explain" the case with our own transcription error. It is reported
    # first and separately, because everything downstream of it is unsafe until it is fixed.
    controls = [a for a in confirmed
                if by_id[a.hypothesis_id].test.kind == "recomputed-total"]
    control_ids = {a.hypothesis_id for a in controls}
    substantive = [a for a in confirmed if a.hypothesis_id not in control_ids]

    # A confirmed test that accounts for no SAR (recurrence, magnitude) is corroborating
    # context, not the answer. Only an explanatory hypothesis can lead.
    explanatory = sorted(
        (a for a in substantive if abs(a.amount) > 0),
        key=lambda a: (abs(a.amount), CONFIDENCE_RANK[by_id[a.hypothesis_id].confidence]),
        reverse=True)
    context = [a for a in substantive if abs(a.amount) == 0]
    leading = explanatory[0] if explanatory else None

    # ---- round 3: the challenger attacks the leader, so we do not converge too early
    if leading is not None:
        rivals = [a for a in explanatory if a.hypothesis_id != leading.hypothesis_id]
        shortfall = round(abs(difference) - abs(leading.amount), 2)
        if rivals:
            add(3, "objection", CHALLENGER, {
                "against": leading.hypothesis_id,
                "note": ("More than one hypothesis is confirmed and they claim the same "
                         "difference. The auditor must choose between them: "
                         + ", ".join(a.hypothesis_id for a in rivals) + ".")})
        elif shortfall > recon["materiality"]:
            add(3, "objection", CHALLENGER, {
                "against": leading.hypothesis_id,
                "note": (f"The leading hypothesis accounts for {_sar(leading.amount)} of a "
                         f"{_sar(difference)} difference, leaving {_sar(shortfall)} unaccounted "
                         f"for — above materiality. It cannot be the whole story.")})
        else:
            add(3, "objection", CHALLENGER, {
                "against": leading.hypothesis_id,
                "note": "No competing hypothesis survived adjudication and the leader accounts "
                        "for the difference within materiality."})
    else:
        add(3, "objection", CHALLENGER, {
            "against": None,
            "note": "No hypothesis was confirmed. The difference is not explained by any pattern "
                    "the evidence agents can test."})

    # ---- round 4: conclusion
    explained = round(abs(leading.amount) if leading else 0.0, 2)
    unexplained = round(abs(difference) - explained, 2)
    if leading is None:
        conclusion = (f"No tested pattern explains the {_sar(unexplained)} difference. Escalate to "
                      f"the auditor with the ranked hypotheses for a manual line review.")
        if context:
            conclusion += " Supporting context: " + " ".join(a.explanation for a in context)
    elif unexplained <= recon["materiality"]:
        conclusion = (f"{by_id[leading.hypothesis_id].agent} proposed it and the engine confirmed "
                      f"it: {leading.explanation}")
    else:
        conclusion = (f"{leading.explanation} That still leaves {_sar(unexplained)} unaccounted "
                      f"for, which needs a separate explanation.")
    if controls:
        # said first, because it is a reason to distrust everything after it
        conclusion = (" ".join(a.explanation for a in controls) + " " + conclusion)
    add(4, "conclusion", CASE_LEAD, {"leading": leading.hypothesis_id if leading else None,
                                     "explained": explained, "unexplained": unexplained,
                                     "controls": [a.hypothesis_id for a in controls],
                                     "conclusion": conclusion})

    found = from_investigation(hypotheses, adjudications)
    return Investigation(
        case_id=recon["case_id"], rounds=5, entries=entries,
        hypotheses=hypotheses, adjudications=adjudications,
        leading=leading.hypothesis_id if leading else None,
        conclusion=conclusion, unexplained=unexplained, source="deterministic",
        findings=[f.to_dict() for f in found], exposure=exposure(found),
    )
