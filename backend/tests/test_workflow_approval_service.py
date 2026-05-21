from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.audit import AuditEvent
from app.models.workflow_approval import (
    ApprovalPolicy,
    ApprovalStatus,
    MutationType,
    RejectionReasonCode,
    ThresholdDimension,
    WorkflowApprovalRequest,
)
from app.services.workflow_approval_service import (
    _compute_payload_hash,
    consume_request,
    evaluate_and_maybe_create,
    grant_request,
    reject_request,
    supersede_request,
    sweep_expired,
)


def _payload(amount: str = "600000.00") -> dict:
    return {
        "name": "HB-2 approval gated deal",
        "commodity": "ALUMINUM",
        "links": [{"linked_type": "contract", "linked_id": str(uuid4())}],
        "notional_usd": amount,
    }


def test_approval_policy_seed(session) -> None:
    rows = {
        row.mutation_type: row
        for row in session.query(ApprovalPolicy).order_by(ApprovalPolicy.mutation_type)
    }

    assert rows[MutationType.deal_create].required_approver_roles == ["risk_manager"]
    assert rows[MutationType.deal_create].fallback_when_requester_is == {}
    assert rows[MutationType.deal_create].threshold_dimension == ThresholdDimension.notional_usd
    assert rows[MutationType.deal_award].required_approver_roles == ["risk_manager"]
    assert rows[MutationType.deal_award].fallback_when_requester_is == {}
    assert rows[MutationType.deal_award].threshold_dimension == ThresholdDimension.notional_usd
    assert rows[MutationType.hedge_contract_settle].required_approver_roles == ["auditor"]
    assert rows[MutationType.hedge_contract_settle].fallback_when_requester_is == {}
    assert (
        rows[MutationType.hedge_contract_settle].threshold_dimension
        == ThresholdDimension.settlement_amount_usd
    )


def test_compute_payload_hash_reuses_normalize_payload_raw_ordering() -> None:
    left = {"b": 2, "a": {"z": "last", "m": "middle"}}
    right = {"a": {"m": "middle", "z": "last"}, "b": 2}

    assert _compute_payload_hash(left) == _compute_payload_hash(right)


def test_below_threshold_returns_none_without_creating_request(session) -> None:
    result = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        _payload("499999.99"),
        Decimal("499999.99"),
        "risk-requester",
        "10.0.0.1",
        "sess-1",
        uuid4(),
        "below-threshold",
        {"risk_manager"},
    )

    assert result is None
    assert session.query(WorkflowApprovalRequest).count() == 0


def test_threshold_crossing_creates_pending_request_and_signed_audit(session) -> None:
    payload = _payload()
    request = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        payload,
        Decimal("600000.00"),
        "risk-requester",
        "10.0.0.1",
        "sess-1",
        uuid4(),
        "idem-1",
        {"risk_manager"},
    )

    assert request is not None
    assert request.status == ApprovalStatus.pending
    assert request.threshold_at_request == Decimal("600000.000000")
    assert request.threshold_config_value == Decimal("500000.000000")
    assert request.threshold_dimension == ThresholdDimension.notional_usd
    assert request.mutation_payload_hash == _compute_payload_hash(payload)
    assert request.expires_at > request.created_at

    audit = session.query(AuditEvent).one()
    assert audit.entity_type == "workflow_approval_request"
    assert audit.entity_id == request.id
    assert audit.event_type == "workflow_approval_requested"
    assert audit.signature is not None


def test_idempotency_key_is_scoped_by_requested_by(session) -> None:
    correlation_id = uuid4()
    first = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        _payload(),
        Decimal("600000.00"),
        "risk-a",
        "10.0.0.1",
        "sess-1",
        correlation_id,
        "same-key",
        {"risk_manager"},
    )
    second = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        _payload(),
        Decimal("600000.00"),
        "risk-a",
        "10.0.0.1",
        "sess-1",
        correlation_id,
        "same-key",
        {"risk_manager"},
    )
    third = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        _payload(),
        Decimal("600000.00"),
        "risk-b",
        "10.0.0.2",
        "sess-2",
        correlation_id,
        "same-key",
        {"risk_manager"},
    )

    assert first.id == second.id
    assert third.id != first.id
    assert session.query(WorkflowApprovalRequest).count() == 2


def test_gate_rejects_actor_lacking_risk_manager(session) -> None:
    with pytest.raises(HTTPException) as exc:
        evaluate_and_maybe_create(
            session,
            MutationType.deal_create,
            _payload(),
            Decimal("600000.00"),
            "trader-only",
            "10.0.0.1",
            "sess-1",
            uuid4(),
            "blocked",
            {"trader"},
        )

    assert exc.value.status_code == 403
    assert exc.value.detail == (
        "role lacks risk_manager -- institutional-threshold mutations require "
        "risk_manager scope"
    )


