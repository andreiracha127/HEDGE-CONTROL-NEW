from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.models.base import Base
from app.models.inbound_webhook_delivery import json_payload_type


class InboundWebhookMessage(Base):
    __tablename__ = "inbound_webhook_messages"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_message_id",
            name="uq_inbound_webhook_messages_provider_message_id",
        ),
        CheckConstraint(
            "provider IN ('meta', 'twilio')",
            name="ck_inbound_webhook_messages_provider",
        ),
        CheckConstraint(
            "provider_message_id IS NOT NULL AND length(provider_message_id) > 0",
            name="ck_inbound_webhook_messages_provider_message_id_nonempty",
        ),
        CheckConstraint(
            "processing_status IN ('received', 'processing', 'processed', 'duplicate', 'failed')",
            name="ck_inbound_webhook_messages_processing_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("inbound_webhook_deliveries.id"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    sender_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sender_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    processing_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="received",
    )
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processing_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processing_result: Mapped[dict[str, Any] | None] = mapped_column(
        json_payload_type,
        nullable=True,
    )
    rfq_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    rfq_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    @validates("provider")
    def _validate_provider(self, _key: str, value: str) -> str:
        if value not in {"meta", "twilio"}:
            raise ValueError("provider must be 'meta' or 'twilio'")
        return value

    @validates("provider_message_id")
    def _validate_provider_message_id(self, _key: str, value: str) -> str:
        if not value:
            raise ValueError("provider_message_id must be non-empty")
        return value

    @validates("processing_status")
    def _validate_processing_status(self, _key: str, value: str) -> str:
        allowed = {"received", "processing", "processed", "duplicate", "failed"}
        if value not in allowed:
            raise ValueError(f"processing_status must be one of {sorted(allowed)}")
        return value
