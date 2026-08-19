"""core schema — the internally-held evidence the auditor consults *before* contacting anyone.

The auditors were explicit: a case starts with the risk engine's output, and the auditor then
investigates what ZATCA already holds — returns, e-invoices, imports/exports, taxpayer history,
prior audits, internal financials — and only then asks the taxpayer for what is genuinely
missing. Returns and e-invoices live in `core.py`; the rest lives here.

Prior audits are *not* a table of their own: a closed `AuditCase` already carries the outcome
labels and now the correspondence record, so the history and the precedent corpus are the same
population.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Numeric, Date, DateTime, Boolean, Text, ForeignKey, JSON, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base
from .core import AuditCase  # noqa: F401  (relationship target)

SCHEMA = "core"
Money = Numeric(16, 2)


class RiskReferral(Base):
    """The risk engine's output, as a structured object rather than three flattened columns.

    The engine is out of scope for this PoC — we consume it. Keeping the indicator, the
    contributing signals and the score separate is what lets the precedent agent ask "what
    happened the last twenty times the engine said *this*", which a free-text reason cannot.
    """
    __tablename__ = "risk_referral"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_ref: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.audit_case.id"), unique=True)
    indicator_code: Mapped[str] = mapped_column(String(40), index=True)   # e.g. SALES_UNDERREPORTED
    indicator_label: Mapped[str] = mapped_column(String(120), default="")
    narrative: Mapped[str] = mapped_column(Text, default="")             # why the engine flagged it
    score: Mapped[float] = mapped_column(Numeric(6, 2), default=0)       # 0-100
    threshold: Mapped[float] = mapped_column(Numeric(6, 2), default=0)   # what it had to beat
    # [{"code": "EINV_VS_RETURN_DELTA", "label": "...", "value": 480000.0, "weight": 0.5}]
    signals: Mapped[list] = mapped_column(JSON, default=list)
    model_version: Mapped[str] = mapped_column(String(20), default="")
    generated_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    case: Mapped[AuditCase] = relationship(back_populates="referral")


class CustomsDeclaration(Base):
    """An import or export movement held by ZATCA customs.

    Imports matter twice: they are VAT paid at import (an input-VAT evidence stream the
    e-invoice population does not contain), and a taxpayer importing goods far outside its
    registered activity is exactly the §3 relevance question.
    """
    __tablename__ = "customs_declaration"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    taxpayer_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.taxpayer.id"), index=True)
    declaration_no: Mapped[str] = mapped_column(String(30), index=True)
    declaration_date: Mapped[date] = mapped_column(Date)
    direction: Mapped[str] = mapped_column(String(10))                   # import/export
    port: Mapped[str] = mapped_column(String(60), default="")
    hs_chapter: Mapped[str] = mapped_column(String(4), default="")
    goods_description: Mapped[str] = mapped_column(String(200), default="")
    customs_value: Mapped[float] = mapped_column(Money, default=0)
    duty_paid: Mapped[float] = mapped_column(Money, default=0)
    vat_paid: Mapped[float] = mapped_column(Money, default=0)            # import VAT (deferred or paid)
    vat_deferred: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="cleared")

    taxpayer: Mapped["Taxpayer"] = relationship()  # noqa: F821


class FinancialSummary(Base):
    """Annual financials already held internally — the basis for a purchases-to-sales risk.

    One row per taxpayer per fiscal year. `source` records where it came from, because a figure
    from a filed Zakat return carries different weight to one keyed from a submitted PDF.
    """
    __tablename__ = "financial_summary"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    taxpayer_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.taxpayer.id"), index=True)
    fiscal_year: Mapped[int] = mapped_column(Integer)
    turnover: Mapped[float] = mapped_column(Money, default=0)
    purchases: Mapped[float] = mapped_column(Money, default=0)
    gross_profit: Mapped[float] = mapped_column(Money, default=0)
    net_profit: Mapped[float] = mapped_column(Money, default=0)
    total_assets: Mapped[float] = mapped_column(Money, default=0)
    source: Mapped[str] = mapped_column(String(40), default="zakat-return")
    as_of: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    taxpayer: Mapped["Taxpayer"] = relationship()  # noqa: F821

    @property
    def gross_margin_pct(self) -> float | None:
        t = float(self.turnover or 0)
        return round(float(self.gross_profit) / t * 100, 2) if t else None
