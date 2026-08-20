import { useEffect, useState } from "react";
import { getNarration, type Narration } from "../ai/ai";
import VerifyBadge from "./VerifyBadge";

export default function AiNarration({ id, rev }: { id?: string; rev?: number }) {
  const [d, setD] = useState<Narration | null>(null);
  useEffect(() => {
    if (!id) return;
    setD(null);
    getNarration(id).then(setD).catch(() => {});
  }, [id, rev]);
  return (
    <div className="panel ai-panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="ai-chip">AI</span>
          <h2>What qualifies, and how it compares</h2>
        </div>
        <VerifyBadge source={d ? d.source : null} violations={d?.violations} />
      </div>
      <div className="ai-body">{d ? d.text : <span className="muted">Generating…</span>}</div>
    </div>
  );
}
