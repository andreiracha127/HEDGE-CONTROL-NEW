# backend/tests/test_rfq_kyc_gate.py
import pytest
import uuid
from uuid import UUID
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.counterparty import Counterparty, KycStatus
from app.models.audit import AuditEvent
from app.services.kyc_gate import assert_kyc_approved
from app.services.counterparty_service import CounterpartyService
from app.services.rfq_service import RFQService
from app.schemas.rfq import RFQQuoteCreate
from app.models.rfqs import RFQInvitation, RFQInvitationPurpose, RFQState, RFQIntent
from conftest import mark_counterparty_sanctions_clear

def _create_counterparty(client: TestClient, name: str, phone: str = "+5511999990001") -> dict:
    resp = client.post(
        "/counterparties",
        json={
            "type": "broker",
            "name": name,
            "country": "BRA",
            "whatsapp_phone": phone,
        },
    )
    assert resp.status_code == 201
    return resp.json()

def _create_sales_order(client: TestClient) -> str:
    response = client.post(
        "/orders/sales",
        json={"price_type": "variable", "quantity_mt": 100.0, "commodity": "ALUMINUM"},
    )
    assert response.status_code == 201
    return response.json()["id"]

def _create_hedge_contract(client: TestClient) -> str:
    response = client.post(
        "/contracts/hedge",
        json={
            "commodity": "LME_AL",
            "quantity_mt": 100.0,
            "legs": [
                {"side": "sell", "price_type": "fixed"},
                {"side": "buy", "price_type": "variable"},
            ],
        },
    )
    assert response.status_code == 201
    return response.json()["id"]

