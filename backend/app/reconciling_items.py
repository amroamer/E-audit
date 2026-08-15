"""Declarative registry of the bridge's reconciling items.

Every line the reconciliation bridge can draw is declared here as data, instead
of being an `if` branch inside `recon_engine`. Wiring a new rule into the live
engine is then a matter of appending one `ReconcilingItem` — the engine needs no
change, the API reports the rule as wired, and the UI badges it automatically.

A spec fires only when **both** conditions hold:

1. its rule is present and enabled in `core.rule_library` (so disabling or
   deleting a rule in the Rulebook page removes the line from the bridge), and
2. the invoices it matches carry a non-trivial amount.

`sign` maps the matched invoices' VAT onto the bridge. Credit notes already
carry a negative tax amount, so they pass through at `+1`; timing lines remove a
positive amount from the reconstruction, so they invert at `-1`.

Note what is *not* here: whether an invoice belongs in the reconstructed gross at
all. That is a population question, settled structurally in `recon_engine`
(a credit note is never part of gross, whatever the rulebook says), so disabling
COR-01 drops the explanation without silently restating the reconstruction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Callable

from .rule_taxonomy import REASON_CODES

BOX_OUTPUT = "output"
BOX_INPUT = "input"

CREDIT_NOTE = 381


@dataclass(frozen=True)
class ReconcilingItem:
    """One potential bridge line."""

    rule: str                                   # rule code in core.rule_library
    box: str                                    # BOX_OUTPUT | BOX_INPUT
    label: str                                  # shown on the bridge row
    note: str                                   # shown in the drill-down popup
    match: Callable[[object, date], bool]       # (invoice, period_to) -> in this line?
    sign: int = 1                               # +1 keeps the sign, -1 inverts it

    @property
    def reason_code(self) -> str:
        from .rule_taxonomy import classify
        return classify(self.rule)["reason_code"]

    @property
    def reason_label(self) -> str:
        entry = REASON_CODES.get(self.reason_code)
        return entry[1] if entry else ""


# ------------------------------------------------------------------ matchers
def _credit_note(inv, _period_to) -> bool:
    return inv.invoice_type_code == CREDIT_NOTE


def _delivered_next_period(inv, period_to) -> bool:
    """Issued inside the period, supplied after it — the supply belongs to the next return."""
    return (inv.invoice_type_code != CREDIT_NOTE
            and inv.delivery_date is not None
            and inv.delivery_date > period_to)


# --------------------------------------------------------------- the registry
SPECS: tuple[ReconcilingItem, ...] = (
    ReconcilingItem(
        rule="COR-01",
        box=BOX_OUTPUT,
        label="Credit notes (381) already applied in the return",
        note="These credit notes (type 381) are already reflected in the taxpayer's declared "
             "figure, so they are removed from the reconstructed total to avoid double-counting.",
        match=_credit_note,
        sign=1,
    ),
    ReconcilingItem(
        rule="OUT-07",
        box=BOX_OUTPUT,
        label="Clearance lag — invoices delivered in the next period",
        note="Issued within the period but delivered in the next period (tax-point / clearance "
             "lag) — the supply belongs to the following return.",
        match=_delivered_next_period,
        sign=-1,
    ),
    ReconcilingItem(
        rule="COR-02",
        box=BOX_INPUT,
        label="Supplier credit notes (381) reducing recoverable input",
        note="Supplier credit notes (type 381) reduce recoverable input VAT and are already "
             "reflected in the declared figure.",
        match=_credit_note,
        sign=1,
    ),
    ReconcilingItem(
        rule="INP-09",
        box=BOX_INPUT,
        label="Input claimed in the wrong / a late period",
        note="Purchase invoices delivered in the next period — the input belongs to the "
             "following return.",
        match=_delivered_next_period,
        sign=-1,
    ),
)


def specs_for(box: str) -> tuple[ReconcilingItem, ...]:
    return tuple(s for s in SPECS if s.box == box)


def wired_codes() -> frozenset[str]:
    """Rule codes the live engine can actually draw a bridge line for."""
    return frozenset(s.rule for s in SPECS)
