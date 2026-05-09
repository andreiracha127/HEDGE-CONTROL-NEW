import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class MTMObjectType(enum.Enum):
    hedge_contract = "hedge_contract"
    order = "order"


class MTMSnapshot(Base):
    __tablename__ = "mtm_snapshots"
    __table_args__ = (
        UniqueConstraint("object_type", "object_id", "as_of_date", name="uq_mtm_snapshots_object_type_id_as_of"),
        CheckConstraint(
            "(price_source IS NULL AND price_symbol IS NULL AND price_settlement_date IS NULL AND inputs_hash IS NULL) "
            "OR (price_source IS NOT NULL AND price_symbol IS NOT NULL AND price_settlement_date IS NOT NULL AND inputs_hash IS NOT NULL)",
            name="ck_mtm_snapshots_provenance_all_or_none",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    object_type: Mapped[MTMObjectType] = mapped_column(Enum(MTMObjectType, name="mtm_object_type"), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    as_of_date: Mapped[date] = mapped_column(Date, nullable=False)

    mtm_value: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price_d1: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    quantity_mt: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price_source: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    price_symbol: Mapped[str | None] = mapped_column(String(length=32), nullable=True)
    price_settlement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    inputs_hash: Mapped[str | None] = mapped_column(String(length=64), nullable=True)

    correlation_id: Mapped[str] = mapped_column(String(length=64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
