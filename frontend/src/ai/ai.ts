export type AiSource =
  | "claude"
  | "engine-override"
  | "deterministic-fallback"
  | "pdpl-fallback"
  | "api-error"
  | "blocked-unverified"
  | "blocked-refusal"
  | "stream-error";

export interface Narration {
  text: string;
  source: AiSource;
  verified: boolean;
  mode: string;
  violations: string[];
}
export interface Nba {
  action_type: string;
  document_requested: string;
  addressed_to: string;
  rationale: string;
  expected_yield: string;
  minimises_contact: boolean;
  source: AiSource;
  verified: boolean;
  violations: string[];
}
export interface Summary {
  headline: string;
  points: string[];
  risk_flags: string[];
  prior_pattern: string;
  source: AiSource;
  verified: boolean;
  violations: string[];
}

const j = async <T>(p: string): Promise<T> => {
  const r = await fetch("/api" + p);
  if (!r.ok) throw new Error(r.statusText);
  return r.json() as Promise<T>;
};

export const getNarration = (id: string) => j<Narration>(`/cases/${id}/narrate`);
export const getNba = (id: string) => j<Nba>(`/cases/${id}/nba`);
export const getSummary = (id: string) => j<Summary>(`/cases/${id}/summary`);
