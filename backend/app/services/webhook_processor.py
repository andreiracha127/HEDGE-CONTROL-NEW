"""Webhook processor — parses and enqueues inbound WhatsApp messages.

The processor:
1. Validates the signature from the webhook provider (Meta HMAC or Twilio).
2. Extracts individual messages from the webhook payload.
3. Enqueues them as ``WhatsAppInboundMessage`` objects for downstream
   consumers (LLM Agent, RFQ Orchestrator).

Supports two inbound providers:
- **Meta Cloud API** — HMAC-SHA256 via ``X-Hub-Signature-256``
- **Twilio**         — Request signature via ``X-Twilio-Signature``

The queue is an in-process :class:`collections.deque` for now; it can be
swapped for a durable message broker (Service Bus, Redis Streams) when needed.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from base64 import b64encode
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any
from urllib.parse import urlencode

from app.core.logging import get_logger
from app.schemas.whatsapp import WhatsAppInboundMessage

logger = get_logger()

# ---------------------------------------------------------------------------
# In-process message queue (replaced by broker in production)
# ---------------------------------------------------------------------------

_message_queue: deque[WhatsAppInboundMessage] = deque(maxlen=10_000)

_SEEN_IDS_MAX = 5_000
_seen_message_ids: deque[str] = deque(maxlen=_SEEN_IDS_MAX)
_seen_set: set[str] = set()
_active_durable_message_ids: set[uuid.UUID] = set()
_queue_state_lock = Lock()


def enqueue_message(msg: WhatsAppInboundMessage) -> bool:
    """Add a parsed inbound message to the processing queue.

    Legacy messages without a durable row retain the local duplicate guard.
    Durable webhook paths set ``delivery_message_id`` and rely on database
    uniqueness/status as the authority; the local durable-id set only prevents
    duplicate queue copies while the row is already queued or in-flight.
    """
    with _queue_state_lock:
        if msg.delivery_message_id is None:
            if msg.message_id in _seen_set:
                logger.debug("webhook_duplicate_skipped", message_id=msg.message_id)
                return False

            if len(_seen_message_ids) >= _SEEN_IDS_MAX:
                evicted = _seen_message_ids[0]
                _seen_set.discard(evicted)
            _seen_message_ids.append(msg.message_id)
            _seen_set.add(msg.message_id)
        elif msg.delivery_message_id in _active_durable_message_ids:
            logger.debug(
                "webhook_durable_duplicate_queue_skipped",
                message_id=msg.message_id,
                delivery_message_id=str(msg.delivery_message_id),
            )
            return False
        else:
            _active_durable_message_ids.add(msg.delivery_message_id)

        queue_maxlen = _message_queue.maxlen
        if queue_maxlen is not None and len(_message_queue) >= queue_maxlen:
            evicted = _message_queue[0]
            if evicted.delivery_message_id is not None:
                _active_durable_message_ids.discard(evicted.delivery_message_id)
                logger.warning(
                    "webhook_durable_message_evicted_from_queue",
                    message_id=evicted.message_id,
                    delivery_message_id=str(evicted.delivery_message_id),
                    queue_depth=len(_message_queue),
                )

        _message_queue.append(msg)
        queue_depth_value = len(_message_queue)
    logger.info(
        "webhook_message_enqueued",
        message_id=msg.message_id,
        delivery_message_id=str(msg.delivery_message_id)
        if msg.delivery_message_id
        else None,
        from_phone=msg.from_phone,
        queue_depth=queue_depth_value,
    )
    return True


def mark_message_finished(msg: WhatsAppInboundMessage) -> None:
    """Release local queue/in-flight tracking for a durable message."""
    if msg.delivery_message_id is not None:
        with _queue_state_lock:
            _active_durable_message_ids.discard(msg.delivery_message_id)


def dequeue_message() -> WhatsAppInboundMessage | None:
    """Pop the oldest message from the queue, or ``None`` if empty."""
    with _queue_state_lock:
        try:
            return _message_queue.popleft()
        except IndexError:
            return None


def queue_depth() -> int:
    """Return the current number of messages waiting."""
    with _queue_state_lock:
        return len(_message_queue)


def drain_queue() -> list[WhatsAppInboundMessage]:
    """Remove and return all messages from the queue (useful in tests)."""
    with _queue_state_lock:
        msgs = list(_message_queue)
        _message_queue.clear()
        _active_durable_message_ids.clear()
    return msgs


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def verify_signature(payload_body: bytes, signature_header: str) -> bool:
    """Validate the ``X-Hub-Signature-256`` from Meta.

    Parameters
    ----------
    payload_body:
        Raw request body bytes.
    signature_header:
        Value of the ``X-Hub-Signature-256`` header (``sha256=<hex>``).

    Returns
    -------
    bool
        ``True`` if the HMAC matches.
    """
    app_secret = os.getenv("WHATSAPP_APP_SECRET", "")
    if not app_secret:
        logger.warning("whatsapp_app_secret_missing")
        return False

    if not signature_header.startswith("sha256="):
        return False

    expected = signature_header[7:]  # strip 'sha256='
    computed = hmac.new(
        app_secret.encode("utf-8"),
        payload_body,
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, expected)


# ---------------------------------------------------------------------------
# Payload extraction
# ---------------------------------------------------------------------------


def extract_messages(payload: dict[str, Any]) -> list[WhatsAppInboundMessage]:
    """Extract individual text messages from a Meta webhook payload.

    Meta sends a nested structure::

        {
          "object": "whatsapp_business_account",
          "entry": [{
            "changes": [{
              "value": {
                "contacts": [{"wa_id": "...", "profile": {"name": "..."}}],
                "messages": [{"id": "...", "from": "...", "timestamp": "...",
                              "type": "text", "text": {"body": "..."}}]
              }
            }]
          }]
        }

    We only process ``type == "text"`` messages.
    """
    messages: list[WhatsAppInboundMessage] = []

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            contacts = {
                c.get("wa_id", ""): c.get("profile", {}).get("name")
                for c in value.get("contacts", [])
            }
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                from_phone = msg.get("from", "")
                ts_str = msg.get("timestamp", "0")
                try:
                    ts = datetime.fromtimestamp(int(ts_str), tz=timezone.utc)
                except (ValueError, OSError):
                    ts = datetime.now(timezone.utc)

                text_body = msg.get("text", {}).get("body", "")
                messages.append(
                    WhatsAppInboundMessage(
                        message_id=msg.get("id", ""),
                        from_phone=from_phone,
                        timestamp=ts,
                        text=text_body,
                        sender_name=contacts.get(from_phone),
                    )
                )

    return messages


# ---------------------------------------------------------------------------
# Twilio signature verification
# ---------------------------------------------------------------------------


def verify_twilio_signature(
    url: str,
    form_params: dict[str, str],
    signature_header: str,
) -> bool:
    """Validate the ``X-Twilio-Signature`` header.

    Twilio signs requests using HMAC-SHA1 of the full callback URL
    concatenated with all POST parameter key-value pairs sorted by key.

    Parameters
    ----------
    url:
        The full webhook URL as configured in Twilio (including https://).
    form_params:
        Dict of all POST form parameters received.
    signature_header:
        Value of the ``X-Twilio-Signature`` header.

    Returns
    -------
    bool
        ``True`` if the HMAC matches.
    """
    auth_token = os.getenv("TWILIO_AUTH_TOKEN", "")
    if not auth_token:
        logger.warning("twilio_auth_token_missing")
        return False

    if not signature_header:
        return False

    # Build the data string: URL + sorted key-value pairs
    data_str = url
    for key in sorted(form_params.keys()):
        data_str += key + form_params[key]

    computed = b64encode(
        hmac.new(
            auth_token.encode("utf-8"),
            data_str.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")

    return hmac.compare_digest(computed, signature_header)


# ---------------------------------------------------------------------------
# Twilio payload extraction
# ---------------------------------------------------------------------------


def extract_messages_twilio(
    form_params: dict[str, str],
) -> list[WhatsAppInboundMessage]:
    """Extract a message from a Twilio webhook POST (form-encoded).

    Twilio sends one message per webhook callback with form parameters::

        MessageSid=SM...
        From=whatsapp:+5511999990001
        To=whatsapp:+14155238886
        Body=Hello world
        ProfileName=John Doe
        ...

    Only WhatsApp messages with a non-empty ``Body`` are processed.
    """
    messages: list[WhatsAppInboundMessage] = []

    message_sid = form_params.get("MessageSid", "")
    from_raw = form_params.get("From", "")
    body = form_params.get("Body", "")
    profile_name = form_params.get("ProfileName")

    if not message_sid or not body:
        return messages

    # Strip "whatsapp:" prefix from the phone number
    from_phone = from_raw
    if from_phone.startswith("whatsapp:"):
        from_phone = from_phone[len("whatsapp:") :]

    messages.append(
        WhatsAppInboundMessage(
            message_id=message_sid,
            from_phone=from_phone,
            timestamp=datetime.now(timezone.utc),
            text=body,
            sender_name=profile_name,
        )
    )

    return messages
