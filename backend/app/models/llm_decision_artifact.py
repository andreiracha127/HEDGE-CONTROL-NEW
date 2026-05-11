from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.models.base import Base
from app.models.inbound_webhook_delivery import json_payload_type


LLM_DECISION_ALLOW = "allow_mutation"
LLM_DECISION_DENY = "deny_no_mutation"
LLM_DECISION_VALUES = {LLM_DECISION_ALLOW, LLM_DECISION_DENY}

LLM_FINAL_STATUS_VALUES = {
    "auto_quote_created",
    "counterparty_declined",
    "counterparty_question",
    "needs_human_review",
    "llm_unavailable",
    "hallucinated_price_blocked",
    "duplicate_quote_skipped",
    "auto_quote_skipped_incomplete",
    "auto_quote_skipped_invalid_payload",
    "auto_quote_failed",
}


class LLMDecisionArtifact(Base):
    __tablename__ = "llm_decision_artifacts"
    __table_args__ = (
        CheckConstraint(
            "final_decision IN ('allow_mutation', 'deny_no_mutation')",
            name="ck_llm_decision_artifacts_final_decision",
        ),
        CheckConstraint(
            "final_status IN ("
            "'auto_quote_created', 'counterparty_declined', "
            "'counterparty_question', 'needs_human_review', 'llm_unavailable', "
            "'hallucinated_price_blocked', 'duplicate_quote_skipped', "
            "'auto_quote_skipped_incomplete', "
            "'auto_quote_skipped_invalid_payload', 'auto_quote_failed'"
            ")",
            name="ck_llm_decision_artifacts_final_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    inbound_message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("inbound_webhook_messages.id"),
        nullable=False,
        unique=True,
    )
    delivery_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("inbound_webhook_deliveries.id"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    provider_message_id: Mapped[str] = mapped_column(String(128), nullable=False)
    rfq_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rfqs.id"),
        nullable=True,
    )
    quote_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("rfq_quotes.id"),
        nullable=True,
    )
    counterparty_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("counterparties.id"),
        nullable=True,
    )
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    llm_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    classification_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    parse_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    classification_prompt: Mapped[dict[str, Any] | None] = mapped_column(
        json_payload_type,
        nullable=True,
    )
    classification_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    classification_parsed: Mapped[dict[str, Any] | None] = mapped_column(
        json_payload_type,
        nullable=True,
    )
    classification_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_prompt: Mapped[dict[str, Any] | None] = mapped_column(
        json_payload_type,
        nullable=True,
    )
    parse_raw_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    parse_parsed: Mapped[dict[str, Any] | None] = mapped_column(
        json_payload_type,
        nullable=True,
    )
    parse_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(
        json_payload_type,
        nullable=False,
    )
    guard_outcomes: Mapped[dict[str, Any]] = mapped_column(
        json_payload_type,
        nullable=False,
    )
    final_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    final_status: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    @validates("final_decision")
    def _validate_final_decision(self, _key: str, value: str) -> str:
        if value not in LLM_DECISION_VALUES:
            raise ValueError(f"final_decision must be one of {sorted(LLM_DECISION_VALUES)}")
        return value

    @validates("final_status")
    def _validate_final_status(self, _key: str, value: str) -> str:
        if value not in LLM_FINAL_STATUS_VALUES:
            raise ValueError(f"final_status must be one of {sorted(LLM_FINAL_STATUS_VALUES)}")
        return value
