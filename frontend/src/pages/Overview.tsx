import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listCases, getOverview, getScope, reseedDemo, type CaseRow, type ExecOverview, type ScopeCard } from "../api";

const money = (n: number) =>
  n >= 1e6 ? `SAR ${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `SAR ${Math.round(n / 1e3)}K` : `SAR ${Math.round(n)}`;

export default function Overview() {
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [ov, setOv] = useState<ExecOverview | null>(null);
  const [scope, setScope] = useState<ScopeCard | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [resetState, setResetState] = useState<"idle" | "confirm" | "busy">("idle");
  const nav = useNavigate();

  const load = () => {
    listCases().then(setCases).catch((e) => setErr(String(e)));
    getOverview().then(setOv).catch(() => {});
    getScope().then(setScope).catch(() => {});
  };
  useEffect(load, []);

  const reset = async () => {
    if (resetState === "idle") {
      setResetState("confirm");
      return;
    }
    if (resetState !== "confirm") return;
    setResetState("busy");
    setOv(null);
    setCases([]);
    try {
      await reseedDemo();
      load();
    } catch (e) {
      setErr(String(e));
    } finally {
      setResetState("idle");
    }
  };

  const tiles = ov
    ? [
        {
          n: money(ov.exposure_total),
          l: "Output-VAT exposure surfaced",
          note: `${ov.findings} potential finding${ov.findings === 1 ? "" : "s"}`,
        },
        {
          n: money(ov.difference_total),
          l: "Differences to account for",
          note: "expected vs declared, across open cases",
        },
        {
          n: `${Math.round(ov.auto_clearable_pct * 100)}%`,
          l: "Cases clearable with zero taxpayer contact",
          note: `${ov.auto_clearable} of ${ov.open_cases} open cases`,
        },
        {
          n: String(ov.needs_action),
          l: "Cases needing auditor action",
          note: `${ov.findings} finding${ov.findings === 1 ? "" : "s"} · ${ov.to_review} to review`,
        },
      ]
    : [];

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Command deck</p>
          <h1>Overview</h1>
        </div>
        <button
          className={"btn-ghost" + (resetState === "confirm" ? " confirm" : "")}
          onClick={reset}
          disabled={resetState === "busy"}
          title="Restore the demo to its seeded state"
        >
          {resetState === "busy" ? "Resetting…" : resetState === "confirm" ? "Confirm reset?" : "↻ Reset demo"}
        </button>
      </div>

      <div className="tiles">
        {tiles.map((t) => (
          <div className="tile" key={t.l}>
            <div className="tn">{t.n}</div>
            <div className="tl">{t.l}</div>
            <div className="tnote">{t.note}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Flagged cases</h2>
          <span className="muted">Sorted by composite priority — exposure · deadline · history · quick-win</span>
        </div>
        {err && (
          <div className="notice err">
            Backend not reachable — start the API (<code>uvicorn app.main:app</code>) and seed the demo data
            (<code>python -m app.seed.seed</code>).
          </div>
        )}
        {!err && cases.length === 0 && (
          <div className="notice">
            No cases yet. Seed the demo data with <code>python -m app.seed.seed</code>.
          </div>
        )}
        {cases.length > 0 && (
          <div className="tablescroll">
            <table>
              <thead>
                <tr>
                  <th>Priority</th>
                  <th>Case</th>
                  <th>Taxpayer</th>
                  <th>Sector</th>
                  <th>Referral reason</th>
                  <th>Deadline</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => (
                  <tr key={c.case_id} className="rowlink" onClick={() => nav(`/cases/${c.case_id}`)}>
                    <td>
                      <span
                        className={"pscore pri-" + c.priority.band}
                        title={`Exposure ${Math.round(c.priority.signals.exposure * 40)}/40 · Deadline ${Math.round(
                          c.priority.signals.deadline * 30,
                        )}/30 · History ${Math.round(c.priority.signals.history * 20)}/20 · Quick-win ${Math.round(
                          c.priority.signals.quickwin * 10,
                        )}/10`}
                      >
                        {c.priority.score}
                      </span>
                      <div className="sub">{c.priority.driver}</div>
                    </td>
                    <td className="mono">{c.case_id}</td>
                    <td>
                      {c.taxpayer}
                      <div className="sub mono">{c.vat_no}</div>
                    </td>
                    <td>{c.sector}</td>
                    <td>
                      <code>{c.reason}</code>
                    </td>
                    <td className="mono">
                      {c.priority.deadline_days == null
                        ? "—"
                        : c.priority.deadline_days < 0
                          ? "past due"
                          : `${c.priority.deadline_days}d`}
                    </td>
                    <td>
                      <span className="pill status">{c.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {scope && (
        <div className="panel">
          <div className="panel-head">
            <h2>What this PoC covers</h2>
            <span className="muted">and what it deliberately leaves out</span>
          </div>
          <div className="ai-body">
            <p className="detail-note">{scope.headline}</p>
            <div className="scope-grid">
              <div className="scope-col">
                <h4>In scope</h4>
                <ul className="scope-list">
                  {scope.in_scope.map((s) => (
                    <li key={s.item}>
                      <b>{s.item}</b>
                      <span className="sub">{s.detail}</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="scope-col">
                <h4>Out of scope — and where each one belongs</h4>
                <ul className="scope-list">
                  {scope.out_of_scope.map((s) => (
                    <li key={s.item}>
                      <span className="rc" title={s.reason_label}>
                        {s.reason_code}
                      </span>{" "}
                      <b>{s.item}</b>
                      <span className="sub">{s.note}</span>
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <p className="detail-note" style={{ margin: 0 }}>
              {scope.tax_point_note}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
