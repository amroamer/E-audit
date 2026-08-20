import { useEffect, useState } from "react";
import { getInvestigation, type AdjudicationStatus, type Investigation } from "../api";

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const STATUS_PILL: Record<AdjudicationStatus, string> = {
  confirmed: "pri-low",
  refuted: "status",
  "insufficient-evidence": "pri-medium",
};
const STATUS_WORD: Record<AdjudicationStatus, string> = {
  confirmed: "confirmed",
  refuted: "refuted",
  "insufficient-evidence": "cannot be tested",
};

/** Agents propose typed tests; a deterministic adjudicator settles them against the engine.
 *  No model states a figure here, so the panel renders with or without an API key.
 *
 *  The panel shows the whole chain — what was seen, what was therefore proposed, what test
 *  settled it and what the engine concluded — because an auditor has to defend a finding to a
 *  taxpayer, and "an agent suggested it" is not something anyone can defend. */
export default function InvestigationPanel({ id, rev }: { id?: string; rev?: number }) {
  const [d, setD] = useState<Investigation | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setD(null);
    setOpen(null);
    getInvestigation(id).then(setD).catch(() => {});
  }, [id, rev]);

  const adjudication = (hid: string) => d?.adjudications.find((a) => a.hypothesis_id === hid);
  const objection = d?.entries.find((e) => e.kind === "objection");
  const confirmed = d?.adjudications.filter((a) => a.status === "confirmed").length ?? 0;
  const refuted = d?.adjudications.filter((a) => a.status === "refuted").length ?? 0;

  return (
    <div className="panel ai-panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="ai-chip">AGENTS</span>
          <h2>Investigation</h2>
        </div>
        <span
          className="pill status"
          title="Agents propose typed tests; a deterministic adjudicator settles them. No model states a figure."
        >
          ∑ Adjudicated (no AI)
        </span>
      </div>
      <div className="ai-body">
        {!d ? (
          <span className="muted">Investigating…</span>
        ) : (
          <>
            <p className="inv-conc">{d.conclusion}</p>

            {d.hypotheses.length > 0 && (
              <>
                <div className="inv-round">
                  Round 1–2 · {d.hypotheses.length} proposed · {confirmed} confirmed ·{" "}
                  {refuted} refuted
                </div>
                {d.hypotheses.map((h) => {
                  const a = adjudication(h.id);
                  const lead = d.leading === h.id;
                  const isOpen = open === h.id;
                  return (
                    <div className={"hyp" + (lead ? " lead" : "")} key={h.id}>
                      <div>
                        <div className="hid">{h.id}</div>
                        {h.reason_code && <span className="rc">{h.reason_code}</span>}
                      </div>
                      <div>
                        <div className="agent">
                          {h.agent}
                          {lead && " · leading"}
                        </div>
                        {h.claim}

                        {/* the trigger: what the agent actually saw. Without it the claim is
                            an assertion; with it, it is an inference the auditor can check. */}
                        {h.why && (
                          <div className="hyp-why">
                            <b>Why raised</b> {h.why}
                          </div>
                        )}

                        {a && (
                          <div className={"verdict verdict-" + a.status}>
                            <b>{STATUS_WORD[a.status]}</b> — {a.explanation}
                          </div>
                        )}

                        <button
                          className="linklike hyp-more"
                          onClick={() => setOpen(isOpen ? null : h.id)}
                        >
                          {isOpen ? "hide the test" : "how it was tested"}
                        </button>
                        {isOpen && (
                          <div className="hyp-test">
                            <div>
                              <span className="k">Test run</span>
                              <code>{h.test.kind}</code>
                              <span className="sub"> on the {h.test.box} box</span>
                            </div>
                            {!!Object.keys(h.test.params || {}).length && (
                              <div>
                                <span className="k">Against</span>
                                <code>
                                  {Object.entries(h.test.params)
                                    .map(([k, v]) => `${k}=${String(v)}`)
                                    .join(", ")}
                                </code>
                              </div>
                            )}
                            <div>
                              <span className="k">Confidence when proposed</span>
                              {h.confidence}
                            </div>
                            {h.outcome_code && (
                              <div>
                                <span className="k">Reports as</span>
                                <code>{h.outcome_code}</code>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                      <div style={{ textAlign: "right" }}>
                        <span className={"pill " + (a ? STATUS_PILL[a.status] : "status")}>
                          {(a?.status ?? "").replace(/-/g, " ")}
                        </span>
                        {!!a?.amount && <div className="amt2">{sar(a.amount)}</div>}
                      </div>
                    </div>
                  );
                })}
                {objection && (
                  <>
                    <div className="inv-round">Round 3 · Challenger</div>
                    <p className="detail-note" style={{ margin: 0 }}>
                      {objection.payload.note}
                    </p>
                  </>
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  );
}
