from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class NextBestAction(BaseModel):
    """Feature 2 — the single minimal evidence request for the unexplained difference."""

    action_type: Literal[
        "request-document", "request-reconciliation", "request-explanation",
        "field-visit", "no-action",
    ]
    document_requested: str = Field(
        description="The specific evidence to ask for, plain language. "
        "No digits — use a placeholder token (e.g. {{unexplained}}) if a value is unavoidable.")
    addressed_to: Literal["taxpayer", "tax-representative", "internal-review"]
    rationale: str = Field(description="Why this is the minimal step. Language only, no digits.")
    expected_yield: str = Field(
        description="What confirming/clearing this produces. Figures only as placeholders.")
    minimises_contact: bool = Field(
        description="True if answerable from evidence already held (cleared e-invoices, filed return).")


class LetterExtraction(BaseModel):
    """Feature 5 — read a taxpayer letter / case note and extract what it claims explains the gap.

    This is the ONE place Claude returns a figure: the amount the LETTER ITSELF states. It is a
    DRAFT — the auditor confirms (and may edit) the SAR value before it is committed as a response.
    """

    explains_gap: bool = Field(description="True if the letter plausibly explains part of the output-VAT difference.")
    category: Literal[
        "credit-notes", "timing", "prior-period", "zero-rated-or-exempt", "exports", "other", "none",
    ] = Field(description="The kind of explanation the taxpayer is offering.")
    summary: str = Field(description="One-sentence, plain-language summary of the taxpayer's claim, for the auditor.")
    quote: str = Field(description="The single most relevant sentence copied VERBATIM from the letter (≤200 chars).")
    proposed_amount: float = Field(
        description="The SAR figure the LETTER states this accounts for. 0 if the letter states no explicit amount. "
        "Never invent, estimate, or copy the difference.")
    confidence: Literal["high", "medium", "low"] = Field(description="Confidence that the letter supports this amount.")
    caveat: str = Field(description="What the auditor must still verify before accepting this (evidence required).")


class TaxpayerSummary(BaseModel):
    """Feature 3 — short auditor brief. STRICTLY figure-free (PDPL + F14)."""

    headline: str = Field(description="One-sentence orientation. No figures, no names beyond the alias.")
    points: list[str] = Field(
        min_length=2, max_length=5,
        description="2–5 salient facts grounded ONLY in the provided history. No figures.")
    risk_flags: list[str] = Field(
        default_factory=list, max_length=4,
        description="0–4 concrete risk signals from the data. Empty if none. No figures.")
    prior_pattern: str = Field(description="Recurring vs one-off pattern across prior periods. Language only.")
