import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import CaseTabs from "../components/CaseTabs";
import LifecycleRail from "../components/LifecycleRail";
import {
  getDossier, getLoop, parseRequestEmail, uploadDocument,
  type Dossier, type LoopState, type ParsedRequest,
} from "../api";

const SAMPLE_EMAIL = `Dear Sir/Madam,

Further to our review of your VAT position for Q1 2025, please provide the following
within 20 working days:

1. A detailed sales analysis for the period, with the following columns: invoice date,
   invoice number, customer name, customer VAT number, description, taxable amount,
   VAT rate and VAT amount.
2. A detailed purchases analysis on which input VAT was claimed.
3. The trial balance as at 31 March 2025.
4. Copies of the tax invoices for the ten largest purchases.

Yours faithfully,
Zakat, Tax and Customs Authority`;

/* ---------------------------------------------------------------- who we are dealing with */
/** The registration and the audit record, and nothing else.
 *
 *  The wider taxpayer 360 is out of scope now that planning is: these two blocks stay because
 *  the work needs them. Undisclosed secondary-activity revenue is undetectable without the
 *  registered activity list, and a repeat of a prior root cause is the first thing to check. */
function CaseContext({ d }: { d: Dossier }) {
  const tp = d.taxpayer;
  const h = tp.audit_history;
  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Who you are dealing with</h2>
        <span className="pill status">∑ From the registration</span>
      </div>
      <div className="ctx">
        <div className="ctx-block">
          <h4>Registered activities</h4>
          {tp.activities?.length ? (
            <ul className="acts">
              {tp.activities.map((a) => (
                <li key={a.isic}>
                  <span className="rc">{a.isic}</span> {a.description}
                  {a.primary && <span className="pill status">primary</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted">No economic activities are recorded on the registration.</p>
          )}
          <p className="detail-note">
            Revenue described in terms that match none of these is a secondary activity the
            return may not disclose — which is why the list is here and not in the dossier.
          </p>
        </div>

        <div className="ctx-block">
          <h4>Audit history</h4>
          {h.closed_cases ? (
            <>
              <div className="kv2">
                <div><span className="k">Closed cases</span>{h.closed_cases}</div>
                <div><span className="k">Findings</span>{h.findings}</div>
                <div>
                  <span className="k">Total assessed</span>
                  SAR {Math.abs(h.total_assessed).toLocaleString("en-US", { maximumFractionDigits: 0 })}
                </div>
                <div><span className="k">Last outcome</span>{h.last_outcome || "—"}</div>
              </div>
              {!!h.root_causes?.length && (
                <div className="causes">
                  <span className="k">Root causes previously found</span>
                  {h.root_causes.map((c) => <span className="rc" key={c}>{c}</span>)}
                </div>
              )}
            </>
          ) : (
            <p className="muted">This taxpayer has not been audited before.</p>
          )}
        </div>

        <div className="ctx-block">
          <h4>Registration</h4>
          <div className="kv2">
            <div><span className="k">Sector</span>{tp.sector}</div>
            <div><span className="k">Size</span>{tp.size}</div>
            <div><span className="k">Registered</span>{tp.registered_from || "—"}</div>
            <div><span className="k">Accounting</span>{tp.accounting_method}</div>
            <div><span className="k">POS registered</span>{tp.pos_registered ? "yes" : "no"}</div>
            <div><span className="k">Branches</span>{tp.branches}</div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------- what we asked for, from the email */
function RequestEmail({ id }: { id: string }) {
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParsedRequest | null>(null);
  const [keep, setKeep] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [confirmed, setConfirmed] = useState(false);

  const run = async () => {
    if (!text.trim()) return;
    setBusy(true);
    setConfirmed(false);
    try {
      const p = await parseRequestEmail(id, text);
      setParsed(p);
      setKeep(new Set(p.items.map((i) => i.key)));
    } finally { setBusy(false); }
  };

  const toggle = (key: string) => {
    const next = new Set(keep);
    next.has(key) ? next.delete(key) : next.add(key);
    setKeep(next);
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>What you asked for</h2>
        <span className="pill status" title="Read from your own email. The parse is a proposal you confirm before anything is checked against it.">
          ∑ Recovered from the email
        </span>
      </div>
      <div className="panel-body">
        <p className="detail-note" style={{ marginTop: 0 }}>
          Paste the email you sent the taxpayer. It becomes the specification the response is
          checked against — so nothing binds until you have confirmed the reading below.
        </p>
        <textarea className="letter-input" rows={8} value={text}
                  placeholder="Paste the request email here…"
                  onChange={(e) => setText(e.target.value)} />
        <div className="row-actions">
          <button className="btn" disabled={busy || !text.trim()} onClick={run}>
            {busy ? "Reading…" : "Read the email"}
          </button>
          <button className="linklike" onClick={() => setText(SAMPLE_EMAIL)}>use a sample</button>
        </div>

        {parsed && (
          <>
            <div className="parsed-head">
              <b>{parsed.items.length} item(s) recognised</b>
              {parsed.period_from && (
                <span className="sub">
                  Period read as {parsed.period_from} to {parsed.period_to}
                </span>
              )}
              {parsed.due_phrase && <span className="sub">Due: {parsed.due_phrase}</span>}
            </div>

            {parsed.items.map((i) => (
              <label className={"parsed-item" + (keep.has(i.key) ? " on" : "")} key={i.key}>
                <input type="checkbox" checked={keep.has(i.key)} onChange={() => toggle(i.key)} />
                <div>
                  <b>{i.label}</b>
                  {i.confidence === "low" && <span className="pill pri-medium">check this one</span>}
                  <div className="sub">
                    matched on “{i.cue}” · {i.required_columns.length} required column(s)
                  </div>
                  {!!i.required_columns.length && (
                    <div className="cols">
                      {i.required_columns.map((c) => <span className="ct" key={c}>{c}</span>)}
                    </div>
                  )}
                </div>
              </label>
            ))}

            {!!parsed.unmatched.length && (
              <div className="callout warn">
                <b>Could not be placed.</b> These asks did not match anything in the catalogue,
                so they were not guessed into an item:
                <ul>{parsed.unmatched.map((u, n) => <li key={n}>{u}</li>)}</ul>
              </div>
            )}

            <div className="row-actions">
              <button className="btn" disabled={!keep.size} onClick={() => setConfirmed(true)}>
                Confirm {keep.size} item(s) as the request
              </button>
              {confirmed && <span className="pill pri-low">Confirmed</span>}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/* --------------------------------------------------------------------- the received files */
function Uploads({ id, onUploaded }: { id: string; onUploaded: () => void }) {
  const [loop, setLoop] = useState<LoopState | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => { getLoop(id).then(setLoop).catch(() => {}); }, [id]);
  useEffect(load, [load]);

  const send = async (files: FileList | null) => {
    if (!files?.length) return;
    setBusy(true);
    setErr("");
    try {
      for (const f of Array.from(files)) await uploadDocument(id, f);
      load();
      onUploaded();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Upload failed.");
    } finally { setBusy(false); }
  };

  // Superseded uploads are history, not evidence — a corrected resubmission replaces the file
  // it corrects, and listing both would suggest two documents arrived when one did.
  const received = (loop?.documents ?? []).filter((doc) => !doc.superseded);

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Documents received</h2>
        <span className="pill status">
          {received.length ? `${received.length} on file` : "nothing yet"}
        </span>
      </div>
      <div className="panel-body">
        <div
          className={"dropzone" + (drag ? " over" : "")}
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
          onClick={() => fileRef.current?.click()}
        >
          <input ref={fileRef} type="file" multiple accept=".xlsx,.xlsm,.csv,.tsv"
                 style={{ display: "none" }}
                 onChange={(e) => send(e.target.files)} />
          <b>{busy ? "Reading…" : "Drop the taxpayer's spreadsheets here"}</b>
          <span className="sub">or click to choose — .xlsx, .xlsm, .csv</span>
        </div>
        {err && <div className="callout warn">{err}</div>}

        {!!received.length && (
          <div className="doclist">
            {received.map((doc) => (
              <div className="docrow" key={doc.id}>
                <b>{doc.filename}</b>
                <span className="sub">
                  {doc.row_count} rows · {doc.columns?.length ?? 0} columns
                </span>
                {!!doc.columns?.length && (
                  <div className="cols">
                    {doc.columns.map((c: string) => <span className="ct" key={c}>{c}</span>)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        <p className="detail-note">
          Each file is read into columns and rows on arrival. Everything downstream — the
          completeness check, the agents and your own calculations — works from that reading.
        </p>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------------------ the page */
export default function Intake() {
  const { id = "" } = useParams();
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [rev, setRev] = useState(0);

  useEffect(() => {
    if (!id) return;
    getDossier(id).then(setDossier).catch(() => {});
  }, [id, rev]);

  return (
    <>
      <CaseTabs id={id} />
      <LifecycleRail id={id} />
      {dossier && <CaseContext d={dossier} />}
      <RequestEmail id={id} />
      <Uploads id={id} onUploaded={() => setRev((r) => r + 1)} />
    </>
  );
}
