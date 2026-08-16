"""Guards for the live Claude path, with the SDK stubbed so no key is needed.

`test_verify.py` proves the guard rejects bad prose in isolation. These tests prove the
boundary that uses it: that a compliant draft reaches the screen with the engine's figures
substituted, that a non-compliant one never does, and that every failure mode degrades to a
labelled deterministic draft instead of an error or unverified text.
"""
import json
import types

import pytest

from app.llm import service as svc

HERO = {
    "case_id": "CASE-TEST", "taxpayer": "Al-Faisaliah Trading Co.",
    "box": "Standard-rated sales VAT",
    "declared": 2_000_000.0, "reconstructed_gross": 2_480_000.0, "apparent_gap": 480_000.0,
    "explained_total": 405_000.0, "explained_pct": 0.8438, "residual": 75_000.0,
    "materiality": 10_000.0, "band": "material", "state": "potential-finding",
    "invoices_considered": 27, "expected_vat": 2_075_000.0,
    "bridge": [
        {"seq": 0, "kind": "anchor", "rule": None, "label": "Declared (as filed)",
         "amount": 2_000_000.0, "running": 2_000_000.0},
        {"seq": 1, "kind": "gap", "rule": None, "label": "Reconstructed from e-invoices",
         "amount": 480_000.0, "running": 2_480_000.0},
        {"seq": 2, "kind": "explain", "rule": "OUT-07", "label": "Clearance lag",
         "amount": -100_000.0, "running": 2_380_000.0},
        {"seq": 3, "kind": "explain", "rule": "COR-01", "label": "Credit notes netted",
         "amount": -305_000.0, "running": 2_075_000.0},
        {"seq": 4, "kind": "residual", "rule": None, "label": "Unexplained residual",
         "amount": 75_000.0, "running": 2_075_000.0},
    ],
}
SUPPORTED = {**HERO, "residual": 0.0, "state": "supported", "band": "immaterial", "explained_pct": 1.0}
RULES = [{"code": "COR-01", "family": "Corrections", "title": "Sales credit notes",
          "explains_gap": "Yes", "severity": "Medium"},
         {"code": "OUT-07", "family": "Output", "title": "Tax-point timing",
          "explains_gap": "Yes", "severity": "Medium"}]


# --------------------------------------------------------------- the stub SDK
class _Stream:
    def __init__(self, text, stop_reason=None):
        self.text_stream = [text]
        self._stop = stop_reason

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def get_final_message(self): return types.SimpleNamespace(stop_reason=self._stop)


def stub_client(*, prose=None, parsed=None, stop_reason=None, raises=False):
    """Build a fake anthropic client. `prose` may be a list, to script the retry."""
    drafts = list(prose) if isinstance(prose, list) else [prose]

    class Messages:
        def stream(self, **_kw):
            if raises:
                raise RuntimeError("connection reset")
            return _Stream(drafts.pop(0) if len(drafts) > 1 else drafts[0], stop_reason)

        def parse(self, **kw):
            if raises:
                raise RuntimeError("connection reset")
            model = kw["output_format"]
            return types.SimpleNamespace(
                stop_reason=stop_reason,
                parsed_output=model.model_validate(parsed),
                content=[types.SimpleNamespace(text=json.dumps(parsed))])

    return lambda: types.SimpleNamespace(messages=Messages())


@pytest.fixture
def live(monkeypatch):
    """Pretend a credential exists so availability() opens the live path."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(svc.settings, "llm_disabled", False, raising=False)
    monkeypatch.setattr(svc.settings, "data_is_synthetic", True, raising=False)


# ------------------------------------------------------------------ narration
GOOD = ("Reconstructed output VAT of {{reconstructed_gross}} exceeds the declared "
        "{{declared}}, an apparent gap of {{apparent_gap}}. COR-01 accounts for "
        "{{bridge.COR-01}} and OUT-07 for {{bridge.OUT-07}}, leaving {{residual}}.")


def test_compliant_draft_reaches_the_screen_with_engine_figures(live, monkeypatch):
    monkeypatch.setattr(svc, "_client", stub_client(prose=GOOD))
    out = svc.llm.narrate(HERO, RULES)
    assert out["source"] == "claude" and out["verified"] is True
    # placeholders replaced by the engine's own values
    assert "SAR 2,480,000" in out["text"] and "SAR 75,000" in out["text"]
    assert "{{" not in out["text"]
    # the pseudonym used for egress is not what the auditor sees
    assert "Taxpayer A" not in out["text"]


def test_fabricated_figure_never_reaches_the_screen(live, monkeypatch):
    bad = "The unexplained residual is SAR 90,000, which exceeds materiality."
    monkeypatch.setattr(svc, "_client", stub_client(prose=[bad, bad]))
    out = svc.llm.narrate(HERO, RULES)
    assert out["source"] == "blocked-unverified" and out["verified"] is False
    assert "90,000" not in out["text"]
    assert out["text"] == svc.fb_narration(HERO)      # the honest deterministic draft


def test_corrective_retry_can_rescue_a_bad_first_draft(live, monkeypatch):
    monkeypatch.setattr(svc, "_client", stub_client(prose=["Residual is SAR 90,000.", GOOD]))
    out = svc.llm.narrate(HERO, RULES)
    assert out["source"] == "claude" and "SAR 75,000" in out["text"]


def test_wrong_verdict_is_blocked_even_with_no_figures(live, monkeypatch):
    """The subtle failure: every number correct, the conclusion inverted."""
    wrong = "The case is fully explained and no further action is needed."
    monkeypatch.setattr(svc, "_client", stub_client(prose=[wrong, wrong]))
    out = svc.llm.narrate(HERO, RULES)
    assert out["source"] == "blocked-unverified"


def test_refusal_and_api_error_are_distinguished(live, monkeypatch):
    monkeypatch.setattr(svc, "_client", stub_client(prose=GOOD, stop_reason="refusal"))
    assert svc.llm.narrate(HERO, RULES)["source"] == "blocked-refusal"

    monkeypatch.setattr(svc, "_client", stub_client(raises=True))
    out = svc.llm.narrate(HERO, RULES)
    assert out["source"] == "api-error" and out["text"] == svc.fb_narration(HERO)


def test_no_credentials_is_not_an_api_error(monkeypatch):
    """A missing key must read as demo mode, never as a misconfigured integration."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_PROFILE", raising=False)
    out = svc.llm.narrate(HERO, RULES)
    assert out["source"] == "deterministic-fallback" and out["verified"] is True


