import { useEffect, useMemo, useState } from "react";
import { listRules, setRuleEnabled, deleteRule, type RuleRow } from "../api";

// rules currently wired into the live reconciliation engine — toggling these changes a case's bridge
const WIRED = new Set(["COR-01", "OUT-07"]);

const SEV = [
  { v: "high", l: "High" },
  { v: "medium", l: "Medium" },
  { v: "low", l: "Low" },
];
const GAP = [
  { v: "yes", l: "Explains a gap" },
  { v: "partial", l: "Partial" },
  { v: "no", l: "No direct gap" },
];

export default function Rules() {
  const [rules, setRules] = useState<RuleRow[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [fam, setFam] = useState<string | null>(null);
  const [sev, setSev] = useState<string | null>(null);
  const [gap, setGap] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  useEffect(() => {
    listRules().then(setRules).catch((e) => setErr(String(e)));
  }, []);

  const onToggle = async (code: string, next: boolean) => {
    setRules((rs) => rs.map((r) => (r.code === code ? { ...r, enabled: next } : r)));
    try {
      await setRuleEnabled(code, next);
    } catch {
      setRules((rs) => rs.map((r) => (r.code === code ? { ...r, enabled: !next } : r))); // revert
    }
  };

  const onDelete = async (code: string) => {
    const prev = rules;
    setConfirmDelete(null);
    setRules((rs) => rs.filter((r) => r.code !== code));
    try {
      await deleteRule(code);
    } catch {
      setRules(prev); // restore on failure
    }
  };

  const families = useMemo(() => [...new Set(rules.map((r) => r.family))], [rules]);

  const shown = rules.filter((r) => {
    const hay = `${r.code} ${r.title} ${r.family} ${r.explains_gap}`.toLowerCase();
    if (q && !hay.includes(q.toLowerCase())) return false;
    if (fam && r.family !== fam) return false;
    if (sev && r.severity_band !== sev) return false;
    if (gap && r.gap_band !== gap) return false;
    return true;
  });

  const toggle = (cur: string | null, v: string, set: (x: string | null) => void) =>
    set(cur === v ? null : v);

  const active = rules.filter((r) => r.enabled).length;

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <p className="eyebrow">Detection rules</p>
          <h1>VAT Mistakes Rulebook</h1>
        </div>
      </div>

      {err ? (
        <div className="panel">
          <div className="notice err">
            Backend not reachable — start the API and seed the demo data (<code>python -m app.seed.seed</code>).
          </div>
        </div>
      ) : (
        <>
          <div className="controls">
            <div className="search">
              <input
                placeholder="Search rules — reverse charge, late filing, credit note, Box 9…"
                value={q}
                onChange={(e) => setQ(e.target.value)}
              />
            </div>
            {families.map((f) => (
              <button key={f} className={"chip" + (fam === f ? " on" : "")} onClick={() => toggle(fam, f, setFam)}>
                {f}
              </button>
            ))}
            {SEV.map((s) => (
              <button
                key={s.v}
                className={"chip sev-" + s.v + (sev === s.v ? " on" : "")}
                onClick={() => toggle(sev, s.v, setSev)}
              >
                {s.l}
              </button>
            ))}
            {GAP.map((g) => (
              <button key={g.v} className={"chip" + (gap === g.v ? " on" : "")} onClick={() => toggle(gap, g.v, setGap)}>
                {g.l}
              </button>
            ))}
            <span className="rescount">
              {active} active · {shown.length} of {rules.length} shown
            </span>
          </div>

          <div className="cards">
            {shown.map((r) => (
              <div className={"card sev-" + r.severity_band + (r.enabled ? "" : " off")} key={r.code}>
                <div className="card-top">
                  <span className="code">{r.code}</span>
                  <span className="fam">{r.family}</span>
                </div>
                <h3>{r.title}</h3>
                <div className="card-badges">
                  <span className={"badge gap-" + r.gap_band}>
                    {r.gap_band === "no" ? "No direct gap" : r.explains_gap}
                  </span>
                  <span className={"pill sev-" + r.severity_band}>{r.severity}</span>
                </div>
                <div className="card-foot">
                  <label className="switch">
                    <input
                      type="checkbox"
                      checked={r.enabled}
                      onChange={(e) => onToggle(r.code, e.target.checked)}
                    />
                    <span className="switch-track">
                      <span className="switch-thumb" />
                    </span>
                    <span className="switch-label">{r.enabled ? "Active" : "Disabled"}</span>
                  </label>
                  <div className="foot-right">
                    {WIRED.has(r.code) && (
                      <span className="live-badge" title="Wired into the live reconciliation engine">
                        ● live
                      </span>
                    )}
                    {confirmDelete === r.code ? (
                      <span className="del-confirm">
                        <button className="linklike danger" onClick={() => onDelete(r.code)}>
                          delete
                        </button>
                        <button className="linklike" onClick={() => setConfirmDelete(null)}>
                          cancel
                        </button>
                      </span>
                    ) : (
                      <button className="card-del" title="Delete rule" onClick={() => setConfirmDelete(r.code)}>
                        ×
                      </button>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
