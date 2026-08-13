import { useEffect, useState } from "react";
import { getSummary, type Summary } from "../ai/ai";
import VerifyBadge from "./VerifyBadge";

export default function TaxpayerBrief({ id }: { id?: string }) {
  const [d, setD] = useState<Summary | null>(null);
  useEffect(() => {
    if (!id) return;
    setD(null);
    getSummary(id).then(setD).catch(() => {});
  }, [id]);
  return (
    <div className="panel ai-panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="ai-chip">AI</span>
          <h2>Taxpayer brief</h2>
        </div>
        <VerifyBadge source={d ? d.source : null} violations={d?.violations} />
      </div>
      <div className="ai-body">
        {!d ? (
          <span className="muted">Summarising…</span>
        ) : (
          <>
            <p className="brief-head">{d.headline}</p>
            <ul className="brief-points">
              {d.points.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
            {d.risk_flags.length > 0 && (
              <div className="chips">
                {d.risk_flags.map((f) => (
                  <span key={f} className="pill pri-medium">
                    {f}
                  </span>
                ))}
              </div>
            )}
            <p className="detail-note" style={{ margin: "10px 0 0" }}>{d.prior_pattern}</p>
          </>
        )}
      </div>
    </div>
  );
}
