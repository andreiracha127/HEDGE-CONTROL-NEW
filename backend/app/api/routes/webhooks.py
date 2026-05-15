"""WhatsApp webhook endpoints.

Supports two inbound providers based on ``WHATSAPP_PROVIDER``:

**Meta Cloud API** (default):
- ``GET  /webhooks/whatsapp`` — Meta challenge verification
- ``POST /webhooks/whatsapp`` — receive inbound messages (JSON + HMAC)

**Twilio**:
- ``GET  /webhooks/whatsapp`` — returns 200 (Twilio doesn't verify)
- ``POST /webhooks/whatsapp`` — receive inbound messages (form-encoded + X-Twilio-Signature)
"""

from __future__ import annotations

import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.inbound_webhook_delivery import InboundWebhookDelivery
from app.models.inbound_webhook_message import InboundWebhookMessage
from app.services.audit_trail_service import AuditTrailService
from app.services.whatsapp_providers import get_provider_name
from app.services.webhook_processor import (
    enqueue_message,
    extract_messages,
    extract_messages_twilio,
    verify_signature,
    verify_twilio_signature,
)

logger = get_logger()
router = APIRouter()

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rfq-inbound")

_LOCAL_WEBHOOK_AUTH_ENVS = {"test", "local", "development", "dev"}
_PROCESSING_STALE_AFTER = timedelta(minutes=15)
_TERMINAL_MESSAGE_STATUSES = {"processed", "duplicate"}
_RECOVERABLE_MESSAGE_STATUSES = {"received", "failed"}


def _webhook_auth_bypass_allowed() -> bool:
    app_env = os.getenv("APP_ENV", "production").strip().lower()
    return app_env in _LOCAL_WEBHOOK_AUTH_ENVS


def _signature_headers(request: Request, signature_header_name: str) -> dict[str, str]:
    header_names = {
        signature_header_name.lower(),
        "content-type",
        "user-agent",
        "x-forwarded-for",
        "x-forwarded-proto",
        "x-real-ip",
    }
    return {
        key: value
        for key, value in request.headers.items()
        if key.lower() in header_names
    }


def _persist_initial_delivery(delivery: InboundWebhookDelivery) -> InboundWebhookDelivery:
    delivery.validate_invariants()
    session = SessionLocal()
    try:
        session.add(delivery)
        session.commit()
        session.refresh(delivery)
        return delivery
    finally:
        session.close()


def _update_delivery(delivery_id: uuid.UUID, **values: Any) -> None:
    session = SessionLocal()
    try:
        delivery = session.get(InboundWebhookDelivery, delivery_id)
        if delivery is None:
            raise RuntimeError(f"Inbound webhook delivery not found: {delivery_id}")
        for key, value in values.items():
            setattr(delivery, key, value)
        delivery.validate_invariants()
        session.commit()
    finally:
        session.close()


def _first_provider_message(messages: list[Any]) -> tuple[str | None, str | None]:
    if not messages:
        return None, None
    first = messages[0]
    return first.message_id or None, first.from_phone or None


def _processing_is_stale(started_at: datetime | None) -> bool:
    if started_at is None:
        return True
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)
    return started_at <= datetime.now(timezone.utc) - _PROCESSING_STALE_AFTER


