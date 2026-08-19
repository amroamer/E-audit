import { useEffect, useState } from "react";
import { getPrecedent, type PrecedentBriefing } from "../api";

const pct = (n: number) => `${n.toFixed(n % 1 ? 1 : 0)}%`;
const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

/** What comparable closed cases turned out to be, and what actually closed them.
 *
 *  This is the panel for the pain point the auditors put last and meant most: sector
 *  knowledge and lessons learned live in whichever auditor has seen enough cases. Every
 *  figure here is a count or a median taken in Python over labelled closed cases — no model
 *  is involved, which is why it renders with no API key and why the ranking is reproducible.
 */
export default function PrecedentPanel({ id }: { id: string }) {
  const [d, setD] = useState<PrecedentBriefing | null>(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    setD(null);
    setErr(false);
    getPrecedent(id).then(setD).catch(() => setErr(true));
  }, [id]);

  if (err) return null;
  if (!d)
    return (
      <div className="panel">
        <div className="panel-head">
          <h2>Precedent</h2>
        </div>
        <div className="panel-body">
          <span className="muted">Searching closed cases…</span>
        </div>
      </div>
    );

  const s = d.summary;
  const noFinding = s.outcomes.find((o) => o.key === "NO_FINDING");
  const finding = s.outcomes.find((o) => o.key === "FINDING");

  return (
    <div className="panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="chip-det">Deterministic</span>
          <h2>Precedent</h2>
        </div>
        <span className="sub">
          {s.comparable} comparable closed case{s.comparable === 1 ? "" : "s"}
          {s.widened && " · search widened"}
        </span>
      </div>

      <div className="panel-body">
        <p className="detail-note" style={{ marginTop: 0 }}>
          When the risk engine raised <b>{s.indicator_label}</b> before, on taxpayers of a similar
          sector, size and filing record:
        </p>

        {noFinding && finding && (
          <div className="outcome-bar" title={`${noFinding.count} no finding · ${finding.count} finding`}>
            <div className="ob-seg ob-clear" style={{ width: `${noFinding.pct}%` }}>
              {noFinding.pct >= 18 && <span>{pct(noFinding.pct)} no finding</span>}
            </div>
            <div className="ob-seg ob-finding" style={{ width: `${finding.pct}%` }}>
              {finding.pct >= 18 && <span>{pct(finding.pct)} finding</span>}
            </div>
          </div>
        )}

        <div className="prec-grid">
          <div>
            <h4>Where they were explained</h4>
            {s.explained_by.length === 0 && <p className="muted">None in the comparable set.</p>}
            <ul className="tally">
              {s.explained_by.slice(0, 4).map((r) => (
                <li key={r.key}>
                  <code>{r.key}</code>
                  <span className="meter">
                    <i style={{ width: `${r.pct}%` }} />
                  </span>
                  <b>{pct(r.pct)}</b>
                </li>
              ))}
            </ul>
          </div>
          <div>
            <h4>Where a finding was raised</h4>
            {s.caused_by.length === 0 && <p className="muted">None in the comparable set.</p>}
            <ul className="tally">
              {s.caused_by.slice(0, 4).map((r) => (
                <li key={r.key}>
                  <code>{r.key}</code>
                  <span className="meter">
                    <i className="warn" style={{ width: `${r.pct}%` }} />
                  </span>
                  <b>{pct(r.pct)}</b>
                </li>
              ))}
            </ul>
          </div>
        </div>

        <h4>What actually closed them</h4>
        <p className="detail-note" style={{ marginTop: 0 }}>
          Ranked by how often an item was the evidence that settled the case — not by how often it
          was asked for. An item requested every time and decisive rarely costs a round trip.
        </p>
        <div className="tablescroll">
          <table className="inv-table">
            <thead>
              <tr>
                <th>Evidence</th>
                <th style={{ textAlign: "right" }}>Requested in</th>
                <th style={{ textAlign: "right" }}>Decisive in</th>
                <th style={{ width: 110 }}>Hit rate</th>
              </tr>
            </thead>
            <tbody>
              {s.evidence.map((e) => (
                <tr key={e.key}>
                  <td>{e.label}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{e.requested}</td>
                  <td className="mono" style={{ textAlign: "right" }}>{e.decisive}</td>
                  <td>
                    <span className="meter">
                      <i style={{ width: `${e.decisive_rate}%` }} />
                    </span>
                    <span className="sub"> {pct(e.decisive_rate)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="prec-facts">
          {s.effort.median_rounds != null && (
            <div>
              <span className="k">Typical effort</span>
              <span className="v">
                {s.effort.median_rounds} rounds · {s.effort.median_days_to_close} days
              </span>
            </div>
          )}
          {s.effort.single_round_pct != null && (
            <div>
              <span className="k">Closed in one round</span>
              <span className="v">{pct(s.effort.single_round_pct)}</span>
            </div>
          )}
          {s.assessed.median != null && (
            <div>
              <span className="k">Median assessment</span>
              <span className="v">{sar(s.assessed.median)}</span>
            </div>
          )}
        </div>

        {s.recurrence && (
          <div className="callout warn">
            <b>This taxpayer is in the comparable set.</b>{" "}
            {s.recurrence.findings > 0 ? (
              <>
                {s.recurrence.cases} closed case{s.recurrence.cases === 1 ? "" : "s"},{" "}
                {s.recurrence.findings} with a finding ({s.recurrence.root_causes.join(", ")}) —{" "}
                {s.recurrence.case_ids.join(", ")}. Rule the earlier cause out first; if it applies
                again, the resolution is already on file.
              </>
            ) : (
              <>
                {s.recurrence.cases} closed case{s.recurrence.cases === 1 ? "" : "s"}, none of which
                resulted in a finding.
              </>
            )}
          </div>
        )}

        <details className="drill">
          <summary>The comparable cases ({s.matches.length} closest)</summary>
          <div className="tablescroll">
            <table className="inv-table">
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Sector · size</th>
                  <th>Why comparable</th>
                  <th>Outcome</th>
                  <th style={{ textAlign: "right" }}>Assessed</th>
                </tr>
              </thead>
              <tbody>
                {s.matches.map((m) => (
                  <tr key={m.case_id}>
                    <td className="mono">{m.case_id}</td>
                    <td>
                      {m.sector} <span className="sub">· {m.size}</span>
                    </td>
                    <td className="sub">{m.reasons.join(", ") || "indicator only"}</td>
                    <td>
                      <span className={"pill " + (m.result === "FINDING" ? "pri-high" : "pri-low")}>
                        {m.result === "FINDING" ? m.root_cause : "No finding"}
                      </span>
                    </td>
                    <td className="mono" style={{ textAlign: "right" }}>
                      {m.assessed ? sar(m.assessed) : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </div>
    </div>
  );
}
