"""Guards for the qualification pipeline — the properties sum-then-subtract could not hold.

Pure unit tests over synthetic line rows: no database, so they run with the rest of the suite.
"""
from datetime import date

import sqlite3

from app.pipeline.predicates import All, Any_, Col, Not, eq, gt, is_null, ne, not_in, not_null
from app.pipeline.rules import RULES, Action, rules_in_order
from app.pipeline.run import compose, deferred, qualify

PERIOD_FROM, PERIOD_TO = date(2025, 1, 1), date(2025, 3, 31)
ALL_ON = {"COR-01", "COR-02", "OUT-07", "INP-09"}


def line(tax, *, type_code=388, delivery=date(2025, 1, 10), category="S", rate=15,
         status="cleared", direction="sale", counterparty_class="", approval=None,
         sector=""):
    return {
        "type_code": type_code, "delivery_date": delivery, "issue_date": date(2025, 1, 10),
        "approval_date": approval, "counterparty_class": counterparty_class, "sector": sector,
        "category": category, "rate": rate, "status": status, "direction": direction,
        "tax_amount": float(tax), "taxable_amount": float(tax) / 0.15,
        "period_from": PERIOD_FROM, "period_to": PERIOD_TO, "invoice_uuid": f"INV-{tax}",
    }


def hero_rows():
    """The Al-Faisaliah shape: 20 in-period invoices, 2 delivered next period, 5 credit notes."""
    rows = [line(119_000) for _ in range(20)]
    rows += [line(50_000, delivery=date(2025, 4, 3)) for _ in range(2)]
    rows += [line(-61_000, type_code=381, delivery=date(2025, 2, 15)) for _ in range(5)]
    return rows


# ------------------------------------------------------- the arithmetic identity
def test_every_line_is_either_counted_or_accounted_for():
    """The funnel is a partition of the population, not a story told over one.

    This is the property that replaces the old waterfall identity, and it is stronger: a
    document either qualifies or appears in exactly one funnel step explaining why it does
    not. Nothing can be silently dropped, and nothing can be counted twice.
    """
    lines = qualify(hero_rows(), ALL_ON, "sale")
    comp = compose(lines, ALL_ON, "sale")
    assert comp.counted + sum(g["count"] for g in comp.funnel) == comp.population
    assert len({id(l) for g in comp.funnel for l in g["lines"]}) == \
        sum(g["count"] for g in comp.funnel)


def test_the_expected_figure_is_the_sum_of_what_qualified():
    """No baseline, no adjustments — the total is the qualifying lines, added up."""
    lines = qualify(hero_rows(), ALL_ON, "sale")
    comp = compose(lines, ALL_ON, "sale")
    assert comp.expected_vat == round(sum(l.tax_amount for l in comp.counted_lines), 2)
    assert comp.expected_vat == 2_075_000.0
    # the difference against a declared 2,000,000 is 75,000 immediately — no 480,000 artefact
    assert round(comp.expected_vat - 2_000_000, 2) == 75_000.0


def test_the_composition_adds_up_to_the_expected_figure():
    lines = qualify(hero_rows(), ALL_ON, "sale")
    comp = compose(lines, ALL_ON, "sale")
    assert round(sum(c["amount"] for c in comp.composition), 2) == comp.expected_vat
    # credit notes are part of the qualifying set, not a deduction from a larger one
    notes = next(c for c in comp.composition if c["type_code"] == 381)
    assert notes["amount"] < 0


# --------------------------------------------------- properties of the pipeline
def test_a_line_is_admitted_at_most_once():
    """Two rules cannot both act on the same document, so they cannot double-count it."""
    lines = qualify(hero_rows(), ALL_ON, "sale")
    for l in lines:
        settling = [d for d in l.decisions if d.verdict != "admitted"]
        assert len(settling) <= 1, [d.rule_code for d in settling]


def test_deferred_lines_leave_the_period():
    lines = qualify(hero_rows(), ALL_ON, "sale")
    out = deferred(lines)
    assert len(out) == 2
    assert round(sum(l.tax_amount for l in out), 2) == 100_000.0
    # and they are genuinely not in this period's sum
    assert all(not l.counted for l in out)
    comp = compose(lines, ALL_ON, "sale")
    assert comp.expected_vat == round(
        sum(l.tax_amount for l in lines if l.in_population)
        - sum(l.tax_amount for l in out), 2)


