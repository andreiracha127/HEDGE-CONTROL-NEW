# backend/app/services/kyc_gate.py
"""KYC gate primitive for RFQ-lifecycle admission and quote ingestion.

Constitutional anchor: docs/governance.md "Counterparty KYC gate
(binding, Pilot Hard Blocker 1)" subsection of AUTHORIZATION MATRIX.
"""
from __future__ import annotations

import uuid
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.counterparty import Counterparty, KycStatus
from app.services.audit_trail_service import AuditTrailService
from app.services.counterparty_service import CounterpartyService

GatePoint = Literal["rfq_invitation", "rfq_quote", "rfq_award"]

_EVENT_TYPE_BY_GATE = {
    "rfq_invitation": "rfq_invitation_rejected_kyc_not_approved",
    "rfq_quote": "rfq_quote_rejected_kyc_not_approved",
    "rfq_award": "rfq_award_rejected_kyc_not_approved",
}


def assert_kyc_approved(
    db: Session,
    counterparty_id: uuid.UUID,
    *,
    gate_point: GatePoint,
    requesting_actor_sub: str | None,
    rfq_id: uuid.UUID | None = None,
    extra_payload: dict | None = None,
) -> Counterparty:
    """Refuse the operation if counterparty.kyc_status != approved.

    On refusal:
      1. Emits an HMAC-signed audit event on a SEPARATE committed session
         (dual-session pattern, mirrors
         backend/app/services/rfq_service.py:101-144
         ``_persist_outbox_queued``) so the row survives the outer
         ``unit_of_work`` rollback that fires on HTTPException
         (backend/app/api/dependencies/uow.py:27-29 catches every
         Exception, including HTTPException, and calls session.rollback()
         before re-raising).
      2. Raises HTTPException(422) — the caller's unit_of_work then
         rolls back the failed mutation while the rejection audit row,
         already committed on the separate session, remains.

    Returns the loaded Counterparty when status is approved.
    """
    # Use CounterpartyService.get_by_id (NOT db.get) so soft-deleted rows
    # return None and the gate fails closed with 404. Raw db.get returns
    # soft-deleted counterparties; a counterparty that is logically deleted
    # but still has kyc_status=approved would otherwise pass the gate and
    # admit RFQ invitations, quotes, and awards against a deleted entity.
    # Mirrors §4.3.2 set_kyc_status and every other mutation path in
    # backend/app/api/routes/counterparties.py (see counterparties.py:136
    # update_counterparty for the canonical pattern).
    cp = CounterpartyService.get_by_id(db, counterparty_id)
    if cp is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Counterparty not found",
        )
    if cp.kyc_status == KycStatus.approved:
        return cp

    event_type = _EVENT_TYPE_BY_GATE[gate_point]
    payload = {
        "counterparty_id": str(counterparty_id),
        "kyc_status_observed": cp.kyc_status.value,
        "requesting_actor_sub": requesting_actor_sub,
        "rfq_id": str(rfq_id) if rfq_id is not None else None,
        **(extra_payload or {}),
    }

    # Dual-session: write the rejection audit on its own SessionLocal
    # and commit it BEFORE raising HTTPException. The outer route's
    # unit_of_work will roll back ``db`` (the request session) when the
    # exception bubbles, but ``audit_session`` is already committed and
    # independent, so the rejection evidence persists.
    audit_session = SessionLocal()
    try:
        AuditTrailService.record(
            audit_session,
            event_id=uuid.uuid4(),
            entity_type="counterparty",
            entity_id=counterparty_id,
            event_type=event_type,
            payload_raw="",  # canonicalized from payload_obj internally
            payload_obj=payload,
            commit=True,  # own session, own commit — survives outer rollback
        )
    finally:
        audit_session.close()

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail={
            "code": event_type,
            "counterparty_id": str(counterparty_id),
            "kyc_status_observed": cp.kyc_status.value,
        },
    )
