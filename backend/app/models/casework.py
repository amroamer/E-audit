"""The information request/response loop — what was asked for, what arrived, and what is missing.

This is the loop the auditors described as their heaviest administrative burden and their
longest delay: a targeted request goes out, the taxpayer answers with something incomplete or
wrongly structured, the auditor compares the two by hand, and another round trip begins. Each
round costs weeks; the whole exchange can run for months.

Modelling it needs three things the codebase did not have:

* the request as a **structured list of items**, not a letter — an item that names its columns
  can be checked against what arrives, and one that says "a sales analysis" cannot;
* the response as **documents linked to the items they answer**, so "wrong document" is a
  detectable state rather than an impression;
* the **gaps** as first-class records, because they are what the follow-up is drafted from and
  what the round counter counts.

`InformationRequest` and `RequestItem` live in `core` (they are case facts). `GapFinding` lives
in `recon`: it is derived working state, recomputed whenever a document arrives.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Numeric, Date, DateTime, Boolean, Text, ForeignKey, JSON, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

CORE = "core"
RECON = "recon"


class InformationRequest(Base):
    """One round of correspondence with the taxpayer."""
    __tablename__ = "information_request"
    __table_args__ = {"schema": CORE}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)          # round number, 1-based
    # draft -> issued -> answered -> satisfied. A round is only satisfied when no gap remains.
    status: Mapped[str] = mapped_column(String(20), default="draft")
    subject: Mapped[str] = mapped_column(String(200), default="")
    body: Mapped[str] = mapped_column(Text, default="")           # the drafted letter/email
    body_source: Mapped[str] = mapped_column(String(30), default="")  # claude | deterministic
    issued_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    answered_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    items: Mapped[list["RequestItem"]] = relationship(
        back_populates="request", cascade="all, delete-orphan",
        order_by="RequestItem.seq",
    )


class RequestItem(Base):
    """One asked-for thing. `required_columns` is what makes it checkable."""
    __tablename__ = "request_item"
    __table_args__ = {"schema": CORE}

    id: Mapped[int] = mapped_column(primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey(f"{CORE}.information_request.id"))
    seq: Mapped[int] = mapped_column(Integer, default=1)
    catalog_key: Mapped[str] = mapped_column(String(40), default="")   # requests.catalog key
    kind: Mapped[str] = mapped_column(String(20), default="document")  # analysis/document/explanation
    label: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    required_columns: Mapped[list] = mapped_column(JSON, default=list)
    mandatory_columns: Mapped[list] = mapped_column(JSON, default=list)
    expected_format: Mapped[str] = mapped_column(String(20), default="")
    period_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    # (stated total field, column to sum) — lets the checker re-add the taxpayer's own figures
    footed_by: Mapped[list] = mapped_column(JSON, default=list)
    addresses: Mapped[list] = mapped_column(JSON, default=list)        # rule/reason codes
    hypothesis_id: Mapped[str] = mapped_column(String(12), default="") # what it would settle
    rationale: Mapped[str] = mapped_column(Text, default="")           # why we are asking
    status: Mapped[str] = mapped_column(String(20), default="outstanding")
    # outstanding -> received -> satisfied | waived

    request: Mapped[InformationRequest] = relationship(back_populates="items")


class ReceivedDocument(Base):
    """Something the taxpayer sent back.

    `content` is the extracted structure — headers, rows and any totals the document states —
    normalised by `requests/extract.py`. Keeping the extraction separate from the checking is
    what lets the completeness checks stay deterministic regardless of the file format.
    """
    __tablename__ = "received_document"
    __table_args__ = {"schema": CORE}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(f"{CORE}.information_request.id"), nullable=True)
    # null when the taxpayer sends something nobody asked for — itself worth flagging
    request_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey(f"{CORE}.request_item.id"), nullable=True)
    filename: Mapped[str] = mapped_column(String(200))
    media_type: Mapped[str] = mapped_column(String(60), default="")
    file_format: Mapped[str] = mapped_column(String(20), default="")    # xlsx/csv/pdf/letter
    received_at: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    # {"columns": [...], "rows": [[...]], "stated_totals": {...},
    #  "period_from": "...", "period_to": "...", "text": "..."}
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    extraction_note: Mapped[str] = mapped_column(String(200), default="")

    item: Mapped[Optional[RequestItem]] = relationship()


class GapFinding(Base):
    """A difference between what was asked for and what arrived.

    Recomputed from scratch each time the completeness checker runs, so a resolved gap simply
    stops being produced rather than needing to be reconciled away.
    """
    __tablename__ = "gap_finding"
    __table_args__ = {"schema": RECON}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    request_item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    document_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    item_label: Mapped[str] = mapped_column(String(160), default="")
    # missing-item | wrong-document | missing-column | empty-mandatory-field | wrong-period
    # | arithmetic-mismatch | wrong-format | unrequested-document | too-vague
    kind: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(12), default="blocking")  # blocking/advisory
    detail: Mapped[str] = mapped_column(Text, default="")
    citation: Mapped[str] = mapped_column(String(200), default="")   # sheet!cell, page, column
    source: Mapped[str] = mapped_column(String(20), default="deterministic")  # or claude
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuditorCalculation(Base):
    """A figure the auditor worked out themselves, and how they say they worked it out.

    The auditors asked for a second pair of eyes on their own arithmetic, and the second half of
    that request is the important one: without the **method**, a stated total can only be
    compared against a total the engine chose to compute, which is not the same question. So
    `method` is captured in the auditor's own words, parsed into an executable query, and the
    query is stored beside the verdict — the record of what was checked, not merely that
    something was.

    A disagreement is a prompt to look, never a conclusion. `status` is one of agree / disagree
    / not-checkable, and the last of those is a legitimate outcome: a method the closed algebra
    cannot express is reported honestly rather than approximated by a query answering something
    else.
    """
    __tablename__ = "auditor_calculation"
    __table_args__ = {"schema": CORE}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=1)
    label: Mapped[str] = mapped_column(String(200))          # "total output VAT on the listing"
    method: Mapped[str] = mapped_column(Text, default="")    # how they say they calculated it
    stated_amount: Mapped[float] = mapped_column(Numeric(16, 2), default=0)
    document_name: Mapped[str] = mapped_column(String(160), default="")

    # the parse + the verdict, kept together: what was checked, and what it produced
    query: Mapped[str] = mapped_column(String(400), default="")      # CalcQuery.describe()
    query_spec: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    understood: Mapped[str] = mapped_column(Text, default="")        # the parse, in plain words
    status: Mapped[str] = mapped_column(String(16), default="")      # agree/disagree/not-checkable
    computed_amount: Mapped[Optional[float]] = mapped_column(Numeric(16, 2), nullable=True)
    delta: Mapped[float] = mapped_column(Numeric(16, 2), default=0)
    explanation: Mapped[str] = mapped_column(Text, default="")       # engine-authored
    parse_source: Mapped[str] = mapped_column(String(24), default="")  # claude | auditor | ...
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
