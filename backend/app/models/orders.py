import enum
import uuid
from datetime import datetime
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


class OrderType(enum.Enum):
    sales = "SO"
    purchase = "PO"


class PriceType(enum.Enum):
    fixed = "fixed"
    variable = "variable"


class OrderPricingConvention(enum.Enum):
    avg = "AVG"
    avginter = "AVGInter"
    c2r = "C2R"


class PricingType(enum.Enum):
    fixed = "fixed"
    average = "average"
    avginter = "avginter"
    fix = "fix"
    c2r = "c2r"


class Order(Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    order_type: Mapped[OrderType] = mapped_column(
        Enum(OrderType, name="order_type"), nullable=False
    )
    price_type: Mapped[PriceType] = mapped_column(
        Enum(PriceType, name="price_type"), nullable=False
    )
    commodity: Mapped[str] = mapped_column(
        String(length=64), nullable=False, index=True
    )
    quantity_mt: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
    )
    pricing_convention: Mapped[OrderPricingConvention | None] = mapped_column(
        Enum(OrderPricingConvention, name="order_pricing_convention"),
        nullable=True,
    )
    avg_entry_price: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), nullable=True
    )

    # --- Counterparty (free text) ---
    counterparty_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # --- Variable pricing detail ---
    reference_month: Mapped[str | None] = mapped_column(
        String(7), nullable=True
    )  # yyyy-MM for AVG
    observation_date_start: Mapped[datetime | None] = mapped_column(
        Date, nullable=True
    )  # AVGInter start
    observation_date_end: Mapped[datetime | None] = mapped_column(
        Date, nullable=True
    )  # AVGInter end
    fixing_date: Mapped[datetime | None] = mapped_column(
        Date, nullable=True
    )  # C2R fixing date

    # --- New fields (1.2 enrichment) ---
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("counterparties.id"),
        nullable=True,
    )
    pricing_type: Mapped[PricingType | None] = mapped_column(
        Enum(PricingType, name="pricing_type"), nullable=True
    )
    delivery_terms: Mapped[str | None] = mapped_column(String(50), nullable=True)
    delivery_date_start: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    delivery_date_end: Mapped[datetime | None] = mapped_column(Date, nullable=True)
    payment_terms_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    deleted_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class SoPoLink(Base):
    __tablename__ = "so_po_links"
    __table_args__ = (
        UniqueConstraint("sales_order_id", "purchase_order_id", name="uq_sopo_link"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    sales_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    linked_tons: Mapped[Decimal] = mapped_column(
        Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
