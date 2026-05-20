# backend/tests/test_counterparty_kyc_transition.py
import os
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.main import app
from app.models.audit import AuditEvent
from app.models.counterparty import Counterparty, KycStatus
from app.models.quotes import RFQQuote
from app.schemas.rfq import RFQQuoteCreate
from app.services.audit_trail_service import _reset_signing_key_cache
from app.services.rfq_service import RFQService


@contextmanager
def _without_signing_key():
    previous = os.environ.pop("AUDIT_SIGNING_KEY", None)
    _reset_signing_key_cache()
    try:
        yield
    finally:
        if previous is not None:
            os.environ["AUDIT_SIGNING_KEY"] = previous
        else:
            os.environ["AUDIT_SIGNING_KEY"] = "test-signing-key-for-audit-hmac"
        _reset_signing_key_cache()


def _create_counterparty(client: TestClient, name: str) -> dict:
    # Set fallback user role to risk_manager (since client usually defaults to anonymous having all roles,
    # but we make it explicit here)
    resp = client.post(
        "/counterparties",
        json={
            "type": "broker",
            "name": name,
            "country": "BRA",
            "whatsapp_phone": "+5511999990001",
        },
    )
    assert resp.status_code == 201
    return resp.json()


def test_risk_manager_can_transition_pending_to_approved(
    client: TestClient, session: Session
) -> None:
    # 1. Create counterparty
    cp = _create_counterparty(client, "Cpty RM Approved")
    cp_id = cp["id"]
    assert cp["kyc_status"] == "pending"

    # 2. Mock risk_manager role explicitly
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "rm-user",
        "roles": ["risk_manager"],
    }
    try:
        r = client.post(
            f"/counterparties/{cp_id}/kyc-status",
            json={"new_status": "approved", "reason": "KYC cleared via external provider"},
        )
        assert r.status_code == 200
        assert r.json()["kyc_status"] == "approved"

    # 3. Assert kyc_status_changed audit event is recorded with expected attributes
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    with session.no_autoflush:
        audit_event = (
            session.query(AuditEvent)
            .filter(AuditEvent.event_type == "kyc_status_changed")
            .filter(AuditEvent.entity_id == UUID(cp_id))
            .first()
        )
        assert audit_event is not None
        assert audit_event.payload["request"]["new_status"] == "approved"
        assert audit_event.payload["request"]["reason"] == "KYC cleared via external provider"
        assert audit_event.payload["metadata"]["previous_status"] == "pending"
        assert audit_event.payload["metadata"]["new_status"] == "approved"
        assert audit_event.payload["metadata"]["actor_sub"] == "rm-user"
        assert audit_event.payload["metadata"]["reason"] == "KYC cleared via external provider"


def test_trader_cannot_transition_kyc_status(client: TestClient) -> None:
    cp = _create_counterparty(client, "Cpty Trader Revoke")
    cp_id = cp["id"]

    # Mock trader role
    app.dependency_overrides[get_current_user] = lambda: {"sub": "trader-user", "roles": ["trader"]}
    try:
        r = client.post(
            f"/counterparties/{cp_id}/kyc-status",
            json={"new_status": "approved", "reason": "Test transition reason"},
        )
        assert r.status_code == 403
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_set_kyc_status_404_on_soft_deleted(client: TestClient) -> None:
    cp = _create_counterparty(client, "Soft Deleted Kyc")
    cp_id = cp["id"]

    # Soft delete the counterparty
    r_del = client.delete(f"/counterparties/{cp_id}")
    assert r_del.status_code == 200

    # Try to change status
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "rm-user",
        "roles": ["risk_manager"],
    }
    try:
        r = client.post(
            f"/counterparties/{cp_id}/kyc-status",
            json={"new_status": "approved", "reason": "Test transition reason"},
        )
        assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_kyc_transition_rolls_back_when_audit_signing_fails(
    client: TestClient, session: Session
) -> None:
    cp = _create_counterparty(client, "Audit Failure Rollback")
    cp_id = cp["id"]

    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "rm-user",
        "roles": ["risk_manager"],
    }
    try:
        with _without_signing_key():
            r = client.post(
                f"/counterparties/{cp_id}/kyc-status",
                json={"new_status": "approved", "reason": "Test transition reason"},
            )
            assert r.status_code >= 500

        # Assert counterparty KYC status is STILL pending (rolled back)
        session.expire_all()
        db_cp = session.get(Counterparty, UUID(cp_id))
        assert db_cp.kyc_status == KycStatus.pending
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_submit_quote_attribution(client: TestClient, session: Session) -> None:
    # 1. Create and approve counterparty
    cp = _create_counterparty(client, "Attribution Corp")
    cp_id = cp["id"]
    r_kyc = client.post(
        f"/counterparties/{cp_id}/kyc-status",
        json={"new_status": "approved", "reason": "Test transition reason"},
    )
    assert r_kyc.status_code == 200

    # 2. Setup RFQ
    so_resp = client.post(
        "/orders/sales",
        json={"price_type": "variable", "quantity_mt": 100.0, "commodity": "ALUMINUM"},
    )
    so_id = so_resp.json()["id"]
    r_rfq = client.post(
        "/rfqs",
        json={
            "intent": "COMMERCIAL_HEDGE",
            "commodity": "ALUMINUM",
            "quantity_mt": 100.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "SELL",
            "order_id": so_id,
            "invitations": [{"counterparty_id": cp_id}],
        },
    )
    assert r_rfq.status_code == 201
    rfq_id = UUID(r_rfq.json()["id"])

    # 3. Test submitting with actor_sub via direct service method
    payload1 = RFQQuoteCreate(
        rfq_id=rfq_id,
        counterparty_id=UUID(cp_id),
        fixed_price_value=Decimal("1500.0"),
        fixed_price_unit="USD/MT",
        float_pricing_convention="avg",
        received_at=datetime.now(UTC),
    )
    quote1 = RFQService.submit_quote(
        session=session,
        rfq_id=rfq_id,
        payload=payload1,
        actor_sub="human-actor-1",
    )
    session.commit()
    quote1_id = quote1.id
    session.expire_all()
    reloaded1 = session.get(RFQQuote, quote1_id)
    assert reloaded1.actor_sub == "human-actor-1"
    assert reloaded1.inbound_message_id is None

    # 4. Test submitting with inbound_message_id via direct service method
    msg_id = uuid.uuid4()
    payload2 = RFQQuoteCreate(
        rfq_id=rfq_id,
        counterparty_id=UUID(cp_id),
        fixed_price_value=Decimal("1600.0"),
        fixed_price_unit="USD/MT",
        float_pricing_convention="avg",
        received_at=datetime.now(UTC),
    )
    quote2 = RFQService.submit_quote(
        session=session,
        rfq_id=rfq_id,
        payload=payload2,
        inbound_message_id=msg_id,
    )
    session.commit()
    quote2_id = quote2.id
    session.expire_all()
    reloaded2 = session.get(RFQQuote, quote2_id)
    assert reloaded2.inbound_message_id == msg_id
    assert reloaded2.actor_sub is None


def test_set_kyc_status_concurrency(client: TestClient, session: Session) -> None:
    # Basic functional check of set_kyc_status service API locking
    cp = _create_counterparty(client, "Concurrency Corp")
    cp_id = cp["id"]

    from app.services.counterparty_service import CounterpartyService

    # Call set_kyc_status directly which uses with_for_update() locking internally
    db_cp, _ = CounterpartyService.set_kyc_status(
        session=session,
        cp_id=UUID(cp_id),
        new_status=KycStatus.approved,
    )
    session.commit()
    assert db_cp.kyc_status == KycStatus.approved
