import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, JSON, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class PLSnapshot(Base):
    __tablename__ = "pl_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "entity_type",
            "entity_id",
            "period_start",
            "period_end",
            name="uq_pl_snapshot_entity_period",
        ),
        CheckConstraint(
            "(price_references IS NULL AND inputs_hash IS NULL) "
            "OR (price_references IS NOT NULL AND inputs_hash IS NOT NULL)",
            name="ck_pl_snapshots_provenance_all_or_none",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(length=32), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    realized_pl: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    unrealized_mtm: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price_references: Mapped[list[dict] | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=True,
    )
    inputs_hash: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
