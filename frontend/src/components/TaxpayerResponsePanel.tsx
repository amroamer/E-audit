import { useEffect, useState } from "react";
import { readLetter, type LetterExtraction } from "../api";

interface Resp {
  seq: number;
  code: string;
  label: string;
  amount: number;
  doc_name: string;
}

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

export default function TaxpayerResponsePanel({
  id,
  residual,
  onChanged,
}: {
  id?: string;
  residual: number;
  onChanged: () => void;
}) {
  const [list, setList] = useState<Resp[]>([]);
  const [label, setLabel] = useState("");
  const [amount, setAmount] = useState("");
  const [doc, setDoc] = useState("");
  const [busy, setBusy] = useState(false);
  const [letterText, setLetterText] = useState("");
  const [extraction, setExtraction] = useState<LetterExtraction | null>(null);
  const [analyzing, setAnalyzing] = useState(false);

  const load = () => {
    if (!id) return;
    fetch(`/api/cases/${id}/responses`)
      .then((r) => r.json())
      .then(setList)
      .catch(() => {});
  };
  useEffect(load, [id]);

  const add = async () => {
    if (!id || !label.trim() || !amount) return;
    setBusy(true);
    try {
      await fetch(`/api/cases/${id}/responses`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ label: label.trim(), amount: Number(amount), doc_name: doc.trim() }),
      });
      setLabel("");
      setAmount("");
      setDoc("");
      load();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const remove = async (seq: number) => {
    if (!id) return;
    setBusy(true);
    try {
      await fetch(`/api/cases/${id}/responses/${seq}`, { method: "DELETE" });
      load();
      onChanged();
    } finally {
      setBusy(false);
    }
  };

  const sample = () => {
    setLabel(
      "Sales ledger provided by the taxpayer shows the residual relates to prior-period invoices already declared in an earlier return.",
    );
    setAmount(String(Math.max(0, Math.round(residual))));
    setDoc("sales_ledger_Q1-2025.xlsx");
  };

  const analyze = async () => {
    if (!id || !letterText.trim()) return;
    setAnalyzing(true);
    setExtraction(null);
    try {
      setExtraction(await readLetter(id, letterText.trim()));
    } catch {
      /* leave extraction null on failure */
    } finally {
      setAnalyzing(false);
    }
  };

  const sampleLetter = () => {
    setLetterText(
      "Dear Sir/Madam,\n\nFurther to your enquiry regarding our Q1 2025 VAT return, we confirm that the " +
        "difference of SAR " +
        Math.max(0, Math.round(residual)).toLocaleString("en-US") +
        " between your reconstruction and our declared output VAT relates to standard-rated sales that were " +
        "invoiced and delivered in December 2024 and already declared in our prior-period (Q4 2024) return. " +
        "The clearance timestamps fell in early January 2025, which is why they appear in this period's e-invoice " +
        "data. Our sales ledger and the prior return are attached as supporting evidence.\n\nRegards,\nFinance Department",
    );
    setExtraction(null);
  };

  const useExtraction = () => {
    if (!extraction) return;
    setLabel(extraction.summary);
    setAmount(String(Math.max(0, Math.round(extraction.proposed_amount))));
    setDoc("taxpayer_letter.pdf");
  };

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Taxpayer response</h2>
        <span className="muted">
          record what the taxpayer supplied — the auditor confirms the amount, the AI only describes it
        </span>
      </div>
      <div className="ai-body">
        <div className="letter">
          <div className="letter-head">
            <span className="ai-chip">AI</span>
            <span className="muted">Paste a taxpayer letter or case note — AI drafts a response for you to confirm</span>
          </div>
          <textarea
            className="letter-input"
            placeholder="Paste the taxpayer's letter or a case note here…"
            value={letterText}
            onChange={(e) => setLetterText(e.target.value)}
            rows={4}
          />
          <div className="resp-actions">
            <button className="btn" disabled={analyzing || !letterText.trim()} onClick={analyze}>
              {analyzing ? "Reading…" : "Analyse with AI"}
            </button>
            <button className="linklike" onClick={sampleLetter} disabled={analyzing}>
              use sample letter
            </button>
          </div>
          {extraction && (
            <div className="extract-card">
              <div className="extract-top">
                <span className={"pill " + (extraction.explains_gap ? "pri-low" : "pri-medium")}>
                  {extraction.category.replace(/-/g, " ")}
                </span>
                <span className="muted">confidence: {extraction.confidence}</span>
                {extraction.source !== "claude" && <span className="muted">· {extraction.source}</span>}
              </div>
              <p className="extract-summary">{extraction.summary}</p>
              {extraction.quote && <blockquote className="extract-quote">“{extraction.quote}”</blockquote>}
              <div className="kv">
                <div>
                  <span className="k">Proposed amount (stated in the letter)</span>
                  <span className="v">
                    <b>{sar(extraction.proposed_amount)}</b>
                  </span>
                </div>
              </div>
              {extraction.caveat && <p className="extract-caveat">⚠ {extraction.caveat}</p>}
              {extraction.proposed_amount > 0 && (
                <button className="btn ghost-fill" onClick={useExtraction}>
                  Use this ↓ (fills the form to confirm)
                </button>
              )}
              <p className="extract-note">
                AI-extracted from the letter — a draft. Confirm or edit the amount below before recording.
              </p>
            </div>
          )}
          <div className="resp-divider">
            <span>then confirm &amp; record</span>
          </div>
        </div>
        {list.length > 0 && (
          <div className="resp-list">
            {list.map((r) => (
              <div className="resp-item" key={r.seq}>
                <div>
                  <span className="rc">{r.code}</span> {r.label}
                  {r.doc_name && <span className="sub"> · {r.doc_name}</span>}
                </div>
                <div className="resp-amt">
                  −{sar(r.amount)}
                  <button className="linklike" disabled={busy} onClick={() => remove(r.seq)}>
                    remove
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
        <div className="resp-form">
          <input
            placeholder="What the taxpayer provided (e.g. sales ledger showing the residual was already declared)"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
          />
          <div className="resp-row">
            <input
              type="number"
              placeholder="Amount it accounts for (SAR)"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
            />
            <input placeholder="Document name (optional)" value={doc} onChange={(e) => setDoc(e.target.value)} />
          </div>
          <div className="resp-actions">
            <button className="btn" disabled={busy || !label.trim() || !amount} onClick={add}>
              {busy ? "Regenerating…" : "Record response & regenerate"}
            </button>
            <button className="linklike" onClick={sample} disabled={busy}>
              use sample
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
