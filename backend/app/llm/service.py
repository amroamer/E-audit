"""The single Claude boundary for E-AUDIT Phase 2.

Four features, one class:
  1. narrate            -> prose  (streamed internally, returned whole + verdict)
  2. next_best_action   -> structured (schema-validated)
  3. summarise_history  -> structured (schema-validated, figure-free)
  4. stream_report      -> prose  (STREAMED as SSE)

Division of labour (NON-NEGOTIABLE): recon_engine.reconcile_case computes EVERY
number. Claude writes LANGUAGE ONLY and emits figures ONLY as placeholder tokens
({{difference}}, {{step.OUT-07}}, ...). verify_claims/verify_conclusion validate the
output against the recon dict BEFORE anything is shown; render_placeholders then
substitutes the engine's exact values.

PDPL: the DEMO calls hosted Claude on SYNTHETIC data only, and only when
settings.data_is_synthetic is True. PRODUCTION swaps an in-tenant model behind THIS
interface by pointing _client() at an in-VPC gateway (settings.anthropic_base_url) —
zero call-site change. Nothing outside this module imports `anthropic`.
"""
from __future__ import annotations

import os
from typing import Iterator

from ..config import settings
from .schemas import NextBestAction, TaxpayerSummary, LetterExtraction
from .prompts import (
    FROZEN_PREAMBLE, build_context, build_history_context,
    NARRATE_INSTR, NBA_INSTR, SUMMARY_INSTR, REPORT_INSTR,
    LETTER_SYSTEM, LETTER_INSTR, build_letter_context, fence_letter,
    DRAFT_LETTER_SYSTEM, DRAFT_REQUEST_INSTR, DRAFT_FOLLOWUP_INSTR,
    DRAFT_VERDICT_INSTR, fence_facts,
)
from .verify import (
    verify_claims, verify_conclusion, verify_correspondence, render_placeholders, StreamGuard,
    fb_narration, fb_nba, fb_summary, fb_report,
)

MODEL = settings.claude_model  # "claude-opus-5"
_ALIAS = "Taxpayer A"          # PDPL pseudonym sent to a hosted model (F7)


class _Refusal(Exception):
    ...


# ---------------------------------------------------------------- availability
def _is_public_endpoint() -> bool:
    base = (os.getenv("ANTHROPIC_BASE_URL") or settings.anthropic_base_url or "").lower()
    return ("api.anthropic.com" in base) or base == ""  # default SDK base is public


def availability() -> tuple[bool, str]:
    """Returns (enabled, reason). reason is machine-readable for the UI badge (F11)."""
    if settings.llm_disabled or os.getenv("EAUDIT_LLM_DISABLED") == "1":
        return False, "disabled"
    has_cred = bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
                    or os.getenv("ANTHROPIC_PROFILE"))
    if not has_cred:
        return False, "no-credentials"
    if not settings.data_is_synthetic and _is_public_endpoint() and not settings.allow_hosted_egress:
        return False, "pdpl-blocked"
    return True, "claude"


def _client():
    import anthropic
    kwargs = {}
    if settings.anthropic_base_url:
        kwargs["base_url"] = settings.anthropic_base_url  # the ONLY prod swap point
    return anthropic.Anthropic(**kwargs)  # resolves key / token / ant profile


# ------------------------------------------------------------- message assembly
def _system_blocks() -> list:
    return [{"type": "text", "text": FROZEN_PREAMBLE, "cache_control": {"type": "ephemeral"}}]


