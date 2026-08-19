import { useEffect, useState } from "react";
import VerifyBadge from "./VerifyBadge";
import { getVerdict, type Draft } from "../api";

/** The letter telling the taxpayer the outcome — §8's second named administrative burden.
 *
 *  Drafted from the engine's conclusion and nothing else. The guard is the same one the
 *  request letters use: every numeric literal in the draft must appear in the facts block,
 *  so the model may repeat a figure the engine established and may not introduce one.
 *  Nothing is sent from here; the auditor edits and approves.
 */
export default function VerdictLetter({ id }: { id: string }) {
  const [d, setD] = useState<Draft | null>(null);
  const [copied, setCopied] = useState(false);
  const [err, setErr] = useState(false);

  useEffect(() => {
    setD(null);
    setErr(false);
    getVerdict(id).then(setD).catch(() => setErr(true));
  }, [id]);

  if (err) return null;
  return (
    <div className="panel ai-panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="ai-chip">AI</span>
          <h2>Draft letter to the taxpayer</h2>
        </div>
        <div className="chips">
          <VerifyBadge source={d ? (d.source === "none" ? null : d.source) : null}
                       violations={d?.violations} />
          {d?.text && (
            <button
              className="btn small"
              onClick={() => {
                navigator.clipboard?.writeText(d.text);
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              }}
            >
              {copied ? "Copied" : "Copy"}
            </button>
          )}
        </div>
      </div>
      <div className="panel-body">
        {!d ? (
          <span className="muted">Drafting…</span>
        ) : (
          <>
            <pre className="letterpre">{d.text}</pre>
            <p className="detail-note">
              A draft for the auditor to edit and approve — nothing is sent from here. Every
              figure in it was computed by the engine.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
