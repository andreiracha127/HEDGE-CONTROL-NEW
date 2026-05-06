"""Phase 5 tests — WhatsApp Service, Webhook Processor, LLM Agent, RFQ Orchestrator.

These tests mock external services (WhatsApp Cloud API, OpenAI) so that
the full automated RFQ lifecycle can be validated end-to-end without network
calls.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = datetime.now(timezone.utc)


def _make_meta_payload(
    from_phone: str = "+5511999999999",
    text: str = "Ofereço 2450 USD/MT avg",
    message_id: str = "wamid.test123",
    name: str = "Trader João",
    timestamp: int | None = None,
) -> dict:
    """Build a Meta-format webhook payload with one text message."""
    ts = timestamp or int(_NOW.timestamp())
    return {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "BIZ_ACCOUNT_ID",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "+5511000000000",
                                "phone_number_id": "PHONE_ID",
                            },
                            "contacts": [
                                {
                                    "profile": {"name": name},
                                    "wa_id": from_phone,
                                }
                            ],
                            "messages": [
                                {
                                    "from": from_phone,
                                    "id": message_id,
                                    "timestamp": str(ts),
                                    "text": {"body": text},
                                    "type": "text",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }


def _sign_payload(body: bytes, secret: str) -> str:
    """Compute X-Hub-Signature-256 for a body and secret."""
    h = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={h}"


# ===================================================================
# 1. WhatsApp Service
# ===================================================================


@pytest.mark.no_mock_whatsapp
class TestWhatsAppService:
    """Tests for ``app.services.whatsapp_service.WhatsAppService``."""

    @patch.dict(
        os.environ,
        {
            "WHATSAPP_API_URL": "https://graph.facebook.com/v19.0",
            "WHATSAPP_ACCESS_TOKEN": "test_token",
            "WHATSAPP_PHONE_NUMBER_ID": "12345",
        },
    )
    @patch("app.services.whatsapp_service.httpx.post")
    def test_send_text_message_success(self, mock_post: MagicMock) -> None:
        from app.services.whatsapp_service import WhatsAppService

        mock_post.return_value = MagicMock(
            is_success=True,
            json=lambda: {"messages": [{"id": "wamid.abc"}]},
        )

        result = WhatsAppService.send_text_message("+5511999999999", "Hello")

        assert result.success is True
        assert result.provider_message_id == "wamid.abc"
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["type"] == "text"
        assert call_kwargs.kwargs["json"]["text"]["body"] == "Hello"

    @patch.dict(
        os.environ,
        {
            "WHATSAPP_API_URL": "https://graph.facebook.com/v19.0",
            "WHATSAPP_ACCESS_TOKEN": "test_token",
            "WHATSAPP_PHONE_NUMBER_ID": "12345",
        },
    )
    @patch("app.services.whatsapp_service.httpx.post")
    def test_send_text_message_api_error(self, mock_post: MagicMock) -> None:
        from app.services.whatsapp_service import WhatsAppService

        mock_post.return_value = MagicMock(
            is_success=False,
            status_code=400,
            json=lambda: {"error": {"code": 100, "message": "Invalid phone number"}},
        )

        result = WhatsAppService.send_text_message("+000", "Hello")

        assert result.success is False
        assert result.error_code == "100"
        assert "Invalid phone number" in (result.error_message or "")

    @patch.dict(
        os.environ,
        {
            "WHATSAPP_API_URL": "https://graph.facebook.com/v19.0",
            "WHATSAPP_ACCESS_TOKEN": "test_token",
            "WHATSAPP_PHONE_NUMBER_ID": "12345",
        },
    )
    @patch("app.services.whatsapp_service.httpx.post")
    def test_send_text_message_timeout(self, mock_post: MagicMock) -> None:
        from app.services.whatsapp_service import WhatsAppService

        mock_post.side_effect = httpx.TimeoutException("timed out")

        result = WhatsAppService.send_text_message("+5511999999999", "Hello")

        assert result.success is False
        assert result.error_code == "TIMEOUT"

    @patch.dict(
        os.environ,
        {
            "WHATSAPP_API_URL": "https://graph.facebook.com/v19.0",
            "WHATSAPP_ACCESS_TOKEN": "test_token",
            "WHATSAPP_PHONE_NUMBER_ID": "12345",
        },
    )
    @patch("app.services.whatsapp_service.httpx.post")
    def test_send_template_message(self, mock_post: MagicMock) -> None:
        from app.services.whatsapp_service import WhatsAppService

        mock_post.return_value = MagicMock(
            is_success=True,
            json=lambda: {"messages": [{"id": "wamid.tpl1"}]},
        )

        result = WhatsAppService.send_template_message(
            phone="+5511999999999",
            template_name="rfq_request_v1",
            params=["RFQ-001", "Zinc", "100 MT"],
        )

        assert result.success is True
        assert result.provider_message_id == "wamid.tpl1"
        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["json"]["type"] == "template"

    @patch.dict(
        os.environ,
        {
            "WHATSAPP_API_URL": "https://graph.facebook.com/v19.0",
            "WHATSAPP_ACCESS_TOKEN": "test_token",
            "WHATSAPP_PHONE_NUMBER_ID": "12345",
        },
    )
    @patch("app.services.whatsapp_service.httpx.post")
    def test_send_text_message_generic_exception(self, mock_post: MagicMock) -> None:
        from app.services.whatsapp_service import WhatsAppService

        mock_post.side_effect = Exception("Connection refused")

        result = WhatsAppService.send_text_message("+5511999999999", "Hello")

        assert result.success is False
        assert result.error_code == "INTERNAL"


# ===================================================================
# 2. Webhook Processor
# ===================================================================


class TestWebhookProcessor:
    """Tests for ``app.services.webhook_processor``."""

    def test_extract_messages_single(self) -> None:
        from app.services.webhook_processor import extract_messages

        payload = _make_meta_payload(
            from_phone="+5511888888888",
            text="Cotação: 2500 USD/MT",
            message_id="wamid.msg1",
            name="Carlos",
        )
        msgs = extract_messages(payload)

        assert len(msgs) == 1
        assert msgs[0].from_phone == "+5511888888888"
        assert msgs[0].text == "Cotação: 2500 USD/MT"
        assert msgs[0].sender_name == "Carlos"
        assert msgs[0].message_id == "wamid.msg1"

    def test_extract_messages_empty(self) -> None:
        from app.services.webhook_processor import extract_messages

        payload = {"object": "whatsapp_business_account", "entry": []}
        msgs = extract_messages(payload)

        assert msgs == []

    def test_extract_messages_non_text_ignored(self) -> None:
        from app.services.webhook_processor import extract_messages

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
                                        "from": "+5511000000000",
                                        "id": "m1",
                                        "timestamp": "1700000000",
                                        "type": "image",
                                    }
                                ],
                            }
                        }
                    ]
                }
            ],
        }
        msgs = extract_messages(payload)

        assert msgs == []

    def test_enqueue_dequeue(self) -> None:
        from app.services.webhook_processor import (
            dequeue_message,
            drain_queue,
            enqueue_message,
            queue_depth,
        )

        # Ensure queue is empty
        drain_queue()

        from app.schemas.whatsapp import WhatsAppInboundMessage

        msg = WhatsAppInboundMessage(
            message_id="m1",
            from_phone="+5511999999999",
            timestamp=_NOW,
            text="Test",
        )
        enqueue_message(msg)
        assert queue_depth() == 1

        popped = dequeue_message()
        assert popped is not None
        assert popped.message_id == "m1"
        assert queue_depth() == 0

        assert dequeue_message() is None

    def test_drain_queue(self) -> None:
        from app.services.webhook_processor import drain_queue, enqueue_message

        drain_queue()

        from app.schemas.whatsapp import WhatsAppInboundMessage

        for i in range(3):
            enqueue_message(
                WhatsAppInboundMessage(
                    message_id=f"m{i}",
                    from_phone="+5511999999999",
                    timestamp=_NOW,
                    text=f"Msg {i}",
                )
            )

        msgs = drain_queue()
        assert len(msgs) == 3

    @patch.dict(os.environ, {"WHATSAPP_APP_SECRET": "my_secret"})
    def test_verify_signature_valid(self) -> None:
        from app.services.webhook_processor import verify_signature

        body = b'{"test": true}'
        sig = _sign_payload(body, "my_secret")

        assert verify_signature(body, sig) is True

    @patch.dict(os.environ, {"WHATSAPP_APP_SECRET": "my_secret"})
    def test_verify_signature_invalid(self) -> None:
        from app.services.webhook_processor import verify_signature

        body = b'{"test": true}'
        sig = "sha256=bad"

        assert verify_signature(body, sig) is False

    @patch.dict(os.environ, {"WHATSAPP_APP_SECRET": ""})
    def test_verify_signature_no_secret(self) -> None:
        from app.services.webhook_processor import verify_signature

        assert verify_signature(b"body", "sha256=abc") is False


# ===================================================================
# 3. Webhook Routes
# ===================================================================


class TestWebhookRoutes:
    """Test ``GET /webhooks/whatsapp`` and ``POST /webhooks/whatsapp``."""

    @patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "my_token"})
    def test_get_verify_success(self, client: TestClient) -> None:
        resp = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "my_token",
                "hub.challenge": "42",
            },
        )
        assert resp.status_code == 200
        assert resp.json() == 42

    @patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "my_token"})
    def test_get_verify_wrong_token(self, client: TestClient) -> None:
        resp = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "wrong",
                "hub.challenge": "42",
            },
        )
        assert resp.status_code == 403

    @patch.dict(os.environ, {"WHATSAPP_VERIFY_TOKEN": "my_token"})
    def test_get_verify_wrong_mode(self, client: TestClient) -> None:
        resp = client.get(
            "/webhooks/whatsapp",
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": "my_token",
                "hub.challenge": "42",
            },
        )
        assert resp.status_code == 403

    @patch.dict(os.environ, {"WHATSAPP_APP_SECRET": ""})
    @patch("app.api.routes.webhooks._process_queue_in_background")
    def test_post_webhook_enqueues_messages(
        self, _mock_bg: MagicMock, client: TestClient
    ) -> None:
        from app.services.webhook_processor import drain_queue

        drain_queue()

        payload = _make_meta_payload(text="2450 USD avg")
        resp = client.post("/webhooks/whatsapp", json=payload)

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

        msgs = drain_queue()
        assert len(msgs) == 1
        assert msgs[0].text == "2450 USD avg"

    @patch.dict(os.environ, {"WHATSAPP_APP_SECRET": "secret123"})
    def test_post_webhook_invalid_signature(self, client: TestClient) -> None:
        payload = _make_meta_payload()
        body = json.dumps(payload).encode()

        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": "sha256=bad",
            },
        )
        assert resp.status_code == 403

    @patch.dict(os.environ, {"WHATSAPP_APP_SECRET": "secret123"})
    @patch("app.api.routes.webhooks._process_queue_in_background")
    def test_post_webhook_valid_signature(
        self, _mock_bg: MagicMock, client: TestClient
    ) -> None:
        from app.services.webhook_processor import drain_queue

        drain_queue()

        payload = _make_meta_payload(text="2500 USD/MT")
        body = json.dumps(payload).encode()
        sig = _sign_payload(body, "secret123")

        resp = client.post(
            "/webhooks/whatsapp",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Hub-Signature-256": sig,
            },
        )
        assert resp.status_code == 200
        msgs = drain_queue()
        assert len(msgs) == 1


# ===================================================================
# 4. LLM Agent
# ===================================================================


class TestLLMAgent:
    """Tests for ``app.services.llm_agent.LLMAgent``."""

    def test_should_auto_create_quote_true(self) -> None:
        from app.schemas.llm import MessageIntent, ParsedQuote
        from app.services.llm_agent import LLMAgent

        parsed = ParsedQuote(
            intent=MessageIntent.quote,
            confidence=0.95,
            fixed_price_value=Decimal("2450.00"),
            fixed_price_unit="USD/MT",
            float_pricing_convention="avg",
            counterparty_name="Glencore",
        )
        assert LLMAgent.should_auto_create_quote(parsed) is True

    def test_should_auto_create_quote_low_confidence(self) -> None:
        from app.schemas.llm import MessageIntent, ParsedQuote
        from app.services.llm_agent import LLMAgent

        parsed = ParsedQuote(
            intent=MessageIntent.quote,
            confidence=0.60,
            fixed_price_value=Decimal("2450.00"),
            counterparty_name="Glencore",
        )
        assert LLMAgent.should_auto_create_quote(parsed) is False

    def test_should_auto_create_quote_no_price(self) -> None:
        from app.schemas.llm import MessageIntent, ParsedQuote
        from app.services.llm_agent import LLMAgent

        parsed = ParsedQuote(
            intent=MessageIntent.quote,
            confidence=0.95,
            fixed_price_value=None,
            counterparty_name="Glencore",
        )
        assert LLMAgent.should_auto_create_quote(parsed) is False

    def test_should_auto_create_quote_rejection(self) -> None:
        from app.schemas.llm import MessageIntent, ParsedQuote
        from app.services.llm_agent import LLMAgent

        parsed = ParsedQuote(
            intent=MessageIntent.rejection,
            confidence=0.95,
            fixed_price_value=Decimal("2450"),
            counterparty_name="Glencore",
        )
        assert LLMAgent.should_auto_create_quote(parsed) is False

    def test_generate_outbound_message_ptbr(self) -> None:
        from app.services.llm_agent import LLMAgent

        msg = LLMAgent.generate_outbound_message(
            action="award",
            language="pt_BR",
            recipient_name="João",
            rfq_number="RFQ-001",
            price=2450.00,
            unit="USD/MT",
        )
        assert "João" in msg
        assert "RFQ-001" in msg
        assert "2450" in msg

    def test_generate_outbound_message_en(self) -> None:
        from app.services.llm_agent import LLMAgent

        msg = LLMAgent.generate_outbound_message(
            action="reject",
            language="en",
            recipient_name="John",
            rfq_number="RFQ-002",
        )
        assert "John" in msg
        assert "RFQ-002" in msg
        assert "closed" in msg.lower()

    def test_generate_outbound_message_unknown_action(self) -> None:
        from app.services.llm_agent import LLMAgent

        msg = LLMAgent.generate_outbound_message(
            action="unknown_action",
            rfq_number="RFQ-003",
        )
        # Fallback format
        assert "RFQ-003" in msg

    @patch("app.services.llm_agent._call_openai")
    def test_classify_intent_quote(self, mock_openai: MagicMock) -> None:
        from app.services.llm_agent import LLMAgent

        mock_openai.return_value = {
            "intent": "QUOTE",
            "confidence": 0.92,
            "reasoning": "Contains a price offer",
        }

        result = LLMAgent.classify_intent("Ofereço 2500 USD/MT avg")

        assert result.intent.value == "QUOTE"
        assert result.confidence == 0.92
        assert result.raw_reasoning is not None

    @patch("app.services.llm_agent._call_openai")
    def test_classify_intent_rejection(self, mock_openai: MagicMock) -> None:
        from app.services.llm_agent import LLMAgent

        mock_openai.return_value = {
            "intent": "REJECTION",
            "confidence": 0.88,
            "reasoning": "Declines to quote",
        }

        result = LLMAgent.classify_intent("Não temos interesse")
        assert result.intent.value == "REJECTION"

    @patch("app.services.llm_agent._call_openai")
    def test_parse_quote_message(self, mock_openai: MagicMock) -> None:
        from app.services.llm_agent import LLMAgent

        mock_openai.return_value = {
            "intent": "QUOTE",
            "confidence": 0.95,
            "fixed_price_value": 2450.50,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "counterparty_name": "Trader João",
            "notes": None,
        }

        parsed = LLMAgent.parse_quote_message(
            rfq_context="RFQ: RFQ-001\nCommodity: Zinc\nQuantity: 100 MT",
            raw_message="Ofereço 2450.50 USD/MT baseado na média mensal",
            sender_name="Trader João",
        )

        assert parsed.intent.value == "QUOTE"
        assert parsed.confidence == 0.95
        assert parsed.fixed_price_value == Decimal("2450.50")
        assert parsed.fixed_price_unit == "USD/MT"
        assert parsed.float_pricing_convention == "avg"

    @patch("app.services.llm_agent._call_openai")
    def test_parse_quote_message_unknown_intent(self, mock_openai: MagicMock) -> None:
        from app.services.llm_agent import LLMAgent

        mock_openai.return_value = {
            "intent": "BANANA",  # invalid
            "confidence": 0.5,
            "counterparty_name": "Test",
        }

        parsed = LLMAgent.parse_quote_message(
            rfq_context="RFQ-001",
            raw_message="Random text",
        )
        assert parsed.intent.value == "OTHER"

    @patch("app.services.llm_agent.OpenAI")
    def test_call_openai_uses_openai_client_and_model(
        self, mock_openai: MagicMock
    ) -> None:
        from app.services import llm_agent

        completion = MagicMock()
        completion.choices[0].message.content = json.dumps(
            {
                "intent": "OTHER",
                "confidence": 0.10,
                "reasoning": "test",
            }
        )
        mock_openai.return_value.chat.completions.create.return_value = completion

        with patch(
            "app.services.llm_agent.get_settings",
            return_value=SimpleNamespace(
                openai_api_key="sk-test",
                openai_model="gpt-test-model",
            ),
        ):
            result = llm_agent._call_openai("system prompt", "user prompt")

        mock_openai.assert_called_once_with(
            api_key="sk-test",
            timeout=30.0,
            max_retries=0,
        )
        mock_openai.return_value.chat.completions.create.assert_called_once_with(
            model="gpt-test-model",
            messages=[
                {"role": "system", "content": "system prompt"},
                {"role": "user", "content": "user prompt"},
            ],
            temperature=0.1,
            max_tokens=500,
            response_format={"type": "json_object"},
        )
        assert result["intent"] == "OTHER"

    def test_llm_unavailable_error(self) -> None:
        from app.services.llm_agent import LLMAgent, LLMUnavailableError

        # Without OPENAI_API_KEY the call should raise
        with patch(
            "app.services.llm_agent.get_settings",
            return_value=SimpleNamespace(
                openai_api_key="",
                openai_model="gpt-4o-mini",
            ),
        ):
            with pytest.raises(LLMUnavailableError):
                LLMAgent.classify_intent("test")


# ===================================================================
# 5. RFQ Orchestrator
# ===================================================================


class TestRFQOrchestrator:
    """Tests for ``app.services.rfq_orchestrator.RFQOrchestrator``."""

    def _create_rfq_with_invitation(
        self, client: TestClient, phone: str = "+5511999999999"
    ) -> dict:
        """Helper — create a GLOBAL_POSITION RFQ with a whatsapp invitation."""
        from datetime import date

        # Create counterparty with the given phone
        cp_resp = client.post(
            "/counterparties",
            json={
                "type": "broker",
                "name": f"CP-{uuid4().hex[:8]}",
                "country": "BRA",
                "whatsapp_phone": phone,
            },
        )
        assert cp_resp.status_code == 201
        cp_id = cp_resp.json()["id"]

        payload = {
            "intent": "GLOBAL_POSITION",
            "commodity": "Zinc",
            "quantity_mt": 100.0,
            "delivery_window_start": str(date.today()),
            "delivery_window_end": str(date.today() + timedelta(days=30)),
            "direction": "BUY",
            "invitations": [{"counterparty_id": cp_id}],
        }
        resp = client.post("/rfqs/", json=payload)
        assert resp.status_code == 201
        data = resp.json()
        data["_cp_id"] = cp_id  # stash for tests that need it
        return data

    def test_dispatch_whatsapp_invitations(self, client: TestClient, session) -> None:
        from app.services.rfq_orchestrator import RFQOrchestrator

        rfq_data = self._create_rfq_with_invitation(client)
        rfq_id = UUID(rfq_data["id"])

        results = RFQOrchestrator.dispatch_whatsapp_invitations(session, rfq_id)

        # All invitations should have been sent or already processed
        # (the create() method in rfq_service also sends — so status may
        # already be sent/failed. The orchestrator re-sends only queued ones.)
        assert isinstance(results, dict)

    @patch("app.services.llm_agent._call_openai")
    def test_process_inbound_message_auto_quote(
        self, mock_openai: MagicMock, client: TestClient, session
    ) -> None:
        from app.schemas.whatsapp import WhatsAppInboundMessage
        from app.services.rfq_orchestrator import RFQOrchestrator
        from app.services.webhook_processor import drain_queue, enqueue_message

        drain_queue()

        phone = "+5511888888888"
        rfq_data = self._create_rfq_with_invitation(client, phone=phone)

        # Manually set the RFQ state to SENT for testing
        from app.models.rfqs import RFQ as RFQModel, RFQState

        rfq = session.get(RFQModel, UUID(rfq_data["id"]))
        rfq.state = RFQState.sent
        session.commit()

        mock_openai.return_value = {
            "intent": "QUOTE",
            "confidence": 0.95,
            "fixed_price_value": 2450.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "counterparty_name": "Test Bank",
            "notes": None,
        }

        enqueue_message(
            WhatsAppInboundMessage(
                message_id="wamid.in1",
                from_phone=phone,
                timestamp=_NOW,
                text="Ofereço 2450 USD/MT avg",
                sender_name="Test Bank",
            )
        )

        results = RFQOrchestrator.process_inbound_queue(session)

        assert len(results) == 1
        assert results[0]["status"] == "auto_quote_created"
        assert "quote_id" in results[0]

    @patch("app.services.llm_agent._call_openai")
    def test_process_inbound_message_low_confidence(
        self, mock_openai: MagicMock, client: TestClient, session
    ) -> None:
        from app.schemas.whatsapp import WhatsAppInboundMessage
        from app.services.rfq_orchestrator import RFQOrchestrator
        from app.services.webhook_processor import drain_queue, enqueue_message

        drain_queue()

        phone = "+5511777777777"
        rfq_data = self._create_rfq_with_invitation(client, phone=phone)

        from app.models.rfqs import RFQ as RFQModel, RFQState

        rfq = session.get(RFQModel, UUID(rfq_data["id"]))
        rfq.state = RFQState.sent
        session.commit()

        mock_openai.return_value = {
            "intent": "QUOTE",
            "confidence": 0.50,  # Below threshold
            "fixed_price_value": 2400.0,
            "fixed_price_unit": "USD/MT",
            "counterparty_name": "Test Bank",
        }

        enqueue_message(
            WhatsAppInboundMessage(
                message_id="wamid.low",
                from_phone=phone,
                timestamp=_NOW,
                text="Maybe 2400?",
                sender_name="Test Bank",
            )
        )

        results = RFQOrchestrator.process_inbound_queue(session)

        assert len(results) == 1
        assert results[0]["status"] == "needs_human_review"

    def test_process_inbound_message_no_matching_rfq(
        self, client: TestClient, session
    ) -> None:
        from app.schemas.whatsapp import WhatsAppInboundMessage
        from app.services.rfq_orchestrator import RFQOrchestrator
        from app.services.webhook_processor import drain_queue, enqueue_message

        drain_queue()

        enqueue_message(
            WhatsAppInboundMessage(
                message_id="wamid.unknown",
                from_phone="+0000000000",  # No invitation for this phone
                timestamp=_NOW,
                text="Hello",
            )
        )

        results = RFQOrchestrator.process_inbound_queue(session)

        assert len(results) == 1
        assert results[0]["status"] == "no_matching_rfq"

    def test_check_rfq_timeouts_no_quotes(self, client: TestClient, session) -> None:
        """RFQ with no quotes past timeout → flagged (state stays SENT;
        trader decides in the UI)."""
        from app.services.rfq_orchestrator import RFQOrchestrator

        rfq_data = self._create_rfq_with_invitation(client)

        from app.models.rfqs import RFQ as RFQModel, RFQState

        rfq = session.get(RFQModel, UUID(rfq_data["id"]))
        rfq.state = RFQState.sent
        # Set created_at to the past
        rfq.created_at = _NOW - timedelta(hours=25)
        session.commit()

        timed_out = RFQOrchestrator.check_rfq_timeouts(session, timeout_hours=24)

        assert len(timed_out) == 1
        assert timed_out[0]["rfq_id"] == rfq_data["id"]

        # check_rfq_timeouts does NOT auto-transition — it only flags
        session.refresh(rfq)
        assert rfq.state == RFQState.sent

    @patch("app.services.whatsapp_service.WhatsAppService.send_text_message")
    def test_notify_award(
        self, mock_send: MagicMock, client: TestClient, session
    ) -> None:
        from app.schemas.whatsapp import WhatsAppSendResult
        from app.services.rfq_orchestrator import RFQOrchestrator

        mock_send.return_value = WhatsAppSendResult(
            success=True, provider_message_id="wamid.award"
        )

        phone = "+5511111111111"
        rfq_data = self._create_rfq_with_invitation(client, phone=phone)

        from app.models.rfqs import RFQ as RFQModel

        rfq = session.get(RFQModel, UUID(rfq_data["id"]))

        RFQOrchestrator.notify_award(
            session,
            rfq,
            winning_counterparty_id=rfq_data["_cp_id"],
            price=2450.0,
            unit="USD/MT",
        )

        # Should have called WhatsApp
        assert mock_send.called
        call_kwargs = mock_send.call_args.kwargs
        assert "2450" in call_kwargs["text"]

    @patch("app.services.whatsapp_service.WhatsAppService.send_text_message")
    def test_notify_reject(
        self, mock_send: MagicMock, client: TestClient, session
    ) -> None:
        from app.schemas.whatsapp import WhatsAppSendResult
        from app.services.rfq_orchestrator import RFQOrchestrator

        mock_send.return_value = WhatsAppSendResult(
            success=True, provider_message_id="wamid.rej"
        )

        phone = "+5511222222222"
        rfq_data = self._create_rfq_with_invitation(client, phone=phone)

        from app.models.rfqs import RFQ as RFQModel

        rfq = session.get(RFQModel, UUID(rfq_data["id"]))

        RFQOrchestrator.notify_reject(session, rfq)

        assert mock_send.called
        call_kwargs = mock_send.call_args.kwargs
        assert "encerrada" in call_kwargs["text"]


# ===================================================================
# 6. RFQ Timeout Task
# ===================================================================


class TestRFQTimeoutTask:
    """Tests for ``app.tasks.rfq_timeout_task``."""

    @patch("app.tasks.rfq_timeout_task.RFQOrchestrator")
    def test_run_rfq_timeout_check(self, mock_orchestrator: MagicMock) -> None:
        from app.tasks.rfq_timeout_task import run_rfq_timeout_check

        mock_orchestrator.check_low_response_rfqs.return_value = []
        mock_orchestrator.check_rfq_timeouts.return_value = []

        run_rfq_timeout_check()

        mock_orchestrator.check_low_response_rfqs.assert_called_once()
        mock_orchestrator.check_rfq_timeouts.assert_called_once()


# ---------------------------------------------------------------------------
# Brazilian phone variant & retry tests
# ---------------------------------------------------------------------------


class TestBrazilianPhoneVariant:
    """Unit tests for TwilioWhatsAppProvider._brazilian_phone_variant()."""

    def _variant(self, phone: str) -> str | None:
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        return TwilioWhatsAppProvider._brazilian_phone_variant(phone)

    def test_9digit_to_8digit(self) -> None:
        assert self._variant("whatsapp:+5541991022018") == "whatsapp:+554191022018"

    def test_8digit_to_9digit(self) -> None:
        assert self._variant("whatsapp:+554191022018") == "whatsapp:+5541991022018"

    def test_non_brazilian_returns_none(self) -> None:
        assert self._variant("whatsapp:+14155238886") is None

    def test_raw_phone_9digit(self) -> None:
        assert self._variant("+5541991022018") == "whatsapp:+554191022018"

    def test_raw_phone_8digit(self) -> None:
        assert self._variant("+554191022018") == "whatsapp:+5541991022018"

    def test_short_number_returns_none(self) -> None:
        assert self._variant("+551234") is None

    def test_non_9_prefix_11digit(self) -> None:
        # 11 digits after +55 but 3rd digit is not 9 → no variant
        assert self._variant("whatsapp:+5541891022018") is None


class TestSandboxDetection:
    """Tests for _is_sandbox() and _sandbox_normalize_brazilian()."""

    def test_is_sandbox_true(self) -> None:
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+14155238886",
        }):
            provider = TwilioWhatsAppProvider()
            assert provider._is_sandbox() is True

    def test_is_sandbox_false_production(self) -> None:
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+5511999888777",
        }):
            provider = TwilioWhatsAppProvider()
            assert provider._is_sandbox() is False

    def test_is_sandbox_false_missing_env(self) -> None:
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
        }, clear=False):
            # Remove TWILIO_WHATSAPP_FROM if present
            env = os.environ.copy()
            env.pop("TWILIO_WHATSAPP_FROM", None)
            with patch.dict(os.environ, env, clear=True):
                provider = TwilioWhatsAppProvider()
                assert provider._is_sandbox() is False

    def test_sandbox_normalize_9digit_to_8digit(self) -> None:
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+14155238886",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._sandbox_normalize_brazilian("whatsapp:+5541991022018")
            assert result == "whatsapp:+554191022018"

    def test_sandbox_normalize_8digit_unchanged(self) -> None:
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+14155238886",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._sandbox_normalize_brazilian("whatsapp:+554191022018")
            # Already 8-digit → no change
            assert result == "whatsapp:+554191022018"

    def test_sandbox_normalize_non_br_unchanged(self) -> None:
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+14155238886",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._sandbox_normalize_brazilian("whatsapp:+14155551234")
            assert result == "whatsapp:+14155551234"

    def test_production_no_normalize(self) -> None:
        """In production mode, Brazilian 9-digit numbers stay as-is."""
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+5511999888777",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._sandbox_normalize_brazilian("whatsapp:+5541991022018")
            # Production → no change
            assert result == "whatsapp:+5541991022018"


class TestTwilioProactiveSandboxSend:
    """Test that _send() proactively normalizes BR phones in sandbox mode."""

    @patch("app.services.whatsapp_providers.httpx.post")
    def test_sandbox_sends_8digit_for_br_9digit(self, mock_post: MagicMock) -> None:
        """In sandbox mode, 9-digit BR phone should be converted to 8-digit BEFORE sending."""
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        ok_resp = MagicMock()
        ok_resp.status_code = 201
        ok_resp.json.return_value = {"sid": "SM_proactive", "status": "queued"}

        mock_post.return_value = ok_resp

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+14155238886",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._send(phone="+5541991022018", body="Test")

        assert result.success is True
        assert result.provider_message_id == "SM_proactive"
        # Should have sent to the 8-digit variant (proactive normalization)
        assert mock_post.call_count == 1
        sent_data = mock_post.call_args.kwargs.get("data") or mock_post.call_args[1].get("data")
        assert sent_data["To"] == "whatsapp:+554191022018"

    @patch("app.services.whatsapp_providers.httpx.post")
    def test_production_sends_9digit_as_is(self, mock_post: MagicMock) -> None:
        """In production mode, 9-digit BR phone should be sent unchanged."""
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        ok_resp = MagicMock()
        ok_resp.status_code = 201
        ok_resp.json.return_value = {"sid": "SM_prod", "status": "queued"}

        mock_post.return_value = ok_resp

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+5511999888777",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._send(phone="+5541991022018", body="Test")

        assert result.success is True
        assert mock_post.call_count == 1
        sent_data = mock_post.call_args.kwargs.get("data") or mock_post.call_args[1].get("data")
        assert sent_data["To"] == "whatsapp:+5541991022018"

    @patch("app.services.whatsapp_providers.httpx.post")
    def test_sandbox_non_br_phone_unchanged(self, mock_post: MagicMock) -> None:
        """In sandbox mode, non-BR phones are not modified."""
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        ok_resp = MagicMock()
        ok_resp.status_code = 201
        ok_resp.json.return_value = {"sid": "SM_nonbr", "status": "queued"}

        mock_post.return_value = ok_resp

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+14155238886",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._send(phone="+14155551234", body="Test")

        assert result.success is True
        assert mock_post.call_count == 1
        sent_data = mock_post.call_args.kwargs.get("data") or mock_post.call_args[1].get("data")
        assert sent_data["To"] == "whatsapp:+14155551234"


class TestTwilioBrazilianRetry:
    """Test that _send() retries with BR phone variant on error 63015.

    NOTE: With proactive sandbox normalization, the first call already
    goes to the 8-digit variant. The sync retry only triggers if:
    (a) we're NOT in sandbox mode, or
    (b) the proactively-normalized number ALSO returns 63015 synchronously.
    In practice these tests set sandbox FROM so proactive norm fires first.
    """

    @patch("app.services.whatsapp_providers.httpx.post")
    def test_retry_on_63015_with_br_phone(self, mock_post: MagicMock) -> None:
        """First call (already proactively normalized) fails sync 63015,
        retry with the 9-digit variant succeeds."""
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        fail_resp = MagicMock()
        fail_resp.status_code = 400
        fail_resp.json.return_value = {"code": 63015, "message": "sandbox error"}

        ok_resp = MagicMock()
        ok_resp.status_code = 201
        ok_resp.json.return_value = {"sid": "SM_retry_ok", "status": "queued"}

        mock_post.side_effect = [fail_resp, ok_resp]

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+14155238886",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._send(phone="+5541991022018", body="Test")

        assert result.success is True
        assert result.provider_message_id == "SM_retry_ok"
        assert mock_post.call_count == 2
        # First call: proactive norm → 8-digit
        first_data = mock_post.call_args_list[0].kwargs.get("data") or mock_post.call_args_list[0][1].get("data")
        assert first_data["To"] == "whatsapp:+554191022018"
        # Second call (retry): variant of 8-digit → 9-digit
        second_data = mock_post.call_args_list[1].kwargs.get("data") or mock_post.call_args_list[1][1].get("data")
        assert second_data["To"] == "whatsapp:+5541991022018"

    @patch("app.services.whatsapp_providers.httpx.post")
    def test_no_retry_on_non_br_phone(self, mock_post: MagicMock) -> None:
        """Non-Brazilian phone with 63015 error should NOT retry."""
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        fail_resp = MagicMock()
        fail_resp.status_code = 400
        fail_resp.json.return_value = {"code": 63015, "message": "sandbox error"}

        mock_post.return_value = fail_resp

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+14155238886",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._send(phone="+14155551234", body="Test")

        assert result.success is False
        assert result.error_code == "63015"
        assert mock_post.call_count == 1

    @patch("app.services.whatsapp_providers.httpx.post")
    def test_no_infinite_retry(self, mock_post: MagicMock) -> None:
        """Even if retry also gets 63015, it should not recurse further."""
        from app.services.whatsapp_providers import TwilioWhatsAppProvider

        fail_resp = MagicMock()
        fail_resp.status_code = 400
        fail_resp.json.return_value = {"code": 63015, "message": "sandbox error"}

        mock_post.return_value = fail_resp

        with patch.dict(os.environ, {
            "TWILIO_ACCOUNT_SID": "ACtest",
            "TWILIO_AUTH_TOKEN": "token",
            "TWILIO_WHATSAPP_FROM": "+14155238886",
        }):
            provider = TwilioWhatsAppProvider()
            result = provider._send(phone="+5541991022018", body="Test")

        assert result.success is False
        # Exactly 2 calls: original (proactive 8-digit) + 1 retry (9-digit)
        assert mock_post.call_count == 2
