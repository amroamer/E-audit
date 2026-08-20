import { useEffect, useState } from "react";
import { getStepEmails, type StepEmails as StepEmailsData } from "../api";
import VerifyBadge from "./VerifyBadge";

/** The drafts that go back out: the chase, and the verdict.
 *
 *  A draft appears only when its trigger exists — a chase with nothing outstanding, or a verdict
 *  before there is a position to report, would train the auditor to ignore the panel. Nothing is
 *  sent from here; every figure in a draft was established by the engine before Claude saw it. */
export default function StepEmails({ id, rev }: { id?: string; rev?: number }) {
  const [d, setD] = useState<StepEmailsData | null>(null);
  const [copied, setCopied] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    setD(null);
    getStepEmails(id).then(setD).catch(() => {});
  }, [id, rev]);

  const copy = (kind: string, text: string) => {
    navigator.clipboard?.writeText(text);
    setCopied(kind);
    setTimeout(() => setCopied(null), 1500);
  };

  if (!d) return null;

  return (
    <>
      {d.emails.map((e) => (
        <div className="panel ai-panel" key={e.kind}>
          <div className="panel-head">
            <div className="ai-h">
              <span className="ai-chip">AI</span>
              <h2>{e.title}</h2>
            </div>
            <div className="chips">
              <span className="pill status" title="What caused this draft to exist">
                {e.trigger}
              </span>
              <VerifyBadge source={e.source === "none" ? null : (e.source as any)}
                           violations={e.violations} />
              {e.text && (
                <button className="btn small" onClick={() => copy(e.kind, e.text)}>
                  {copied === e.kind ? "Copied" : "Copy"}
                </button>
              )}
            </div>
          </div>
          <div className="panel-body">
            <pre className="letterpre">{e.text}</pre>
            <p className="detail-note">
              {e.kind === "follow-up"
                ? "Written from the gaps alone — items already supplied in full are not repeated. A draft for you to edit and send."
                : "Written from the findings established on review. Each amount is stated once; where several statements describe one piece of evidence, the others follow without repeating the figure."}
            </p>
          </div>
        </div>
      ))}
    </>
  );
}
