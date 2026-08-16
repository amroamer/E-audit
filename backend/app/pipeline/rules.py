"""The qualification registry — what counts, for which period, in which box.

This replaces `reconciling_items.py`. The difference is not cosmetic: those items were
subtractions applied to a finished total, so they could only ever *reduce a number*. A
qualification rule acts on a line **before** anything is summed, so it can also move the
line to another period or another box — which a subtraction cannot express.

Two kinds of entry live here:

* **structural** rules (no rulebook code) draw the population boundary. They are not
  toggleable, because a rejected document or a zero-rated line is not "an explanation the
  auditor may switch off" — it is simply not part of this box.
* **coded** rules carry a `core.rule_library` code and fire only while that rule is
  enabled. Disabling one changes the expected return, exactly as toggling it in the
  Rulebook page changes the bridge today.

Ordering is `rule_taxonomy.STAGES`, and it matters: a line is deferred to the next period
*before* notes are netted, so a note never lands in a period its original has left.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..rule_taxonomy import STAGES
from .predicates import Col, All, Predicate, eq, gt, ne, not_in, not_null

CREDIT_NOTE = 381

# the boxes this PoC reconstructs (see app/scope.py for everything it does not)
BOX_SALES = "standard_rate_sales"
BOX_PURCHASE = "standard_rate_purchase"
BOX_BY_DIRECTION = {"sale": BOX_SALES, "purchase": BOX_PURCHASE}


class Action(str, Enum):
    ADMIT = "admit"            # keep the line in this period's expected return
    EXCLUDE = "exclude"        # it is not part of this box at all
    DEFER_NEXT = "defer-next"  # it belongs to the following period


@dataclass(frozen=True)
class QualificationRule:
    stage: str
    action: Action
    when: Predicate
    reason_code: str
    note: str
    code: str = ""                        # rule_library code; "" = structural
    label: str = ""                       # bridge caption, when it moves an amount
    direction: str = ""                   # "" = both
    exclude_when_disabled: bool = False    # ADMIT rules: dropping the rule drops the lines

    def __post_init__(self):
        assert self.stage in STAGES, f"unknown stage {self.stage!r}"

    @property
    def structural(self) -> bool:
        return not self.code

    def sql_when(self) -> str:
        """The same test as a WHERE fragment — the set-based path for real volumes."""
        return self.when.to_sql()

    def matches(self, row: dict) -> bool:
        if self.direction and row.get("direction") != self.direction:
            return False
        return self.when.evaluate(row)


RULES: tuple[QualificationRule, ...] = (
    # ---------------------------------------------------------------- status
    QualificationRule(
        stage="status",
        action=Action.EXCLUDE,
        when=not_in("status", ("cleared", "reported")),
        reason_code="D06",
        note="Rejected, cancelled or superseded documents are not evidence of a supply.",
    ),
    # -------------------------------------------------------------- category
    # Only standard-rated 15% maps to a box this PoC reconstructs. Zero-rated, exempt and
    # out-of-scope lines are excluded here rather than silently never summed.
    QualificationRule(
        stage="category",
        action=Action.EXCLUDE,
        when=ne("category", "S"),
        reason_code="S01",
        note="Not standard-rated. Zero-rated, exempt and out-of-scope boxes are outside this PoC.",
    ),
    QualificationRule(
        stage="category",
        action=Action.EXCLUDE,
        when=All(eq("category", "S"), ne("rate", 15)),
        reason_code="R07",
        note="Standard-rated at a rate other than 15% — the 5% transitional box is out of scope.",
    ),
    # ------------------------------------------------------------- tax-point
    QualificationRule(
        code="OUT-07",
        stage="tax-point",
        action=Action.DEFER_NEXT,
        direction="sale",
        when=All(ne("type_code", CREDIT_NOTE), not_null("delivery_date"),
                 gt("delivery_date", Col("period_to"))),
        reason_code="T02",
        label="Clearance lag — invoices delivered in the next period",
        note="Issued within the period but delivered in the next period (tax-point / clearance "
             "lag) — the supply belongs to the following return.",
    ),
    QualificationRule(
        code="INP-09",
        stage="tax-point",
        action=Action.DEFER_NEXT,
        direction="purchase",
        when=All(ne("type_code", CREDIT_NOTE), not_null("delivery_date"),
                 gt("delivery_date", Col("period_to"))),
        reason_code="T02",
        label="Input claimed in the wrong / a late period",
        note="Purchase invoices delivered in the next period — the input belongs to the "
             "following return.",
    ),
    # ------------------------------------------------------------ adjustment
    # Credit notes are part of the correct sum, not a subtraction from a finished one: they
    # carry a negative tax amount and are simply admitted. Disabling the rule drops them.
    QualificationRule(
        code="COR-01",
        stage="adjustment",
        action=Action.ADMIT,
        direction="sale",
        when=eq("type_code", CREDIT_NOTE),
        reason_code="D03",
        label="Credit notes (381) netted against sales",
        note="Credit notes reduce output VAT and belong in the expected return. Disabling "
             "COR-01 removes them from the reconstruction.",
        exclude_when_disabled=True,
    ),
    QualificationRule(
        code="COR-02",
        stage="adjustment",
        action=Action.ADMIT,
        direction="purchase",
        when=eq("type_code", CREDIT_NOTE),
        reason_code="D03",
        label="Supplier credit notes (381) netted against purchases",
        note="Supplier credit notes reduce recoverable input VAT and belong in the expected "
             "return. Disabling COR-02 removes them from the reconstruction.",
        exclude_when_disabled=True,
    ),
)

STAGE_ORDER = {s: i for i, s in enumerate(STAGES)}


def rules_in_order(direction: str = "") -> tuple[QualificationRule, ...]:
    sel = [r for r in RULES if not r.direction or not direction or r.direction == direction]
    return tuple(sorted(sel, key=lambda r: STAGE_ORDER[r.stage]))


def coded_rules() -> frozenset[str]:
    """Rule-library codes the pipeline can act on — drives the API's `wired` flag."""
    return frozenset(r.code for r in RULES if r.code)
