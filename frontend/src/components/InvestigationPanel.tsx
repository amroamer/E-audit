import { useEffect, useState } from "react";
import { getInvestigation, type AdjudicationStatus, type Investigation } from "../api";

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const STATUS_PILL: Record<AdjudicationStatus, string> = {
  confirmed: "pri-low",
  refuted: "status",
  "insufficient-evidence": "pri-medium",
};

/** Agents propose typed tests; a deterministic adjudicator settles them against the engine.
 *  No model states a figure here, so the panel renders with or without an API key. */
export default function InvestigationPanel({ id, rev }: { id?: string; rev?: number }) {
  const [d, setD] = useState<Investigation | null>(null);

  useEffect(() => {
    if (!id) return;
    setD(null);
    getInvestigation(id).then(setD).catch(() => {});
  }, [id, rev]);

  const adjudication = (hid: string) => d?.adjudications.find((a) => a.hypothesis_id === hid);
  const objection = d?.entries.find((e) => e.kind === "objection");

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
                  Round 1–2 · {d.hypotheses.length} hypotheses proposed, each settled against the engine
                </div>
                {d.hypotheses.map((h) => {
                  const a = adjudication(h.id);
                  const lead = d.leading === h.id;
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
                        {a?.explanation && <div className="verdict">{a.explanation}</div>}
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