def _create_linkage(client: TestClient, order_id: str, contract_id: str) -> str:
    response = client.post(
        "/linkages",
        json={
            "order_id": order_id,
            "contract_id": contract_id,
            "quantity_mt": 100.0,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]

def test_create_rejects_pending_counterparty(client: TestClient, session: Session) -> None:
    # 1. Create counterparty (default KYC status: pending)
    cp = _create_counterparty(client, "Pending Corp")
    cp_id = cp["id"]

    # 2. Set up order
    so_id = _create_sales_order(client)

    # 3. Try to create RFQ inviting the pending counterparty
    payload = {
        "intent": "COMMERCIAL_HEDGE",
        "commodity": "ALUMINUM",
        "quantity_mt": 100.0,
        "delivery_window_start": "2026-03-01",
        "delivery_window_end": "2026-03-31",
        "direction": "SELL",
        "order_id": so_id,
        "invitations": [{"counterparty_id": cp_id}],
    }
    r = client.post("/rfqs", json=payload)
    assert r.status_code == 422
    
    # 4. Check error detail
    detail = r.json()["detail"]
    assert detail["code"] == "rfq_invitation_rejected_kyc_not_approved"
    assert detail["counterparty_id"] == cp_id
    assert detail["kyc_status_observed"] == "pending"

    # 5. Verify audit event was written
    db_fresh = SessionLocal()
    try:
        audit = (
            db_fresh.query(AuditEvent)
            .filter(AuditEvent.entity_id == UUID(cp_id))
            .filter(AuditEvent.event_type == "rfq_invitation_rejected_kyc_not_approved")
            .first()
        )
        assert audit is not None
        assert audit.payload["attempted_purpose"] == "rfq_invite"
        assert audit.payload["requesting_actor_sub"] is not None
    finally:
        db_fresh.close()

def test_award_rejects_non_approved_at_award_moment(client: TestClient, session: Session) -> None:
    # 1. Create counterparty
    cp = _create_counterparty(client, "Award Kyc Corp")
    cp_id = cp["id"]

    # 2. Approve counterparty
    mark_counterparty_sanctions_clear(cp_id)
    r_kyc = client.post(f"/counterparties/{cp_id}/kyc-status", json={"new_status": "approved", "reason": "Test approval"})
    assert r_kyc.status_code == 200

    # 3. Create RFQ (succeeds because counterparty is approved)
    so_id = _create_sales_order(client)
    
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
    rfq_id = r_rfq.json()["id"]

    # 4. Ingest quote
    r_quote = client.post(
        f"/rfqs/{rfq_id}/quotes",
        json={
            "rfq_id": rfq_id,
            "counterparty_id": cp_id,
            "fixed_price_value": 1500.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": "2026-02-01T00:00:00Z",
        },
    )
    assert r_quote.status_code == 201
    quote_id = r_quote.json()["id"]

    # 5. Revoke KYC status (transition to expired)
    r_revoke = client.post(f"/counterparties/{cp_id}/kyc-status", json={"new_status": "expired", "reason": "Test expiration"})
    assert r_revoke.status_code == 200

    # 6. Try to award (should reject with 422)
    r_award = client.post(
        f"/rfqs/{rfq_id}/actions/award",
        json={},
    )
    assert r_award.status_code == 422
    
    detail = r_award.json()["detail"]
    assert detail["code"] == "rfq_award_rejected_kyc_not_approved"
    assert detail["counterparty_id"] == cp_id
    assert detail["kyc_status_observed"] == "expired"

    # 7. Verify audit event
    db_fresh = SessionLocal()
    try:
        audit = (
            db_fresh.query(AuditEvent)
            .filter(AuditEvent.entity_id == UUID(cp_id))
            .filter(AuditEvent.event_type == "rfq_award_rejected_kyc_not_approved")
            .first()
        )
        assert audit is not None
        assert audit.payload["quote_id"] == quote_id
        assert audit.payload["rfq_id"] == rfq_id
    finally:
        db_fresh.close()

def test_gate_rejects_soft_deleted_counterparty(client: TestClient, session: Session) -> None:
    # 1. Create counterparty
    cp = _create_counterparty(client, "Soft Delete Corp")
    cp_id = cp["id"]

    # 2. Approve counterparty
    mark_counterparty_sanctions_clear(cp_id)
    r_kyc = client.post(f"/counterparties/{cp_id}/kyc-status", json={"new_status": "approved", "reason": "Test approval"})
    assert r_kyc.status_code == 200

    # 3. Soft delete the counterparty
    r_del = client.delete(f"/counterparties/{cp_id}")
    assert r_del.status_code == 200

    # 4. Attempt to call assert_kyc_approved directly — expect 404 (not 422)
    with pytest.raises(HTTPException) as exc_info:
        assert_kyc_approved(
            session,
            UUID(cp_id),
            gate_point="rfq_invitation",
            requesting_actor_sub="test-actor",
        )
    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Counterparty not found"

    # 5. Assert no rejection audit event was written
    db_fresh = SessionLocal()
    try:
        audit = (
            db_fresh.query(AuditEvent)
            .filter(AuditEvent.entity_id == UUID(cp_id))
            .filter(AuditEvent.event_type == "rfq_invitation_rejected_kyc_not_approved")
            .first()
        )
        assert audit is None, "Should not record rejection audit event for soft-deleted counterparty"
    finally:
        db_fresh.close()

def test_gate_audit_survives_route_rollback(client: TestClient, session: Session) -> None:
    # 1. Create counterparty (status: pending)
    cp = _create_counterparty(client, "Rollback Surviver")
    cp_id = cp["id"]

    # 2. Set up order
    so_id = _create_sales_order(client)

    # 3. Drive gate fire through route POST /rfqs (which uses Unit of Work rollback)
    payload = {
        "intent": "COMMERCIAL_HEDGE",
        "commodity": "ALUMINUM",
        "quantity_mt": 100.0,
        "delivery_window_start": "2026-03-01",
        "delivery_window_end": "2026-03-31",
        "direction": "SELL",
        "order_id": so_id,
        "invitations": [{"counterparty_id": cp_id}],
    }
    r = client.post("/rfqs", json=payload)
    assert r.status_code == 422

    # 4. Open a fresh independent database session to verify the audit event exists
    db_fresh = SessionLocal()
    try:
        audit = (
            db_fresh.query(AuditEvent)
            .filter(AuditEvent.entity_id == UUID(cp_id))
            .filter(AuditEvent.event_type == "rfq_invitation_rejected_kyc_not_approved")
            .first()
        )
        assert audit is not None, "Audit event did not survive route transaction rollback!"
        # Check HMAC signature is valid
        assert audit.signature is not None
        assert len(audit.signature) > 0
    finally:
        db_fresh.close()

def test_outbox_notifications_fire_despite_post_event_kyc_revocation(client: TestClient, session: Session) -> None:
    """Verify outbox notifications use snapshot-at-event-time KYC admissibility.

    Constitutional rationale: outbox-exempt RFQInvitationPurpose values
    (reject_quote, award_notify, reject_notify) are durable evidence of
    decisions ALREADY MADE at the originating event time (submit_quote
    rejection / award / rejection trigger). Re-checking KYC at outbox
    send time would create an institutional deadlock: a counterparty whose
    KYC is revoked post-event could not be notified of the award or quote
    rejection, leaving the platform state inconsistent with real-world physical
    trade agreements already entered.
    """
    # 1. Create counterparty
    cp = _create_counterparty(client, "Outbox Revocation Corp")
    cp_id = cp["id"]

    # 2. Approve counterparty
    mark_counterparty_sanctions_clear(cp_id)
    r_kyc = client.post(f"/counterparties/{cp_id}/kyc-status", json={"new_status": "approved", "reason": "Test approval"})
    assert r_kyc.status_code == 200

    # 3. Create RFQ
    so_id = _create_sales_order(client)
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
    rfq_id = r_rfq.json()["id"]

    # 4. Ingest quote
    r_quote = client.post(
        f"/rfqs/{rfq_id}/quotes",
        json={
            "rfq_id": rfq_id,
            "counterparty_id": cp_id,
            "fixed_price_value": 1500.0,
            "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg",
            "received_at": "2026-02-01T00:00:00Z",
        },
    )
    assert r_quote.status_code == 201
    quote_id = r_quote.json()["id"]

    # 5. Revoke counterparty's KYC
    r_revoke = client.post(f"/counterparties/{cp_id}/kyc-status", json={"new_status": "rejected", "reason": "Test rejection"})
    assert r_revoke.status_code == 200

    # 6. Reject the quote (which triggers outbox notification with purpose `reject_quote`)
    r_reject = client.post(f"/rfqs/{rfq_id}/actions/reject-quote?quote_id={quote_id}", json={})
    assert r_reject.status_code == 200

    # 7. Verify the outbox invitation with purpose "reject_quote" was created successfully!
    r_rfq_get = client.get(f"/rfqs/{rfq_id}")
    assert r_rfq_get.status_code == 200
    invitations = r_rfq_get.json()["invitations"]
    
    reject_invitation = next((inv for inv in invitations if inv["purpose"] == "reject_quote"), None)
    assert reject_invitation is not None, "reject_quote outbox invitation was not created!"
    assert reject_invitation["counterparty_id"] == cp_id

def test_quote_ingestion_rejects_degraded_kyc_human_path(client: TestClient, session: Session) -> None:
    # 1. Create counterparty & approve
    cp = _create_counterparty(client, "Degraded Human Quoter")
    cp_id = cp["id"]
    mark_counterparty_sanctions_clear(cp_id)
    r_kyc = client.post(f"/counterparties/{cp_id}/kyc-status", json={"new_status": "approved", "reason": "Initial setup"})
    assert r_kyc.status_code == 200

    # 2. Create RFQ
    so_id = _create_sales_order(client)
    r_rfq = client.post(
        "/rfqs",
        json={
            "intent": "COMMERCIAL_HEDGE", "commodity": "ALUMINUM", "quantity_mt": 100.0,
            "delivery_window_start": "2026-03-01", "delivery_window_end": "2026-03-31",
            "direction": "SELL", "order_id": so_id, "invitations": [{"counterparty_id": cp_id}],
        },
    )
    assert r_rfq.status_code == 201
    rfq_id = r_rfq.json()["id"]

    # 3. Degrade KYC to expired
    r_revoke = client.post(f"/counterparties/{cp_id}/kyc-status", json={"new_status": "expired", "reason": "Degraded"})
    assert r_revoke.status_code == 200

    # 4. Attempt to ingest quote (Human REST path)
    r_quote = client.post(
        f"/rfqs/{rfq_id}/quotes",
        json={
            "rfq_id": rfq_id, "counterparty_id": cp_id,
            "fixed_price_value": 1500.0, "fixed_price_unit": "USD/MT",
            "float_pricing_convention": "avg", "received_at": "2026-02-01T00:00:00Z",
        },
    )
    assert r_quote.status_code == 422
    
    detail = r_quote.json()["detail"]
    assert detail["code"] == "rfq_quote_rejected_kyc_not_approved"
    assert detail["counterparty_id"] == cp_id
    assert detail["kyc_status_observed"] == "expired"

    # 5. Verify audit event
    db_fresh = SessionLocal()
    try:
        audit = (
            db_fresh.query(AuditEvent)
            .filter(AuditEvent.entity_id == UUID(cp_id))
            .filter(AuditEvent.event_type == "rfq_quote_rejected_kyc_not_approved")
            .first()
        )
        assert audit is not None
        assert audit.payload["rfq_id"] == rfq_id
    finally:
        db_fresh.close()

def test_quote_ingestion_rejects_degraded_kyc_llm_path(client: TestClient, session: Session) -> None:
    # 1. Create counterparty & approve
    cp = _create_counterparty(client, "Degraded LLM Quoter")
    cp_id = cp["id"]
    mark_counterparty_sanctions_clear(cp_id)
    client.post(f"/counterparties/{cp_id}/kyc-status", json={"new_status": "approved", "reason": "Initial setup"})

    # 2. Create RFQ
    so_id = _create_sales_order(client)
    r_rfq = client.post(
        "/rfqs",
        json={
            "intent": "COMMERCIAL_HEDGE", "commodity": "ALUMINUM", "quantity_mt": 100.0,
            "delivery_window_start": "2026-03-01", "delivery_window_end": "2026-03-31",
            "direction": "SELL", "order_id": so_id, "invitations": [{"counterparty_id": cp_id}],
        },
    )
    rfq_id = r_rfq.json()["id"]

    # 3. Degrade KYC
    client.post(f"/counterparties/{cp_id}/kyc-status", json={"new_status": "rejected", "reason": "Risk threshold"})

    # 4. Attempt quote ingestion directly via service to simulate LLM inbound message without actor_sub
    inbound_msg_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc_info:
        RFQService.submit_quote(
            session,
            UUID(rfq_id),
            RFQQuoteCreate(
                rfq_id=UUID(rfq_id),
                counterparty_id=UUID(cp_id),
                fixed_price_value=1500.0,
                fixed_price_unit="USD/MT",
                float_pricing_convention="avg",
                received_at="2026-02-01T00:00:00Z",
            ),
            actor_sub=None,  # Nullable for inbound/LLM path
            inbound_message_id=inbound_msg_id
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "rfq_quote_rejected_kyc_not_approved"

    # 5. Verify audit event
    db_fresh = SessionLocal()
    try:
        audit = (
            db_fresh.query(AuditEvent)
            .filter(AuditEvent.entity_id == UUID(cp_id))
            .filter(AuditEvent.event_type == "rfq_quote_rejected_kyc_not_approved")
            .first()
        )
        assert audit is not None
        assert audit.payload["inbound_message_id"] == str(inbound_msg_id)
        assert audit.payload["requesting_actor_sub"] is None
    finally:
        db_fresh.close()
