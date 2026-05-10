"""Unit tests for webhook_processor — queue, HMAC, payload extraction."""

from __future__ import annotations

import hashlib
import hmac
import os
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from app.schemas.whatsapp import WhatsAppInboundMessage
from app.services.webhook_processor import (
    dequeue_message,
    drain_queue,
    enqueue_message,
    extract_messages,
    extract_messages_twilio,
    mark_message_finished,
    queue_depth,
    verify_signature,
    verify_twilio_signature,
    _active_durable_message_ids,
    _message_queue,
    _seen_message_ids,
    _seen_set,
)

import pytest


# ── fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_queue():
    """Reset the in-process queue between tests."""
    _active_durable_message_ids.clear()
    _message_queue.clear()
    _seen_message_ids.clear()
    _seen_set.clear()
    yield
    _active_durable_message_ids.clear()
    _message_queue.clear()
    _seen_message_ids.clear()
    _seen_set.clear()


def _make_msg(
    msg_id: str = "msg-1", phone: str = "+5511999990001"
) -> WhatsAppInboundMessage:
    return WhatsAppInboundMessage(
        message_id=msg_id,
        from_phone=phone,
        timestamp=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        text="Hello, I'd like to quote",
        sender_name="Test Sender",
    )


# ── enqueue / dequeue ───────────────────────────────────────────────────


def test_enqueue_and_dequeue():
    msg = _make_msg()
    enqueue_message(msg)
    assert queue_depth() == 1

    popped = dequeue_message()
    assert popped is not None
    assert popped.message_id == "msg-1"
    assert queue_depth() == 0


def test_dequeue_empty_returns_none():
    assert dequeue_message() is None


def test_enqueue_duplicate_ignored():
    msg = _make_msg("dup-1")
    enqueue_message(msg)
    enqueue_message(msg)  # duplicate
    assert queue_depth() == 1


def test_enqueue_durable_duplicate_ignored_until_finished():
    durable_id = uuid.uuid4()
    msg = _make_msg("durable-dup").model_copy(
        update={"delivery_message_id": durable_id}
    )

    assert enqueue_message(msg) is True
    assert enqueue_message(msg) is False
    assert queue_depth() == 1

    mark_message_finished(msg)
    assert enqueue_message(msg) is True
    assert queue_depth() == 2


def test_drain_queue_returns_all():
    enqueue_message(_make_msg("a"))
    enqueue_message(_make_msg("b"))
    enqueue_message(_make_msg("c"))
    assert queue_depth() == 3

    drained = drain_queue()
    assert len(drained) == 3
    assert queue_depth() == 0


def test_fifo_ordering():
    enqueue_message(_make_msg("first"))
    enqueue_message(_make_msg("second"))
    assert dequeue_message().message_id == "first"
    assert dequeue_message().message_id == "second"


def test_queue_depth_updates():
    assert queue_depth() == 0
    enqueue_message(_make_msg("x"))
    assert queue_depth() == 1
    dequeue_message()
    assert queue_depth() == 0


# ── verify_signature ────────────────────────────────────────────────────


def test_verify_signature_valid():
    secret = "test-secret-123"
    body = b'{"entry": []}'
    expected_hmac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    sig_header = f"sha256={expected_hmac}"

    with patch.dict(os.environ, {"WHATSAPP_APP_SECRET": secret}):
        assert verify_signature(body, sig_header) is True


def test_verify_signature_invalid():
    secret = "test-secret-123"
    body = b'{"entry": []}'

    with patch.dict(os.environ, {"WHATSAPP_APP_SECRET": secret}):
        assert verify_signature(body, "sha256=badhex") is False


def test_verify_signature_missing_secret():
    with patch.dict(os.environ, {"WHATSAPP_APP_SECRET": ""}):
        assert verify_signature(b"data", "sha256=abc") is False


def test_verify_signature_no_sha256_prefix():
    with patch.dict(os.environ, {"WHATSAPP_APP_SECRET": "secret"}):
        assert verify_signature(b"data", "md5=abc") is False


