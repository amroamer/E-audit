"""core schema — the taxpayer/declared/evidence data the agent reasons over."""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    String, Integer, Numeric, Date, DateTime, Boolean, Text, ForeignKey, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base

SCHEMA = "core"
Money = Numeric(16, 2)


class Taxpayer(Base):
    __tablename__ = "taxpayer"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    vat_registration_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    partner: Mapped[str] = mapped_column(String(20), default="")
    id_number: Mapped[str] = mapped_column(String(20), default="")
    name: Mapped[str] = mapped_column(String(200))
    ind_sector: Mapped[str] = mapped_column(String(80), default="")
    business_size: Mapped[str] = mapped_column(String(20), default="")          # micro/small/medium/large
    accounting_method: Mapped[str] = mapped_column(String(20), default="accrual")  # accrual/cash
    resident_flag: Mapped[bool] = mapped_column(Boolean, default=True)
    vat_group_rep_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    bp_type: Mapped[str] = mapped_column(String(20), default="org")             # org/individual
    reg_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    reg_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    dereg_type: Mapped[str] = mapped_column(String(30), default="")


class VatReturn(Base):
    """The declared position (as filed). Boxes are normalised in VatReturnBox."""
    __tablename__ = "vat_return"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    form_number: Mapped[str] = mapped_column(String(30), index=True)
    taxpayer_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.taxpayer.id"))
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    data_version: Mapped[int] = mapped_column(Integer, default=1)
    current_flag: Mapped[bool] = mapped_column(Boolean, default=True)
    reason_for_amendment: Mapped[str] = mapped_column(String(200), default="")
    submission_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    filing_deadline: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sadad_bill_number: Mapped[str] = mapped_column(String(40), default="")
    sadad_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    late_filing_penalty: Mapped[float] = mapped_column(Money, default=0)
    total_vat_due: Mapped[float] = mapped_column(Money, default=0)             # Box 13
    corrections_prev_period: Mapped[float] = mapped_column(Money, default=0)   # Box 14
    vat_credit: Mapped[float] = mapped_column(Money, default=0)                # Box 15
    net_due_vat: Mapped[float] = mapped_column(Money, default=0)               # Box 16

    taxpayer: Mapped[Taxpayer] = relationship()
    boxes: Mapped[list["VatReturnBox"]] = relationship(
        back_populates="vat_return", cascade="all, delete-orphan"
    )


class VatReturnBox(Base):
    """One declared box: base + VAT + the taxpayer's own adjustment."""
    __tablename__ = "vat_return_box"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    return_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.vat_return.id"))
    box_code: Mapped[str] = mapped_column(String(40))          # e.g. standard_rate_sales
    box_label: Mapped[str] = mapped_column(String(120), default="")
    direction: Mapped[str] = mapped_column(String(10))          # sale/purchase/calc
    category: Mapped[str] = mapped_column(String(4), default="")  # S/Z/E/O
    rate: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 15/5/0
    base_amount: Mapped[float] = mapped_column(Money, default=0)
    vat_amount: Mapped[float] = mapped_column(Money, default=0)
    adjustment: Mapped[float] = mapped_column(Money, default=0)

    vat_return: Mapped[VatReturn] = relationship(back_populates="boxes")


class Invoice(Base):
    """A cleared/reported FATOORA e-invoice (evidence). Direction is the (mocked) party link."""
    __tablename__ = "invoice"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    uuid: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    taxpayer_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.taxpayer.id"))
    invoice_type_code: Mapped[int] = mapped_column(Integer)     # 388/381/383/386
    type_flags: Mapped[str] = mapped_column(String(40), default="")  # standard/simplified/export/self-billed
    direction: Mapped[str] = mapped_column(String(10))          # sale/purchase
    issue_date: Mapped[date] = mapped_column(Date)
    delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    document_currency: Mapped[str] = mapped_column(String(3), default="SAR")
    tax_currency: Mapped[str] = mapped_column(String(3), default="SAR")
    status_code: Mapped[str] = mapped_column(String(20), default="cleared")  # cleared/reported/rejected
    buyer_vat: Mapped[str] = mapped_column(String(20), default="")
    seller_vat: Mapped[str] = mapped_column(String(20), default="")
    tax_exclusive_amount: Mapped[float] = mapped_column(Money, default=0)
    tax_amount: Mapped[float] = mapped_column(Money, default=0)
    rounding_amount: Mapped[float] = mapped_column(Money, default=0)
    allowance_total: Mapped[float] = mapped_column(Money, default=0)
    prepaid_amount: Mapped[float] = mapped_column(Money, default=0)

    subtotals: Mapped[list["InvoiceTaxSubtotal"]] = relationship(
        back_populates="invoice", cascade="all, delete-orphan"
    )


class InvoiceTaxSubtotal(Base):
    """The linchpin: taxable base + VAT per tax category — aggregating this rebuilds the return."""
    __tablename__ = "invoice_taxsubtotal"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.invoice.id"))
    category: Mapped[str] = mapped_column(String(4))            # S/Z/E/O
    rate: Mapped[int] = mapped_column(Integer)                  # 15/5/0
    taxable_amount: Mapped[float] = mapped_column(Money, default=0)
    tax_amount: Mapped[float] = mapped_column(Money, default=0)

    invoice: Mapped[Invoice] = relationship(back_populates="subtotals")


class AuditCase(Base):
    """A case referred by the (out-of-scope) risk engine, plus closed-case outcome labels."""
    __tablename__ = "audit_case"
    __table_args__ = {"schema": SCHEMA}

    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    taxpayer_id: Mapped[int] = mapped_column(ForeignKey(f"{SCHEMA}.taxpayer.id"))
    form_number: Mapped[str] = mapped_column(String(30), default="")
    period_from: Mapped[date] = mapped_column(Date)
    period_to: Mapped[date] = mapped_column(Date)
    case_reason_code: Mapped[str] = mapped_column(String(30), default="")
    risk_category: Mapped[str] = mapped_column(String(30), default="")
    vat_priority: Mapped[str] = mapped_column(String(20), default="")
    audit_type: Mapped[str] = mapped_column(String(30), default="desk")
    status: Mapped[str] = mapped_column(String(20), default="referred")
    referral_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    sla_due: Mapped[Optional[date]] = mapped_column(Date, nullable=True)  # audit deadline (prioritization)
    scenario_key: Mapped[str] = mapped_column(String(30), default="")   # demo scenario tag
    action_taken: Mapped[str] = mapped_column(String(60), default="")
    audit_result_type: Mapped[str] = mapped_column(String(30), default="")
    root_cause_code: Mapped[str] = mapped_column(String(30), default="")
    old_tax_amt: Mapped[float] = mapped_column(Money, default=0)
    new_tax_amt: Mapped[float] = mapped_column(Money, default=0)
    diff_tax_amt: Mapped[float] = mapped_column(Money, default=0)
    vat_amt: Mapped[float] = mapped_column(Money, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    taxpayer: Mapped[Taxpayer] = relationship()