def test_grant_requires_distinct_approver_and_required_role(session) -> None:
    request = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        _payload(),
        Decimal("600000.00"),
        "risk-requester",
        "10.0.0.1",
        "sess-1",
        uuid4(),
        "grant-role",
        {"risk_manager"},
    )

    with pytest.raises(HTTPException) as same_actor:
        grant_request(
            session,
            request.id,
            "risk-requester",
            {"risk_manager"},
            "10.0.0.2",
            "sess-approver",
        )
    assert same_actor.value.status_code == 422

    with pytest.raises(HTTPException) as wrong_role:
        grant_request(
            session,
            request.id,
            "auditor-1",
            {"auditor"},
            "10.0.0.2",
            "sess-approver",
        )
    assert wrong_role.value.status_code == 403

    granted = grant_request(
        session,
        request.id,
        "risk-approver",
        {"risk_manager"},
        "10.0.0.2",
        "sess-approver",
    )
    assert granted.status == ApprovalStatus.approved
    assert granted.approved_by == "risk-approver"
    assert granted.approver_ip == "10.0.0.2"
    assert granted.approver_session_id == "sess-approver"


def test_reject_requires_reason_pair_and_transitions_terminal(session) -> None:
    request = evaluate_and_maybe_create(
        session,
        MutationType.hedge_contract_settle,
        _payload(),
        Decimal("300000.00"),
        "risk-requester",
        "10.0.0.1",
        "sess-1",
        uuid4(),
        "reject-case",
        {"risk_manager"},
    )

    with pytest.raises(HTTPException) as short_reason:
        reject_request(
            session,
            request.id,
            "auditor-1",
            {"auditor"},
            "10.0.0.3",
            "sess-audit",
            RejectionReasonCode.other,
            "short",
        )
    assert short_reason.value.status_code == 422

    rejected = reject_request(
        session,
        request.id,
        "auditor-1",
        {"auditor"},
        "10.0.0.3",
        "sess-audit",
        RejectionReasonCode.counterparty_risk,
        "counterparty exposure too high",
    )
    assert rejected.status == ApprovalStatus.rejected
    assert rejected.rejection_reason_code == RejectionReasonCode.counterparty_risk

    with pytest.raises(HTTPException) as terminal:
        grant_request(
            session,
            request.id,
            "auditor-2",
            {"auditor"},
            "10.0.0.4",
            "sess-audit-2",
        )
    assert terminal.value.status_code == 409


def test_consume_detects_payload_drift_and_preserves_approved_state(session) -> None:
    payload = _payload()
    request = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        payload,
        Decimal("600000.00"),
        "risk-requester",
        "10.0.0.1",
        "sess-1",
        uuid4(),
        "consume-drift",
        {"risk_manager"},
    )
    grant_request(
        session,
        request.id,
        "risk-approver",
        {"risk_manager"},
        "10.0.0.2",
        "sess-approver",
    )

    with pytest.raises(HTTPException) as drift:
        consume_request(
            session,
            request.id,
            "risk-requester",
            _payload("700000.00"),
            lambda _: {"created": True},
        )

    assert drift.value.status_code == 422
    assert drift.value.detail["code"] == "payload_drift_detected"
    assert session.get(WorkflowApprovalRequest, request.id).status == ApprovalStatus.approved


def test_consume_calls_executor_once_and_marks_consumed(session) -> None:
    payload = _payload()
    request = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        payload,
        Decimal("600000.00"),
        "risk-requester",
        "10.0.0.1",
        "sess-1",
        uuid4(),
        "consume-ok",
        {"risk_manager"},
    )
    grant_request(
        session,
        request.id,
        "risk-approver",
        {"risk_manager"},
        "10.0.0.2",
        "sess-approver",
    )
    calls: list[dict] = []

    row, result = consume_request(
        session,
        request.id,
        "risk-requester",
        payload,
        lambda data: calls.append(data) or {"created": True},
    )

    assert row.status == ApprovalStatus.consumed
    assert row.consumed_at is not None
    assert result == {"created": True}
    assert calls == [payload]


@pytest.mark.parametrize("source_status", [ApprovalStatus.pending, ApprovalStatus.approved])
def test_supersede_is_requester_only_from_pending_or_approved(session, source_status) -> None:
    request = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        _payload(),
        Decimal("600000.00"),
        "risk-requester",
        "10.0.0.1",
        "sess-1",
        uuid4(),
        f"supersede-{source_status.value}",
        {"risk_manager"},
    )
    if source_status == ApprovalStatus.approved:
        grant_request(
            session,
            request.id,
            "risk-approver",
            {"risk_manager"},
            "10.0.0.2",
            "sess-approver",
        )

    with pytest.raises(HTTPException) as peer:
        supersede_request(session, request.id, "risk-peer")
    assert peer.value.status_code == 403

    superseded = supersede_request(session, request.id, "risk-requester")
    assert superseded.status == ApprovalStatus.superseded


@pytest.mark.parametrize("source_status", [ApprovalStatus.pending, ApprovalStatus.approved])
def test_sweep_expired_handles_pending_and_approved(session, source_status) -> None:
    request = evaluate_and_maybe_create(
        session,
        MutationType.deal_create,
        _payload(),
        Decimal("600000.00"),
        "risk-requester",
        "10.0.0.1",
        "sess-1",
        uuid4(),
        f"expire-{source_status.value}",
        {"risk_manager"},
    )
    if source_status == ApprovalStatus.approved:
        grant_request(
            session,
            request.id,
            "risk-approver",
            {"risk_manager"},
            "10.0.0.2",
            "sess-approver",
        )
    request.expires_at = request.created_at - timedelta(minutes=1)
    session.flush()

    expired = sweep_expired(session)

    assert [row.id for row in expired] == [request.id]
    assert session.get(WorkflowApprovalRequest, request.id).status == ApprovalStatus.expired

