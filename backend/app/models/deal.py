"""Deal models — Deal, DealLink, DealPNLSnapshot (component 1.5)."""

from __future__ import annotations

import enum
import uuid as _uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.core.precision import (
    MT_NUMERIC_PRECISION,
    MT_NUMERIC_SCALE,
    PRICE_NUMERIC_PRECISION,
    PRICE_NUMERIC_SCALE,
)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class DealStatus(enum.Enum):
    open = "open"
    partially_hedged = "partially_hedged"
    fully_hedged = "fully_hedged"
    settled = "settled"
    closed = "closed"


class DealLinkedType(enum.Enum):
    sales_order = "sales_order"
    purchase_order = "purchase_order"
    hedge = "hedge"
    contract = "contract"


# ---------------------------------------------------------------------------
# Deal
# ---------------------------------------------------------------------------


class Deal(Base):
    __tablename__ = "deals"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    reference: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    commodity: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[DealStatus] = mapped_column(
        Enum(DealStatus, name="deal_status"), nullable=False, default=DealStatus.open
    )
    total_physical_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False, default=0
    )
    total_hedge_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False, default=0
    )
    hedge_ratio: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


# ---------------------------------------------------------------------------
# DealLink (polymorphic)
# ---------------------------------------------------------------------------


class DealLink(Base):
    __tablename__ = "deal_links"
    __table_args__ = (
        UniqueConstraint("deal_id", "linked_type", "linked_id", name="uq_deal_link"),
        UniqueConstraint(
            "linked_type",
            "linked_id",
            name="uq_deal_link_entity",
        ),
    )

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    deal_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False
    )
    linked_type: Mapped[DealLinkedType] = mapped_column(
        Enum(DealLinkedType, name="deal_linked_type"), nullable=False
    )
    linked_id: Mapped[_uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# DealPNLSnapshot
# ---------------------------------------------------------------------------


class DealPNLSnapshot(Base):
    __tablename__ = "deal_pnl_snapshots"

    id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_uuid.uuid4
    )
    deal_id: Mapped[_uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("deals.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    physical_revenue: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    physical_cost: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    hedge_pnl_realized: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    hedge_pnl_mtm: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    total_pnl: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0
    )
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
