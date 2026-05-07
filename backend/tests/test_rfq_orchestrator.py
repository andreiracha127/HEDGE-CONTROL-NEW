"""Unit tests for RFQOrchestrator — full RFQ lifecycle coordination."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone, date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.utils import now_utc
from app.models.quotes import RFQQuote
from app.models.rfqs import (
    RFQ,
    RFQDirection,
    RFQIntent,
    RFQInvitation,
    RFQInvitationChannel,
    RFQInvitationStatus,
    RFQState,
)
from app.schemas.llm import LLMClassifyResult, MessageIntent, ParsedQuote
from app.schemas.whatsapp import WhatsAppInboundMessage, WhatsAppSendResult
from app.services.llm_agent import LLMUnavailableError
from app.services.rfq_orchestrator import RFQOrchestrator


# ── helpers ──────────────────────────────────────────────────────────────


def _create_rfq(
    session: Session,
    *,
    state: RFQState = RFQState.sent,
    rfq_number: str = "RFQ-TST-001",
    created_at: datetime | None = None,
) -> RFQ:
    rfq = RFQ(
        id=uuid.uuid4(),
        rfq_number=rfq_number,
        intent=RFQIntent.commercial_hedge,
        commodity="COPPER",
        quantity_mt=100.0,
        delivery_window_start=date(2026, 1, 1),
        delivery_window_end=date(2026, 3, 31),
        direction=RFQDirection.buy,
        commercial_active_mt=100.0,
        commercial_passive_mt=0.0,
        commercial_net_mt=100.0,
        commercial_reduction_applied_mt=0.0,
        exposure_snapshot_timestamp=now_utc(),
        state=state,
        created_at=created_at or now_utc(),
    )
    session.add(rfq)
    session.flush()
    return rfq


def _create_invitation(
    session: Session,
    rfq: RFQ,
    *,
    phone: str = "+5511999990001",
    name: str = "Counterparty A",
    channel: RFQInvitationChannel = RFQInvitationChannel.whatsapp,
    status: RFQInvitationStatus = RFQInvitationStatus.queued,
    counterparty_id: uuid.UUID | None = None,
) -> RFQInvitation:
    inv = RFQInvitation(
        id=uuid.uuid4(),
        rfq_id=rfq.id,
        rfq_number=rfq.rfq_number,
        counterparty_id=counterparty_id or uuid.uuid4(),
        recipient_name=name,
        recipient_phone=phone,
        channel=channel,
        message_body="RFQ for 100MT Copper — please reply with your quote.",
        provider_message_id="",
        send_status=status,
        sent_at=now_utc(),
        idempotency_key=f"idem-{uuid.uuid4()}",
    )
    session.add(inv)
    session.flush()
    return inv


def _make_inbound(
    phone: str = "+5511999990001",
    text: str = "I can offer 2550 USD/MT",
    msg_id: str | None = None,
) -> WhatsAppInboundMessage:
    return WhatsAppInboundMessage(
        message_id=msg_id or f"wamid.{uuid.uuid4().hex[:8]}",
        from_phone=phone,
        timestamp=now_utc(),
        text=text,
        sender_name="Test Sender",
    )


def _send_result(success: bool = True) -> WhatsAppSendResult:
    return WhatsAppSendResult(
        success=success,
        provider_message_id="wamid.xyz" if success else None,
        error_code=None if success else "TIMEOUT",
        error_message=None if success else "Timed out",
    )


def _parsed_quote(
    intent: MessageIntent = MessageIntent.quote,
    confidence: float = 0.92,
    price: Decimal | str | None = Decimal("2550.0"),
    unit: str | None = "USD/MT",
    convention: str | None = "avg",
) -> ParsedQuote:
    return ParsedQuote(
        intent=intent,
        confidence=confidence,
        fixed_price_value=price,
        fixed_price_unit=unit,
        float_pricing_convention=convention,
        premium_discount=None,
        counterparty_name="Test Counterparty",
        notes=None,
    )


def _auto_quote_context(session: Session) -> tuple[RFQ, RFQInvitation]:
    rfq = _create_rfq(session, state=RFQState.sent)
    invitation = _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
    session.commit()
    return rfq, invitation


# ── dispatch_whatsapp_invitations ────────────────────────────────────────


@patch("app.services.rfq_orchestrator.WhatsAppService.send_text_message")
def test_dispatch_sends_queued_whatsapp(mock_send):
    mock_send.return_value = _send_result(True)

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        inv = _create_invitation(session, rfq)
        session.commit()

        results = RFQOrchestrator.dispatch_whatsapp_invitations(session, rfq.id)
        session.commit()

    assert results["+5511999990001"] == "sent"
    mock_send.assert_called_once()


@patch("app.services.rfq_orchestrator.WhatsAppService.send_text_message")
def test_dispatch_marks_failed_on_error(mock_send):
    mock_send.return_value = _send_result(False)

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq)
        session.commit()

        results = RFQOrchestrator.dispatch_whatsapp_invitations(session, rfq.id)
        session.commit()

    assert results["+5511999990001"] == "failed"


@patch("app.services.rfq_orchestrator.WhatsAppService.send_text_message")
def test_dispatch_ignores_already_sent(mock_send):
    mock_send.return_value = _send_result(True)

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        results = RFQOrchestrator.dispatch_whatsapp_invitations(session, rfq.id)
        session.commit()

    assert results == {}
    mock_send.assert_not_called()


# ── _process_single_message ──────────────────────────────────────────────


@patch("app.services.rfq_orchestrator.LLMAgent.should_auto_create_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_process_no_matching_rfq(mock_parse, mock_auto):
    msg = _make_inbound(phone="+0000000000")

    with SessionLocal() as session:
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "no_matching_rfq"
    mock_parse.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.should_auto_create_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_process_rfq_not_quotable(mock_parse, mock_auto):
    """Invitation for a closed RFQ is now excluded by the JOIN filter,
    so the orchestrator returns no_matching_rfq instead of rfq_not_quotable."""
    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.closed)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "no_matching_rfq"
    mock_parse.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_process_counterparty_declined(mock_classify):
    mock_classify.return_value = LLMClassifyResult(
        intent=MessageIntent.rejection, confidence=0.95, raw_reasoning=None
    )

    cp_id = uuid.uuid4()
    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(
            session, rfq, status=RFQInvitationStatus.sent, counterparty_id=cp_id
        )
        session.commit()

        msg = _make_inbound(phone="+5511999990001", text="No thanks, passing on this")
        result = RFQOrchestrator._process_single_message(session, msg)
        session.commit()

    assert result["status"] == "counterparty_declined"
    assert result["counterparty"] == str(cp_id)
    mock_classify.assert_called_once()


@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_process_counterparty_question(mock_classify):
    mock_classify.return_value = LLMClassifyResult(
        intent=MessageIntent.question, confidence=0.88, raw_reasoning=None
    )

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001", text="What alloy grade?")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "counterparty_question"
    assert "What alloy grade?" in result["text"]
    mock_classify.assert_called_once()


@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_process_needs_human_review(mock_classify):
    mock_classify.return_value = LLMClassifyResult(
        intent=MessageIntent.other, confidence=0.4, raw_reasoning=None
    )

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001", text="Hmm let me think about it")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "needs_human_review"
    mock_classify.assert_called_once()


@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_process_llm_unavailable(mock_classify, mock_parse):
    mock_classify.side_effect = LLMUnavailableError("LLM is down")
    mock_parse.side_effect = LLMUnavailableError("LLM is down")

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "llm_unavailable"


@patch("app.services.rfq_orchestrator.RFQService.submit_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.should_auto_create_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_process_auto_quote_created(mock_classify, mock_parse, mock_auto, mock_submit):
    mock_classify.return_value = LLMClassifyResult(
        intent=MessageIntent.quote, confidence=0.95, raw_reasoning=None
    )
    parsed = _parsed_quote(intent=MessageIntent.quote, confidence=0.95, price=2550.0)
    mock_parse.return_value = parsed
    mock_auto.return_value = True

    mock_quote = MagicMock()
    mock_quote.id = uuid.uuid4()
    mock_submit.return_value = mock_quote

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001", text="2550 USD/MT avg")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "auto_quote_created"
    assert result["confidence"] == 0.95
    mock_submit.assert_called_once()
    mock_classify.assert_called_once()


@patch("app.services.rfq_orchestrator.RFQService.submit_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.should_auto_create_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_process_auto_quote_fails_gracefully(
    mock_classify, mock_parse, mock_auto, mock_submit
):
    mock_classify.return_value = LLMClassifyResult(
        intent=MessageIntent.quote, confidence=0.95, raw_reasoning=None
    )
    parsed = _parsed_quote(intent=MessageIntent.quote, confidence=0.95, price=2550.0)
    mock_parse.return_value = parsed
    mock_auto.return_value = True
    mock_submit.side_effect = HTTPException(status_code=409, detail="DB conflict")

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001", text="2550 USD/MT")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "auto_quote_failed"
    assert "DB conflict" in result["error"]


@patch("app.services.rfq_orchestrator.RFQService.submit_quote")
def test_auto_quote_skipped_when_unit_missing(mock_submit):
    with SessionLocal() as session:
        rfq, invitation = _auto_quote_context(session)
        msg = _make_inbound(text="2550 avg")
        result = RFQOrchestrator._auto_create_quote(
            session,
            rfq,
            invitation,
            msg,
            _parsed_quote(price=Decimal("2550.0"), unit=None, convention="avg"),
        )

    assert result["status"] == "auto_quote_skipped_incomplete"
    assert result["missing"] == ["unit"]
    mock_submit.assert_not_called()


@patch("app.services.rfq_orchestrator.RFQService.submit_quote")
def test_auto_quote_skipped_when_convention_missing(mock_submit):
    with SessionLocal() as session:
        rfq, invitation = _auto_quote_context(session)
        msg = _make_inbound(text="2550 USD/MT")
        result = RFQOrchestrator._auto_create_quote(
            session,
            rfq,
            invitation,
            msg,
            _parsed_quote(price=Decimal("2550.0"), unit="USD/MT", convention=None),
        )

    assert result["status"] == "auto_quote_skipped_incomplete"
    assert result["missing"] == ["convention"]
    mock_submit.assert_not_called()


@patch("app.services.rfq_orchestrator.RFQService.submit_quote")
def test_auto_quote_skipped_when_price_missing(mock_submit):
    with SessionLocal() as session:
        rfq, invitation = _auto_quote_context(session)
        msg = _make_inbound(text="USD/MT avg")
        result = RFQOrchestrator._auto_create_quote(
            session,
            rfq,
            invitation,
            msg,
            _parsed_quote(price=None, unit="USD/MT", convention="avg"),
        )

    assert result["status"] == "auto_quote_skipped_incomplete"
    assert result["missing"] == ["price"]
    mock_submit.assert_not_called()


@patch("app.services.rfq_orchestrator.RFQService.submit_quote")
def test_auto_quote_skipped_when_unit_non_canonical(mock_submit):
    with SessionLocal() as session:
        rfq, invitation = _auto_quote_context(session)
        msg = _make_inbound(text="2550 USD/KG avg")
        result = RFQOrchestrator._auto_create_quote(
            session,
            rfq,
            invitation,
            msg,
            _parsed_quote(price=Decimal("2550.0"), unit="USD/KG", convention="avg"),
        )

    assert result["status"] == "auto_quote_skipped_incomplete"
    assert result["missing"] == ["unit (non-canonical: 'USD/KG')"]
    mock_submit.assert_not_called()


@patch("app.services.rfq_orchestrator.RFQService.submit_quote")
def test_auto_quote_proceeds_when_all_fields_present_and_canonical(mock_submit):
    mock_quote = MagicMock()
    mock_quote.id = uuid.uuid4()
    mock_submit.return_value = mock_quote

    with SessionLocal() as session:
        rfq, invitation = _auto_quote_context(session)
        msg = _make_inbound(text="2550 USD/MT avg")
        result = RFQOrchestrator._auto_create_quote(
            session,
            rfq,
            invitation,
            msg,
            _parsed_quote(price=Decimal("2550.0"), unit="USD/MT", convention="avg"),
        )

    assert result["status"] == "auto_quote_created"
    mock_submit.assert_called_once()
    quote_payload = mock_submit.call_args.args[2]
    assert quote_payload.counterparty_id == invitation.counterparty_id
    assert quote_payload.fixed_price_value == Decimal("2550.0")
    assert quote_payload.fixed_price_unit == "USD/MT"
    assert quote_payload.float_pricing_convention.value == "avg"


def test_auto_quote_post_commit_log_failure_still_reports_success():
    with SessionLocal() as session:
        rfq, invitation = _auto_quote_context(session)
        msg = _make_inbound(text="2550 USD/MT avg")
        with patch("app.services.rfq_orchestrator.logger.info") as mock_info:
            mock_info.side_effect = RuntimeError("logger serializer failed")
            result = RFQOrchestrator._auto_create_quote(
                session,
                rfq,
                invitation,
                msg,
                _parsed_quote(price=Decimal("2550.0"), unit="USD/MT", convention="avg"),
            )
            quote_id = uuid.UUID(result["quote_id"])

    assert result["status"] == "auto_quote_created"
    with SessionLocal() as session:
        assert session.get(RFQQuote, quote_id) is not None


@patch("app.services.rfq_orchestrator.RFQService.submit_quote")
def test_auto_quote_pre_commit_failure_rolls_back_and_reports_failed(mock_submit):
    mock_submit.side_effect = HTTPException(status_code=409, detail="DB conflict")

    with SessionLocal() as session:
        rfq, invitation = _auto_quote_context(session)
        msg = _make_inbound(text="2550 USD/MT avg")
        with patch.object(session, "rollback", wraps=session.rollback) as rollback:
            result = RFQOrchestrator._auto_create_quote(
                session,
                rfq,
                invitation,
                msg,
                _parsed_quote(price=Decimal("2550.0"), unit="USD/MT", convention="avg"),
            )

    assert result["status"] == "auto_quote_failed"
    assert "DB conflict" in result["error"] or "409" in result["error"]
    rollback.assert_called_once()


# ── process_inbound_queue ────────────────────────────────────────────────


@patch("app.services.rfq_orchestrator.dequeue_message")
def test_process_inbound_empty_queue(mock_dequeue):
    mock_dequeue.return_value = None

    with SessionLocal() as session:
        results = RFQOrchestrator.process_inbound_queue(session)

    assert results == []


@patch("app.services.rfq_orchestrator.RFQOrchestrator._process_single_message")
@patch("app.services.rfq_orchestrator.dequeue_message")
def test_process_inbound_drains_queue(mock_dequeue, mock_process):
    msgs = [_make_inbound(msg_id=f"msg-{i}") for i in range(3)]
    mock_dequeue.side_effect = msgs + [None]
    mock_process.return_value = {"status": "processed"}

    with SessionLocal() as session:
        results = RFQOrchestrator.process_inbound_queue(session)

    assert len(results) == 3
    assert mock_process.call_count == 3


# ── notify_award / notify_reject ─────────────────────────────────────────


@patch("app.services.rfq_orchestrator.WhatsAppService.send_text_message")
@patch("app.services.rfq_orchestrator.LLMAgent.generate_outbound_message")
def test_notify_award_sends_message(mock_gen, mock_send):
    mock_gen.return_value = "Congratulations! You won the RFQ."
    mock_send.return_value = _send_result(True)

    cp_id = uuid.uuid4()
    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.awarded)
        _create_invitation(
            session,
            rfq,
            status=RFQInvitationStatus.sent,
            counterparty_id=cp_id,
        )
        session.commit()

        RFQOrchestrator.notify_award(
            session, rfq, str(cp_id), price=2550.0, unit="USD/MT"
        )

    mock_gen.assert_called_once()
    mock_send.assert_called_once_with(
        phone="+5511999990001",
        text="Congratulations! You won the RFQ.",
    )


@patch("app.services.rfq_orchestrator.WhatsAppService.send_text_message")
@patch("app.services.rfq_orchestrator.LLMAgent.generate_outbound_message")
def test_notify_award_no_whatsapp_invitation(mock_gen, mock_send):
    cp_id = uuid.uuid4()
    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.awarded)
        # No whatsapp invitation — the only channel is whatsapp (enum)
        # but the counterparty_id doesn't match
        session.commit()

        RFQOrchestrator.notify_award(session, rfq, str(cp_id), price=2550.0)

    mock_gen.assert_not_called()
    mock_send.assert_not_called()


@patch("app.services.rfq_orchestrator.WhatsAppService.send_text_message")
@patch("app.services.rfq_orchestrator.LLMAgent.generate_outbound_message")
def test_notify_reject_sends_to_all(mock_gen, mock_send):
    mock_gen.return_value = "Unfortunately the RFQ was closed."
    mock_send.return_value = _send_result(True)

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.closed)
        _create_invitation(session, rfq, phone="+5511999990001", name="A")
        _create_invitation(
            session,
            rfq,
            phone="+5511999990002",
            name="B",
        )
        session.commit()

        RFQOrchestrator.notify_reject(session, rfq)

    assert mock_send.call_count == 2


# ── check_rfq_timeouts ──────────────────────────────────────────────────


@patch("app.services.rfq_orchestrator.RFQService.get_latest_trade_quotes")
def test_check_rfq_timeouts_flags_stale(mock_quotes):
    mock_quotes.return_value = {}  # no quotes

    with SessionLocal() as session:
        old_time = now_utc() - timedelta(hours=48)
        rfq = _create_rfq(
            session,
            state=RFQState.sent,
            rfq_number="RFQ-STALE-001",
            created_at=old_time,
        )
        session.commit()

        flagged = RFQOrchestrator.check_rfq_timeouts(session, timeout_hours=24)

    assert len(flagged) >= 1
    stale = [f for f in flagged if f["rfq_number"] == "RFQ-STALE-001"]
    assert len(stale) == 1
    assert stale[0]["has_quotes"] is False


@patch("app.services.rfq_orchestrator.RFQService.get_latest_trade_quotes")
def test_check_rfq_timeouts_ignores_recent(mock_quotes):
    with SessionLocal() as session:
        rfq = _create_rfq(
            session,
            state=RFQState.sent,
            rfq_number="RFQ-RECENT-002",
            created_at=now_utc(),
        )
        session.commit()

        flagged = RFQOrchestrator.check_rfq_timeouts(session, timeout_hours=24)

    recent_flags = [f for f in flagged if f["rfq_number"] == "RFQ-RECENT-002"]
    assert len(recent_flags) == 0


# ── check_low_response_rfqs ─────────────────────────────────────────────


@patch("app.services.rfq_orchestrator.RFQService.get_latest_trade_quotes")
def test_check_low_response_flags_no_quotes(mock_quotes):
    mock_quotes.return_value = {}

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent, rfq_number="RFQ-LOW-001")
        _create_invitation(session, rfq, phone="+5511000000001")
        _create_invitation(session, rfq, phone="+5511000000002")
        session.commit()

        flagged = RFQOrchestrator.check_low_response_rfqs(
            session, min_response_rate=0.5
        )

    low = [f for f in flagged if f["rfq_number"] == "RFQ-LOW-001"]
    assert len(low) == 1
    assert low[0]["response_rate"] == 0.0
    assert low[0]["total_recipients"] == 2


@patch("app.services.rfq_orchestrator.RFQService.get_latest_trade_quotes")
def test_check_low_response_ok_when_all_replied(mock_quotes):
    mock_quotes.return_value = {
        "+5511000000001": MagicMock(),
        "+5511000000002": MagicMock(),
    }

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent, rfq_number="RFQ-OK-002")
        _create_invitation(session, rfq, phone="+5511000000001")
        _create_invitation(session, rfq, phone="+5511000000002")
        session.commit()

        flagged = RFQOrchestrator.check_low_response_rfqs(
            session, min_response_rate=0.5
        )

    ok = [f for f in flagged if f["rfq_number"] == "RFQ-OK-002"]
    assert len(ok) == 0


# ── Anti-hallucination guards ────────────────────────────────────────────


class TestIsTrivialMessage:
    """Unit tests for _is_trivial_message guard."""

    @pytest.mark.parametrize(
        "text",
        [
            "oi",
            "Ola",
            "olá",
            "OK",
            "ok.",
            "Bom dia!",
            "hi",
            "Hello",
            "thanks!",
            "Got it",
            "sim",
            "valeu",
            "",
            "a",
            "ok",
        ],
    )
    def test_trivial_messages_detected(self, text):
        assert RFQOrchestrator._is_trivial_message(text) is True

    @pytest.mark.parametrize(
        "text",
        [
            "No thanks, passing on this",
            "What alloy grade?",
            "I can offer 2550 USD/MT",
            "2550 USD/MT avg",
            "Hmm let me think about it",
            "Can we do 2600 instead?",
            "We quote 2729 USD/MT for Q1 delivery",
            "Oferecemos 2550 USD/MT média",
        ],
    )
    def test_non_trivial_messages_pass(self, text):
        assert RFQOrchestrator._is_trivial_message(text) is False


class TestPriceAppearsInText:
    """Unit tests for _price_appears_in_text guard."""

    def test_integer_price_found(self):
        assert (
            RFQOrchestrator._price_appears_in_text(2550.0, "We offer 2550 USD/MT")
            is True
        )

    def test_float_price_found(self):
        assert (
            RFQOrchestrator._price_appears_in_text(2550.5, "Price is 2550.5 USD")
            is True
        )

    def test_comma_decimal_found(self):
        assert (
            RFQOrchestrator._price_appears_in_text(2550.5, "Preço 2550,5 USD") is True
        )

    def test_price_not_in_text(self):
        assert RFQOrchestrator._price_appears_in_text(2729.0, "ola") is False

    def test_price_not_in_greeting(self):
        assert RFQOrchestrator._price_appears_in_text(2729.0, "ok bom dia") is False

    def test_none_price(self):
        assert RFQOrchestrator._price_appears_in_text(None, "some text") is False


# ── Hallucinated price blocking (integration) ───────────────────────────


@patch("app.services.rfq_orchestrator.LLMAgent.should_auto_create_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_hallucinated_price_blocked(mock_classify, mock_parse, mock_auto):
    """Guard 3: LLM extracts a price that doesn't exist in the raw text."""
    mock_classify.return_value = LLMClassifyResult(
        intent=MessageIntent.quote, confidence=0.95, raw_reasoning=None
    )
    # LLM hallucinates 2729.0 from a message that says "ola tudo bem?"
    mock_parse.return_value = _parsed_quote(
        intent=MessageIntent.quote, confidence=0.95, price=2729.0
    )
    mock_auto.return_value = True

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001", text="ola tudo bem amigo?")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "hallucinated_price_blocked"
    assert result["hallucinated_price"] == 2729.0