def _persist_message_for_enqueue(
    *,
    delivery_id: uuid.UUID,
    provider: str,
    msg: Any,
) -> uuid.UUID | None:
    if msg.timestamp is None:
        # timestamp is required by the durable message schema; malformed
        # provider messages are not partially persisted or enqueued.
        logger.warning(
            "webhook_message_missing_timestamp",
            provider=provider,
            provider_message_id=msg.message_id,
        )
        return None

    session = SessionLocal()
    try:
        row = InboundWebhookMessage(
            delivery_id=delivery_id,
            provider=provider,
            provider_message_id=msg.message_id,
            sender_phone=msg.from_phone,
            sender_name=msg.sender_name,
            timestamp=msg.timestamp,
            text=msg.text,
            processing_status="received",
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        try:
            session.commit()
            session.refresh(row)
            AuditTrailService.record_worker_event(
                session,
                entity_type="inbound_webhook_message",
                entity_id=row.id,
                event_type="received",
                actor="service:webhook_inbound",
                source="webhooks.whatsapp",
                metadata={"actor_sub": "service:webhook_inbound"},
            )
            session.commit()
            return row.id
        except IntegrityError:
            session.rollback()

        existing = (
            session.query(InboundWebhookMessage)
            .filter(
                InboundWebhookMessage.provider == provider,
                InboundWebhookMessage.provider_message_id == msg.message_id,
            )
            .one_or_none()
        )
        if existing is None:
            logger.warning(
                "webhook_message_insert_conflict_without_existing_row",
                provider=provider,
                provider_message_id=msg.message_id,
            )
            return None
        if existing.processing_status in _TERMINAL_MESSAGE_STATUSES:
            logger.info(
                "webhook_message_redelivery_already_consumed",
                provider=provider,
                provider_message_id=msg.message_id,
                delivery_message_id=str(existing.id),
                processing_status=existing.processing_status,
            )
            return None
        if existing.processing_status == "processing" and not _processing_is_stale(
            existing.processing_started_at
        ):
            logger.info(
                "webhook_message_redelivery_already_processing",
                provider=provider,
                provider_message_id=msg.message_id,
                delivery_message_id=str(existing.id),
            )
            return None

        if (
            existing.processing_status == "processing"
            and existing.processing_completed_at is not None
        ):
            existing.processing_status = "processed"
            if existing.processing_result is None:
                existing.processing_result = {
                    "status": "completed_processing_reconciled"
                }
            session.commit()
            logger.info(
                "webhook_message_redelivery_completed_processing_reconciled",
                provider=provider,
                provider_message_id=msg.message_id,
                delivery_message_id=str(existing.id),
            )
            return None

        if existing.processing_status == "processing":
            stale_cutoff = datetime.now(timezone.utc) - _PROCESSING_STALE_AFTER
            recovered = (
                session.query(InboundWebhookMessage)
                .filter(
                    InboundWebhookMessage.id == existing.id,
                    InboundWebhookMessage.provider == provider,
                    InboundWebhookMessage.provider_message_id == msg.message_id,
                    InboundWebhookMessage.processing_status == "processing",
                    InboundWebhookMessage.processing_completed_at.is_(None),
                    or_(
                        InboundWebhookMessage.processing_started_at.is_(None),
                        InboundWebhookMessage.processing_started_at <= stale_cutoff,
                    ),
                )
                .update(
                    {
                        InboundWebhookMessage.processing_status: "received",
                        InboundWebhookMessage.processing_started_at: None,
                    },
                    synchronize_session=False,
                )
            )
            session.commit()
            if recovered != 1:
                logger.warning(
                    "webhook_message_redelivery_stale_processing_not_recovered",
                    provider=provider,
                    provider_message_id=msg.message_id,
                    delivery_message_id=str(existing.id),
                )
                return None
            logger.info(
                "webhook_message_redelivery_recovered_stale_processing",
                provider=provider,
                provider_message_id=msg.message_id,
                delivery_message_id=str(existing.id),
            )
            return existing.id

        if existing.processing_status in _RECOVERABLE_MESSAGE_STATUSES:
            logger.info(
                "webhook_message_redelivery_recovered",
                provider=provider,
                provider_message_id=msg.message_id,
                delivery_message_id=str(existing.id),
                processing_status=existing.processing_status,
            )
            return existing.id

        logger.warning(
            "webhook_message_redelivery_unexpected_status",
            provider=provider,
            provider_message_id=msg.message_id,
            delivery_message_id=str(existing.id),
            processing_status=existing.processing_status,
        )
        return None
    finally:
        session.close()


def _persist_and_enqueue_messages(
    *,
    delivery_id: uuid.UUID,
    provider: str,
    messages: list[Any],
) -> int:
    enqueued = 0
    for msg in messages:
        durable_id = _persist_message_for_enqueue(
            delivery_id=delivery_id,
            provider=provider,
            msg=msg,
        )
        if durable_id is None:
            continue
        # Durable rows stay "received" while queued. RFQOrchestrator claims the
        # row with an atomic status update before invoking LLM/quote mutation.
        if enqueue_message(msg.model_copy(update={"delivery_message_id": durable_id})):
            enqueued += 1
    return enqueued


def _process_queue_in_background() -> None:
    """Drain the inbound queue in a background thread so the webhook
    returns 200 within Meta's 5-second window."""
    from app.core.database import SessionLocal
    from app.services.rfq_orchestrator import RFQOrchestrator

    session = SessionLocal()
    try:
        results = RFQOrchestrator.process_inbound_queue(session)
        if results:
            logger.info(
                "webhook_background_processed",
                processed_count=len(results),
                statuses=[r.get("status") for r in results],
            )
    except Exception:
        session.rollback()
        logger.exception("webhook_background_processing_error")
    finally:
        session.close()


@router.get("/whatsapp")
def verify_webhook(
    request: Request,
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
) -> int | dict[str, str]:
    """Webhook verification.

    - **Meta**: echoes ``hub.challenge`` if verify token matches.
    - **Twilio**: no verification needed — returns 200.
    """
    provider = get_provider_name()

    if provider == "twilio":
        logger.info("webhook_twilio_get_ok")
        return {"status": "ok"}

    # Meta verification
    expected_token = os.getenv("WHATSAPP_VERIFY_TOKEN", "")
    if hub_mode != "subscribe" or hub_verify_token != expected_token:
        logger.warning("webhook_verify_failed", hub_mode=hub_mode)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Verification failed",
        )
    logger.info("webhook_verified")
    return int(hub_challenge or "0")


