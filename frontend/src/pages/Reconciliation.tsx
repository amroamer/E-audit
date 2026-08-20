import { useEffect, useState, type ReactNode } from "react";
import { useParams, Link } from "react-router-dom";
import TaxpayerBrief from "../components/TaxpayerBrief";
import AiNarration from "../components/AiNarration";
import NextBestAction from "../components/NextBestAction";
import AuditReport from "../components/AuditReport";
import VerdictLetter from "../components/VerdictLetter";
import InvestigationPanel from "../components/InvestigationPanel";
import CaseTabs from "../components/CaseTabs";
import LifecycleRail from "../components/LifecycleRail";
import TaxpayerResponsePanel from "../components/TaxpayerResponsePanel";

/** One step in the narrowing from the population to the qualifying set.
 *  `population` and `qualified` are the two ends; every step between them is a rule that
 *  removed documents. Nothing here is a movement of money — `amount` is the tax the
 *  documents carry, reported so the auditor can see the size of what was set aside. */
interface FunnelStep {
  seq: number;
  kind: "population" | "exclude" | "defer" | "qualified";
  rule: string | null;
  stage?: string;
  label: string;
  count: number;
  amount: number;
  detail?: Detail;
}
interface CompositionRow {
  type_code: number;
  label: string;
  count: number;
  amount: number;
  detail?: Detail;
}
interface EvidenceRow {
  code: string;
  label: string;
  amount: number;
  doc_name: string;
  detail?: Detail;
}
type Detail = Record<string, any>;
interface BoxResult {
  box: string;
  declared: number;
  expected_vat: number;
  expected_base: number;
  difference: number;
  evidence_total: number;
  evidence: EvidenceRow[];
  unexplained: number;
  materiality: number;
  band: string;
  state: string;
  funnel: FunnelStep[];
  composition: CompositionRow[];
  declared_detail?: Detail;
  difference_detail?: Detail;
  invoices_considered: number;
  population_lines: number;
  counted_lines: number;
  evidence_invoices: Detail[];
}
interface Combined {
  total_exposure: number;
  state: string;
  output_state: string;
  input_state: string;
  output_unexplained: number;
  input_unexplained: number;
  finding_boxes: string[];
}
interface Recon extends BoxResult {
  case_id: string;
  taxpayer: string;
  purchase?: BoxResult;
  combined?: Combined;
}

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

  if (detail.type === "difference")
    return (
      <>
        {kv([
          ["Expected (qualifying documents)", sar(detail.expected)],
          ["Declared on the return", sar(detail.declared)],
          ["Difference", <b>{sar(detail.difference)}</b>],
          ["Accounted for by evidence", sar(detail.evidence_total)],
          ["Left unexplained", <b>{sar(detail.unexplained)}</b>],
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

  // population | qualified | rule | structural | composition → note (+ rule card) + the documents
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

/** How the population narrowed to the qualifying set.
 *
 *  This replaces a waterfall, and the difference is the whole point. A waterfall starts
 *  from a total and walks deductions to another total — which forced the page to invent a
 *  "before" figure that included documents the rules put in another period and excluded
 *  documents the rules admit. It corresponded to nothing, and it taught the auditor that
 *  clearance lag is money being subtracted rather than invoices that were never in the
 *  period.
 *
 *  A funnel says what actually happened: this many documents, these rules removed these
 *  ones for these reasons, this many are left, and they total this. The bars measure
 *  documents, not money.
 */
function Funnel({ d, open }: { d: BoxResult; open: (title: string, detail?: Detail, amount?: number) => void }) {
  const start = d.funnel.find((f) => f.kind === "population");
  const endStep = d.funnel.find((f) => f.kind === "qualified");
  const steps = d.funnel.filter((f) => f.kind === "exclude" || f.kind === "defer");
  const max = Math.max(start?.count ?? 1, 1);

  const row = (f: FunnelStep, remaining: number) => (
    <div
      className={"frow clickable " + f.kind}
      key={f.seq}
      role="button"
      tabIndex={0}
      onClick={() => open(f.label, f.detail, f.amount)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && open(f.label, f.detail, f.amount)}
    >
      <div className="fcount">
        {f.kind === "exclude" || f.kind === "defer" ? "−" : ""}
        {f.count}
      </div>
      <div className="flbl">
        {f.rule && <span className="rc">{f.rule}</span>}
        {f.label}
        <span className="rowhint">›</span>
      </div>
      <div className="ftrack">
        <div className={"fbar " + f.kind} style={{ width: (remaining / max) * 100 + "%" }} />
      </div>
      <div className={"famt " + f.kind}>{sar(f.amount)}</div>
    </div>
  );

  let remaining = start?.count ?? 0;
  return (
    <div className="funnel">
      {start && row(start, remaining)}
      {steps.map((f) => {
        remaining -= f.count;
        return row(f, remaining);
      })}
      {endStep && row(endStep, endStep.count)}
      {d.composition.length > 0 && (
        <div className="fcomp">
          {d.composition.map((c) => (
            <button
              key={c.type_code}
              className="fchip"
              onClick={() => open(c.label, c.detail, c.amount)}
            >
              <b>{c.count}</b> {c.label.toLowerCase()}
              <span className={c.amount < 0 ? "neg" : ""}>
                {c.amount < 0 ? "−" : ""}
                {sar(c.amount)}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

/** Expected vs declared, and what is left. Three figures and a subtraction. */
function Compare({ d, open }: { d: BoxResult; open: (title: string, detail?: Detail, amount?: number) => void }) {
  const risky = d.state === "potential-finding";
  return (
    <div className="compare">
      <button className="cmp" onClick={() => open("Qualifying e-invoices", d.funnel.find((f) => f.kind === "qualified")?.detail, d.expected_vat)}>
        <span className="cl">Expected</span>
        <span className="cn">{sar(d.expected_vat)}</span>
        <span className="cs">{d.counted_lines} qualifying documents</span>
      </button>
      <span className="cop">−</span>
      <button className="cmp" onClick={() => open("Declared by the taxpayer", d.declared_detail, d.declared)}>
        <span className="cl">Declared</span>
        <span className="cn">{sar(d.declared)}</span>
        <span className="cs">as filed</span>
      </button>
      <span className="cop">=</span>
      <button
        className={"cmp result " + (risky ? "risk" : d.state === "supported" ? "ok" : "warn")}
        onClick={() => open("Difference", d.difference_detail, d.difference)}
      >
        <span className="cl">Difference</span>
        <span className="cn">
          {d.difference < 0 ? "−" : ""}
          {sar(d.difference)}
        </span>
        <span className="cs">{STATE_LABEL[d.state] || d.state}</span>
      </button>
    </div>
  );
}

/** Taxpayer evidence — the only thing that can account for a difference after the fact. */
function Evidence({ d, open }: { d: BoxResult; open: (title: string, detail?: Detail, amount?: number) => void }) {
  if (!d.evidence?.length) return null;
  return (
    <div className="evidence">
      <h4>Accounted for by taxpayer evidence</h4>
      {d.evidence.map((e) => (
        <button key={e.code} className="erow" onClick={() => open(e.label, e.detail, e.amount)}>
          <span className="rc">{e.code}</span>
          <span className="elbl">{e.label}</span>
          <span className="eamt">−{sar(e.amount)}</span>
        </button>
      ))}
      <div className="erow total">
        <span className="elbl">Still unexplained</span>
        <span className="eamt" style={{ color: d.state === "supported" ? "var(--low)" : "var(--high)" }}>
          {sar(d.unexplained)}
        </span>
      </div>
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
              + input over-claim {sar(d.combined.input_unexplained)}
            </span>
          )}
          <span className={"pill " + (STATE_CLASS[cstate] || "status")} style={{ fontSize: 13, padding: "6px 14px" }}>
            {STATE_LABEL[cstate] || cstate}
          </span>
        </div>
      </div>

      <CaseTabs id={id!} />
      <LifecycleRail id={id!} />

      <TaxpayerBrief id={id} />

      <div className="tiles">
        <div className="tile">
          <div className="tn">{d.counted_lines}</div>
          <div className="tl">Documents that qualify</div>
          <div className="tnote">of {d.population_lines} on file</div>
        </div>
        <div className="tile">
          <div className="tn">{sar(d.expected_vat)}</div>
          <div className="tl">Expected output VAT</div>
          <div className="tnote">what qualifies, summed</div>
        </div>
        <div className="tile">
          <div className="tn">{sar(d.declared)}</div>
          <div className="tl">Declared output VAT</div>
          <div className="tnote">as filed</div>
        </div>
        <div className="tile">
          <div className="tn" style={{ color: d.unexplained !== 0 ? "var(--high)" : "var(--low)" }}>
            {d.unexplained < 0 ? "−" : ""}
            {sar(d.unexplained)}
          </div>
          <div className="tl">{d.evidence_total ? "Still unexplained" : "Difference"}</div>
          <div className="tnote">{d.band}</div>
        </div>
      </div>

      <AiNarration id={id} rev={rev} />

      <div className="panel">
        <div className="panel-head">
          <h2>Which documents belong in {d.box}</h2>
          <button
            className="linklike"
            onClick={() => open("E-invoices on file", { type: "invoice-list", invoices: d.evidence_invoices, count: d.invoices_considered, note: "Every sale e-invoice held for this taxpayer, before any rule is applied." })}
          >
            {d.invoices_considered} e-invoices on file ›
          </button>
        </div>
        <Funnel d={d} open={open} />
        <Compare d={d} open={open} />
        <Evidence d={d} open={open} />
        <div className="panel-note">
          <span className="ct">∑ computed</span> The rules decide which documents belong in this box and this period;
          the qualifying ones are then summed. Nothing is totalled and later adjusted, so there is no figure here
          &ldquo;before&rdquo; the rules. Click any line for the documents behind it.
        </div>
      </div>

      {d.purchase && (
        <div className="panel">
          <div className="panel-head">
            <h2>Which documents belong in standard-rated purchases</h2>
            <span
              className={"pill " + (STATE_CLASS[d.purchase.state] || "status")}
              style={{ fontSize: 12, padding: "5px 12px" }}
            >
              {STATE_LABEL[d.purchase.state] || d.purchase.state}
            </span>
          </div>
          <Funnel d={d.purchase} open={open} />
          <Compare d={d.purchase} open={open} />
          <Evidence d={d.purchase} open={open} />
          <div className="panel-note">
            <span className="ct">∑ computed</span> The same order on the purchases side. Here an over-claim — declaring
            more input VAT than the qualifying invoices support — is the revenue risk, so a negative difference is the
            one to look at.
          </div>
        </div>
      )}

      <InvestigationPanel id={id} rev={rev} />
      <NextBestAction id={id} rev={rev} />
      <TaxpayerResponsePanel id={id} difference={d.unexplained} onChanged={() => setRev((r) => r + 1)} />
      <AuditReport id={id} rev={rev} />
      <VerdictLetter id={id!} />

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
