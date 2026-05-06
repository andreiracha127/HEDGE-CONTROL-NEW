"""HedgeContract model — unified hedge/derivative position.

Replaces the old separate Hedge model. Every hedge position (whether created
manually or via RFQ award) is stored as a HedgeContract with two legs (fixed
and variable) and a classification (long/short).
"""

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
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


class HedgeLegSide(enum.Enum):
    buy = "buy"
    sell = "sell"


class HedgeClassification(enum.Enum):
    long = "long"
    short = "short"


class HedgeContractStatus(enum.Enum):
    active = "active"
    partially_settled = "partially_settled"
    settled = "settled"
    cancelled = "cancelled"


# Valid state transitions for the status lifecycle
VALID_STATUS_TRANSITIONS: dict[HedgeContractStatus, set[HedgeContractStatus]] = {
    HedgeContractStatus.active: {
        HedgeContractStatus.partially_settled,
        HedgeContractStatus.settled,
        HedgeContractStatus.cancelled,
    },
    HedgeContractStatus.partially_settled: {
        HedgeContractStatus.settled,
        HedgeContractStatus.cancelled,
    },
    HedgeContractStatus.settled: set(),
    HedgeContractStatus.cancelled: set(),
}


class HedgeSourceType(enum.Enum):
    rfq_award = "rfq_award"
    manual = "manual"
    auto = "auto"


class HedgeContract(Base):
    __tablename__ = "hedge_contracts"
    __table_args__ = (
        CheckConstraint(
            "(fixed_leg_side = 'buy' AND classification = 'long') OR "
            "(fixed_leg_side = 'sell' AND classification = 'short')",
            name="chk_classification_matches_fixed_leg",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    reference: Mapped[str | None] = mapped_column(
        String(length=50), unique=True, nullable=True
    )
    commodity: Mapped[str] = mapped_column(String(length=64), nullable=False)
    quantity_mt: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
    )
    rfq_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("rfqs.id", ondelete="RESTRICT"), nullable=True
    )
    rfq_quote_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rfq_quotes.id", ondelete="RESTRICT"),
        nullable=True,
    )
    counterparty_id: Mapped[str | None] = mapped_column(
        String(length=100), nullable=True
    )
    fixed_price_value: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), nullable=True
    )
    fixed_price_unit: Mapped[str | None] = mapped_column(
        String(length=32), nullable=True
    )
    float_pricing_convention: Mapped[str | None] = mapped_column(
        String(length=64), nullable=True
    )
    premium_discount: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), default=0, nullable=True
    )

    # ── Verification period fields ──
    pricing_period_month: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Reference month for avg convention (1-12)"
    )
    pricing_period_year: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Reference year for avg convention"
    )
    fixing_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="Fixing date for c2r convention"
    )
    avg_computation_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="Number of days for avginter convention"
    )
    status: Mapped[HedgeContractStatus] = mapped_column(
        Enum(HedgeContractStatus, name="hedge_contract_status"),
        nullable=False,
        default=HedgeContractStatus.active,
    )
    fixed_leg_side: Mapped[HedgeLegSide] = mapped_column(
        Enum(HedgeLegSide, name="hedge_leg_side"),
        nullable=False,
    )
    variable_leg_side: Mapped[HedgeLegSide] = mapped_column(
        Enum(HedgeLegSide, name="hedge_leg_side"),
        nullable=False,
    )
    classification: Mapped[HedgeClassification] = mapped_column(
        Enum(HedgeClassification, name="hedge_classification"),
        nullable=False,
    )

    # ── Dates ──
    settlement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    prompt_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    trade_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ── Provenance ──
    source_type: Mapped[str | None] = mapped_column(String(length=20), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    # ── Metadata ──
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(length=200), nullable=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    deleted_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )

    # ── Convenience properties for backward compatibility ──

    @property
    def direction(self) -> str:
        """Derive direction from classification: long=buy, short=sell."""
        return "buy" if self.classification == HedgeClassification.long else "sell"

    @property
    def tons(self) -> Decimal:
        """Alias for quantity_mt."""
        return self.quantity_mt

    @property
    def price_per_ton(self) -> Decimal:
        """Alias for fixed_price_value."""
        return self.fixed_price_value or Decimal("0")
