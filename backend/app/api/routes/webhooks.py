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
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.inbound_webhook_delivery import InboundWebhookDelivery
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
    for msg in messages:
        enqueue_message(msg)

    if messages:
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
    for msg in messages:
        enqueue_message(msg)

    if messages:
        _executor.submit(_process_queue_in_background)

    _update_delivery(delivery.id, acknowledged_at=datetime.now(timezone.utc))

    logger.info("webhook_processed", provider="twilio", messages_received=len(messages))
    return {"status": "ok"}