@router.post("/whatsapp", status_code=200)
async def receive_webhook(request: Request) -> dict[str, str]:
    """Receive inbound WhatsApp messages.

    Provider-aware:

    - **Meta** (JSON body + HMAC-SHA256 via ``X-Hub-Signature-256``)
    - **Twilio** (form-encoded body + ``X-Twilio-Signature``)

    In both cases, messages are enqueued and a background task drains
    the queue via ``RFQOrchestrator``.  Returns 200 immediately to
    meet provider timeout requirements.
    """
    provider = get_provider_name()

    if provider == "twilio":
        return await _receive_twilio(request)
    return await _receive_meta(request)


async def _receive_meta(request: Request) -> dict[str, str]:
    """Handle Meta Cloud API inbound webhook."""
    body = await request.body()

    signature = request.headers.get("X-Hub-Signature-256", "")
    app_secret_configured = bool(os.getenv("WHATSAPP_APP_SECRET", "").strip())
    signature_status = "missing"
    signature_verified = False

    if not app_secret_configured:
        if not _webhook_auth_bypass_allowed():
            logger.warning("webhook_meta_secret_missing_fail_closed")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="WHATSAPP_APP_SECRET is required for inbound webhooks",
            )
        logger.warning(
            "webhook_no_hmac_verification_bypassed",
            app_env=os.getenv("APP_ENV"),
        )
        signature_status = "bypassed"
    elif not signature:
        logger.warning("webhook_missing_signature")
        _persist_initial_delivery(
            InboundWebhookDelivery(
                provider="meta",
                raw_body=body.decode("utf-8", errors="replace"),
                raw_form=None,
                headers=_signature_headers(request, "X-Hub-Signature-256"),
                signature_present=False,
                signature_verified=False,
                signature_status="missing",
                parse_status="received",
            )
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing signature",
        )
    elif not verify_signature(body, signature):
        logger.warning("webhook_invalid_signature")
        _persist_initial_delivery(
            InboundWebhookDelivery(
                provider="meta",
                raw_body=body.decode("utf-8", errors="replace"),
                raw_form=None,
                headers=_signature_headers(request, "X-Hub-Signature-256"),
                signature_present=True,
                signature_verified=False,
                signature_status="invalid",
                parse_status="received",
            )
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid signature",
        )
    else:
        signature_status = "verified"
        signature_verified = True

    delivery = _persist_initial_delivery(
        InboundWebhookDelivery(
            provider="meta",
            raw_body=body.decode("utf-8", errors="replace"),
            raw_form=None,
            headers=_signature_headers(request, "X-Hub-Signature-256"),
            signature_present=bool(signature),
            signature_verified=signature_verified,
            signature_status=signature_status,
            parse_status="received",
        )
    )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        _update_delivery(delivery.id, parse_status="parse_failed")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON",
        )

    messages = extract_messages(payload)
    provider_message_id, sender_phone = _first_provider_message(messages)
    _update_delivery(
        delivery.id,
        provider_message_id=provider_message_id,
        sender_phone=sender_phone,
        parse_status="parsed",
        messages_extracted=len(messages),
    )
    enqueued = _persist_and_enqueue_messages(
        delivery_id=delivery.id,
        provider="meta",
        messages=messages,
    )

    if enqueued:
        _executor.submit(_process_queue_in_background)

    _update_delivery(delivery.id, acknowledged_at=datetime.now(timezone.utc))

    logger.info("webhook_processed", provider="meta", messages_received=len(messages))
    return {"status": "ok"}


