import type { AiSource } from "./ai/ai";

const BASE = "/api";

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(BASE + path);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(BASE + path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

export interface PriorityScore {
  score: number;
  band: string;
  driver: string;
  at_stake: number;
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
  /** true when the live engine acts on it — toggling it changes which documents qualify */
  wired: boolean;
}

/* ---- investigation (app/agents) --------------------------------------------
   Agents propose typed tests; a deterministic adjudicator settles them against the
   engine. Nothing here is model output, which is why it renders without an API key. */
export type AdjudicationStatus = "confirmed" | "refuted" | "insufficient-evidence";

export interface Hypothesis {
  id: string;
  agent: string;
  claim: string;
  /** what the agent saw on the case file that made this worth testing */
  why: string;
  /** the outcome in the Authority's vocabulary this becomes if confirmed */
  outcome_code: string;
  reason_code: string;
  test: { kind: string; box: string; params: Record<string, unknown> };
  evidence_refs: string[];
  confidence: "high" | "medium" | "low";
}

/** A confirmed hypothesis, worded by the Authority's own vocabulary. This — never an
 *  agent's exploratory `claim` — is what reaches the report and the taxpayer letter. */
export interface Finding {
  code: string;
  statement: string;
  amount: number;
  effect: "increases-output" | "disallows-input" | "documentation";
  direction: string;
  agent: string;
  hypothesis_id: string;
  /** the evidence this rests on; findings sharing a basis are readings of one amount */
  basis: string;
  why: string;
  explanation: string;
  detail: Record<string, any>;
}
export interface Exposure {
  increases_output: number;
  disallows_input: number;
  documentation_at_risk: number;
  total: number;
  count: number;
  distinct_bases: number;
}
export interface Adjudication {
  hypothesis_id: string;
  status: AdjudicationStatus;
  amount: number;
  detail: Record<string, unknown>;
  explanation: string;
}
export interface CaseFileEntry {
  seq: number;
  round: number;
  kind: "fact" | "hypothesis" | "adjudication" | "objection" | "conclusion";
  agent: string;
  payload: Record<string, any>;
}
export interface Investigation {
  case_id: string;
  rounds: number;
  entries: CaseFileEntry[];
  hypotheses: Hypothesis[];
  adjudications: Adjudication[];
  leading: string | null;
  conclusion: string;
  unexplained: number;
  source: string;
  findings: Finding[];
  exposure: Exposure;
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
  difference_total: number;
  accounted_total: number;
  auto_clearable: number;
  auto_clearable_pct: number;
  needs_action: number;
  findings: number;
  to_review: number;
}

/* ---- the case dossier (app/dossier) ----------------------------------------
   Everything ZATCA already holds on this taxpayer and period. The auditors start a case by
   investigating internal data and only then decide what is genuinely missing; today that
   means opening several systems. `sources[].held` is what lets the planner drop a request
   mechanically rather than relying on the auditor to remember what the Authority has. */
export interface Activity {
  isic: string;
  description: string;
  primary?: boolean;
}
export interface RelatedParty {
  name: string;
  vat_no: string;
  relation: string;
}
export interface TaxpayerProfile {
  id: number;
  name: string;
  vat_no: string;
  legal_form: string;
  bp_type: string;
  sector: string;
  size: string;
  primary_activity: Activity;
  activities: Activity[];
  resident: boolean;
  vat_group_rep: boolean;
  accounting_method: string;
  registered_from: string | null;
  registered_years: number | null;
  deregistered: string | null;
  einvoicing_onboarded: string | null;
  employees: number | null;
  branches: number;
  pos_registered: boolean;
  importer: boolean;
  exporter: boolean;
  related_parties: RelatedParty[];
  compliance: Record<string, number>;
  audit_history: {
    closed_cases: number;
    findings: number;
    total_assessed: number;
    last_outcome: string | null;
    root_causes: string[];
  };
}
export interface RiskSignal {
  code: string;
  label: string;
  value: number;
  weight: number;
}
export interface Referral {
  held: boolean;
  structured: boolean;
  indicator_code: string;
  indicator_label: string;
  description?: string;
  narrative: string;
  score: number | null;
  threshold?: number;
  signals: RiskSignal[];
  model_version?: string;
  generated_at?: string | null;
  consult_first?: string[];
}
export interface DossierSource {
  key: string;
  label: string;
  held: boolean;
  count: number | null;
  as_of: string | null;
}
export interface Dossier {
  case_id: string;
  period_from: string;
  period_to: string;
  status: string;
  audit_type: string;
  sla_due: string | null;
  taxpayer: TaxpayerProfile;
  referral: Referral;
  sources: DossierSource[];
  blocks: Record<string, any>;
}

/* ---- precedent (app/precedent) ---------------------------------------------
   What comparable closed cases turned out to be, and which evidence actually closed them.
   Deterministic retrieval and a Python tally — no model, so the ranked list is stable. */
export interface Tally {
  key: string;
  count: number;
  pct: number;
}
export interface EvidenceStat {
  key: string;
  label: string;
  requested: number;
  decisive: number;
  decisive_rate: number;
}
export interface PrecedentMatch {
  case_id: string;
  similarity: number;
  reasons: string[];
  sector: string;
  size: string;
  result: string;
  root_cause: string;
  rounds: number;
  assessed: number;
  note: string;
}
export interface PrecedentSummary {
  case_id: string;
  indicator: string;
  indicator_label: string;
  comparable: number;
  widened: boolean;
  outcomes: Tally[];
  explained_by: Tally[];
  caused_by: Tally[];
  evidence: EvidenceStat[];
  effort: {
    median_rounds?: number | null;
    max_rounds?: number | null;
    median_days_to_close?: number | null;
    single_round_pct?: number | null;
  };
  assessed: { findings?: number; median?: number | null; total?: number };
  recurrence: { cases: number; findings: number; root_causes: string[]; case_ids: string[] } | null;
  matches: PrecedentMatch[];
}
export interface SuggestedItem {
  key: string;
  label: string;
  kind: string;
  decisive_rate: number;
  requested_in: number;
  decisive_in: number;
  held_internally: string;
  recommend: boolean;
  why: string;
}
export interface PrecedentBriefing {
  agent: string;
  summary: PrecedentSummary;
  narrative: string[];
  hypotheses: Hypothesis[];
  suggested_items: SuggestedItem[];
}

/* ---- the case lifecycle (app/casefile) --------------------------------------
   Five stages, derived from the case's own data rather than stored, so the rail cannot drift
   from reality. No stage advances by itself — every gate is a human decision. */
export type StageState = "done" | "active" | "waiting" | "pending" | "skipped";
export interface LifecycleStage {
  key: string;
  label: string;
  state: StageState;
  owner: string;
  summary: string;
  next_action: string;
  detail: Record<string, any>;
}
export interface Lifecycle {
  case_id: string;
  stages: LifecycleStage[];
  current: string;
  current_label: string;
  waiting_on: string;
  next_action: string;
  complete: boolean;
  /** the auto-clear claim: this case resolved without any request to the taxpayer */
  no_contact_needed: boolean;
}

/* ---- the request/response loop (app/requests) ------------------------------- */
export interface PlannedItem {
  key: string;
  label: string;
  kind: string;
  description: string;
  required_columns: string[];
  mandatory_columns: string[];
  expected_format: string;
  addresses: string[];
  include: boolean;
  reason: string;
  rationale: string;
  decisive_rate: number | null;
  requested_in: number;
  hypothesis_id: string;
}
export interface RequestPlan {
  case_id: string;
  indicator: string;
  held_internally: string[];
  items: PlannedItem[];
  dropped: PlannedItem[];
  notes: string[];
}
export type GapKind =
  | "missing-item"
  | "wrong-document"
  | "missing-column"
  | "empty-mandatory-field"
  | "wrong-period"
  | "arithmetic-mismatch"
  | "wrong-format"
  | "unrequested-document"
  | "too-vague";
export interface Gap {
  id?: number;
  kind: GapKind;
  severity: "blocking" | "advisory";
  detail: string;
  citation: string;
  item_label: string;
  source: string;
  request_item_id: number | null;
  document_id: number | null;
}
export interface LoopItem {
  id: number;
  seq: number;
  key: string;
  kind: string;
  label: string;
  description: string;
  required_columns: string[];
  mandatory_columns: string[];
  expected_format: string;
  rationale: string;
  hypothesis_id: string;
  status: "outstanding" | "received" | "satisfied" | "waived";
  period: string;
}
export interface LoopRound {
  seq: number;
  status: string;
  subject: string;
  issued_at: string | null;
  due_at: string | null;
  answered_at: string | null;
  body: string;
  body_source: string;
  items: LoopItem[];
  gaps: Gap[];
}
export interface LoopDocument {
  id: number;
  filename: string;
  format: string;
  round: number;
  request_item_id: number | null;
  /** replaced by a later upload against the same item — history, not evidence */
  superseded: boolean;
  received_at: string | null;
  columns: string[];
  raw_headers: string[];
  row_count: number;
  stated_totals: Record<string, number>;
  period_from: string | null;
  period_to: string | null;
  note: string;
}
export interface LoopState {
  case_id: string;
  round: number;
  status: string;
  complete: boolean;
  rounds: LoopRound[];
  documents: LoopDocument[];
  blocking: number;
  draft?: Draft;
}
export interface Draft {
  text: string;
  source: AiSource | "none";
  verified?: boolean;
  mode?: string;
  violations?: string[];
  note?: string;
}

export const listCases = () => getJSON<CaseRow[]>("/cases");
export const listRules = () => getJSON<RuleRow[]>("/rules");
export const getHealth = () => getJSON<Health>("/health");
export const getOverview = () => getJSON<ExecOverview>("/overview");
export const getScope = () => getJSON<ScopeCard>("/scope");
export const getInvestigation = (id: string) => getJSON<Investigation>(`/cases/${id}/investigate`);
export const getDossier = (id: string) => getJSON<Dossier>(`/cases/${id}/dossier`);
export const getPrecedent = (id: string) => getJSON<PrecedentBriefing>(`/cases/${id}/precedent`);
export const getPlan = (id: string) => getJSON<RequestPlan>(`/cases/${id}/plan`);
export const getLoop = (id: string) => getJSON<LoopState>(`/cases/${id}/requests`);
export const getFollowup = (id: string) => getJSON<Draft>(`/cases/${id}/followup`);
export const getLifecycle = (id: string) => getJSON<Lifecycle>(`/cases/${id}/lifecycle`);
export const getVerdict = (id: string) => getJSON<Draft>(`/cases/${id}/verdict`);

const post = async <T>(path: string): Promise<T> => {
  const r = await fetch(BASE + path, { method: "POST" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
};

export const openRound = (id: string) => post<LoopState>(`/cases/${id}/requests`);
export const issueRound = (id: string, seq: number) =>
  post<LoopState>(`/cases/${id}/requests/${seq}/issue`);
export const recheck = (id: string) => post<LoopState>(`/cases/${id}/requests/check`);

/** Upload a file the taxpayer sent. The response comes back with the gaps already recomputed. */
export const uploadDocument = async (
  id: string,
  file: File,
  itemId?: number,
): Promise<LoopState> => {
  const body = new FormData();
  body.append("file", file);
  if (itemId != null) body.append("item_id", String(itemId));
  const r = await fetch(`${BASE}/cases/${id}/documents`, { method: "POST", body });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

/** The seeded deficient response, so the upload path can be demonstrated live. */
export const demoResponseFileUrl = `${BASE}/demo/response-file`;

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

/* ---- the post-receipt workflow -------------------------------------------
   Planning is out of scope: a case starts when the taxpayer's documents arrive.
   These cover recovering the request spec from the email that was sent, checking
   the auditor's own arithmetic, and the drafts that go back out. */

export interface ParsedRequestItem {
  key: string;
  label: string;
  required_columns: string[];
  mandatory_columns: string[];
  /** the phrase in the email that produced this match, so the parse can be checked */
  cue: string;
  source: "keyword" | "model" | "auditor";
  confidence: "high" | "medium" | "low";
}
export interface ParsedRequest {
  items: ParsedRequestItem[];
  period_from: string | null;
  period_to: string | null;
  due_phrase: string;
  columns_stated: Record<string, string[]>;
  /** asks the parser could not place — for the auditor to resolve, never guessed */
  unmatched: string[];
  source: string;
  needs_confirmation: boolean;
  catalog: { key: string; label: string; kind: string; description: string;
             required_columns: string[] }[];
}

export type CalcStatus = "agree" | "disagree" | "not-checkable" | "ok";

export interface CalcQuerySpec {
  op: string;
  column?: string;
  document?: string;
  filters?: { column: string; op: string; value?: unknown }[];
}
export interface CalcResultDetail {
  status: string;
  value: number | null;
  matched: number;
  scanned: number;
  column: string;
  document: string;
  query: string;
  rows: Record<string, any>[];
  note: string;
}
export interface CalcAnswer {
  status: CalcStatus;
  answer: number | null;
  understood: string;
  note: string;
  detail: CalcResultDetail | Record<string, never>;
  source: string;
}
export interface AuditorCalculation {
  id: number;
  seq: number;
  label: string;
  method: string;
  stated: number;
  document: string;
  query: string;
  understood: string;
  status: CalcStatus;
  computed: number | null;
  delta: number;
  explanation: string;
  source: string;
  detail: Record<string, any>;
}
export interface CalcListing {
  calculations: AuditorCalculation[];
  documents: { filename: string; columns: string[]; row_count: number }[];
}

export interface StepEmail {
  step: "response-check" | "closure";
  kind: "follow-up" | "verdict";
  title: string;
  /** why this draft exists — a draft appears only when it has something to say */
  trigger: string;
  text: string;
  source: string;
  violations?: string[];
}
export interface StepEmails {
  case_id: string;
  emails: StepEmail[];
  findings: Finding[];
  exposure: Exposure;
}

export const parseRequestEmail = (id: string, text: string) =>
  postJSON<ParsedRequest>(`/cases/${id}/request-email/parse`, { text });

export const askCalc = (id: string, question: string, spec?: CalcQuerySpec) =>
  postJSON<CalcAnswer>(`/cases/${id}/calc/ask`, { question, spec });

export const checkCalc = (
  id: string,
  body: { label: string; method?: string; stated_amount: number;
          document_name?: string; spec?: CalcQuerySpec },
) => postJSON<AuditorCalculation>(`/cases/${id}/calc/check`, body);

export const listCalcs = (id: string) => getJSON<CalcListing>(`/cases/${id}/calc`);

export const deleteCalc = (id: string, calcId: number) =>
  fetch(`/api/cases/${id}/calc/${calcId}`, { method: "DELETE" }).then((r) => r.json());

export const getStepEmails = (id: string) => getJSON<StepEmails>(`/cases/${id}/emails`);
