"""Inbound canonical-id correlation tests for Phase A2 PR-5."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.utils import now_utc
from app.models.counterparty import Counterparty, CounterpartyType
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
from app.schemas.whatsapp import WhatsAppInboundMessage
from app.services.rfq_orchestrator import (
    RFQOrchestrator,
    _parse_canonical_ids,
    _strip_canonical_id,
)


def _create_rfq(
    session: Session,
    *,
    state: RFQState = RFQState.sent,
    rfq_number: str = "RFQ-2026-000123",
    created_at: datetime | None = None,
) -> RFQ:
    rfq = RFQ(
        id=uuid.uuid4(),
        rfq_number=rfq_number,
        intent=RFQIntent.commercial_hedge,
        commodity="COPPER",
        quantity_mt=Decimal("100.000"),
        delivery_window_start=date(2026, 1, 1),
        delivery_window_end=date(2026, 3, 31),
        direction=RFQDirection.buy,
        commercial_active_mt=Decimal("100.000"),
        commercial_passive_mt=Decimal("0.000"),
        commercial_net_mt=Decimal("100.000"),
        commercial_reduction_applied_mt=Decimal("0.000"),
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
    phone: str = "+5511999999999",
    name: str = "Counterparty A",
    status: RFQInvitationStatus = RFQInvitationStatus.sent,
) -> RFQInvitation:
    counterparty = Counterparty(
        type=CounterpartyType.broker,
        name=f"{name}-{uuid.uuid4().hex[:6]}",
        country="BRA",
    )
    session.add(counterparty)
    session.flush()
    invitation = RFQInvitation(
        id=uuid.uuid4(),
        rfq_id=rfq.id,
        rfq_number=rfq.rfq_number,
        counterparty_id=counterparty.id,
        recipient_name=name,
        recipient_phone=phone,
        channel=RFQInvitationChannel.whatsapp,
        message_body=f"RFQ#{rfq.rfq_number} — quote 100MT Copper",
        provider_message_id="wamid.outbound",
        send_status=status,
        sent_at=now_utc(),
        idempotency_key=f"idem-{uuid.uuid4()}",
    )
    session.add(invitation)
    session.flush()
    return invitation


def _make_inbound(
    *,
    phone: str = "+5511999999999",
    text: str = "RFQ#RFQ-2026-000123 — 2550 USD/MT avg",
    msg_id: str | None = None,
) -> WhatsAppInboundMessage:
    return WhatsAppInboundMessage(
        message_id=msg_id or f"wamid.{uuid.uuid4().hex[:8]}",
        from_phone=phone,
        timestamp=now_utc(),
        text=text,
        sender_name="Inbound Sender",
    )


def _canonical_text(rfq: RFQ, text: str) -> str:
    return f"RFQ#{rfq.rfq_number} — {text}"


def _parsed_quote(price: Decimal | str | float = Decimal("2550.0")) -> ParsedQuote:
    return ParsedQuote(
        intent=MessageIntent.quote,
        confidence=0.95,
        fixed_price_value=price,
        fixed_price_unit="USD/MT",
        float_pricing_convention="avg",
        premium_discount=None,
        counterparty_name="Counterparty A",
        notes=None,
    )


def test_parse_canonical_ids_extracts_from_prefixed_body():
    assert _parse_canonical_ids("RFQ#RFQ-2026-000123 — your quote please") == [
        "RFQ-2026-000123"
    ]


def test_parse_canonical_ids_handles_whitespace_prefix():
    assert _parse_canonical_ids("  RFQ#RFQ-2026-000123 ...") == [
        "RFQ-2026-000123"
    ]


def test_parse_canonical_ids_handles_internal_position():
    assert _parse_canonical_ids("Ola! RFQ#RFQ-2026-000456 esta confirmado") == [
        "RFQ-2026-000456"
    ]


def test_parse_canonical_ids_returns_empty_list_on_missing():
    assert _parse_canonical_ids("Bom dia, segue minha cotacao") == []


def test_parse_canonical_ids_returns_empty_list_on_empty_or_none():
    assert _parse_canonical_ids("") == []
    assert _parse_canonical_ids(None) == []


def test_parse_canonical_ids_rejects_bare_rfq_number_without_hash():
    assert _parse_canonical_ids("RFQ-2026-000123") == []


def test_parse_canonical_ids_rejects_short_sequence():
    assert _parse_canonical_ids("RFQ#RFQ-2026-12345") == []


def test_parse_canonical_ids_rejects_overlong_sequence_post_overflow():
    assert _parse_canonical_ids("RFQ#RFQ-2026-1234567") == []


def test_parse_canonical_ids_rejects_adversarial_digit_prepend():
    assert _parse_canonical_ids("RFQ#RFQ-2026-0001234") == []


@pytest.mark.parametrize(
    "text",
    [
        "RFQ#RFQ-2026-000123A",
        "RFQ#RFQ-2026-000123_",
        "RFQ#RFQ-2026-000123abc",
    ],
)
def test_parse_canonical_ids_rejects_alphanumeric_suffix(text):
    assert _parse_canonical_ids(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "abcRFQ#RFQ-2026-000123",
        "_RFQ#RFQ-2026-000123",
        "123RFQ#RFQ-2026-000456",
    ],
)
def test_parse_canonical_ids_rejects_adjacent_word_prefix(text):
    assert _parse_canonical_ids(text) == []


def test_parse_canonical_ids_returns_all_distinct_matches_for_multi_id():
    assert _parse_canonical_ids(
        "RFQ#RFQ-2026-000123 — 2550\nRFQ#RFQ-2026-000456 — 2600"
    ) == ["RFQ-2026-000123", "RFQ-2026-000456"]


def test_parse_canonical_ids_returns_repeated_for_quoted_self_outbound():
    assert _parse_canonical_ids(
        "RFQ#RFQ-2026-000123 — RFQ#RFQ-2026-000123 — ok"
    ) == ["RFQ-2026-000123", "RFQ-2026-000123"]


def test_strip_canonical_id_preserves_leading_minus_sign():
    assert _strip_canonical_id("RFQ#RFQ-2026-000123 — -5 USD/MT") == "-5 USD/MT"


@pytest.mark.parametrize("dash", ["–", "—"])
def test_strip_canonical_id_preserves_compact_dash_sign(dash):
    assert _strip_canonical_id(f"RFQ#RFQ-2026-000123 {dash}5 USD/MT") == (
        f"{dash}5 USD/MT"
    )


def test_strip_canonical_id_preserves_trivial_word():
    assert _strip_canonical_id("RFQ#RFQ-2026-000123 — ok") == "ok"


@patch("app.services.rfq_orchestrator.RFQService.submit_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.should_auto_create_quote")
@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_inbound_with_canonical_id_resolves_by_rfq_number(
    mock_classify, mock_parse, mock_auto, mock_submit
):
    mock_classify.return_value = LLMClassifyResult(
        intent=MessageIntent.quote, confidence=0.95, raw_reasoning=None
    )
    mock_parse.return_value = _parsed_quote()
    mock_auto.return_value = True
    mock_quote = MagicMock()
    mock_quote.id = uuid.uuid4()
    mock_submit.return_value = mock_quote

    with SessionLocal() as session:
        rfq = _create_rfq(session, rfq_number="RFQ-2026-000123")
        _create_invitation(session, rfq)
        session.commit()

        msg = _make_inbound(text=_canonical_text(rfq, "2550 USD/MT avg"))
        result = RFQOrchestrator._process_single_message(session, msg)
        rfq_id = str(rfq.id)

    assert result["status"] == "auto_quote_created"
    assert result["rfq_id"] == rfq_id
    mock_submit.assert_called_once()


def test_inbound_without_canonical_id_is_parked_not_correlated_by_phone():
    session = MagicMock()
    session.query.side_effect = AssertionError("DB query must not run")
    msg = _make_inbound(text="ola tudo bem")

    result = RFQOrchestrator._process_single_message(session, msg)

    assert result == {
        "message_id": msg.message_id,
        "status": "no_canonical_id",
        "from_phone": msg.from_phone,
    }


@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_inbound_with_canonical_id_phone_mismatch_defense_in_depth(mock_parse):
    with SessionLocal() as session:
        rfq = _create_rfq(session, rfq_number="RFQ-2026-000124")
        _create_invitation(session, rfq, phone="+5511111111111")
        session.commit()

        msg = _make_inbound(
            phone="+5522222222222",
            text=_canonical_text(rfq, "2550 USD/MT avg"),
        )
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "phone_mismatch"
    assert result["canonical_number"] == rfq.rfq_number
    assert result["rfq_id"] == str(rfq.id)
    mock_parse.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_inbound_with_canonical_id_unknown_rfq(mock_parse):
    with SessionLocal() as session:
        msg = _make_inbound(text="RFQ#RFQ-2026-999999 — 2550 USD/MT avg")
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "canonical_id_unknown"
    assert result["canonical_number"] == "RFQ-2026-999999"
    mock_parse.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_inbound_with_canonical_id_archived_rfq(mock_parse):
    with SessionLocal() as session:
        rfq = _create_rfq(
            session, state=RFQState.closed, rfq_number="RFQ-2026-000125"
        )
        rfq.deleted_at = now_utc()
        _create_invitation(session, rfq)
        session.commit()

        msg = _make_inbound(text=_canonical_text(rfq, "2550 USD/MT avg"))
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "rfq_archived"
    assert result["rfq_id"] == str(rfq.id)
    mock_parse.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_inbound_with_canonical_id_terminal_state_rfq(mock_parse):
    with SessionLocal() as session:
        rfq = _create_rfq(
            session, state=RFQState.awarded, rfq_number="RFQ-2026-000126"
        )
        _create_invitation(session, rfq)
        session.commit()

        msg = _make_inbound(text=_canonical_text(rfq, "2550 USD/MT avg"))
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "rfq_not_quotable"
    assert result["rfq_id"] == str(rfq.id)
    assert result["rfq_state"] == "AWARDED"
    mock_parse.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_inbound_with_canonical_id_closed_not_archived_rfq(mock_parse):
    with SessionLocal() as session:
        rfq = _create_rfq(
            session, state=RFQState.closed, rfq_number="RFQ-2026-000127"
        )
        _create_invitation(session, rfq)
        session.commit()

        msg = _make_inbound(text=_canonical_text(rfq, "2550 USD/MT avg"))
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "rfq_not_quotable"
    assert result["rfq_state"] == "CLOSED"
    mock_parse.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_inbound_strips_canonical_token_before_trivial_guard(mock_classify):
    with SessionLocal() as session:
        rfq = _create_rfq(session, rfq_number="RFQ-2026-000128")
        _create_invitation(session, rfq)
        session.commit()

        msg = _make_inbound(text=_canonical_text(rfq, "ok"))
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "trivial_message_skipped"
    assert result["rfq_id"] == str(rfq.id)
    mock_classify.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_inbound_strips_canonical_token_before_llm_classify(
    mock_classify, mock_parse
):
    mock_classify.return_value = LLMClassifyResult(
        intent=MessageIntent.question, confidence=0.9, raw_reasoning=None
    )

    with SessionLocal() as session:
        rfq = _create_rfq(session, rfq_number="RFQ-2026-000129")
        _create_invitation(session, rfq)
        session.commit()

        raw_text = _canonical_text(rfq, "vou ver com o time e te respondo")
        msg = _make_inbound(text=raw_text)
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "counterparty_question"
    assert msg.text == raw_text
    mock_classify.assert_called_once_with("vou ver com o time e te respondo")
    mock_parse.assert_not_called()


def test_inbound_with_multiple_canonical_ids_parks():
    session = MagicMock()
    session.query.side_effect = AssertionError("DB query must not run")
    msg = _make_inbound(
        text="RFQ#RFQ-2026-000123 — 2550\nRFQ#RFQ-2026-000456 — 2600"
    )

    result = RFQOrchestrator._process_single_message(session, msg)

    assert result == {
        "message_id": msg.message_id,
        "status": "multi_canonical_id",
        "canonical_numbers": ["RFQ-2026-000123", "RFQ-2026-000456"],
    }


@patch("app.services.rfq_orchestrator.LLMAgent.classify_intent")
def test_inbound_with_repeated_same_canonical_id_correlates(mock_classify):
    with SessionLocal() as session:
        rfq = _create_rfq(session, rfq_number="RFQ-2026-000130")
        _create_invitation(session, rfq)
        session.commit()

        text = f"RFQ#{rfq.rfq_number} — RFQ#{rfq.rfq_number} — ok"
        msg = _make_inbound(text=text)
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "trivial_message_skipped"
    assert result["rfq_id"] == str(rfq.id)
    mock_classify.assert_not_called()


@patch("app.services.rfq_orchestrator.LLMAgent.parse_quote_message")
def test_inbound_with_canonical_id_skips_phone_variant_match_on_other_rfq(mock_parse):
    with SessionLocal() as session:
        rfq_a = _create_rfq(session, rfq_number="RFQ-2026-000131")
        _create_invitation(session, rfq_a, phone="+5511999999999")
        rfq_b = _create_rfq(session, rfq_number="RFQ-2026-000132")
        _create_invitation(session, rfq_b, phone="+5511999999998")
        session.commit()

        msg = _make_inbound(
            phone="+5511999999999",
            text=_canonical_text(rfq_b, "2550 USD/MT avg"),
        )
        result = RFQOrchestrator._process_single_message(session, msg)

    assert result["status"] == "phone_mismatch"
    assert result["canonical_number"] == rfq_b.rfq_number
    assert result["rfq_id"] == str(rfq_b.id)
    mock_parse.assert_not_called()
