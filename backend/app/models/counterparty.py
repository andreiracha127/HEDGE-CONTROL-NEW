import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class CounterpartyType(enum.Enum):
    broker = "broker"
    bank_br = "bank_br"
    customer = "customer"
    supplier = "supplier"


# RfqChannelType removed — all RFQ communication is via WhatsApp only


class KycStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    expired = "expired"
    rejected = "rejected"


class SanctionsStatus(enum.Enum):
    unscreened = "unscreened"
    clear = "clear"
    flagged = "flagged"
    blocked = "blocked"


class RiskRating(enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[CounterpartyType] = mapped_column(
        Enum(CounterpartyType, name="counterparty_type"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    whatsapp_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    payment_terms_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    credit_limit_usd: Mapped[float | None] = mapped_column(
        Numeric(15, 2), nullable=True
    )
    kyc_status: Mapped[KycStatus] = mapped_column(
        Enum(KycStatus, name="kyc_status"),
        nullable=False,
        default=KycStatus.pending,
    )
    sanctions_status: Mapped[SanctionsStatus] = mapped_column(
        Enum(SanctionsStatus, name="sanctions_status"),
        nullable=False,
        default=SanctionsStatus.unscreened,
    )
    risk_rating: Mapped[RiskRating] = mapped_column(
        Enum(RiskRating, name="risk_rating"),
        nullable=False,
        default=RiskRating.medium,
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
