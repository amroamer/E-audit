"""Guards for the rule taxonomy and the reconciling-item registry.

Pure functions only — no database, so these run with the rest of `pytest backend/tests`.
"""
import re
from datetime import date

from app.reconciling_items import BOX_INPUT, BOX_OUTPUT, SPECS, specs_for, wired_codes
from app.rule_taxonomy import (
    KINDS, REASON_CODES, RULE_TAXONOMY, STAGES, classify,
)
from app.scope import scope_card
from app.seed.rulebook_loader import parse_rules


# ------------------------------------------------------------------ taxonomy
def test_every_rulebook_rule_is_classified():
    """A rule the loader produces must carry a kind, a stage and a reason code."""
    for r in parse_rules():
        assert r["rule_kind"] in KINDS, r["code"]
        assert r["stage"] in STAGES, r["code"]
        assert r["reason_code"] in REASON_CODES, r["code"]


def test_taxonomy_covers_the_whole_rulebook():
    codes = {r["code"] for r in parse_rules()}
    assert codes - set(RULE_TAXONOMY) == set(), "unclassified rules"
    assert set(RULE_TAXONOMY) - codes == set(), "taxonomy entries with no rule"


def test_taxonomy_values_are_valid():
    for code, (kind, stage, reason) in RULE_TAXONOMY.items():
        assert kind in KINDS, code
        assert stage in STAGES, code
        assert reason in REASON_CODES, code


def test_reason_codes_are_well_formed():
    for code, (group, label) in REASON_CODES.items():
        assert re.fullmatch(r"[TSDAR]\d{2}", code), code
        assert group in {"timing", "scope", "document", "accounting", "risk"}, code
        assert label


def test_unknown_rule_falls_back_instead_of_crashing():
    """A rule added to the rulebook before anyone classifies it still loads."""
    derived = classify("ZZZ-99", family="Compliance", gap_band="no")
    assert derived["rule_kind"] == "risk"
    assert derived["stage"] in STAGES
    assert derived["reason_code"] == ""


# ------------------------------------------------- reconciling-item registry
def test_specs_reference_real_rules():
    codes = {r["code"] for r in parse_rules()}
    for spec in SPECS:
        assert spec.rule in codes, spec.rule
        assert spec.box in (BOX_OUTPUT, BOX_INPUT)
        assert spec.sign in (1, -1)
        assert spec.label and spec.note


def test_wired_rules_are_classified_as_explanations():
    """Anything the bridge can draw must be an explanation, never a mistake or a risk flag."""
    taxonomy = dict(RULE_TAXONOMY)
    for code in wired_codes():
        assert taxonomy[code][0] == "explanation", code


def test_each_box_has_its_own_specs():
    assert {s.rule for s in specs_for(BOX_OUTPUT)} == {"COR-01", "OUT-07"}
    assert {s.rule for s in specs_for(BOX_INPUT)} == {"COR-02", "INP-09"}


class _Inv:
    def __init__(self, type_code, delivery):
        self.invoice_type_code = type_code
        self.delivery_date = delivery


def test_matchers_partition_the_population():
    period_to = date(2025, 3, 31)
    credit = _Inv(381, date(2025, 2, 15))
    in_period = _Inv(388, date(2025, 1, 10))
    straddling = _Inv(388, date(2025, 4, 3))

    cn_spec = next(s for s in SPECS if s.rule == "COR-01")
    lag_spec = next(s for s in SPECS if s.rule == "OUT-07")

    assert cn_spec.match(credit, period_to)
    assert not cn_spec.match(in_period, period_to)
    # a credit note is never also a timing line — the two lines cannot double-count
    assert not lag_spec.match(credit, period_to)
    assert not lag_spec.match(in_period, period_to)
    assert lag_spec.match(straddling, period_to)


def test_signs_move_the_bridge_the_right_way():
    """Credit notes arrive negative and pass through; timing removes a positive amount."""
    assert next(s for s in SPECS if s.rule == "COR-01").sign == 1
    assert next(s for s in SPECS if s.rule == "OUT-07").sign == -1


# ------------------------------------------------------------------- scope
def test_scope_card_tags_every_exclusion_with_a_real_reason_code():
    card = scope_card()
    assert card["in_scope"] and card["out_of_scope"]
    for row in card["out_of_scope"]:
        assert row["reason_code"] in REASON_CODES, row["item"]
        assert row["reason_label"], row["item"]
        assert row["note"]
