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
  Rulebook page changes which documents qualify, and so changes the expected figure.

Ordering is `rule_taxonomy.STAGES`, and it matters: a line is deferred to the next period
*before* notes are netted, so a note never lands in a period its original has left.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..rule_taxonomy import STAGES
from .predicates import Col, All, Predicate, eq, gt, is_in, ne, not_in, not_null

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
    label: str = ""                       # funnel caption, when it sets documents aside
    direction: str = ""                   # "" = both
    exclude_when_disabled: bool = False    # ADMIT rules: dropping the rule drops the lines
    # Scope. The auditors were explicit that the expected relationship varies by sector and by
    # who the counterparty is — a government supply may not be recognised until it clears
    # Etimad, months after the transaction period, and telecoms differ again. A rule that
    # applies to every taxpayer cannot express that, so both are matched like `direction`.
    sectors: tuple[str, ...] = ()          # () = every sector
    counterparty_class: str = ""           # "" = any counterparty

    def __post_init__(self):
        assert self.stage in STAGES, f"unknown stage {self.stage!r}"

    @property
    def structural(self) -> bool:
        return not self.code

    @property
    def scoped(self) -> bool:
        return bool(self.sectors or self.counterparty_class)

    def scope_predicate(self) -> Predicate:
        """`when`, narrowed by the rule's sector and counterparty scope.

        The scope has to live *inside* the predicate, not beside it. `sql_when()` is the
        set-based path for real volumes, and a scope applied only in Python would mean the
        batch job silently ran the rule on every taxpayer — the one bug the predicate algebra
        exists to prevent. `test_pipeline.py` asserts the two agree, government rows included.
        """
        parts: list[Predicate] = []
        if self.sectors:
            parts.append(is_in("sector", self.sectors))
        if self.counterparty_class:
            parts.append(eq("counterparty_class", self.counterparty_class))
        return All(*parts, self.when) if parts else self.when

    def sql_when(self) -> str:
        """The same test as a WHERE fragment — the set-based path for real volumes.

        `direction` is not included: a batch run partitions by direction, one pass per box.
        """
        return self.scope_predicate().to_sql()

    def matches(self, row: dict) -> bool:
        if self.direction and row.get("direction") != self.direction:
            return False
        return self.scope_predicate().evaluate(row)


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
    # The sector rule the auditors gave us. A supply to a government body is commonly not
    # recognised until the invoice clears the procurement platform, which can be months after
    # the transaction period — so the e-invoice sits in this period and the supply belongs to
    # a later return. Scoped by counterparty rather than applied to everyone, because that is
    # what makes it correct: the same delay on a commercial customer is not this rule.
    # It sits after OUT-07 so a straightforward delivery straddle keeps the simpler label.
    QualificationRule(
        code="OUT-11",
        stage="tax-point",
        action=Action.DEFER_NEXT,
        direction="sale",
        counterparty_class="government",
        when=All(ne("type_code", CREDIT_NOTE), not_null("approval_date"),
                 gt("approval_date", Col("period_to"))),
        reason_code="T02",
        label="Government supplies awaiting platform approval (Etimad)",
        note="Supplied to a government body and not yet approved on the procurement platform "
             "at the period end — recognition, and the output VAT, fall in a later return.",
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
