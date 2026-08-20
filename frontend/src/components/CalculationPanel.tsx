import { useEffect, useState } from "react";
import {
  askCalc, checkCalc, deleteCalc, listCalcs,
  type AuditorCalculation, type CalcAnswer, type CalcListing,
} from "../api";

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 2 });

const STATUS_PILL: Record<string, string> = {
  agree: "pri-low",
  disagree: "pri-high",
  "not-checkable": "pri-medium",
  ok: "pri-low",
};

/** The auditor's arithmetic: ask for a figure, or have one you worked out checked.
 *
 *  The model reads the described method into a query; Python computes the number. That split is
 *  the whole point — a verification agent that could hallucinate a total would be worse than no
 *  agent at all. Without a key the auditor picks the operation and column themselves and the
 *  same executor runs, which is why this works with no credentials. */
export default function CalculationPanel({ id, onChanged }: { id?: string; onChanged?: () => void }) {
  const [d, setD] = useState<CalcListing | null>(null);
  const [tab, setTab] = useState<"check" | "ask">("check");
  const [busy, setBusy] = useState(false);

  // check
  const [label, setLabel] = useState("");
  const [method, setMethod] = useState("");
  const [stated, setStated] = useState("");
  const [doc, setDoc] = useState("");
  const [op, setOp] = useState("sum");
  const [column, setColumn] = useState("");

  // ask
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState<CalcAnswer | null>(null);

  const load = () => { if (id) listCalcs(id).then(setD).catch(() => {}); };
  useEffect(load, [id]);

  const columns = d?.documents.find((x) => x.filename === doc)?.columns ?? [];
  // With no key the method cannot be parsed, so the auditor's own choice of operation and
  // column is the query. Sent whenever they have made one — it is never a guess.
  const spec = () =>
    op && (op === "count" || column)
      ? { op, column: op === "count" ? "" : column, document: doc }
      : undefined;

  const runCheck = async () => {
    if (!id || !label.trim() || !stated) return;
    setBusy(true);
    try {
      await checkCalc(id, {
        label: label.trim(), method: method.trim(), stated_amount: Number(stated),
        document_name: doc, spec: spec(),
      });
      setLabel(""); setMethod(""); setStated("");
      load();
      onChanged?.();
    } finally { setBusy(false); }
  };

  const runAsk = async () => {
    if (!id || (!question.trim() && !spec())) return;
    setBusy(true);
    setAnswer(null);
    try { setAnswer(await askCalc(id, question.trim(), spec())); }
    finally { setBusy(false); }
  };

  const remove = async (calcId: number) => {
    if (!id) return;
    await deleteCalc(id, calcId);
    load();
    onChanged?.();
  };

  const docPicker = (
    <select className="letter-input calc-select" value={doc} onChange={(e) => { setDoc(e.target.value); setColumn(""); }}>
      <option value="">Which document?</option>
      {d?.documents.map((x) => (
        <option key={x.filename} value={x.filename}>
          {x.filename} ({x.row_count} rows)
        </option>
      ))}
    </select>
  );

  const queryPicker = (
    <div className="calc-query">
      <select className="letter-input calc-select" value={op} onChange={(e) => setOp(e.target.value)}>
        <option value="sum">sum</option>
        <option value="count">count rows</option>
        <option value="count_distinct">count distinct</option>
        <option value="average">average</option>
        <option value="max">max</option>
        <option value="min">min</option>
      </select>
      {op !== "count" && (
        <select className="letter-input calc-select" value={column} onChange={(e) => setColumn(e.target.value)} disabled={!doc}>
          <option value="">of which column?</option>
          {columns.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      )}
    </div>
  );

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Your calculations</h2>
        <span className="pill status" title="The method is parsed into a query; Python computes the figure. The model never does arithmetic.">
          ∑ Recomputed from source
        </span>
      </div>

      {!d?.documents.length ? (
        <div className="panel-note">
          <span className="ct">∑ computed</span> Upload the documents the taxpayer sent and this
          will check any figure you work out against them.
        </div>
      ) : (
        <>
          <div className="calc-tabs">
            <button className={"calc-tab" + (tab === "check" ? " on" : "")} onClick={() => setTab("check")}>
              Check a figure I calculated
            </button>
            <button className={"calc-tab" + (tab === "ask" ? " on" : "")} onClick={() => setTab("ask")}>
              Ask for a figure
            </button>
          </div>

          {tab === "check" ? (
            <div className="calc-form">
              <input className="letter-input" placeholder="What did you calculate? (e.g. total output VAT on the sales listing)"
                     value={label} onChange={(e) => setLabel(e.target.value)} />
              <textarea className="letter-input" rows={2}
                        placeholder="How did you calculate it? (e.g. summed the VAT column for invoices dated in the quarter)"
                        value={method} onChange={(e) => setMethod(e.target.value)} />
              <div className="calc-row">
                <input className="letter-input" type="number" placeholder="The figure you got (SAR)"
                       value={stated} onChange={(e) => setStated(e.target.value)} />
                {docPicker}
              </div>
              {queryPicker}
              <button className="btn" disabled={busy || !label.trim() || !stated} onClick={runCheck}>
                {busy ? "Checking…" : "Check it against the documents"}
              </button>
            </div>
          ) : (
            <div className="calc-form">
              <input className="letter-input" placeholder="What do you want to know? (e.g. how many invoices did they send?)"
                     value={question} onChange={(e) => setQuestion(e.target.value)} />
              <div className="calc-row">{docPicker}</div>
              {queryPicker}
              <button className="btn" disabled={busy} onClick={runAsk}>
                {busy ? "Computing…" : "Compute it"}
              </button>
              {answer && (
                <div className={"calc-answer " + (answer.status === "ok" ? "ok" : "warn")}>
                  {answer.status === "ok" ? (
                    <>
                      <b>{answer.answer?.toLocaleString("en-US", { maximumFractionDigits: 2 })}</b>
                      <div className="sub">
                        {answer.detail && "query" in answer.detail
                          ? `${answer.detail.query} over ${answer.detail.matched} of ${answer.detail.scanned} rows in ${answer.detail.document}`
                          : null}
                      </div>
                    </>
                  ) : (
                    <div className="sub">{answer.note}</div>
                  )}
                </div>
              )}
            </div>
          )}

          {!!d.calculations.length && (
            <div className="calc-list">
              {d.calculations.map((c: AuditorCalculation) => (
                <div className="calc-item" key={c.id}>
                  <div className="calc-item-top">
                    <span className={"pill " + (STATUS_PILL[c.status] || "status")}>
                      {c.status.replace(/-/g, " ")}
                    </span>
                    <b>{c.label}</b>
                    <button className="linklike" onClick={() => remove(c.id)}>remove</button>
                  </div>
                  <div className="calc-figures">
                    <span><span className="k">You recorded</span> {sar(c.stated)}</span>
                    {c.computed !== null && (
                      <span><span className="k">Recomputed</span> {sar(c.computed)}</span>
                    )}
                    {!!c.delta && <span className="calc-delta"><span className="k">Difference</span> {sar(c.delta)}</span>}
                  </div>
                  <div className="sub">{c.explanation}</div>
                  {c.query && <div className="sub"><span className="k">Checked</span> <code>{c.query}</code></div>}
                </div>
              ))}
            </div>
          )}

          <div className="panel-note">
            <span className="ct">∑ computed</span> Every figure here is recomputed from the
            uploaded rows in Python. A method that cannot be reproduced is reported as such
            rather than approximated by a calculation answering a different question.
          </div>
        </>
      )}
    </div>
  );
}
