"""config tables (in core schema) — rule library, assumptions register, code dictionary."""
from __future__ import annotations

from sqlalchemy import String, Integer, Boolean, Text
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base

SCHEMA = "core"


class Rule(Base):
    """The VAT Mistakes Rulebook, one row per detection rule (docs/VAT-Mistakes-Rulebook.md)."""
    __tablename__ = "rule_library"
    __table_args__ = {"schema": SCHEMA}

    code: Mapped[str] = mapped_column(String(12), primary_key=True)   # OUT-01, INP-03, ...
    family: Mapped[str] = mapped_column(String(30), index=True)
    title: Mapped[str] = mapped_column(String(200))
    taxpayer_mistake: Mapped[str] = mapped_column(Text, default="")
    why_it_happens: Mapped[str] = mapped_column(Text, default="")
    detection: Mapped[str] = mapped_column(Text, default="")
    data_used: Mapped[str] = mapped_column(Text, default="")
    explains_gap: Mapped[str] = mapped_column(String(160), default="")
    gap_band: Mapped[str] = mapped_column(String(10), default="")     # yes/partial/no
    severity: Mapped[str] = mapped_column(String(60), default="")
    severity_band: Mapped[str] = mapped_column(String(10), default="")  # high/medium/low
    confirming_evidence: Mapped[str] = mapped_column(Text, default="")
    ai_assist: Mapped[str] = mapped_column(Text, default="")
    root_cause_code: Mapped[str] = mapped_column(String(30), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class Assumption(Base):
    """Flippable assumptions (Total=Amount+Adjustment?, tax-point date, version selector, ...)."""
    __tablename__ = "assumptions"
    __table_args__ = {"schema": SCHEMA}

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")


class CodeDictionary(Base):
    """Decode lists for coded fields (placeholders until ZATCA supplies the real ones)."""
    __tablename__ = "code_dictionary"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_set: Mapped[str] = mapped_column(String(40), index=True)
    code: Mapped[str] = mapped_column(String(40))
    label: Mapped[str] = mapped_column(String(120), default="")
    meaning: Mapped[str] = mapped_column(Text, default="")
    is_placeholder: Mapped[bool] = mapped_column(Boolean, default=True)
