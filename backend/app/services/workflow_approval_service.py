"""WorkflowApprovalRequest lifecycle service.

Constitutional anchor: docs/governance.md "Workflow Approval gate
(binding, Pilot Hard Blocker 2)" subsection of AUTHORIZATION MATRIX.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.workflow_approval import (
    ApprovalPolicy,
    ApprovalStatus,
    MutationType,
    RejectionReasonCode,
    ThresholdDimension,
    WorkflowApprovalRequest,
)
from app.services.audit_trail_service import AuditTrailService, normalize_payload_raw

settings = get_settings()

MutationTypeLiteral = Literal["deal_create", "deal_award", "hedge_contract_settle"]

WORKFLOW_APPROVAL_REQUESTED = "workflow_approval_requested"
WORKFLOW_APPROVAL_GRANTED = "workflow_approval_granted"
WORKFLOW_APPROVAL_REJECTED = "workflow_approval_rejected"
WORKFLOW_APPROVAL_EXPIRED = "workflow_approval_expired"
WORKFLOW_APPROVAL_CONSUMED = "workflow_approval_consumed"
WORKFLOW_APPROVAL_SUPERSEDED = "workflow_approval_superseded"

_EXPIRY_BY_MUTATION_TYPE = {
    MutationType.deal_create: timedelta(hours=48),
    MutationType.deal_award: timedelta(hours=24),
    MutationType.hedge_contract_settle: timedelta(hours=2),
}

_THRESHOLD_BY_MUTATION_TYPE = {
    MutationType.deal_create: lambda: settings.workflow_approval_deal_threshold_usd,
    MutationType.deal_award: lambda: settings.workflow_approval_deal_threshold_usd,
    MutationType.hedge_contract_settle: lambda: settings.workflow_approval_settle_threshold_usd,
}

_THRESHOLD_DIMENSION_BY_MUTATION_TYPE = {
    MutationType.deal_create: ThresholdDimension.notional_usd,
    MutationType.deal_award: ThresholdDimension.notional_usd,
    MutationType.hedge_contract_settle: ThresholdDimension.settlement_amount_usd,
}


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _as_mutation_type(value: MutationType | MutationTypeLiteral | str) -> MutationType:
    if isinstance(value, MutationType):
        return value
    return MutationType(value)


def _compute_payload_hash(payload_obj: object) -> str:
    payload_canonical, _ = normalize_payload_raw(payload_obj)
    return hashlib.sha256(payload_canonical.encode("utf-8")).hexdigest()


def _time_to_approval_ms(row: WorkflowApprovalRequest, transition_time: datetime) -> int:
    created = row.created_at
    if created.tzinfo is not None:
        created = created.replace(tzinfo=None)
    if transition_time.tzinfo is not None:
        transition_time = transition_time.replace(tzinfo=None)
    return int((transition_time - created).total_seconds() * 1000)


def _audit_payload(
    row: WorkflowApprovalRequest,
    *,
    previous_status: ApprovalStatus | None,
    approver_sub: str | None = None,
    rejection_reason: dict | None = None,
    transition_time: datetime | None = None,
) -> dict:
    transition_time = transition_time or _utcnow()
    return {
        "approval_id": str(row.id),
        "mutation_type": row.mutation_type.value,
        "correlation_id": str(row.correlation_id),
        "threshold_dimension_used": row.threshold_dimension.value,
        "threshold_at_request": str(row.threshold_at_request),
        "threshold_config_value": str(row.threshold_config_value),
        "requested_by": row.requested_by,
        "previous_status": previous_status.value if previous_status is not None else None,
        "approver_sub": approver_sub,
        "approver_ip": row.approver_ip if approver_sub is not None else None,
        "approver_session_id": row.approver_session_id if approver_sub is not None else None,
        "rejection_reason": rejection_reason,
        "time_to_approval_ms": (
            None if previous_status is None else _time_to_approval_ms(row, transition_time)
        ),
        "mutation_payload_hash": row.mutation_payload_hash,
    }


def _emit_audit_event(
    session: Session,
    row: WorkflowApprovalRequest,
    event_type: str,
    *,
    previous_status: ApprovalStatus | None,
    approver_sub: str | None = None,
    rejection_reason: dict | None = None,
) -> None:
    transition_time = _utcnow()
    payload = _audit_payload(
        row,
        previous_status=previous_status,
        approver_sub=approver_sub,
        rejection_reason=rejection_reason,
        transition_time=transition_time,
    )
    payload_raw, payload_obj = normalize_payload_raw(payload)
    AuditTrailService.record(
        session,
        event_id=uuid.uuid4(),
        entity_type="workflow_approval_request",
        entity_id=row.id,
        event_type=event_type,
        payload_raw=payload_raw,
        payload_obj=payload_obj,
        commit=False,
    )


def _broadcast_state_change(
    row: WorkflowApprovalRequest,
    old_status: ApprovalStatus | None,
    new_status: ApprovalStatus,
) -> None:
    # The repo currently exposes WebSocket broadcast, not an SSE endpoint. Route
    # integration can call the same state payload; unit tests keep this no-op.
    return None


def _load_for_update(session: Session, approval_id: uuid.UUID) -> WorkflowApprovalRequest:
    row = (
        session.query(WorkflowApprovalRequest)
        .filter(WorkflowApprovalRequest.id == approval_id)
        .with_for_update()
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return row


def _get_policy(session: Session, mutation_type: MutationType) -> ApprovalPolicy:
    policy = session.get(ApprovalPolicy, mutation_type)
    if policy is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Approval policy missing for {mutation_type.value}",
        )
    return policy


def evaluate_and_maybe_create(
    session: Session,
    mutation_type: MutationType | MutationTypeLiteral,
    payload_obj: object,
    threshold_value: Decimal,
    requesting_actor_sub: str,
    requesting_actor_ip: str | None,
    requesting_actor_session_id: str | None,
    correlation_id: uuid.UUID,
    idempotency_key: str | None,
    request_role_set: set[str],
) -> WorkflowApprovalRequest | None:
    mutation_type = _as_mutation_type(mutation_type)
    configured_threshold = Decimal(str(_THRESHOLD_BY_MUTATION_TYPE[mutation_type]()))
    if Decimal(str(threshold_value)) <= configured_threshold:
        return None

    if "risk_manager" not in request_role_set:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "role lacks risk_manager -- institutional-threshold mutations require "
                "risk_manager scope"
            ),
        )

    policy = _get_policy(session, mutation_type)
    if idempotency_key:
        existing = (
            session.query(WorkflowApprovalRequest)
            .filter(
                WorkflowApprovalRequest.idempotency_key == idempotency_key,
                WorkflowApprovalRequest.requested_by == requesting_actor_sub,
            )
            .one_or_none()
        )
        if existing is not None:
            return existing

    payload_canonical, _ = normalize_payload_raw(payload_obj)
    row = WorkflowApprovalRequest(
        mutation_type=mutation_type,
        status=ApprovalStatus.pending,
        requested_by=requesting_actor_sub,
        threshold_at_request=Decimal(str(threshold_value)),
        threshold_config_value=configured_threshold,
        threshold_dimension=policy.threshold_dimension,
        mutation_payload_canonical=payload_canonical,
        mutation_payload_hash=_compute_payload_hash(payload_obj),
        correlation_id=correlation_id,
        idempotency_key=idempotency_key,
        expires_at=_utcnow() + _EXPIRY_BY_MUTATION_TYPE[mutation_type],
    )
    session.add(row)
    session.flush()
    _emit_audit_event(
        session,
        row,
        WORKFLOW_APPROVAL_REQUESTED,
        previous_status=None,
    )
    _broadcast_state_change(row, None, ApprovalStatus.pending)
    return row


def grant_request(
    session: Session,
    approval_id: uuid.UUID,
    approver_actor_sub: str,
    approver_role_set: set[str],
    approver_ip: str | None,
    approver_session_id: str | None,
) -> WorkflowApprovalRequest:
    row = _load_for_update(session, approval_id)
    if row.status != ApprovalStatus.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not pending")
    if approver_actor_sub == row.requested_by:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="requested_by and approved_by must be distinct",
        )
    policy = _get_policy(session, row.mutation_type)
    if not set(policy.required_approver_roles).intersection(approver_role_set):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Approver role not allowed"
        )

    old_status = row.status
    row.status = ApprovalStatus.approved
    row.approved_by = approver_actor_sub
    row.approver_ip = approver_ip
    row.approver_session_id = approver_session_id
    session.flush()
    _emit_audit_event(
        session,
        row,
        WORKFLOW_APPROVAL_GRANTED,
        previous_status=old_status,
        approver_sub=approver_actor_sub,
    )
    _broadcast_state_change(row, old_status, row.status)
    return row


def reject_request(
    session: Session,
    approval_id: uuid.UUID,
    approver_actor_sub: str,
    approver_role_set: set[str],
    approver_ip: str | None,
    approver_session_id: str | None,
    reason_code: RejectionReasonCode,
    reason_text: str,
) -> WorkflowApprovalRequest:
    row = _load_for_update(session, approval_id)
    if row.status != ApprovalStatus.pending:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not pending")
    if len(reason_text.strip()) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="rejection_reason_text must be at least 8 characters",
        )
    policy = _get_policy(session, row.mutation_type)
    if approver_actor_sub == row.requested_by:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="requested_by and approved_by must be distinct",
        )
    if not set(policy.required_approver_roles).intersection(approver_role_set):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Approver role not allowed"
        )

    old_status = row.status
    row.status = ApprovalStatus.rejected
    row.approved_by = approver_actor_sub
    row.approver_ip = approver_ip
    row.approver_session_id = approver_session_id
    row.rejection_reason_code = reason_code
    row.rejection_reason_text = reason_text
    session.flush()
    _emit_audit_event(
        session,
        row,
        WORKFLOW_APPROVAL_REJECTED,
        previous_status=old_status,
        approver_sub=approver_actor_sub,
        rejection_reason={
            "code": reason_code.value,
            "text": reason_text,
        },
    )
    _broadcast_state_change(row, old_status, row.status)
    return row


def supersede_request(
    session: Session,
    approval_id: uuid.UUID,
    requesting_actor_sub: str,
) -> WorkflowApprovalRequest:
    row = _load_for_update(session, approval_id)
    if row.status not in {ApprovalStatus.pending, ApprovalStatus.approved}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only pending or approved approvals can be superseded",
        )
    if requesting_actor_sub != row.requested_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="supersede restricted to the original requester",
        )
    old_status = row.status
    row.status = ApprovalStatus.superseded
    session.flush()
    _emit_audit_event(
        session,
        row,
        WORKFLOW_APPROVAL_SUPERSEDED,
        previous_status=old_status,
    )
    _broadcast_state_change(row, old_status, row.status)
    return row


def consume_request(
    session: Session,
    approval_id: uuid.UUID,
    requesting_actor_sub: str,
    consume_payload_obj: object,
    executor: Callable[[object], object],
) -> tuple[WorkflowApprovalRequest, object]:
    row = _load_for_update(session, approval_id)
    if requesting_actor_sub != row.requested_by:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="consume restricted to the original requester",
        )
    if row.status != ApprovalStatus.approved:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approval is not approved")
    if _compute_payload_hash(consume_payload_obj) != row.mutation_payload_hash:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "payload_drift_detected",
                "message": "consume payload canonical hash does not match approval",
            },
        )

    result = executor(consume_payload_obj)
    old_status = row.status
    row.status = ApprovalStatus.consumed
    row.consumed_at = _utcnow()
    session.flush()
    _emit_audit_event(
        session,
        row,
        WORKFLOW_APPROVAL_CONSUMED,
        previous_status=old_status,
        approver_sub=requesting_actor_sub,
    )
    _broadcast_state_change(row, old_status, row.status)
    return row, result


def sweep_expired(session: Session) -> list[WorkflowApprovalRequest]:
    now = _utcnow()
    rows = (
        session.query(WorkflowApprovalRequest)
        .filter(
            WorkflowApprovalRequest.status.in_([ApprovalStatus.pending, ApprovalStatus.approved]),
            WorkflowApprovalRequest.expires_at < now,
        )
        .with_for_update()
        .all()
    )
    for row in rows:
        old_status = row.status
        row.status = ApprovalStatus.expired
        session.flush()
        _emit_audit_event(
            session,
            row,
            WORKFLOW_APPROVAL_EXPIRED,
            previous_status=old_status,
        )
        _broadcast_state_change(row, old_status, row.status)
    return rows