# ------------------------------------------------------------ next best action
NBA_OK = {"action_type": "request-explanation",
          "document_requested": "A written reconciliation of the residual.",
          "addressed_to": "taxpayer", "rationale": "Only the residual remains.",
          "expected_yield": "Confirms or clears {{residual}}.", "minimises_contact": False}


def test_next_best_action_substitutes_placeholders(live, monkeypatch):
    monkeypatch.setattr(svc, "_client", stub_client(parsed=NBA_OK))
    out = svc.llm.next_best_action(HERO, RULES)
    assert out["source"] == "claude"
    assert out["expected_yield"] == "Confirms or clears SAR 75,000."


def test_engine_overrides_an_action_on_a_supported_case(live, monkeypatch):
    """The model may not invent work on a case the engine has already cleared."""
    monkeypatch.setattr(svc, "_client", stub_client(parsed=NBA_OK))
    out = svc.llm.next_best_action(SUPPORTED, RULES)
    assert out["source"] == "engine-override" and out["action_type"] == "no-action"


# ------------------------------------------------------------- taxpayer brief
def test_taxpayer_brief_rejects_any_digit(live, monkeypatch):
    profile = {"name": "Al-Faisaliah Trading Co.", "sector": "Wholesale", "size": "large"}
    bad = {"headline": "Wholesale trader with 3 prior cases.",
           "points": ["Sector: wholesale.", "Filed on time."],
           "risk_flags": [], "prior_pattern": "Recurring."}
    monkeypatch.setattr(svc, "_client", stub_client(parsed=bad))
    out = svc.llm.summarise_history(profile, [], [])
    assert out["source"] == "blocked-unverified"

    ok = {**bad, "headline": "Wholesale trader with prior audit history."}
    monkeypatch.setattr(svc, "_client", stub_client(parsed=ok))
    out = svc.llm.summarise_history(profile, [], [])
    assert out["source"] == "claude"
    assert "Taxpayer A" not in json.dumps(out)     # alias restored to the real name


# ------------------------------------------------------------------- report
def test_report_streams_verified_prose_then_done(live, monkeypatch):
    md = ("## Case summary\nReconstructed {{reconstructed_gross}} against {{declared}}.\n\n"
          "## Residual & conclusion\nA residual of {{residual}} remains; a potential finding.")
    monkeypatch.setattr(svc, "_client", stub_client(prose=md))
    frames = "".join(svc.llm.stream_report(HERO, RULES))
    assert "SAR 2,480,000" in frames and "{{" not in frames
    assert frames.rstrip().endswith("event: done\ndata: claude")


def test_report_falls_back_without_leaking_the_bad_draft(live, monkeypatch):
    bad = "## Case summary\nThe residual is SAR 90,000."
    monkeypatch.setattr(svc, "_client", stub_client(prose=[bad, bad]))
    frames = "".join(svc.llm.stream_report(HERO, RULES))
    assert "event: fallback" in frames          # tells the UI to clear any partial text
    assert "90,000" not in frames
    assert frames.rstrip().endswith("event: done\ndata: blocked-unverified")


# ------------------------------------------------------------- letter reader
def test_letter_reader_returns_the_letters_own_figure_as_a_draft(live, monkeypatch):
    parsed = {"explains_gap": True, "category": "prior-period",
              "summary": "The taxpayer says the difference was declared in an earlier return.",
              "quote": "already declared in our prior-period return",
              "proposed_amount": -75000.0, "confidence": "medium",
              "caveat": "Obtain the prior return before accepting."}
    monkeypatch.setattr(svc, "_client", stub_client(parsed=parsed))
    out = svc.llm.read_letter(HERO, "Dear Sir, the difference relates to Q4 2024...")
    assert out["source"] == "claude"
    assert out["proposed_amount"] == 75000.0      # normalised, and the auditor still confirms it


def test_letter_reader_without_credentials_says_so(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    out = svc.llm.read_letter(HERO, "Dear Sir...")
    assert out["source"] == "deterministic-fallback"
    assert out["proposed_amount"] == 0.0