def test_verify_signature_tampered_body():
    secret = "test-secret-123"
    body = b'{"entry": []}'
    expected_hmac = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    sig_header = f"sha256={expected_hmac}"

    with patch.dict(os.environ, {"WHATSAPP_APP_SECRET": secret}):
        assert verify_signature(b'{"entry": [TAMPERED]}', sig_header) is False


# ── extract_messages ─────────────────────────────────────────────────────


def _meta_payload(messages: list[dict], contacts: list[dict] | None = None) -> dict:
    """Build a minimal Meta webhook payload."""
    if contacts is None:
        contacts = [
            {"wa_id": m.get("from", ""), "profile": {"name": "Counterparty"}}
            for m in messages
        ]
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": contacts,
                            "messages": messages,
                        }
                    }
                ]
            }
        ],
    }


def test_extract_text_message():
    payload = _meta_payload(
        [
            {
                "id": "wamid.1",
                "from": "+5511999990001",
                "timestamp": "1700000000",
                "type": "text",
                "text": {"body": "I can offer 2550 USD/MT"},
            }
        ]
    )
    msgs = extract_messages(payload)
    assert len(msgs) == 1
    assert msgs[0].message_id == "wamid.1"
    assert msgs[0].from_phone == "+5511999990001"
    assert msgs[0].text == "I can offer 2550 USD/MT"
    assert msgs[0].sender_name == "Counterparty"


def test_extract_skips_non_text():
    payload = _meta_payload(
        [
            {
                "id": "wamid.2",
                "from": "+5511999990001",
                "timestamp": "1700000000",
                "type": "image",
                "image": {"id": "img-1"},
            }
        ]
    )
    msgs = extract_messages(payload)
    assert len(msgs) == 0


def test_extract_multiple_messages():
    payload = _meta_payload(
        [
            {
                "id": "wamid.3",
                "from": "+5511999990001",
                "timestamp": "1700000000",
                "type": "text",
                "text": {"body": "msg 1"},
            },
            {
                "id": "wamid.4",
                "from": "+5511999990002",
                "timestamp": "1700000001",
                "type": "text",
                "text": {"body": "msg 2"},
            },
        ],
        contacts=[
            {"wa_id": "+5511999990001", "profile": {"name": "Alice"}},
            {"wa_id": "+5511999990002", "profile": {"name": "Bob"}},
        ],
    )
    msgs = extract_messages(payload)
    assert len(msgs) == 2
    assert msgs[0].sender_name == "Alice"
    assert msgs[1].sender_name == "Bob"


def test_extract_empty_payload():
    msgs = extract_messages({"entry": []})
    assert msgs == []

    msgs = extract_messages({})
    assert msgs == []


def test_extract_bad_timestamp_uses_now():
    payload = _meta_payload(
        [
            {
                "id": "wamid.5",
                "from": "+5511999990001",
                "timestamp": "not-a-number",
                "type": "text",
                "text": {"body": "hello"},
            }
        ]
    )
    msgs = extract_messages(payload)
    assert len(msgs) == 1
    # Timestamp should be close to now (UTC)
    assert msgs[0].timestamp.tzinfo is not None


def test_extract_no_contacts():
    payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "contacts": [],
                            "messages": [
                                {
                                    "id": "wamid.6",
                                    "from": "+5511999990001",
                                    "timestamp": "1700000000",
                                    "type": "text",
                                    "text": {"body": "test"},
                                }
                            ],
                        }
                    }
                ]
            }
        ],
    }
    msgs = extract_messages(payload)
    assert len(msgs) == 1
    assert msgs[0].sender_name is None


# ── verify_twilio_signature ─────────────────────────────────────────────


