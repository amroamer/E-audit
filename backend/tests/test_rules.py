"""Guards for the rule taxonomy and the reconciling-item registry.

Pure functions only — no database, so these run with the rest of `pytest backend/tests`.
"""
import re
from datetime import date

from app.pipeline.rules import RULES, coded_rules, rules_in_order
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


# --------------------------------------------------- qualification registry
def test_coded_rules_reference_real_rules():
    codes = {r["code"] for r in parse_rules()}
    for rule in RULES:
        if rule.structural:
            continue
        assert rule.code in codes, rule.code
        assert rule.label and rule.note


def test_wired_rules_are_classified_as_explanations():
    """Anything that changes the expected return must be an explanation, not a mistake or risk."""
    taxonomy = dict(RULE_TAXONOMY)
    for code in coded_rules():
        assert taxonomy[code][0] == "explanation", code


def test_each_direction_gets_its_own_rules():
    assert {r.code for r in rules_in_order("sale") if r.code} == {"COR-01", "OUT-07", "OUT-11"}
    assert {r.code for r in rules_in_order("purchase") if r.code} == {"COR-02", "INP-09"}


def test_rules_run_in_stage_order():
    """A line must be deferred before notes are netted, or a note lands in a period its
    original has left."""
    for direction in ("sale", "purchase"):
        stages = [STAGES.index(r.stage) for r in rules_in_order(direction)]
        assert stages == sorted(stages)
        coded = [r.stage for r in rules_in_order(direction) if r.code]
        assert coded.index("tax-point") < coded.index("adjustment")


def _line(type_code, delivery, category="S", rate=15, status="cleared"):
    return {"type_code": type_code, "delivery_date": delivery, "category": category,
            "rate": rate, "status": status, "direction": "sale",
            "period_to": date(2025, 3, 31), "tax_amount": 100.0, "taxable_amount": 666.67}


def test_predicates_partition_the_population():
    credit = _line(381, date(2025, 2, 15))
    in_period = _line(388, date(2025, 1, 10))
    straddling = _line(388, date(2025, 4, 3))

    cn = next(r for r in RULES if r.code == "COR-01")
    lag = next(r for r in RULES if r.code == "OUT-07")

    assert cn.matches(credit)
    assert not cn.matches(in_period)
    # a credit note is never also a timing line — the two cannot double-count the same doc
    assert not lag.matches(credit)
    assert not lag.matches(in_period)
    assert lag.matches(straddling)


def test_every_rule_emits_sql():
    """The scale path: each rule's predicate must render as a WHERE fragment."""
    for rule in RULES:
        sql = rule.sql_when()
        assert sql and "None" not in sql, rule.code or rule.stage


# ------------------------------------------------------------------- scope
def test_scope_card_tags_every_exclusion_with_a_real_reason_code():
    card = scope_card()
    assert card["in_scope"] and card["out_of_scope"]
    for row in card["out_of_scope"]:
        assert row["reason_code"] in REASON_CODES, row["item"]
        assert row["reason_label"], row["item"]
        assert row["note"]
