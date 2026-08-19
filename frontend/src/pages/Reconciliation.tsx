import { useEffect, useState, type ReactNode } from "react";
import { useParams, Link } from "react-router-dom";
import TaxpayerBrief from "../components/TaxpayerBrief";
import AiNarration from "../components/AiNarration";
import NextBestAction from "../components/NextBestAction";
import AuditReport from "../components/AuditReport";
import InvestigationPanel from "../components/InvestigationPanel";
import CaseTabs from "../components/CaseTabs";
import TaxpayerResponsePanel from "../components/TaxpayerResponsePanel";

interface BridgeStep {
  seq: number;
  kind: string;
  rule: string | null;
  label: string;
  amount: number;
  running: number;
  detail?: Detail;
}
type Detail = Record<string, any>;
interface BoxResult {
  box: string;
  declared: number;
  reconstructed_gross: number;
  apparent_gap: number;
  explained_total: number;
  explained_pct: number | null;
  residual: number;
  materiality: number;
  band: string;
  state: string;
  bridge: BridgeStep[];
  invoices_considered: number;
  evidence_invoices: Detail[];
}
interface Combined {
  total_exposure: number;
  state: string;
  output_state: string;
  input_state: string;
  output_residual: number;
  input_residual: number;
  finding_boxes: string[];
}
interface Recon extends BoxResult {
  case_id: string;
  taxpayer: string;
  purchase?: BoxResult;
  combined?: Combined;
}
type Row = { title: string; rule?: string | null; kind: string; start: number; end: number; amount: number; detail?: Detail };

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });

const STATE_LABEL: Record<string, string> = {
  "potential-finding": "Potential finding",
  supported: "Supported — no finding",
  unresolved: "Unresolved",
};
const STATE_CLASS: Record<string, string> = {
  "potential-finding": "pri-high",
  supported: "pri-low",
  unresolved: "pri-medium",
};

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", h);
      document.body.style.overflow = "";
    };
  }, [onClose]);
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="modal-close" aria-label="Close" onClick={onClose}>
            ×
          </button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