def _compute_twilio_signature(auth_token: str, url: str, params: dict[str, str]) -> str:
    """Compute a valid Twilio signature for test assertions."""
    import hashlib
    import hmac as _hmac
    from base64 import b64encode as _b64

    data_str = url
    for key in sorted(params.keys()):
        data_str += key + params[key]
    return _b64(
        _hmac.new(
            auth_token.encode("utf-8"),
            data_str.encode("utf-8"),
            hashlib.sha1,
        ).digest()
    ).decode("utf-8")


def test_verify_twilio_signature_valid():
    token = "twilio-test-token"
    url = "https://example.com/webhooks/whatsapp"
    params = {"Body": "Hello", "From": "whatsapp:+5511999990001", "MessageSid": "SM123"}
    sig = _compute_twilio_signature(token, url, params)

    with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": token}):
        assert verify_twilio_signature(url, params, sig) is True


def test_verify_twilio_signature_invalid():
    token = "twilio-test-token"
    url = "https://example.com/webhooks/whatsapp"
    params = {"Body": "Hello", "From": "whatsapp:+5511999990001"}

    with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": token}):
        assert verify_twilio_signature(url, params, "badsig") is False


def test_verify_twilio_signature_missing_token():
    with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": ""}):
        assert verify_twilio_signature("https://x.com", {}, "sig") is False


def test_verify_twilio_signature_empty_header():
    with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": "tok"}):
        assert verify_twilio_signature("https://x.com", {}, "") is False


def test_verify_twilio_signature_tampered_params():
    token = "twilio-test-token"
    url = "https://example.com/webhooks/whatsapp"
    original_params = {"Body": "Hello", "From": "whatsapp:+5511999990001"}
    sig = _compute_twilio_signature(token, url, original_params)

    tampered_params = {"Body": "TAMPERED", "From": "whatsapp:+5511999990001"}
    with patch.dict(os.environ, {"TWILIO_AUTH_TOKEN": token}):
        assert verify_twilio_signature(url, tampered_params, sig) is False


# ── extract_messages_twilio ──────────────────────────────────────────────


def test_extract_twilio_text_message():
    form = {
        "MessageSid": "SM1234567890",
        "From": "whatsapp:+5511999990001",
        "To": "whatsapp:+14155238886",
        "Body": "I can offer 2550 USD/MT",
        "ProfileName": "Counterparty",
    }
    msgs = extract_messages_twilio(form)
    assert len(msgs) == 1
    assert msgs[0].message_id == "SM1234567890"
    assert msgs[0].from_phone == "+5511999990001"  # prefix stripped
    assert msgs[0].text == "I can offer 2550 USD/MT"
    assert msgs[0].sender_name == "Counterparty"


def test_extract_twilio_strips_whatsapp_prefix():
    form = {
        "MessageSid": "SM999",
        "From": "whatsapp:+5521988880000",
        "Body": "test",
    }
    msgs = extract_messages_twilio(form)
    assert len(msgs) == 1
    assert msgs[0].from_phone == "+5521988880000"


def test_extract_twilio_empty_body():
    form = {
        "MessageSid": "SM000",
        "From": "whatsapp:+5511999990001",
        "Body": "",
    }
    msgs = extract_messages_twilio(form)
    assert len(msgs) == 0


def test_extract_twilio_missing_message_sid():
    form = {
        "From": "whatsapp:+5511999990001",
        "Body": "hello",
    }
    msgs = extract_messages_twilio(form)
    assert len(msgs) == 0


def test_extract_twilio_no_profile_name():
    form = {
        "MessageSid": "SM555",
        "From": "whatsapp:+5511999990001",
        "Body": "hello",
    }
    msgs = extract_messages_twilio(form)
    assert len(msgs) == 1
    assert msgs[0].sender_name is None


def test_extract_twilio_phone_without_prefix():
    """Twilio always sends 'whatsapp:' prefix, but handle cases without it."""
    form = {
        "MessageSid": "SM777",
        "From": "+5511999990001",
        "Body": "hello",
    }
    msgs = extract_messages_twilio(form)
    assert len(msgs) == 1
    assert msgs[0].from_phone == "+5511999990001"