def test_trivial_message_skipped_in_flow():
    """Guard 1: trivial greetings are rejected before any LLM call."""
    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001", text="ok")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "trivial_message_skipped"


@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_classify_first_blocks_greeting_with_digits(mock_classify):
    """Guard 2: classify intent blocks non-quote messages that have digits."""
    mock_classify.return_value = LLMClassifyResult(
        intent=MessageIntent.other, confidence=0.6, raw_reasoning=None
    )

    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        # Has digits but not a quote — classify catches it
        msg = _make_inbound(phone="+5511999990001", text="received your msg at 3pm")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "needs_human_review"
    mock_classify.assert_called_once()


# ── Archived RFQ skip (Phase A2 PR-3, J-A2-11) ──────────────────────────


@patch("app.services.rfq_orchestrator.LLMAgent.should_auto_create_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_inbound_message_skips_archived_rfq(mock_parse, mock_auto):
    """A reply that arrives for an archived RFQ must not be processed.

    The orchestrator selects the newest matching invitation first and
    then short-circuits with ``rfq_archived`` when its RFQ is archived,
    rather than falling through to older RFQs on the same phone. The
    LLM must not be invoked.
    """
    with SessionLocal() as session:
        rfq = _create_rfq(session, state=RFQState.sent)
        rfq.deleted_at = now_utc()
        _create_invitation(session, rfq, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001", text="2550 USD/MT")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "rfq_archived"
    assert result["rfq_id"] == str(rfq.id)
    mock_parse.assert_not_called()
    mock_auto.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.should_auto_create_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_archived_rfq_does_not_fall_through_to_older_live_rfq(mock_parse, mock_auto):
    """A late reply for a newer archived RFQ must not auto-attribute to
    an older still-live RFQ on the same phone.

    Pre-fix behaviour: filtering ``deleted_at IS NULL`` in the WHERE
    clause skipped the newer archived row, the ``ORDER BY`` then selected
    the older live RFQ, and the orchestrator could auto-create a quote on
    the wrong RFQ. Post-fix: the newest matching invitation wins, and
    because its RFQ is archived the orchestrator returns ``rfq_archived``
    without touching the older live RFQ.
    """
    with SessionLocal() as session:
        older_live = _create_rfq(
            session,
            state=RFQState.sent,
            rfq_number="RFQ-TST-OLDER",
            created_at=now_utc() - timedelta(days=2),
        )
        _create_invitation(session, older_live, status=RFQInvitationStatus.sent)

        newer_archived = _create_rfq(
            session,
            state=RFQState.sent,
            rfq_number="RFQ-TST-NEWER",
            created_at=now_utc(),
        )
        newer_archived.deleted_at = now_utc()
        _create_invitation(session, newer_archived, status=RFQInvitationStatus.sent)
        session.commit()

        msg = _make_inbound(phone="+5511999990001", text="2550 USD/MT")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "rfq_archived"
    assert result["rfq_id"] == str(newer_archived.id)
    mock_parse.assert_not_called()
    mock_auto.assert_not_called()
