import enum
import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

JsonPayload = sa.JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class SanctionsPartnerType(enum.Enum):
    commercial = "commercial"
    hedge = "hedge"


class ScreeningResult(enum.Enum):
    clear = "clear"
    flagged = "flagged"
    blocked = "blocked"


class ScreeningStatus(enum.Enum):
    success = "success"
    error = "error"


class AdjudicationDecision(enum.Enum):
    clear = "clear"
    blocked = "blocked"


class SanctionsScreening(Base):
    """Append-only, immutable. Written by the W2 screening service; created in W1."""

    __tablename__ = "sanctions_screenings"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    partner_type: Mapped[SanctionsPartnerType] = mapped_column(
        Enum(SanctionsPartnerType, name="sanctions_partner_type"), nullable=False
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    screened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    algorithm: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    query_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    top_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 4), nullable=True)
    match_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    matches_json: Mapped[dict | None] = mapped_column(JsonPayload, nullable=True)
    result: Mapped[ScreeningResult | None] = mapped_column(
        Enum(ScreeningResult, name="sanctions_screening_result"), nullable=True
    )  # NULL when status=error
    actor_sub: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ScreeningStatus] = mapped_column(
        Enum(ScreeningStatus, name="sanctions_screening_status"), nullable=False
    )
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class SanctionsAdjudication(Base):
    """Append-only, immutable risk_manager override of a flagged screening. Created in W1."""

    __tablename__ = "sanctions_adjudications"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    partner_type: Mapped[SanctionsPartnerType] = mapped_column(
        Enum(SanctionsPartnerType, name="sanctions_partner_type"), nullable=False
    )
    partner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    superseded_screening_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sanctions_screenings.id"), nullable=False
    )
    decision: Mapped[AdjudicationDecision] = mapped_column(
        Enum(AdjudicationDecision, name="sanctions_adjudication_decision"),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    adjudicating_actor_sub: Mapped[str] = mapped_column(String(200), nullable=False)
    adjudicated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
