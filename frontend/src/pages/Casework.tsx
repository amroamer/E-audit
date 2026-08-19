import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import CaseTabs from "../components/CaseTabs";
import VerifyBadge from "../components/VerifyBadge";
import {
  demoResponseFileUrl,
  getFollowup,
  getLoop,
  getPlan,
  issueRound,
  openRound,
  recheck,
  uploadDocument,
  type Draft,
  type Gap,
  type LoopRound,
  type LoopState,
  type RequestPlan,
} from "../api";

const GAP_LABEL: Record<string, string> = {
  "missing-item": "Nothing supplied",
  "wrong-document": "Wrong document",
  "missing-column": "Missing column",
  "empty-mandatory-field": "Blank mandatory field",
  "wrong-period": "Period not covered",
  "arithmetic-mismatch": "Does not add up",
  "wrong-format": "Wrong format",
  "unrequested-document": "Not requested",
  "too-vague": "Too vague",
};

const ITEM_STATUS: Record<string, string> = {
  outstanding: "pri-high",
  received: "pri-medium",
  satisfied: "pri-low",
  waived: "",
};

function GapList({ gaps }: { gaps: Gap[] }) {
  if (!gaps.length)
    return <p className="muted">Nothing outstanding — the response meets the request.</p>;
  const grouped = gaps.reduce<Record<string, Gap[]>>((acc, g) => {
    const k = g.item_label || "Other";
    (acc[k] = acc[k] || []).push(g);
    return acc;
  }, {});
  return (
    <div className="gaps">
      {Object.entries(grouped).map(([label, list]) => (
        <div key={label} className="gapgroup">
          <h4>{label}</h4>
          {list.map((g, i) => (
            <div key={i} className={"gap " + g.severity}>
              <span className={"pill " + (g.severity === "blocking" ? "pri-high" : "pri-medium")}>
                {GAP_LABEL[g.kind] || g.kind}
              </span>
              <div>
                <p>{g.detail}</p>
                {g.citation && <small className="mono">{g.citation}</small>}
                {g.source === "claude" && <span className="chip-ai">AI</span>}
              </div>
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

function Letter({ draft, title }: { draft: Draft; title: string }) {
  const [copied, setCopied] = useState(false);
  if (!draft?.text) return null;
  return (
    <div className="panel">
      <div className="panel-head">
        <div className="ai-h">
          <span className="ai-chip">AI</span>
          <h2>{title}</h2>
        </div>
        <div className="chips">
          <VerifyBadge source={draft.source === "none" ? null : draft.source} violations={draft.violations} />
          <button
            className="btn small"
            onClick={() => {
              navigator.clipboard?.writeText(draft.text);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
          >
            {copied ? "Copied" : "Copy"}
          </button>
        </div>
      </div>
      <div className="panel-body">
        <pre className="letterpre">{draft.text}</pre>
        <p className="detail-note">
          A draft for the auditor to edit and approve. Nothing is sent from here. Every figure in
          the letter was established by the engine — the model may repeat one and may not
          introduce one.
        </p>
      </div>
    </div>
  );
}

/** Stages 2 and 3 — plan the request, chase the response, and see the gaps.
 *
 *  This is the loop the auditors described as their longest delay and heaviest administrative
 *  burden: a request goes out, something incomplete comes back, and comparing the two by hand
 *  starts another round trip measured in weeks. The round counter at the top is the metric
 *  that matters; everything on this page exists to keep it at one.
 */
export default function Casework() {
  const { id = "" } = useParams();
  const [plan, setPlan] = useState<RequestPlan | null>(null);
  const [loop, setLoop] = useState<LoopState | null>(null);
  const [followup, setFollowup] = useState<Draft | null>(null);
  const [busy, setBusy] = useState("");
  const [err, setErr] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);
  const [target, setTarget] = useState<number | undefined>(undefined);

  const refreshFollowup = useCallback(
    (state: LoopState | null) => {
      if (state && state.round > 0 && state.blocking > 0) {
        getFollowup(id).then(setFollowup).catch(() => setFollowup(null));
      } else {
        setFollowup(null);
      }
    },
    [id],
  );

  useEffect(() => {
    setPlan(null);
    setLoop(null);
    setFollowup(null);
    setErr("");
    getPlan(id).then(setPlan).catch((e) => setErr(String(e)));
    getLoop(id)
      .then((s) => {
        setLoop(s);
        refreshFollowup(s);
      })
      .catch((e) => setErr(String(e)));
  }, [id, refreshFollowup]);

  const run = async (label: string, fn: () => Promise<LoopState>) => {
    setBusy(label);
    setErr("");
    try {
      const s = await fn();
      setLoop(s);
      refreshFollowup(s);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy("");
    }
  };

  const onFile = async (f: File | null) => {
    if (!f) return;
    await run("upload", () => uploadDocument(id, f, target));
    if (fileRef.current) fileRef.current.value = "";
  };

  const current: LoopRound | undefined = loop?.rounds[loop.rounds.length - 1];
  const started = (loop?.round ?? 0) > 0;

  return (
    <>
      <header className="page-head">
        <div>
          <h1>Casework</h1>
          <p className="sub">
            {id} · what we asked for, what arrived, and what is still missing
          </p>
        </div>
        {started && (
          <div className="chips">
            <span className={"pill " + (loop!.complete ? "pri-low" : "pri-high")}>
              Round {loop!.round}
            </span>
            <span className="pill">{loop!.status}</span>
            {!loop!.complete && (
              <span className="pill pri-high">{loop!.blocking} blocking</span>
            )}
          </div>
        )}
      </header>

      <CaseTabs id={id} />
      {err && <p className="error">{err}</p>}

      {/* ---------------------------------------------- the plan */}
      {plan && (
        <div className="panel">
          <div className="panel-head">
            <div className="ai-h">
              <span className="chip-det">Deterministic</span>
              <h2>What to ask for</h2>
            </div>
            <span className="sub">{plan.items.length} items · {plan.dropped.length} dropped</span>
          </div>
          <div className="panel-body">
            {plan.notes.map((n, i) => (
              <p key={i} className="detail-note" style={i === 0 ? { marginTop: 0 } : undefined}>
                {n}
              </p>
            ))}

            <h4>Requesting</h4>
            <div className="planlist">
              {plan.items.map((p) => (
                <div key={p.key} className="planitem">
                  <div className="pi-head">
                    <b>{p.label}</b>
                    <span className="pill">{p.kind}</span>
                    {p.decisive_rate != null && (
                      <span className="pill pri-low">{p.decisive_rate}% decisive</span>
                    )}
                  </div>
                  <p className="sub">{p.reason}</p>
                  {p.required_columns.length > 0 && (
                    <p className="cols">
                      <span className="k">{p.required_columns.length} columns</span>
                      {p.required_columns.map((c) => (
                        <code key={c}>{c}</code>
                      ))}
                    </p>
                  )}
                </div>
              ))}
            </div>

            {plan.dropped.length > 0 && (
              <>
                <h4>Not requesting</h4>
                <div className="planlist">
                  {plan.dropped.map((p) => (
                    <div key={p.key} className="planitem dropped">
                      <div className="pi-head">
                        <b>{p.label}</b>
                      </div>
                      <p className="sub">{p.reason}</p>
                    </div>
                  ))}
                </div>
                <p className="detail-note">
                  The auditors do not request information the Authority already holds. Here that is
                  mechanical rather than remembered — and the reason stays visible, so the decision
                  can be checked rather than trusted.
                </p>
              </>
            )}

            {!started && (
              <div className="actions">
                <button
                  className="btn primary"
                  disabled={!!busy}
                  onClick={() => run("open", () => openRound(id))}
                >
                  {busy === "open" ? "Drafting…" : "Draft the request"}
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ---------------------------------------------- the rounds */}
      {loop?.rounds.map((r) => (
        <div key={r.seq} className="panel">
          <div className="panel-head">
            <h2>Round {r.seq}</h2>
            <div className="chips">
              <span className={"pill " + (r.status === "satisfied" ? "pri-low" : "pri-medium")}>
                {r.status}
              </span>
              {r.issued_at && <span className="sub">issued {r.issued_at}</span>}
              {r.answered_at && <span className="sub">answered {r.answered_at}</span>}
            </div>
          </div>
          <div className="panel-body">
            <div className="tablescroll">
              <table className="inv-table">
                <thead>
                  <tr>
                    <th style={{ width: 34 }}>#</th>
                    <th>Requested</th>
                    <th>Format</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {r.items.map((it) => (
                    <tr key={it.id}>
                      <td className="mono">{it.seq}</td>
                      <td>
                        <b>{it.label}</b>
                        {it.required_columns.length > 0 && (
                          <div className="sub">
                            {it.required_columns.length} columns:{" "}
                            {it.required_columns.join(", ")}
                          </div>
                        )}
                      </td>
                      <td className="mono">{it.expected_format || "—"}</td>
                      <td>
                        <span className={"pill " + (ITEM_STATUS[it.status] || "")}>
                          {it.status}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {r.status === "draft" && (
              <div className="actions">
                <button
                  className="btn primary"
                  disabled={!!busy}
                  onClick={() => run("issue", () => issueRound(id, r.seq))}
                >
                  {busy === "issue" ? "Issuing…" : "Approve and issue"}
                </button>
              </div>
            )}

            {r.seq === loop.round && (
              <>
                <h4>What arrived</h4>
                {loop.documents.filter((doc) => doc.round === r.seq).length === 0 ? (
                  <p className="muted">Nothing received for this round yet.</p>
                ) : (
                  <div className="tablescroll">
                    <table className="inv-table">
                      <thead>
                        <tr>
                          <th>File</th>
                          <th>Answers</th>
                          <th style={{ textAlign: "right" }}>Rows</th>
                          <th>Columns found</th>
                          <th>Covers</th>
                        </tr>
                      </thead>
                      <tbody>
                        {loop.documents
                          .filter((doc) => doc.round === r.seq)
                          .map((doc) => (
                            <tr key={doc.id} className={doc.superseded ? "dim" : ""}>
                              <td className="mono">
                                {doc.filename}
                                {doc.superseded && (
                                  <span className="sub"> · superseded</span>
                                )}
                              </td>
                              <td className="sub">
                                {r.items.find((i) => i.id === doc.request_item_id)?.label ||
                                  "not linked"}
                              </td>
                              <td className="mono" style={{ textAlign: "right" }}>
                                {doc.row_count || "—"}
                              </td>
                              <td className="sub">
                                {doc.raw_headers.length
                                  ? doc.raw_headers.join(", ")
                                  : doc.note || "—"}
                              </td>
                              <td className="mono sub">
                                {doc.period_from
                                  ? `${doc.period_from} → ${doc.period_to}`
                                  : "—"}
                              </td>
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                )}

                {r.status !== "draft" && (
                  <div className="uploadbar">
                    <select
                      value={target ?? ""}
                      onChange={(e) =>
                        setTarget(e.target.value ? Number(e.target.value) : undefined)
                      }
                    >
                      <option value="">Answers which item?</option>
                      {r.items.map((it) => (
                        <option key={it.id} value={it.id}>
                          {it.label}
                        </option>
                      ))}
                    </select>
                    <input
                      ref={fileRef}
                      type="file"
                      accept=".xlsx,.xlsm,.csv,.pdf"
                      disabled={!!busy}
                      onChange={(e) => onFile(e.target.files?.[0] ?? null)}
                    />
                    <button
                      className="btn"
                      disabled={!!busy}
                      onClick={() => run("check", () => recheck(id))}
                    >
                      {busy === "check" ? "Checking…" : "Re-run checks"}
                    </button>
                    <a className="btn small" href={demoResponseFileUrl}>
                      Download the demo response
                    </a>
                  </div>
                )}

                <h4>
                  Requested versus received
                  {r.gaps.length > 0 && <span className="sub"> · {r.gaps.length} findings</span>}
                </h4>
                <GapList gaps={r.gaps} />
                <p className="detail-note">
                  Column presence, blank mandatory fields, period coverage and whether the stated
                  totals add up are checks, not judgement — they run deterministically, with no
                  model involved. A column the taxpayer named differently is resolved, not
                  reported: flagging &ldquo;Invoice No.&rdquo; as missing would put a false
                  accusation in the letter below.
                </p>
              </>
            )}

            {r.body && r.seq !== loop.round && (
              <details className="drill">
                <summary>The letter sent in round {r.seq}</summary>
                <pre className="letterpre">{r.body}</pre>
              </details>
            )}
          </div>
        </div>
      ))}

      {current?.body && current.seq === loop?.round && (
        <Letter
          draft={{ text: current.body, source: current.body_source as Draft["source"] }}
          title={`Round ${current.seq} — information request`}
        />
      )}
      {followup && <Letter draft={followup} title="Follow-up — outstanding items only" />}

      {loop?.complete && started && (
        <div className="callout ok">
          <b>The response meets the request.</b> Nothing blocking remains, so the substantive
          review can open — see the Reconciliation tab.
        </div>
      )}
    </>
  );
}
