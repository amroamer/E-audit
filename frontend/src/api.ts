const BASE = "/api";

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

export interface PriorityScore {
  score: number;
  band: string;
  driver: string;
  residual: number;
  deadline_days: number | null;
  prior_findings: number;
  signals: { exposure: number; deadline: number; history: number; quickwin: number };
}
export interface CaseRow {
  case_id: string;
  taxpayer: string;
  vat_no: string;
  sector: string;
  period: string;
  reason: string;
  risk: string;
  referral_priority: string;
  status: string;
  scenario: string;
  priority: PriorityScore;
}

export type RuleKind = "explanation" | "mistake" | "risk";

export interface RuleRow {
  code: string;
  family: string;
  title: string;
  explains_gap: string;
  gap_band: string;
  severity: string;
  severity_band: string;
  root_cause_code: string;
  enabled: boolean;
  /** what kind of object this rule is: explains a difference, accuses a mistake, or flags risk */
  rule_kind: RuleKind;
  /** where it sits in the evaluation precedence (population → … → risk) */
  stage: string;
  /** which class of difference it describes (T/S/D/A/R taxonomy) */
  reason_code: string;
  reason_label: string;
  /** true when the live reconciliation engine can draw a bridge line for it */
  wired: boolean;
}

export interface ScopeItem {
  item: string;
  detail?: string;
  note?: string;
  reason_code?: string;
  reason_label?: string;
}
export interface ScopeCard {
  headline: string;
  in_scope: ScopeItem[];
  out_of_scope: ScopeItem[];
  tax_point_note: string;
}

export interface Health {
  status: string;
  taxpayers: number;
  cases: number;
  rules: number;
}

export interface ExecOverview {
  open_cases: number;
  exposure_total: number;
  explained_total: number;
  apparent_gap_total: number;
  auto_clearable: number;
  auto_clearable_pct: number;
  needs_action: number;
  findings: number;
  to_review: number;
}

export const listCases = () => getJSON<CaseRow[]>("/cases");
export const listRules = () => getJSON<RuleRow[]>("/rules");
export const getHealth = () => getJSON<Health>("/health");
export const getOverview = () => getJSON<ExecOverview>("/overview");
export const getScope = () => getJSON<ScopeCard>("/scope");

export const reseedDemo = async (): Promise<{ status: string; message: string }> => {
  const r = await fetch(BASE + "/admin/reseed", { method: "POST" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const setRuleEnabled = async (code: string, enabled: boolean) => {
  const r = await fetch(`${BASE}/rules/${code}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ enabled }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export const deleteRule = async (code: string) => {
  const r = await fetch(`${BASE}/rules/${code}`, { method: "DELETE" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

export interface LetterExtraction {
  explains_gap: boolean;
  category: string;
  summary: string;
  quote: string;
  proposed_amount: number;
  confidence: string;
  caveat: string;
  source: string;
}

export const readLetter = async (id: string, text: string): Promise<LetterExtraction> => {
  const r = await fetch(`${BASE}/cases/${id}/read-letter`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};
