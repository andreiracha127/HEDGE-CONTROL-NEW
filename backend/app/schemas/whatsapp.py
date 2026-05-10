"""Schemas for WhatsApp Cloud API integration."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class WhatsAppMessageType(str, Enum):
    template = "template"
    text = "text"


class WhatsAppDeliveryStatus(str, Enum):
    queued = "queued"
    sent = "sent"
    delivered = "delivered"
    read = "read"
    failed = "failed"


class WhatsAppSendRequest(BaseModel):
    """Internal request to send a WhatsApp message."""

    phone: str = Field(..., max_length=20, description="E.164 phone number")
    message_type: WhatsAppMessageType
    template_name: str | None = Field(None, max_length=128)
    template_params: list[str] = Field(default_factory=list)
    text_body: str | None = Field(None, max_length=4096)


class WhatsAppSendResult(BaseModel):
    """Result from the WhatsApp Cloud API call."""

    success: bool
    provider_message_id: str | None = Field(None, max_length=128)
    error_code: str | None = Field(None, max_length=64)
    error_message: str | None = Field(None, max_length=500)


class WhatsAppWebhookVerification(BaseModel):
    """GET /webhooks/whatsapp query params for Meta challenge verification."""

    hub_mode: str = Field(..., alias="hub.mode", max_length=32)
    hub_verify_token: str = Field(..., alias="hub.verify_token", max_length=256)
    hub_challenge: str = Field(..., alias="hub.challenge", max_length=256)


class WhatsAppInboundMessage(BaseModel):
    """Parsed inbound message from WhatsApp webhook payload.

    Explicitly unhashable; durable replay uses database identity, not object
    set membership.
    """

    message_id: str = Field(..., max_length=128)
    from_phone: str = Field(..., max_length=20)
    timestamp: datetime
    text: str = Field(..., max_length=4096)
    sender_name: str | None = Field(None, max_length=200)
    delivery_message_id: uuid.UUID | None = Field(None)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, WhatsAppInboundMessage):
            return NotImplemented
        # delivery_message_id is intentionally excluded: redeliveries of the
        # same provider message remain content-equal regardless of durable row.
        return (
            self.message_id,
            self.from_phone,
            self.timestamp,
            self.text,
            self.sender_name,
        ) == (
            other.message_id,
            other.from_phone,
            other.timestamp,
            other.text,
            other.sender_name,
        )

    __hash__ = None


class WhatsAppWebhookPayload(BaseModel):
    """Raw webhook payload (simplified — only the fields we need)."""

    object: str = Field(..., max_length=32)
    entry: list[dict] = Field(default_factory=list)
