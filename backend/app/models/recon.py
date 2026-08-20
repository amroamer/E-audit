"""recon schema — the reconciliation working state (populated by later phases)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Numeric, DateTime, Text, ForeignKey, JSON, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

SCHEMA = "recon"
Money = Numeric(16, 2)


class CaseRecon(Base):
    """One box, reconciled.

    There is no pre-qualification total stored here, and there should not be. The rules
    decide which documents belong in the box; `expected_total` is the sum of what qualified.
    The only figures that follow are the comparison and what taxpayer evidence accounted for.
    """
    __tablename__ = "case_recon"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    declared_total: Mapped[float] = mapped_column(Money, default=0)
    expected_total: Mapped[float] = mapped_column(Money, default=0)   # Σ qualifying lines
    difference: Mapped[float] = mapped_column(Money, default=0)       # expected − declared
    evidence_total: Mapped[float] = mapped_column(Money, default=0)   # auditor-confirmed
    unexplained: Mapped[float] = mapped_column(Money, default=0)      # what is left
    status: Mapped[str] = mapped_column(String(30), default="draft")


class BoxOutcome(Base):
    """One box: what qualified, what was declared, and the difference between them.

    `expected_*` is the sum of the lines that qualified — not a rebuild that was later
    adjusted. There is no column for a pre-qualification figure because no such figure
    exists.
    """
    __tablename__ = "box_outcome"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_recon_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.case_recon.id"))
    box_code: Mapped[str] = mapped_column(String(40))
    direction: Mapped[str] = mapped_column(String(10))
    expected_base: Mapped[float] = mapped_column(Money, default=0)
    expected_vat: Mapped[float] = mapped_column(Money, default=0)
    declared_vat: Mapped[float] = mapped_column(Money, default=0)
    difference: Mapped[float] = mapped_column(Money, default=0)   # expected − declared


class QualificationStep(Base):
    """One step in the narrowing from population to qualifying set.

    A step is not a movement of money. It records what actually happened: a rule kept N
    documents out of this box, for this reason. `amount` is the tax those documents carry —
    reported so the auditor can see the size of what was set aside, not because anything was
    subtracted from a total.
    """
    __tablename__ = "qualification_step"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_recon_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.case_recon.id"))
    seq: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(20), default="")
    rule_code: Mapped[str] = mapped_column(String(12), default="")   # "" = structural
    verdict: Mapped[str] = mapped_column(String(12), default="")     # exclude / defer
    label: Mapped[str] = mapped_column(String(200))
    line_count: Mapped[int] = mapped_column(Integer, default=0)
    amount: Mapped[float] = mapped_column(Money, default=0)


class Unexplained(Base):
    """What is left on a box once taxpayer evidence is accounted for, and what that means."""
    __tablename__ = "unexplained"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_recon_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.case_recon.id"))
    box_code: Mapped[str] = mapped_column(String(40))
    amount: Mapped[float] = mapped_column(Money, default=0)
    band: Mapped[str] = mapped_column(String(12), default="")      # noise/immaterial/material
    state: Mapped[str] = mapped_column(String(20), default="")     # supported/explained/unresolved/finding


class Conclusion(Base):
    __tablename__ = "conclusion"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_recon_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.case_recon.id"))
    state: Mapped[str] = mapped_column(String(30), default="")
    financial_impact: Mapped[float] = mapped_column(Money, default=0)
    narrative: Mapped[str] = mapped_column(String, default="")     # AI-drafted, claims-verified


class EventLog(Base):
    """Append-only demo action log (production: immutable hash-chained)."""
    __tablename__ = "event_log"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actor: Mapped[str] = mapped_column(String(40), default="system")
    action: Mapped[str] = mapped_column(String(60))
    payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)


class TaxpayerResponse(Base):
    """Evidence the taxpayer supplied after an information request. The auditor confirms the
    SAR amount it accounts for. It is the one thing that can account for a difference
    *after* qualification — a rule decides what qualifies; evidence arrives later."""
    __tablename__ = "taxpayer_response"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    seq: Mapped[int] = mapped_column(Integer)
    code: Mapped[str] = mapped_column(String(12))            # RESP-01, RESP-02, ...
    label: Mapped[str] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Money, default=0)  # SAR it accounts for (auditor-confirmed)
    doc_name: Mapped[str] = mapped_column(String(160), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
