from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Integer,
    JSON,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.models.base import Base


json_payload_type = JSON(none_as_null=True).with_variant(
    JSONB(none_as_null=True),
    "postgresql",
)


class InboundWebhookDelivery(Base):
    __tablename__ = "inbound_webhook_deliveries"
    __table_args__ = (
        CheckConstraint(
            "provider IN ('meta', 'twilio')",
            name="ck_inbound_webhook_deliveries_provider",
        ),
        CheckConstraint(
            "signature_status IN ('missing', 'verified', 'invalid', 'bypassed')",
            name="ck_inbound_webhook_deliveries_signature_status",
        ),
        CheckConstraint(
            "parse_status IN ('received', 'parsed', 'parse_failed')",
            name="ck_inbound_webhook_deliveries_parse_status",
        ),
        CheckConstraint(
            "((provider = 'meta' AND raw_body IS NOT NULL AND raw_form IS NULL) "
            "OR (provider = 'twilio' AND raw_body IS NULL AND raw_form IS NOT NULL))",
            name="ck_inbound_webhook_deliveries_provider_raw_capture",
        ),
        CheckConstraint(
            "((provider = 'meta' AND signature_base_url IS NULL) "
            "OR (provider = 'twilio' AND signature_base_url IS NOT NULL))",
            name="ck_inbound_webhook_deliveries_signature_base_url",
        ),
        CheckConstraint(
            "((parse_status IN ('received', 'parse_failed') AND messages_extracted IS NULL) "
            "OR (parse_status = 'parsed' AND messages_extracted IS NOT NULL))",
            name="ck_inbound_webhook_deliveries_message_count",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sender_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    raw_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_form: Mapped[dict[str, Any] | None] = mapped_column(
        json_payload_type,
        nullable=True,
    )
    headers: Mapped[dict[str, Any]] = mapped_column(json_payload_type, nullable=False)
    signature_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    signature_present: Mapped[bool] = mapped_column(Boolean, nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    signature_status: Mapped[str] = mapped_column(String(16), nullable=False)
    parse_status: Mapped[str] = mapped_column(String(16), nullable=False)
    messages_extracted: Mapped[int | None] = mapped_column(Integer, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.validate_invariants()

    @validates("provider")
    def _validate_provider(self, _key: str, value: str) -> str:
        if value not in {"meta", "twilio"}:
            raise ValueError("provider must be 'meta' or 'twilio'")
        return value

    @validates("signature_status")
    def _validate_signature_status(self, _key: str, value: str) -> str:
        if value not in {"missing", "verified", "invalid", "bypassed"}:
            raise ValueError(
                "signature_status must be missing, verified, invalid, or bypassed"
            )
        return value

    @validates("parse_status")
    def _validate_parse_status(self, _key: str, value: str) -> str:
        if value not in {"received", "parsed", "parse_failed"}:
            raise ValueError("parse_status must be received, parsed, or parse_failed")
        return value

    def validate_invariants(self) -> None:
        if self.provider == "meta":
            if self.raw_body is None or self.raw_form is not None:
                raise ValueError(
                    "Meta deliveries require raw_body and must not set raw_form"
                )
            if self.signature_base_url is not None:
                raise ValueError("Meta deliveries must not set signature_base_url")
        elif self.provider == "twilio":
            if self.raw_form is None or self.raw_body is not None:
                raise ValueError(
                    "Twilio deliveries require raw_form and must not set raw_body"
                )
            if not self.signature_base_url:
                raise ValueError("Twilio deliveries require signature_base_url")

        if (
            self.parse_status in {"received", "parse_failed"}
            and self.messages_extracted is not None
        ):
            raise ValueError("messages_extracted must be NULL until a delivery is parsed")
        if self.parse_status == "parsed" and self.messages_extracted is None:
            raise ValueError("parsed deliveries require messages_extracted")
