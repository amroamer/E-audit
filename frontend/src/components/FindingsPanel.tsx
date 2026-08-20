import { useEffect, useState } from "react";
import { getInvestigation, type Finding, type Investigation } from "../api";

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const EFFECT_LABEL: Record<Finding["effect"], string> = {
  "increases-output": "Output VAT understated",
  "disallows-input": "Input VAT not recoverable",
  documentation: "Documentation defect",
};
const EFFECT_PILL: Record<Finding["effect"], string> = {
  "increases-output": "pri-high",
  "disallows-input": "pri-high",
  documentation: "pri-medium",
};

/** Group findings by the evidence they rest on.
 *
 *  Several of the Authority's statements can be true of one document at once — a listing above
 *  the return is simultaneously "higher than declared", "not disclosed" and "does not
 *  correspond". Listed flat they read as three separate problems and the case looks three times
 *  worse than it is, so the amount is shown once per basis with the other readings under it. */
function group(findings: Finding[]) {
  const by = new Map<string, { basis: string; amount: number; items: Finding[] }>();
  for (const f of findings) {
    const key = f.basis || f.hypothesis_id;
    const g = by.get(key) ?? { basis: key, amount: 0, items: [] };
    g.amount = Math.max(g.amount, f.amount);
    g.items.push(f);
    by.set(key, g);
  }
  return [...by.values()].sort((a, b) => Math.abs(b.amount) - Math.abs(a.amount));
}

export default function FindingsPanel({ id, rev }: { id?: string; rev?: number }) {
  const [d, setD] = useState<Investigation | null>(null);

  useEffect(() => {
    if (!id) return;
    setD(null);
    getInvestigation(id).then(setD).catch(() => {});
  }, [id, rev]);

  if (!d) return null;
  const findings = d.findings ?? [];
  const groups = group(findings);
  const e = d.exposure;

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Findings</h2>
        <span className="pill status" title="Wording is the Authority's own; every amount was computed by the engine.">
          ∑ {findings.length ? `${findings.length} established` : "none established"}
        </span>
      </div>

      {!findings.length ? (
        <div className="panel-note">
          <span className="ct">∑ computed</span> No finding was established from the documents
          supplied. Nothing here is a matter to put to the taxpayer.
        </div>
      ) : (
        <>
          <div className="exposure">
            <div className="exp">
              <span className="exp-l">Output VAT understated</span>
              <b>{sar(e.increases_output)}</b>
            </div>
            <div className="exp">
              <span className="exp-l">Input VAT not recoverable</span>
              <b>{sar(e.disallows_input)}</b>
            </div>
            <div className="exp total">
              <span className="exp-l">Proposed adjustment</span>
              <b>{sar(e.total)}</b>
            </div>
            {!!e.documentation_at_risk && (
              <div className="exp">
                <span className="exp-l" title="Documentation defects on evidence that is not already producing an adjustment. Not part of the proposed adjustment.">
                  Documentation at risk
                </span>
                <b className="muted">{sar(e.documentation_at_risk)}</b>
              </div>
            )}
          </div>

          <div className="findings">
            {groups.map((g) => {
              const [head, ...rest] = g.items;
              return (
                <div className="finding" key={g.basis}>
                  <div className="f-top">
                    <span className={"pill " + EFFECT_PILL[head.effect]}>
                      {EFFECT_LABEL[head.effect]}
                    </span>
                    <span className="rc">{head.code}</span>
                    {!!head.amount && <b className="f-amt">{sar(head.amount)}</b>}
                  </div>
                  <div className="f-statement">{head.statement}</div>
                  <div className="f-why">
                    <span className="k">Established because</span> {head.explanation}
                  </div>
                  {rest.length > 0 && (
                    <div className="f-also">
                      <span className="k">The same matter also reads as</span>
                      <ul>
                        {rest.map((r) => (
                          <li key={r.code}>
                            <span className="rc">{r.code}</span> {r.statement}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  <div className="f-agent">
                    Raised by {head.agent} · {head.hypothesis_id}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="panel-note">
            <span className="ct">∑ computed</span> Each statement is the Authority's own wording,
            selected by an agent and confirmed by a deterministic test. Where several statements
            describe one piece of evidence the amount is shown once — they are readings of a
            single matter, not separate amounts.
          </div>
        </>
      )}
    </div>
  );
}