def _user_blocks(context: str, instr: str, ask: str) -> list:
    # F6: ALL untrusted case data lives here, in the user turn — never system.
    return [
        {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": instr},
        {"type": "text", "text": ask},
    ]


def _parsed(resp, model_cls):
    for attr in ("parsed_output", "parsed", "output_parsed"):
        obj = getattr(resp, attr, None)
        if isinstance(obj, model_cls):
            return obj
        if isinstance(obj, dict):
            return model_cls.model_validate(obj)
    return model_cls.model_validate_json(resp.content[0].text)


def _src(reason: str) -> str:
    return {"no-credentials": "deterministic-fallback", "disabled": "deterministic-fallback",
            "pdpl-blocked": "pdpl-fallback"}.get(reason, reason)


def _guard(text: str, recon: dict) -> dict:
    """verify_claims AND verify_conclusion — a wrong verdict is as fatal as a wrong figure (F1)."""
    v = verify_claims(text, recon)
    concl = verify_conclusion(text, recon)
    if concl:
        return {"ok": False, "violations": v["violations"] + concl}
    return v


def _render_nba(nba: NextBestAction, recon: dict) -> dict:
    d = nba.model_dump()
    for k in ("expected_yield", "document_requested", "rationale"):
        d[k] = render_placeholders(d[k], recon)
    return d


def _sse_token(text: str) -> str:
    return "event: token\ndata: " + text.replace("\n", "\ndata: ") + "\n\n"


def _sse(name: str, payload: str) -> str:
    return f"event: {name}\ndata: {payload}\n\n"


# =============================================================================
class LLMService:

    # ------------------------------------------------- FEATURE 1: BRIDGE NARRATION
    def _prose(self, ctx: str, instr: str, ask: str, max_tokens: int) -> tuple[str, str | None]:
        try:
            with _client().messages.stream(
                model=MODEL, max_tokens=max_tokens, thinking={"type": "adaptive"},
                system=_system_blocks(),
                messages=[{"role": "user", "content": _user_blocks(ctx, instr, ask)}],
            ) as stream:
                raw = "".join(stream.text_stream)
                if stream.get_final_message().stop_reason == "refusal":
                    return "", "blocked-refusal"
            return raw, None
        except Exception:
            return "", "api-error"

    def narrate(self, recon: dict, rules: list) -> dict:
        enabled, reason = availability()
        if not enabled:
            return {"text": fb_narration(recon), "source": _src(reason), "verified": True,
                    "mode": "fallback", "violations": []}
        ctx, unmask = build_context(recon, rules, alias=_ALIAS)
        raw, err = self._prose(ctx, NARRATE_INSTR, "Produce the narration now.", 700)
        if err:
            return {"text": fb_narration(recon), "source": err, "verified": False,
                    "mode": "fallback", "violations": [err]}
        v = _guard(raw, recon)
        if not v["ok"]:
            corr = ("Produce the narration now. Your earlier draft was REJECTED for: "
                    + "; ".join(v["violations"])
                    + ". Rewrite with NO digit and NO scale/comparison word (never 'twice', 'half', "
                    "'double', 'quarter', 'a third', 'thousand', 'million'); reference every figure "
                    "ONLY as an allowed placeholder token.")
            raw2, err2 = self._prose(ctx, NARRATE_INSTR, corr, 700)
            if not err2 and _guard(raw2, recon)["ok"]:
                return {"text": unmask(render_placeholders(raw2, recon)),
                        "source": "claude", "verified": True, "mode": "live", "violations": []}
            return {"text": fb_narration(recon), "source": "blocked-unverified",
                    "verified": False, "mode": "fallback", "violations": v["violations"]}
        return {"text": unmask(render_placeholders(raw, recon)),
                "source": "claude", "verified": True, "mode": "live", "violations": []}

    # ------------------------------------------------- FEATURE 2: NEXT-BEST-ACTION
    def next_best_action(self, recon: dict, rules: list) -> dict:
        immaterial = recon["state"] == "supported" or abs(recon["unexplained"]) <= recon["materiality"]

        enabled, reason = availability()
        if not enabled:
            return {**_render_nba(fb_nba(recon), recon), "source": _src(reason),
                    "verified": True, "violations": []}
        ctx, _unmask = build_context(recon, rules, alias=_ALIAS)
        try:
            resp = _client().messages.parse(
                model=MODEL, max_tokens=800, thinking={"type": "adaptive"},
                system=_system_blocks(),
                messages=[{"role": "user",
                           "content": _user_blocks(ctx, NBA_INSTR, "Decide the next best action now.")}],
                output_format=NextBestAction,
            )
            if resp.stop_reason == "refusal":
                raise _Refusal()
            nba = _parsed(resp, NextBestAction)
        except _Refusal:
            return {**_render_nba(fb_nba(recon), recon), "source": "blocked-refusal",
                    "verified": False, "violations": ["refusal"]}
        except Exception:
            return {**_render_nba(fb_nba(recon), recon), "source": "api-error",
                    "verified": False, "violations": ["api-error"]}

        if immaterial and nba.action_type != "no-action":       # engine override (F2)
            out = _render_nba(fb_nba(recon), recon)
            out.update(source="engine-override", verified=True, violations=[])
            return out

        probe = " ".join([nba.document_requested, nba.rationale, nba.expected_yield])
        v = _guard(probe, recon)
        if not v["ok"]:
            return {**_render_nba(fb_nba(recon), recon), "source": "blocked-unverified",
                    "verified": False, "violations": v["violations"]}
        return {**_render_nba(nba, recon), "source": "claude", "verified": True, "violations": []}

    # ---------------------------------------------- FEATURE 3: TAXPAYER-HISTORY SUMMARY
    def summarise_history(self, profile: dict, prior_returns: list, prior_cases: list) -> dict:
        enabled, reason = availability()
        if not enabled:
            return {**fb_summary(profile, prior_returns, prior_cases), "source": _src(reason),
                    "verified": True, "violations": []}
        ctx = build_history_context(profile, prior_returns, prior_cases, alias=_ALIAS)
        try:
            resp = _client().messages.parse(
                model=MODEL, max_tokens=900, thinking={"type": "adaptive"},
                system=_system_blocks(),
                messages=[{"role": "user",
                           "content": [{"type": "text", "text": ctx, "cache_control": {"type": "ephemeral"}},
                                       {"type": "text", "text": SUMMARY_INSTR},
                                       {"type": "text", "text": "Write the taxpayer brief now."}]}],
                output_format=TaxpayerSummary,
            )
            if resp.stop_reason == "refusal":
                raise _Refusal()
            s = _parsed(resp, TaxpayerSummary)
        except _Refusal:
            return {**fb_summary(profile, prior_returns, prior_cases), "source": "blocked-refusal",
                    "verified": False, "violations": ["refusal"]}
        except Exception:
            return {**fb_summary(profile, prior_returns, prior_cases), "source": "api-error",
                    "verified": False, "violations": ["api-error"]}

        probe = " ".join([s.headline, s.prior_pattern, *s.points, *s.risk_flags])
        v = verify_claims(probe, recon=None, figure_free=True)   # reject ANY numeric literal
        if not v["ok"]:
            return {**fb_summary(profile, prior_returns, prior_cases), "source": "blocked-unverified",
                    "verified": False, "violations": v["violations"]}
        out = s.model_dump()
        real = profile.get("name") or ""
        if real:                                                 # restore the real name for display
            out["headline"] = out["headline"].replace(_ALIAS, real)
            out["prior_pattern"] = out["prior_pattern"].replace(_ALIAS, real)
            out["points"] = [p.replace(_ALIAS, real) for p in out["points"]]
            out["risk_flags"] = [f.replace(_ALIAS, real) for f in out["risk_flags"]]
        return {**out, "source": "claude", "verified": True, "violations": []}

    # ------------------------------------------------- FEATURE 4: AI-DRAFTED REPORT
    def stream_report(self, recon: dict, rules: list) -> Iterator[str]:
        """Yields SSE frames. Verified + placeholder-substituted per segment BEFORE it
        leaves the server (StreamGuard). Every terminal branch emits `fallback` then `done`."""
        enabled, reason = availability()
        if not enabled:
            yield _sse_token(fb_report(recon))
            yield _sse("done", _src(reason))
            return

        ctx, unmask = build_context(recon, rules, alias=_ALIAS)
        raw, err = self._prose(ctx, REPORT_INSTR, "Draft the report now.", 2200)
        if not err:
            v = _guard(raw, recon)
            if not v["ok"]:
                corr = ("Draft the report now. Your earlier draft was REJECTED for: "
                        + "; ".join(v["violations"][:6])
                        + ". Rewrite keeping EXACTLY the four sections, with NO digit and NO scale/"
                        "comparison word (never 'twice', 'half', 'double', 'a third', 'thousand', "
                        "'million'); reference every figure ONLY as an allowed placeholder token.")
                raw2, err2 = self._prose(ctx, REPORT_INSTR, corr, 2200)
                if not err2 and _guard(raw2, recon)["ok"]:
                    raw = raw2
                else:
                    err = "blocked-unverified"
        if err:
            yield _sse("fallback", "")
            yield _sse_token(fb_report(recon))
            yield _sse("done", err if err in ("blocked-refusal", "api-error") else "blocked-unverified")
            return
        # verified — substitute the engine's figures, then stream line-by-line for the typing effect
        text = unmask(render_placeholders(raw, recon))
        for line in text.split("\n"):
            yield _sse_token(line + "\n")
        yield _sse("done", "claude")

    # ------------------------------------------------- FEATURE 5: TAXPAYER-LETTER READER
    def read_letter(self, recon: dict, letter_text: str) -> dict:
        """Read a taxpayer letter / case note and extract its claimed explanation as a DRAFT.

        Unlike the other features, this returns the SAR figure the letter itself states — it is a
        suggestion the auditor confirms (and may edit) before it is committed as a response.
        """
        fallback = {
            "explains_gap": False, "category": "none",
            "summary": "Automated reading is unavailable — review the letter and enter the amount by hand.",
            "quote": "", "proposed_amount": 0.0, "confidence": "low",
            "caveat": "Enter and confirm the amount manually from the letter.",
        }
        text = (letter_text or "").strip()
        if not text:
            return {**fallback, "summary": "Paste a taxpayer letter or case note to analyse.",
                    "source": "deterministic-fallback"}
        enabled, reason = availability()
        if not enabled:
            return {**fallback, "source": _src(reason)}
        try:
            resp = _client().messages.parse(
                model=MODEL, max_tokens=900, thinking={"type": "adaptive"},
                system=[{"type": "text", "text": LETTER_SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": build_letter_context(recon)},
                    {"type": "text", "text": LETTER_INSTR},
                    {"type": "text", "text": fence_letter(text[:6000])},
                ]}],
                output_format=LetterExtraction,
            )
            if resp.stop_reason == "refusal":
                raise _Refusal()
            ext = _parsed(resp, LetterExtraction)
        except _Refusal:
            return {**fallback, "source": "blocked-refusal"}
        except Exception:
            return {**fallback, "source": "api-error"}
        out = ext.model_dump()
        out["proposed_amount"] = round(abs(float(out.get("proposed_amount") or 0.0)), 2)  # auditor confirms
        return {**out, "source": "claude"}

    # ------------------------------------------------- FEATURE 6: OUTBOUND CORRESPONDENCE
    def draft_letter(self, *, kind: str, facts: str, fallback) -> dict:
        """Draft an information request or a follow-up from engine-established facts.

        The placeholder model does not fit a letter that quotes documents rather than
        reconciliation scalars, so the guard is `verify_correspondence`: every numeric literal
        in the draft must already appear in the facts block. Same rule, stated for prose —
        Claude may repeat a figure it was handed, and may not introduce one.

        `fallback` is a callable producing the deterministic letter, which is complete and
        sendable English. Degrading to it costs polish, never correctness.
        """
        instr = {"follow-up": DRAFT_FOLLOWUP_INSTR,
                 "verdict": DRAFT_VERDICT_INSTR}.get(kind, DRAFT_REQUEST_INSTR)
        enabled, reason = availability()
        if not enabled:
            return {"text": fallback(), "source": _src(reason), "verified": True,
                    "mode": "fallback", "violations": []}

        def _write(ask: str) -> tuple[str, str | None]:
            try:
                with _client().messages.stream(
                    model=MODEL, max_tokens=1400, thinking={"type": "adaptive"},
                    system=[{"type": "text", "text": DRAFT_LETTER_SYSTEM,
                             "cache_control": {"type": "ephemeral"}}],
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": fence_facts(facts)},
                        {"type": "text", "text": instr},
                        {"type": "text", "text": ask},
                    ]}],
                ) as stream:
                    raw = "".join(stream.text_stream)
                    if stream.get_final_message().stop_reason == "refusal":
                        return "", "blocked-refusal"
                return raw, None
            except Exception:
                return "", "api-error"

        raw, err = _write("Draft the letter now.")
        if err:
            return {"text": fallback(), "source": err, "verified": False,
                    "mode": "fallback", "violations": [err]}
        v = verify_correspondence(raw, facts)
        if not v["ok"]:
            corr = ("Draft the letter now. Your earlier draft was REJECTED for: "
                    + "; ".join(v["violations"])
                    + ". Rewrite using ONLY figures that appear verbatim in the FACTS block, and "
                      "no scale or comparison words.")
            raw2, err2 = _write(corr)
            if not err2 and verify_correspondence(raw2, facts)["ok"]:
                return {"text": raw2.strip(), "source": "claude", "verified": True,
                        "mode": "live", "violations": []}
            return {"text": fallback(), "source": "blocked-unverified", "verified": False,
                    "mode": "fallback", "violations": v["violations"]}
        return {"text": raw.strip(), "source": "claude", "verified": True,
                "mode": "live", "violations": []}


llm = LLMService()  # module singleton
