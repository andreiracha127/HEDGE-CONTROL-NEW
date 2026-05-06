"""Exposure Engine models — Exposure, ContractExposure, HedgeExposure, HedgeTask."""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Boolean,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
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


class ExposureDirection(enum.Enum):
    long = "long"
    short = "short"


class ExposureSourceType(enum.Enum):
    sales_order = "sales_order"
    purchase_order = "purchase_order"


class ExposureStatus(enum.Enum):
    open = "open"
    partially_hedged = "partially_hedged"
    fully_hedged = "fully_hedged"
    cancelled = "cancelled"


class HedgeTaskAction(enum.Enum):
    hedge_new = "hedge_new"
    increase = "increase"
    decrease = "decrease"
    cancel = "cancel"


class HedgeTaskStatus(enum.Enum):
    pending = "pending"
    executed = "executed"
    cancelled = "cancelled"


# ---------------------------------------------------------------------------
# Exposure
# ---------------------------------------------------------------------------


class Exposure(Base):
    __tablename__ = "exposures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    commodity: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[ExposureDirection] = mapped_column(
        Enum(ExposureDirection, name="exposure_direction"), nullable=False
    )
    source_type: Mapped[ExposureSourceType] = mapped_column(
        Enum(ExposureSourceType, name="exposure_source_type"), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    original_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
    )
    open_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
    )
    price_per_ton: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), nullable=True
    )
    settlement_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    status: Mapped[ExposureStatus] = mapped_column(
        Enum(ExposureStatus, name="exposure_status"),
        default=ExposureStatus.open,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


# ---------------------------------------------------------------------------
# ContractExposure — links an Exposure to a HedgeContract
# ---------------------------------------------------------------------------


class ContractExposure(Base):
    __tablename__ = "contract_exposures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exposure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exposures.id"), nullable=False
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("hedge_contracts.id"), nullable=False
    )
    allocated_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# HedgeExposure — links an Exposure to a Hedge (created in 1.4)
# ---------------------------------------------------------------------------


class HedgeExposure(Base):
    __tablename__ = "hedge_exposures"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exposure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exposures.id"), nullable=False
    )
    hedge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        nullable=False,  # FK deferred — hedges table created in 1.4
    )
    allocated_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# ---------------------------------------------------------------------------
# HedgeTask — recommended hedge actions
# ---------------------------------------------------------------------------


class HedgeTask(Base):
    __tablename__ = "hedge_tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    exposure_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exposures.id"), nullable=False
    )
    recommended_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
    )
    recommended_action: Mapped[HedgeTaskAction] = mapped_column(
        Enum(HedgeTaskAction, name="hedge_task_action"), nullable=False
    )
    status: Mapped[HedgeTaskStatus] = mapped_column(
        Enum(HedgeTaskStatus, name="hedge_task_status"),
        default=HedgeTaskStatus.pending,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    executed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