def test_credit_notes_are_summed_not_subtracted():
    """With COR-01 live the notes are part of the sum; disabling it drops them."""
    rows = hero_rows()
    on = compose(qualify(rows, ALL_ON, "sale"), ALL_ON, "sale")
    off_codes = ALL_ON - {"COR-01"}
    off = compose(qualify(rows, off_codes, "sale"), off_codes, "sale")
    assert on.expected_vat == 2_075_000.0
    assert off.expected_vat == 2_380_000.0       # notes no longer reduce output VAT
    assert round(off.expected_vat - on.expected_vat, 2) == 305_000.0


def test_structural_exclusions_are_not_toggleable():
    """A rejected document or a zero-rated line leaves the population whatever is enabled."""
    rows = [line(119_000, status="rejected"), line(0, category="Z", rate=0),
            line(50_000, rate=5)]
    for enabled in (ALL_ON, set()):
        lines = qualify(rows, enabled, "sale")
        assert all(not l.in_population for l in lines)
        assert compose(lines, enabled, "sale").expected_vat == 0.0


def test_tax_point_runs_before_adjustment():
    """A note must never land in a period its original has already left."""
    coded = [r.stage for r in rules_in_order("sale") if r.code]
    assert coded.index("tax-point") < coded.index("adjustment")


def test_input_box_mirrors_the_output_box():
    rows = [line(15_000, direction="purchase") for _ in range(10)]
    comp = compose(qualify(rows, ALL_ON, "purchase"), ALL_ON, "purchase")
    assert comp.expected_vat == 150_000.0


# ------------------------------------------------- predicate ⇄ SQL equivalence
def test_predicates_and_sql_select_the_same_lines():
    """The scale path: the same rule must select the same rows in Python and in SQL.

    Government rows are included deliberately. A rule scoped to a counterparty class whose
    scope lived outside the predicate would pass in Python and, in a batch run, fire on every
    taxpayer — so the scope belongs inside `sql_when()`, and this is what proves it.
    """
    rows = hero_rows() + [
        # supplied to a government body, approved after the period end -> OUT-11 territory
        line(60_000, counterparty_class="government", approval=date(2025, 5, 12)),
        line(60_000, counterparty_class="government", approval=date(2025, 3, 5)),
        # the same late approval on a commercial customer is NOT this rule
        line(60_000, approval=date(2025, 5, 12)),
    ]
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE line (type_code INT, delivery_date TEXT, approval_date TEXT, "
                "counterparty_class TEXT, sector TEXT, category TEXT, "
                "rate INT, status TEXT, direction TEXT, period_to TEXT, tax_amount REAL)")
    con.executemany(
        "INSERT INTO line VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [(r["type_code"], r["delivery_date"].isoformat() if r["delivery_date"] else None,
          r["approval_date"].isoformat() if r.get("approval_date") else None,
          r.get("counterparty_class", ""), r.get("sector", ""),
          r["category"], r["rate"], r["status"], r["direction"],
          r["period_to"].isoformat(), r["tax_amount"]) for r in rows])

    for rule in RULES:
        if rule.direction and rule.direction != "sale":
            continue
        sql = rule.sql_when().replace("DATE '", "'")     # sqlite compares ISO strings
        n_sql = con.execute(f"SELECT COUNT(*) FROM line WHERE {sql}").fetchone()[0]
        n_py = sum(1 for r in rows if rule.matches(r))
        assert n_sql == n_py, f"{rule.code or rule.stage}: sql={n_sql} python={n_py} :: {sql}"
    con.close()


def test_predicate_algebra_basics():
    row = {"a": 5, "b": None, "c": "x", "d": 5}
    assert eq("a", 5).evaluate(row) and not eq("a", 6).evaluate(row)
    assert eq("a", Col("d")).evaluate(row)
    assert ne("c", "y").evaluate(row)
    assert gt("a", 4).evaluate(row) and not gt("a", 5).evaluate(row)
    assert is_null("b").evaluate(row) and not_null("a").evaluate(row)
    assert not_in("c", ("y", "z")).evaluate(row)
    assert All(eq("a", 5), ne("c", "y")).evaluate(row)
    assert Any_(eq("a", 9), eq("c", "x")).evaluate(row)
    assert Not(eq("a", 9)).evaluate(row)
    # NULL compares false, as in SQL
    assert not gt("b", 1).evaluate(row)