async def _receive_twilio(request: Request) -> dict[str, str]:
    """Handle Twilio inbound webhook (form-encoded)."""
    form_data = await request.form()
    form_params: dict[str, str] = {k: str(v) for k, v in form_data.items()}

    twilio_signature = request.headers.get("X-Twilio-Signature", "")
    auth_token_configured = bool(os.getenv("TWILIO_AUTH_TOKEN", "").strip())
    webhook_url = os.getenv("TWILIO_WEBHOOK_URL", str(request.url))
    signature_status = "missing"
    signature_verified = False

    if not auth_token_configured:
        if not _webhook_auth_bypass_allowed():
            logger.warning("webhook_twilio_token_missing_fail_closed")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="TWILIO_AUTH_TOKEN is required for inbound webhooks",
            )
        logger.warning(
            "webhook_twilio_signature_verification_bypassed",
            app_env=os.getenv("APP_ENV"),
        )
        signature_status = "bypassed"
    elif not twilio_signature:
        logger.warning("webhook_twilio_missing_signature")
        _persist_initial_delivery(
            InboundWebhookDelivery(
                provider="twilio",
                raw_body=None,
                raw_form=form_params,
                headers=_signature_headers(request, "X-Twilio-Signature"),
                signature_base_url=webhook_url,
                signature_present=False,
                signature_verified=False,
                signature_status="missing",
                parse_status="received",
            )
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing Twilio signature",
        )
    elif not verify_twilio_signature(webhook_url, form_params, twilio_signature):
        logger.warning("webhook_twilio_invalid_signature")
        _persist_initial_delivery(
            InboundWebhookDelivery(
                provider="twilio",
                raw_body=None,
                raw_form=form_params,
                headers=_signature_headers(request, "X-Twilio-Signature"),
                signature_base_url=webhook_url,
                signature_present=True,
                signature_verified=False,
                signature_status="invalid",
                parse_status="received",
            )
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid Twilio signature",
        )
    else:
        signature_status = "verified"
        signature_verified = True

    delivery = _persist_initial_delivery(
        InboundWebhookDelivery(
            provider="twilio",
            raw_body=None,
            raw_form=form_params,
            headers=_signature_headers(request, "X-Twilio-Signature"),
            signature_base_url=webhook_url,
            signature_present=bool(twilio_signature),
            signature_verified=signature_verified,
            signature_status=signature_status,
            parse_status="received",
        )
    )

    messages = extract_messages_twilio(form_params)
    provider_message_id, sender_phone = _first_provider_message(messages)
    _update_delivery(
        delivery.id,
        provider_message_id=provider_message_id,
        sender_phone=sender_phone,
        parse_status="parsed",
        messages_extracted=len(messages),
    )
    enqueued = _persist_and_enqueue_messages(
        delivery_id=delivery.id,
        provider="twilio",
        messages=messages,
    )

    if enqueued:
        _executor.submit(_process_queue_in_background)

    _update_delivery(delivery.id, acknowledged_at=datetime.now(timezone.utc))

    logger.info("webhook_processed", provider="twilio", messages_received=len(messages))
    return {"status": "ok"}
