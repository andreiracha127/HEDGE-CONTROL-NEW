from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.workflow_approval import (
    ApprovalStatus,
    MutationType,
    RejectionReasonCode,
    ThresholdDimension,
)


class WorkflowApprovalRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    mutation_type: MutationType
    status: ApprovalStatus
    requested_by: str
    approved_by: str | None = None
    threshold_at_request: Decimal
    threshold_config_value: Decimal
    threshold_dimension: ThresholdDimension
    correlation_id: UUID
    idempotency_key: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    expires_at: datetime
    consumed_at: datetime | None = None
    approver_ip: str | None = None
    approver_session_id: str | None = None
    rejection_reason_code: RejectionReasonCode | None = None
    rejection_reason_text: str | None = None


class WorkflowApprovalPendingResponse(BaseModel):
    approval_id: UUID
    status: ApprovalStatus
    expires_at: datetime
    required_approvers: list[str]
    polling_url: str
    consume_url: str


class WorkflowApprovalRejectRequest(BaseModel):
    reason_code: RejectionReasonCode
    reason_text: str = Field(..., min_length=8, max_length=1000)


class WorkflowApprovalConsumeRequest(BaseModel):
    payload: dict

