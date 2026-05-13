from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from app.core.auth import _ANONYMOUS_USER, get_current_user
from app.core.database import SessionLocal
from app.main import app
from app.models.quotes import RFQQuote, QuoteState
from app.models.rfqs import (
    RFQ,
    RFQInvitation,
    RFQInvitationPurpose,
    RFQInvitationStatus,
    RFQState,
    RFQStateEvent,
)
from app.schemas.whatsapp import WhatsAppSendResult


def _as_actor(sub: str) -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": sub,
        "roles": ["trader", "risk_manager", "auditor"],
    }


def _as_user_without_sub() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "roles": ["trader", "risk_manager", "auditor"],
    }


def _as_anonymous() -> None:
    app.dependency_overrides[get_current_user] = lambda: _ANONYMOUS_USER


def _create_counterparty(client, name: str = "CP-A", phone: str = "+5511999990001") -> str:
    response = client.post(
        "/counterparties",
        json={
            "type": "broker",
            "name": name,
            "country": "BRA",
            "whatsapp_phone": phone,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_rfq(client, cp_ids: list[str]) -> dict:
    response = client.post(
        "/rfqs",
        json={
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": "5.000",
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id} for cp_id in cp_ids],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_quote(client, rfq_id: str, cp_id: str, price: str = "100.000") -> dict:
    response = client.post(
        f"/rfqs/{rfq_id}/quotes",
        json={
            "rfq_id": rfq_id,
            "counterparty_id": cp_id,
            "fixed_price_value": price,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _state_events(rfq_id: str) -> list[RFQStateEvent]:
    with SessionLocal() as session:
        return (
            session.query(RFQStateEvent)
            .filter(RFQStateEvent.rfq_id == UUID(rfq_id))
            .order_by(RFQStateEvent.created_at.asc())
            .all()
        )


def test_reject_rfq_derives_state_event_actor_from_jwt_sub(client) -> None:
    _as_actor("sub-abc")
    cp_id = _create_counterparty(client)
    rfq = _create_rfq(client, [cp_id])
    _create_quote(client, rfq["id"], cp_id)

    response = client.post(f"/rfqs/{rfq['id']}/actions/reject", json={})

    assert response.status_code == 200, response.text
    events = _state_events(rfq["id"])
    assert any(
        event.reason == "USER_REJECTED" and event.user_id == "sub-abc"
        for event in events
    )


@pytest.mark.parametrize("initial_state", ["CREATED", "SENT"])
def test_cancel_rfq_derives_state_event_actor_from_jwt_sub(
    client, initial_state, monkeypatch
) -> None:
    _as_actor("sub-abc")
    cp_id = _create_counterparty(client)
    if initial_state == "CREATED":
        monkeypatch.setattr(
            "app.services.rfq_service.WhatsAppService.send_text_message",
            lambda **_: WhatsAppSendResult(
                success=False,
                error_code="offline",
                error_message="offline",
            ),
        )
    rfq = _create_rfq(client, [cp_id])

    response = client.post(f"/rfqs/{rfq['id']}/actions/cancel", json={})

    assert response.status_code == 200, response.text
    events = _state_events(rfq["id"])
    assert any(
        event.reason == "USER_CANCELLED"
        and event.from_state.value == initial_state
        and event.user_id == "sub-abc"
        for event in events
    )


def test_reject_quote_persists_quote_actor_and_last_quote_event_actor(client) -> None:
    _as_actor("sub-abc")
    cp_id = _create_counterparty(client)
    rfq = _create_rfq(client, [cp_id])
    quote = _create_quote(client, rfq["id"], cp_id)

    response = client.post(
        f"/rfqs/{rfq['id']}/actions/reject-quote?quote_id={quote['id']}",
        json={},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as session:
        quote_row = session.get(RFQQuote, UUID(quote["id"]))
        assert quote_row is not None
        assert quote_row.state == QuoteState.rejected
        assert quote_row.rejected_by == "sub-abc"
        event = (
            session.query(RFQStateEvent)
            .filter_by(rfq_id=UUID(rfq["id"]), reason="ALL_QUOTES_REJECTED")
            .one()
        )
        assert event.user_id == "sub-abc"


def test_reject_quote_with_other_active_quotes_has_no_state_event_but_sets_actor(
    client,
) -> None:
    _as_actor("sub-abc")
    cp_a = _create_counterparty(client, "CP-A", "+5511999990001")
    cp_b = _create_counterparty(client, "CP-B", "+5511999990002")
    rfq = _create_rfq(client, [cp_a, cp_b])
    quote_a = _create_quote(client, rfq["id"], cp_a, "100.000")
    _create_quote(client, rfq["id"], cp_b, "110.000")

    response = client.post(
        f"/rfqs/{rfq['id']}/actions/reject-quote?quote_id={quote_a['id']}",
        json={},
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as session:
        quote_row = session.get(RFQQuote, UUID(quote_a["id"]))
        assert quote_row is not None
        assert quote_row.rejected_by == "sub-abc"
        assert (
            session.query(RFQStateEvent)
            .filter_by(rfq_id=UUID(rfq["id"]), reason="ALL_QUOTES_REJECTED")
            .count()
            == 0
        )


@pytest.mark.parametrize("path", ["refresh", "refresh-counterparty"])
def test_refresh_routes_preserve_no_state_event_sink(client, path) -> None:
    _as_actor("sub-abc")
    cp_id = _create_counterparty(client)
    rfq = _create_rfq(client, [cp_id])
    before = len(_state_events(rfq["id"]))
    body = {"counterparty_id": cp_id} if path == "refresh-counterparty" else {}

    response = client.post(f"/rfqs/{rfq['id']}/actions/{path}", json=body)

    assert response.status_code == 200, response.text
    after = len(_state_events(rfq["id"]))
    assert after == before
    with SessionLocal() as session:
        refresh_rows = (
            session.query(RFQInvitation)
            .filter_by(rfq_id=UUID(rfq["id"]), purpose=RFQInvitationPurpose.refresh)
            .all()
        )
        assert refresh_rows


def test_action_body_user_id_is_rejected_before_state_transition(client) -> None:
    _as_actor("sub-abc")
    cp_id = _create_counterparty(client)
    rfq = _create_rfq(client, [cp_id])
    _create_quote(client, rfq["id"], cp_id)

    response = client.post(
        f"/rfqs/{rfq['id']}/actions/reject", json={"user_id": "spoof"}
    )

    assert response.status_code == 422
    with SessionLocal() as session:
        rfq_row = session.get(RFQ, UUID(rfq["id"]))
        assert rfq_row is not None
        assert rfq_row.state == RFQState.quoted
        assert (
            session.query(RFQStateEvent)
            .filter_by(rfq_id=UUID(rfq["id"]), reason="USER_REJECTED")
            .count()
            == 0
        )


def test_create_body_user_id_is_rejected_with_specific_422(client) -> None:
    _as_actor("sub-abc")
    cp_id = _create_counterparty(client)

    response = client.post(
        "/rfqs",
        json={
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": "5.000",
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [{"counterparty_id": cp_id}],
            "user_id": "spoof",
        },
    )

    assert response.status_code == 422
    assert (
        "user_id is not accepted on POST /rfqs; actor identity is derived from the authenticated JWT sub"
        in response.text
    )
    with SessionLocal() as session:
        assert session.query(RFQ).count() == 0
        assert session.query(RFQInvitation).count() == 0
        assert session.query(RFQStateEvent).count() == 0


def test_create_success_path_persists_actor_on_created_to_sent_event(client) -> None:
    _as_actor("sub-abc")
    cp_id = _create_counterparty(client)

    rfq = _create_rfq(client, [cp_id])

    events = _state_events(rfq["id"])
    assert any(
        event.from_state == RFQState.created
        and event.to_state == RFQState.sent
        and event.user_id == "sub-abc"
        for event in events
    )


def test_create_all_sends_fail_preserves_no_state_event_branch(client, monkeypatch) -> None:
    _as_actor("sub-abc")
    cp_id = _create_counterparty(client)
    monkeypatch.setattr(
        "app.services.rfq_service.WhatsAppService.send_text_message",
        lambda **_: WhatsAppSendResult(
            success=False,
            error_code="offline",
            error_message="offline",
        ),
    )

    rfq = _create_rfq(client, [cp_id])

    assert rfq["state"] == "CREATED"
    with SessionLocal() as session:
        assert session.query(RFQStateEvent).filter_by(rfq_id=UUID(rfq["id"])).count() == 0
        invitation = (
            session.query(RFQInvitation).filter_by(rfq_id=UUID(rfq["id"])).one()
        )
        assert invitation.send_status == RFQInvitationStatus.failed
        assert invitation.failure_reason


def test_missing_sub_claim_is_rejected_with_401(client) -> None:
    _as_actor("setup")
    cp_id = _create_counterparty(client)
    rfq = _create_rfq(client, [cp_id])
    _create_quote(client, rfq["id"], cp_id)
    _as_user_without_sub()

    response = client.post(f"/rfqs/{rfq['id']}/actions/reject", json={})

    assert response.status_code == 401
    assert response.json()["detail"] == "Authenticated subject is required"


def test_anonymous_fallback_subject_is_written_when_dependency_returns_it(client) -> None:
    _as_actor("setup")
    cp_id = _create_counterparty(client)
    rfq = _create_rfq(client, [cp_id])
    _create_quote(client, rfq["id"], cp_id)
    _as_anonymous()

    response = client.post(f"/rfqs/{rfq['id']}/actions/reject", json={})

    assert response.status_code == 200, response.text
    assert any(event.user_id == "anonymous" for event in _state_events(rfq["id"]))


def test_state_event_read_preserves_actor_sub(client) -> None:
    _as_actor("sub-abc")
    cp_id = _create_counterparty(client)
    rfq = _create_rfq(client, [cp_id])
    _create_quote(client, rfq["id"], cp_id)
    client.post(f"/rfqs/{rfq['id']}/actions/reject", json={})

    response = client.get(f"/rfqs/{rfq['id']}/state-events")

    assert response.status_code == 200
    assert any(event["user_id"] == "sub-abc" for event in response.json())
