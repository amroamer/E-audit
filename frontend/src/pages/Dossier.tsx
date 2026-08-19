import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import CaseTabs from "../components/CaseTabs";
import LifecycleRail from "../components/LifecycleRail";
import PrecedentPanel from "../components/PrecedentPanel";
import { getDossier, type Dossier as D } from "../api";

const sar = (n: number) => "SAR " + Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 0 });
const num = (n: number) => n.toLocaleString("en-US", { maximumFractionDigits: 0 });

function Fact({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div>
      <span className="k">{k}</span>
      <span className="v">{v ?? "—"}</span>
    </div>
  );
}

/** Stage 1 — everything ZATCA already holds.
 *
 *  The auditors described starting a case by investigating internal data: returns,
 *  e-invoicing, imports and exports, taxpayer history, previous audits, financials, and the
 *  risk analysis itself. Doing that today means opening several systems, which is pain point
 *  three. This page is that step, assembled — and the "held" markers are not decoration:
 *  they are what the planner uses to drop a request the Authority can already answer.
 */
export default function Dossier() {
  const { id = "" } = useParams();
  const [d, setD] = useState<D | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    setD(null);
    setErr("");
    getDossier(id).then(setD).catch((e) => setErr(String(e)));
  }, [id]);

  if (err) return <p className="error">Could not load the dossier: {err}</p>;
  if (!d) return <p className="muted">Loading dossier…</p>;

  const tp = d.taxpayer;
  const r = d.referral;
  const held = d.sources.filter((s) => s.held);
  const customs = d.blocks["customs"] || {};
  const fin = d.blocks["financials"] || {};
  const prior = d.blocks["prior-audits"] || {};
  const einv = d.blocks["e-invoices"] || {};
  const c = tp.compliance || {};

  return (
    <>
      <header className="page-head">
        <div>
          <h1>{tp.name}</h1>
          <p className="sub">
            {d.case_id} · {d.period_from} → {d.period_to} · {d.audit_type} audit
          </p>
        </div>
        <div className="chips">
          <span className="pill">{tp.size}</span>
          <span className="pill">{tp.sector}</span>
          {tp.importer && <span className="pill">Importer</span>}
          {tp.exporter && <span className="pill">Exporter</span>}
          {tp.pos_registered && <span className="pill">POS</span>}
        </div>
      </header>

      <CaseTabs id={id} />
      <LifecycleRail id={id} />

      {/* ---------------------------------------------- why this case exists */}
      <div className="panel">
        <div className="panel-head">
          <h2>Why this case was raised</h2>
          {r.score != null && (
            <span className="sub">
              Risk score {r.score}
              {r.threshold ? ` · threshold ${r.threshold}` : ""}
            </span>
          )}
        </div>
        <div className="panel-body">
          <p className="brief-head">{r.indicator_label}</p>
          {r.narrative && <p className="detail-note">{r.narrative}</p>}
          {r.signals.length > 0 && (
            <div className="tablescroll">
              <table className="inv-table">
                <thead>
                  <tr>
                    <th>Contributing signal</th>
                    <th style={{ textAlign: "right" }}>Value</th>
                    <th style={{ width: 120 }}>Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {r.signals.map((s) => (
                    <tr key={s.code}>
                      <td>
                        {s.label} <span className="sub mono">{s.code}</span>
                      </td>
                      <td className="mono" style={{ textAlign: "right" }}>{num(s.value)}</td>
                      <td>
                        <span className="meter">
                          <i style={{ width: `${s.weight * 100}%` }} />
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {r.consult_first && r.consult_first.length > 0 && (
            <p className="detail-note">
              <b>Consult first:</b> {r.consult_first.join(", ")}. The risk engine is upstream — this
              is its output, not our reconstruction.
            </p>
          )}
        </div>
      </div>

      {/* ---------------------------------------------- what we hold */}
      <div className="panel">
        <div className="panel-head">
          <h2>What ZATCA already holds</h2>
          <span className="sub">
            {held.length} of {d.sources.length} sources on file
          </span>
        </div>
        <div className="panel-body">
          <div className="srcgrid">
            {d.sources.map((s) => (
              <div key={s.key} className={"srccard" + (s.held ? " held" : "")}>
                <span className="srcmark">{s.held ? "✓" : "·"}</span>
                <div>
                  <b>{s.label}</b>
                  <small>
                    {s.held
                      ? s.count != null
                        ? `${num(s.count)} record${s.count === 1 ? "" : "s"}`
                        : "on file"
                      : "not held"}
                    {s.as_of ? ` · as of ${s.as_of}` : ""}
                  </small>
                </div>
              </div>
            ))}
          </div>
          <p className="detail-note">
            Anything marked on file is <b>not requested from the taxpayer</b>. The Casework tab
            shows each item dropped for that reason.
          </p>
        </div>
      </div>

      {/* ---------------------------------------------- who am I dealing with */}
      <div className="grid-2">
        <div className="panel">
          <div className="panel-head">
            <h2>Who this taxpayer is</h2>
          </div>
          <div className="panel-body">
            <div className="kv">
              <Fact k="VAT registration" v={<span className="mono">{tp.vat_no}</span>} />
              <Fact k="Legal form" v={tp.legal_form || tp.bp_type} />
              <Fact
                k="Registered"
                v={
                  tp.registered_from
                    ? `${tp.registered_from}${tp.registered_years ? ` · ${tp.registered_years} yrs` : ""}`
                    : "—"
                }
              />
              <Fact k="E-invoicing since" v={tp.einvoicing_onboarded || "—"} />
              <Fact k="Size" v={tp.size} />
              <Fact k="Employees" v={tp.employees != null ? num(tp.employees) : "—"} />
              <Fact k="Branches" v={num(tp.branches)} />
              <Fact k="Accounting" v={tp.accounting_method} />
            </div>

            <h4>Registered economic activities</h4>
            <ul className="acts">
              {tp.activities.map((a) => (
                <li key={a.isic}>
                  <code>{a.isic}</code> {a.description}
                  {a.primary && <span className="pill pri-low">primary</span>}
                </li>
              ))}
              {tp.activities.length === 0 && <li className="muted">None recorded.</li>}
            </ul>
            <p className="detail-note">
              What the business is registered to do is the reference point for whether a purchase
              relates to the economic activity — a question the auditors put firmly on the human
              side of the line.
            </p>

            {tp.related_parties.length > 0 && (
              <>
                <h4>Related parties</h4>
                <ul className="acts">
                  {tp.related_parties.map((p) => (
                    <li key={p.vat_no}>
                      {p.name} <span className="sub mono">{p.vat_no}</span>
                      <span className="pill">{p.relation}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>How they have behaved</h2>
          </div>
          <div className="panel-body">
            <h4>Filing and payment</h4>
            <div className="kv">
              <Fact k="Returns due" v={c.returns_due ?? "—"} />
              <Fact k="Returns filed" v={c.returns_filed ?? "—"} />
              <Fact k="Filed late" v={c.filed_late ?? "—"} />
              <Fact k="Average days late" v={c.avg_days_late ?? "—"} />
              <Fact k="Payments late" v={c.payments_late ?? "—"} />
              <Fact
                k="Outstanding"
                v={c.outstanding_balance ? sar(c.outstanding_balance) : "None"}
              />
            </div>

            <h4>Audit history</h4>
            {prior.count ? (
              <div className="tablescroll">
                <table className="inv-table">
                  <thead>
                    <tr>
                      <th>Case</th>
                      <th>Period</th>
                      <th>Outcome</th>
                      <th style={{ textAlign: "right" }}>Assessed</th>
                      <th style={{ textAlign: "right" }}>Rounds</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(prior.audits || []).map((a: any) => (
                      <tr key={a.case_id}>
                        <td className="mono">{a.case_id}</td>
                        <td className="mono">{a.period_from}</td>
                        <td>
                          <span
                            className={"pill " + (a.result === "FINDING" ? "pri-high" : "pri-low")}
                          >
                            {a.result === "FINDING" ? a.root_cause : "No finding"}
                          </span>
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          {a.assessed ? sar(a.assessed) : "—"}
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>{a.rounds || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">No previous audit on file — this is the first.</p>
            )}

            <h4>Financial information held</h4>
            {fin.count ? (
              <div className="tablescroll">
                <table className="inv-table">
                  <thead>
                    <tr>
                      <th>Year</th>
                      <th style={{ textAlign: "right" }}>Turnover</th>
                      <th style={{ textAlign: "right" }}>Purchases</th>
                      <th style={{ textAlign: "right" }}>Purchase ratio</th>
                      <th style={{ textAlign: "right" }}>Gross margin</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(fin.years || []).map((y: any) => (
                      <tr key={y.fiscal_year}>
                        <td className="mono">{y.fiscal_year}</td>
                        <td className="mono" style={{ textAlign: "right" }}>{sar(y.turnover)}</td>
                        <td className="mono" style={{ textAlign: "right" }}>{sar(y.purchases)}</td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          {y.purchase_ratio_pct != null ? `${y.purchase_ratio_pct}%` : "—"}
                        </td>
                        <td className="mono" style={{ textAlign: "right" }}>
                          {y.gross_margin_pct != null ? `${y.gross_margin_pct}%` : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="muted">No financial information on file.</p>
            )}
          </div>
        </div>
      </div>

      {/* ---------------------------------------------- customs + e-invoices */}
      <div className="grid-2">
        <div className="panel">
          <div className="panel-head">
            <h2>Imports and exports</h2>
            {customs.in_period != null && (
              <span className="sub">{customs.in_period} declarations in the period</span>
            )}
          </div>
          <div className="panel-body">
            {customs.count ? (
              <>
                <div className="kv">
                  <Fact k="Import VAT in period" v={sar(customs.import_vat_in_period || 0)} />
                  <Fact k="Export value in period" v={sar(customs.export_value_in_period || 0)} />
                </div>
                <div className="tablescroll">
                  <table className="inv-table">
                    <thead>
                      <tr>
                        <th>Declaration</th>
                        <th>Date</th>
                        <th>Goods</th>
                        <th style={{ textAlign: "right" }}>Value</th>
                        <th style={{ textAlign: "right" }}>VAT</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(customs.declarations || []).map((x: any) => (
                        <tr key={x.declaration_no} className={x.in_period ? "" : "dim"}>
                          <td className="mono">{x.declaration_no}</td>
                          <td className="mono">{x.date}</td>
                          <td>
                            {x.goods} <span className="sub">· HS {x.hs_chapter}</span>
                          </td>
                          <td className="mono" style={{ textAlign: "right" }}>{sar(x.customs_value)}</td>
                          <td className="mono" style={{ textAlign: "right" }}>
                            {x.vat_paid ? sar(x.vat_paid) : "—"}
                            {x.vat_deferred && <span className="sub"> def.</span>}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="detail-note">
                  Held internally, so import declarations are never requested from the taxpayer.
                </p>
              </>
            ) : (
              <p className="muted">No customs movements on file for this taxpayer.</p>
            )}
          </div>
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>E-invoices in the period</h2>
            <span className="sub">{num(einv.count || 0)} documents</span>
          </div>
          <div className="panel-body">
            <div className="tablescroll">
              <table className="inv-table">
                <thead>
                  <tr>
                    <th>Direction</th>
                    <th>Type</th>
                    <th>Status</th>
                    <th style={{ textAlign: "right" }}>Count</th>
                    <th style={{ textAlign: "right" }}>VAT</th>
                  </tr>
                </thead>
                <tbody>
                  {(einv.groups || []).map((g: any, i: number) => (
                    <tr key={i}>
                      <td>{g.direction}</td>
                      <td className="mono">{g.type_code}</td>
                      <td>{g.status}</td>
                      <td className="mono" style={{ textAlign: "right" }}>{g.count}</td>
                      <td className="mono" style={{ textAlign: "right" }}>{sar(g.vat)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="detail-note">
              A count and a sum only. What the population <i>should</i> add to, once qualification
              rules run, is the Reconciliation tab.
            </p>
          </div>
        </div>
      </div>

      <PrecedentPanel id={id} />
    </>
  );
}
