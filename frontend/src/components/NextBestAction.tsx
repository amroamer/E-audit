import { useEffect, useState } from "react";
import { getNba, type Nba } from "../ai/ai";
import VerifyBadge from "./VerifyBadge";

export default function NextBestAction({ id, rev }: { id?: string; rev?: number }) {
  const [d, setD] = useState<Nba | null>(null);
  useEffect(() => {
    if (!id) return;
    setD(null);
    getNba(id).then(setD).catch(() => {});
  }, [id, rev]);
  return (
    <div className="panel ai-panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="ai-chip">AI</span>
          <h2>Next best action</h2>
        </div>
        <VerifyBadge source={d ? d.source : null} violations={d?.violations} />
      </div>
      <div className="ai-body">
        {!d ? (
          <span className="muted">Deciding…</span>
        ) : d.action_type === "no-action" ? (
          <p className="muted">No action — residual within materiality. {d.rationale}</p>
        ) : (
          <>
            <div className="nba-top">
              <span className="pill pri-high">{d.action_type.replace(/-/g, " ")}</span>
              <span className="muted">to {d.addressed_to.replace(/-/g, " ")}</span>
              {d.minimises_contact && <span className="pill pri-low">minimises contact</span>}
            </div>
            <div className="kv">
              <div>
                <span className="k">Request</span>
                <span className="v">{d.document_requested}</span>
              </div>
              <div>
                <span className="k">Expected outcome</span>
                <span className="v">{d.expected_yield}</span>
              </div>
            </div>
            <p className="detail-note" style={{ marginBottom: 0 }}>{d.rationale}</p>
          </>
        )}
      </div>
    </div>
  );
}
