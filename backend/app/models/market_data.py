from datetime import date, datetime
from decimal import Decimal
import uuid

from sqlalchemy import Date, DateTime, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class CashSettlementPrice(Base):
    __tablename__ = "cash_settlement_prices"
    __table_args__ = (
        UniqueConstraint("source", "symbol", "settlement_date", name="uq_cash_settlement_prices_source_symbol_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    source: Mapped[str] = mapped_column(String(length=64), nullable=False)
    symbol: Mapped[str] = mapped_column(String(length=64), nullable=False)
    settlement_date: Mapped[date] = mapped_column(Date, nullable=False)
    price_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)

    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    html_sha256: Mapped[str] = mapped_column(String(length=64), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
