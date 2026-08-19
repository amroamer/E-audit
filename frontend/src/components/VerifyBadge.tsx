import type { AiSource } from "../ai/ai";

export default function VerifyBadge({ source, violations = [] }: { source: AiSource | null; violations?: string[] }) {
  if (source === null) return <span className="pill">AI writing…</span>;
  if (source === "claude" || source === "engine-override")
    return (
      <span className="pill pri-low" title="Every figure traces to the reconciliation engine.">
        ✓ Figures verified
      </span>
    );
  if (source === "deterministic-fallback")
    return (
      <span className="pill status" title="Written by the deterministic engine — no model configured.">
        ∑ Engine-drafted
      </span>
    );
  if (source === "pdpl-fallback")
    return (
      <span className="pill status" title="Hosted model not called on non-synthetic data (PDPL). The engine wrote this.">
        ∑ Engine-drafted (PDPL)
      </span>
    );
  if (source === "blocked-refusal")
    return (
      <span className="pill pri-medium" title="The model declined; showing deterministic draft.">
        Model declined
      </span>
    );
  if (source === "api-error" || source === "stream-error")
    return (
      <span className="pill pri-high" title="AI call failed — check configuration.">
        ⚠ AI unavailable — misconfigured
      </span>
    );
  return (
    <span className="pill pri-high" title={`Withheld: ${violations.join(", ")}`}>
      ⚠ AI output withheld — deterministic draft
    </span>
  );
}
