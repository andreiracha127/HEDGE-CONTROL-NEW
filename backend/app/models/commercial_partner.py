import enum
import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.precision import PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE
from app.models.base import Base
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus

JsonPayload = sa.JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class CommercialPartnerKind(enum.Enum):
    customer = "customer"
    supplier = "supplier"


class LeiStatus(enum.Enum):
    not_provided = "not_provided"
    valid = "valid"
    invalid = "invalid"
    lapsed = "lapsed"
    issued = "issued"
    error = "error"


class CommercialPartner(Base):
    __tablename__ = "commercial_partners"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    kind: Mapped[CommercialPartnerKind] = mapped_column(
        Enum(CommercialPartnerKind, name="commercial_partner_kind"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    short_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    country: Mapped[str] = mapped_column(String(3), nullable=False)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    whatsapp_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    lei: Mapped[str | None] = mapped_column(String(20), nullable=True)
    lei_status: Mapped[LeiStatus] = mapped_column(
        Enum(LeiStatus, name="lei_status"),
        nullable=False,
        default=LeiStatus.not_provided,
    )
    lei_legal_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lei_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    kyc_status: Mapped[KycStatus] = mapped_column(
        Enum(KycStatus, name="commercial_kyc_status"),
        nullable=False,
        default=KycStatus.pending,
    )
    sanctions_status: Mapped[SanctionsStatus] = mapped_column(
        Enum(SanctionsStatus, name="commercial_sanctions_status"),
        nullable=False,
        default=SanctionsStatus.unscreened,
    )
    risk_rating: Mapped[RiskRating] = mapped_column(
        Enum(RiskRating, name="commercial_risk_rating"),
        nullable=False,
        default=RiskRating.medium,
    )

    # customer-only credit fields (CHECK: NULL when kind=supplier)
    credit_limit: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), nullable=True
    )
    credit_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    payment_conditions: Mapped[dict | None] = mapped_column(JsonPayload, nullable=True)

    # supplier-only terms fields (CHECK: NULL when kind=customer)
    approved_value: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), nullable=True
    )
    approved_currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    approved_terms: Mapped[dict | None] = mapped_column(JsonPayload, nullable=True)

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

    __table_args__ = (
        CheckConstraint(
            "kind <> 'supplier' OR ("
            "credit_limit IS NULL AND credit_currency IS NULL "
            "AND payment_conditions IS NULL)",
            name="ck_commercial_partners_supplier_no_customer_credit",
        ),
        CheckConstraint(
            "kind <> 'customer' OR ("
            "approved_value IS NULL AND approved_currency IS NULL "
            "AND approved_terms IS NULL)",
            name="ck_commercial_partners_customer_no_supplier_terms",
        ),
        Index(
            "uq_commercial_partners_tax_id",
            "tax_id",
            unique=True,
            postgresql_where=sa.text("is_deleted = false"),
            sqlite_where=sa.text("is_deleted = 0"),
        ),
    )