function InvoiceTable({ invoices }: { invoices: Detail[] }) {
  if (!invoices?.length) return <p className="muted">No underlying invoices.</p>;
  return (
    <div className="tablescroll">
      <table className="inv-table">
        <thead>
          <tr>
            <th>Invoice UUID</th>
            <th>Type</th>
            <th>Issue</th>
            <th>Delivery</th>
            <th style={{ textAlign: "right" }}>Base</th>
            <th style={{ textAlign: "right" }}>VAT</th>
          </tr>
        </thead>
        <tbody>
          {invoices.map((iv) => (
            <tr key={iv.uuid}>
              <td className="mono">{iv.uuid}</td>
              <td>
                {iv.type}
                {iv.status !== "cleared" && <span className="sub"> · {iv.status}</span>}
              </td>
              <td className="mono">{iv.issue_date}</td>
              <td className="mono">{iv.delivery_date || "—"}</td>
              <td className="mono" style={{ textAlign: "right" }}>{sar(iv.base)}</td>
              <td className="mono" style={{ textAlign: "right" }}>{sar(iv.tax_amount)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DetailBody({ detail, amount }: { detail?: Detail; amount?: number }) {
  if (!detail) return <p className="muted">No further detail.</p>;
  const kv = (rows: [string, ReactNode][]) => (
    <div className="kv">
      {rows.map(([k, v]) => (
        <div key={k}>
          <span className="k">{k}</span>
          <span className="v">{v ?? "—"}</span>
        </div>
      ))}
    </div>
  );

  if (detail.type === "declared")
    return (
      <>
        {kv([
          ["Box", `${detail.box_label} (${detail.box_code})`],
          ["Declared VAT", sar(detail.vat_amount)],
          ["Declared base", detail.base_amount != null ? sar(detail.base_amount) : "—"],
          ["Own adjustment", sar(detail.adjustment || 0)],
          ["Return form", detail.form_number],
          ["Version", detail.data_version],
          ["Submitted", detail.submission_date],
        ])}
        <p className="detail-note">{detail.note}</p>
      </>
    );

  if (detail.type === "residual")
    return (
      <>
        {kv([
          ["Unexplained residual", <b>{sar(detail.amount)}</b>],
          ["Materiality threshold", sar(detail.materiality)],
          ["Band", detail.band],
          ["Verdict", STATE_LABEL[detail.state] || detail.state],
        ])}
        <p className="detail-note">{detail.note}</p>
      </>
    );

  if (detail.type === "response")
    return (
      <>
        {kv([
          ["Accounts for", <b>{sar(Math.abs(detail.total))}</b>],
          ["Document", detail.doc_name || "—"],
          ["Source", "Taxpayer-supplied evidence"],
        ])}
        <p className="detail-note">{detail.note}</p>
      </>
    );

  // reconstruction | rule → note (+ rule card) + invoice evidence
  return (
    <>
      {detail.type === "rule" && detail.rule && (
        <div className="rulecard">
          <div className="rc-top">
            <span className="rc">{detail.rule.code}</span>
            <span className="fam">{detail.rule.family}</span>
            <Link to="/rules" className="rc-link">
              open in rulebook →
            </Link>
          </div>
          <div className="rc-title">{detail.rule.title}</div>
          <div className="rc-meta">
            {detail.rule.explains_gap} · {detail.rule.severity}
          </div>
        </div>
      )}
      {detail.formula && (
        <div className="formula">
          <span className="k">Computation</span>
          <code>{detail.formula}</code>
        </div>
      )}
      <p className="detail-note">{detail.note}</p>
      {kv([
        ["Invoices", detail.count],
        ["Line total", amount != null ? sar(amount) : sar(detail.total)],
      ])}
      <InvoiceTable invoices={detail.invoices} />
    </>
  );
}

function Waterfall({ d, open }: { d: BoxResult; open: (title: string, detail?: Detail, amount?: number) => void }) {
  const max = Math.max(d.reconstructed_gross, d.declared, 1);
  const anchorStep = d.bridge.find((b) => b.kind === "anchor");
  const gapStep = d.bridge.find((b) => b.kind === "gap");
  const residualStep = d.bridge.find((b) => b.kind === "residual");
  const explains = d.bridge
    .filter((b) => b.kind === "explain")
    .map((b) => {
      const idx = d.bridge.findIndex((x) => x.seq === b.seq);
      return { rule: b.rule, label: b.label, amount: b.amount, detail: b.detail, before: d.bridge[idx - 1].running, after: b.running };
    });
  const rows: Row[] = [
    { title: "Reconstructed from e-invoices", kind: "recon", start: 0, end: d.reconstructed_gross, amount: d.reconstructed_gross, detail: gapStep?.detail },
    ...explains.map((e) => ({ title: e.label, rule: e.rule, kind: "explain", start: e.after, end: e.before, amount: e.amount, detail: e.detail })),
    { title: "Declared by the taxpayer", kind: "declared", start: 0, end: d.declared, amount: d.declared, detail: anchorStep?.detail },
    { title: "Unexplained residual", kind: "residual", start: d.declared, end: d.declared + d.residual, amount: d.residual, detail: residualStep?.detail },
  ];
  return (
    <div className="bridge">
      {rows.map((r, i) => {
        const left = (Math.min(r.start, r.end) / max) * 100;
        const width = Math.max((Math.abs(r.end - r.start) / max) * 100, 0.5);
        const sign = r.amount < 0 ? "−" : r.kind === "residual" && r.amount > 0 ? "+" : "";
        return (
          <div
            className="brow clickable"
            key={i}
            role="button"
            tabIndex={0}
            onClick={() => open(r.title, r.detail, r.amount)}
            onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && open(r.title, r.detail, r.amount)}
          >
            <div className="lbl">
              {r.rule && <span className="rc">{r.rule}</span>}
              {r.title}
              <span className="rowhint">›</span>
            </div>
            <div className="track">
              <div className={"bar " + r.kind} style={{ left: left + "%", width: width + "%" }} />
            </div>
            <div className={"amt " + r.kind}>
              {sign}
              {sar(r.amount)}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function Reconciliation() {
  const { id } = useParams();
  const [d, setD] = useState<Recon | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [rev, setRev] = useState(0);
  const [modal, setModal] = useState<{ title: string; detail?: Detail; amount?: number } | null>(null);

  useEffect(() => {
    if (!id) return;
    setD(null);
    setErr(null);
    fetch(`/api/cases/${id}/reconcile`)
      .then((r) => {
        if (!r.ok) throw new Error(r.statusText);
        return r.json();
      })
      .then(setD)
      .catch((e) => setErr(String(e)));
  }, [id, rev]);

  if (err)
    return (
      <div className="page">
        <div className="panel">
          <div className="notice err">Could not reconcile this case — {err}</div>
        </div>
      </div>
    );
  if (!d)
    return (
      <div className="page">
        <p className="muted">Reconstructing from e-invoices…</p>
      </div>
    );

  const open = (title: string, detail?: Detail, amount?: number) => setModal({ title, detail, amount });
  const cstate = d.combined?.state ?? d.state;
  const inputFinding = d.combined?.input_state === "potential-finding";

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">
            <Link to="/">Cases</Link> · {d.case_id}
          </p>
          <h1>{d.taxpayer}</h1>
        </div>
        <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
          {inputFinding && d.combined && (
            <span className="pill pri-high" style={{ fontSize: 12, padding: "5px 12px" }} title="Input-VAT over-claim on the purchases box">
              + input over-claim {sar(d.combined.input_residual)}
            </span>
          )}
          <span className={"pill " + (STATE_CLASS[cstate] || "status")} style={{ fontSize: 13, padding: "6px 14px" }}>
            {STATE_LABEL[cstate] || cstate}
          </span>
        </div>
      </div>

      <CaseTabs id={id!} />

      <TaxpayerBrief id={id} />

      <div className="tiles">
        <div className="tile">
          <div className="tn">{sar(d.declared)}</div>
          <div className="tl">Declared output VAT</div>
          <div className="tnote">as filed</div>
        </div>
        <div className="tile">
          <div className="tn" style={{ color: "var(--med)" }}>{sar(d.apparent_gap)}</div>
          <div className="tl">Apparent gap vs e-invoices</div>
          <div className="tnote">before explanation</div>
        </div>
        <div className="tile">
          <div className="tn">{d.explained_pct != null ? Math.round(d.explained_pct * 100) : 0}%</div>
          <div className="tl">Explained by rules</div>
          <div className="tnote">{sar(d.explained_total)}</div>
        </div>
        <div className="tile">
          <div className="tn" style={{ color: d.residual > 0 ? "var(--high)" : "var(--low)" }}>{sar(d.residual)}</div>
          <div className="tl">Unexplained residual</div>
          <div className="tnote">{d.band}</div>
        </div>
      </div>

      <AiNarration id={id} rev={rev} />

      <div className="panel">
        <div className="panel-head">
          <h2>Reconciliation bridge — {d.box}</h2>
          <button
            className="linklike"
            onClick={() => open("Reconstructed e-invoices", { type: "invoice-list", invoices: d.evidence_invoices, count: d.invoices_considered, note: "All cleared sale e-invoices used to reconstruct this box." })}
          >
            {d.invoices_considered} e-invoices reconstructed ›
          </button>
        </div>
        <Waterfall d={d} open={open} />
        <div className="bridge-foot">
          <span className="ct">∑ computed</span> Every figure is reconstructed deterministically from cleared e-invoices —
          no AI in the numbers. Click any line to see the invoices, rule, and computation behind it.
        </div>
      </div>

      {d.purchase && (
        <div className="panel">
          <div className="panel-head">
            <h2>Input VAT bridge — standard-rated purchases</h2>
            <span
              className={"pill " + (STATE_CLASS[d.purchase.state] || "status")}
              style={{ fontSize: 12, padding: "5px 12px" }}
            >
              {STATE_LABEL[d.purchase.state] || d.purchase.state}
            </span>
          </div>
          <div className="minibar">
            <span>
              Declared input <b>{sar(d.purchase.declared)}</b>
            </span>
            <span>
              Reconstructed <b>{sar(d.purchase.reconstructed_gross)}</b>
            </span>
            <span>
              Residual{" "}
              <b style={{ color: d.purchase.state === "potential-finding" ? "var(--high)" : "var(--low)" }}>
                {sar(d.purchase.residual)}
              </b>
            </span>
          </div>
          <Waterfall d={d.purchase} open={open} />
          <div className="bridge-foot">
            <span className="ct">∑ computed</span> Input VAT rebuilt from cleared purchase e-invoices. On this box an
            over-claim — declaring more input VAT than the invoices support — is the revenue risk.
          </div>
        </div>
      )}

      <InvestigationPanel id={id} rev={rev} />
      <NextBestAction id={id} rev={rev} />
      <TaxpayerResponsePanel id={id} residual={d.residual} onChanged={() => setRev((r) => r + 1)} />
      <AuditReport id={id} rev={rev} />

      {modal && (
        <Modal title={modal.title} onClose={() => setModal(null)}>
          {modal.detail?.type === "invoice-list" ? (
            <>
              <p className="detail-note">{modal.detail.note}</p>
              <InvoiceTable invoices={modal.detail.invoices} />
            </>
          ) : (
            <DetailBody detail={modal.detail} amount={modal.amount} />
          )}
        </Modal>
      )}
    </div>
  );
}
