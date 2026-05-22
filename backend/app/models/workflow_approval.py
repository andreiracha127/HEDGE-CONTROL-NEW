"""Workflow approval gate models for Pilot HB-2."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, Enum, Index, Numeric, String, Text, event, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.precision import PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE
from app.models.base import Base

JsonPayload = sa.JSON().with_variant(JSONB(astext_type=Text()), "postgresql")


class MutationType(enum.Enum):
    deal_create = "deal_create"
    deal_award = "deal_award"
    hedge_contract_settle = "hedge_contract_settle"


class ApprovalStatus(enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    expired = "expired"
    consumed = "consumed"
    superseded = "superseded"


class ThresholdDimension(enum.Enum):
    notional_usd = "notional_usd"
    settlement_amount_usd = "settlement_amount_usd"


class RejectionReasonCode(enum.Enum):
    policy_violation = "policy_violation"
    counterparty_risk = "counterparty_risk"
    payload_concern = "payload_concern"
    threshold_inappropriate = "threshold_inappropriate"
    other = "other"


class WorkflowApprovalRequest(Base):
    __tablename__ = "workflow_approval_requests"
    __table_args__ = (
        CheckConstraint(
            "approved_by IS NULL OR requested_by != approved_by",
            name="ck_workflow_approval_requests_distinct_actors",
        ),
        CheckConstraint(
            "("
            "rejection_reason_code IS NULL AND rejection_reason_text IS NULL"
            ") OR ("
            "rejection_reason_code IS NOT NULL AND rejection_reason_text IS NOT NULL "
            "AND LENGTH(rejection_reason_text) >= 8"
            ")",
            name="ck_workflow_approval_requests_rejection_complete",
        ),
        Index(
            "ux_workflow_approval_requests_idempotency_key",
            "idempotency_key",
            "requested_by",
            "mutation_type",
            unique=True,
            sqlite_where=sa.text("idempotency_key IS NOT NULL"),
            postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_workflow_approval_requests_status_expires_at",
            "status",
            "expires_at",
        ),
        Index("ix_workflow_approval_requests_correlation_id", "correlation_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mutation_type: Mapped[MutationType] = mapped_column(
        Enum(MutationType, name="workflow_approval_mutation_type"), nullable=False
    )
    status: Mapped[ApprovalStatus] = mapped_column(
        Enum(ApprovalStatus, name="workflow_approval_status"),
        nullable=False,
        default=ApprovalStatus.pending,
    )
    requested_by: Mapped[str] = mapped_column(String(length=200), nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String(length=200), nullable=True)
    threshold_at_request: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), nullable=False
    )
    threshold_config_value: Mapped[Decimal] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), nullable=False
    )
    threshold_dimension: Mapped[ThresholdDimension] = mapped_column(
        Enum(ThresholdDimension, name="workflow_approval_threshold_dimension"),
        nullable=False,
    )
    mutation_payload_canonical: Mapped[str] = mapped_column(Text, nullable=False)
    mutation_payload_hash: Mapped[str] = mapped_column(String(length=64), nullable=False)
    correlation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(length=200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approver_ip: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
    approver_session_id: Mapped[str | None] = mapped_column(String(length=200), nullable=True)
    rejection_reason_code: Mapped[RejectionReasonCode | None] = mapped_column(
        Enum(RejectionReasonCode, name="workflow_approval_rejection_reason_code"),
        nullable=True,
    )
    rejection_reason_text: Mapped[str | None] = mapped_column(String(length=1000), nullable=True)


class ApprovalPolicy(Base):
    __tablename__ = "approval_policy"

    mutation_type: Mapped[MutationType] = mapped_column(
        Enum(MutationType, name="workflow_approval_mutation_type"), primary_key=True
    )
    required_approver_roles: Mapped[list[str]] = mapped_column(JsonPayload, nullable=False)
    fallback_when_requester_is: Mapped[dict] = mapped_column(JsonPayload, nullable=False)
    threshold_dimension: Mapped[ThresholdDimension] = mapped_column(
        Enum(ThresholdDimension, name="workflow_approval_threshold_dimension"),
        nullable=False,
    )


_POLICY_SEED = [
    {
        "mutation_type": MutationType.deal_create,
        "required_approver_roles": ["risk_manager"],
        "fallback_when_requester_is": {},
        "threshold_dimension": ThresholdDimension.notional_usd,
    },
    {
        "mutation_type": MutationType.deal_award,
        "required_approver_roles": ["risk_manager"],
        "fallback_when_requester_is": {},
        "threshold_dimension": ThresholdDimension.notional_usd,
    },
    {
        "mutation_type": MutationType.hedge_contract_settle,
        "required_approver_roles": ["auditor"],
        "fallback_when_requester_is": {},
        "threshold_dimension": ThresholdDimension.settlement_amount_usd,
    },
]


@event.listens_for(ApprovalPolicy.__table__, "after_create")
def _seed_approval_policy(target, connection, **_) -> None:  # type: ignore[no-untyped-def]
    connection.execute(target.insert(), _POLICY_SEED)
