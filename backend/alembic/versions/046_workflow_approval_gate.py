"""workflow_approval_gate

Revision ID: 046_workflow_approval_gate
Revises: 045_market_data_governance_columns
Create Date: 2026-05-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "046_workflow_approval_gate"
down_revision = "045_market_data_governance_columns"
branch_labels = None
depends_on = None


mutation_type_enum = sa.Enum(
    "deal_create",
    "deal_award",
    "hedge_contract_settle",
    name="workflow_approval_mutation_type",
)
status_enum = sa.Enum(
    "pending",
    "approved",
    "rejected",
    "expired",
    "consumed",
    "superseded",
    name="workflow_approval_status",
)
threshold_dimension_enum = sa.Enum(
    "notional_usd",
    "settlement_amount_usd",
    name="workflow_approval_threshold_dimension",
)
rejection_reason_enum = sa.Enum(
    "policy_violation",
    "counterparty_risk",
    "payload_concern",
    "threshold_inappropriate",
    "other",
    name="workflow_approval_rejection_reason_code",
)


def _uuid_type() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite")


def _json_type() -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "approval_policy",
        sa.Column("mutation_type", mutation_type_enum, nullable=False),
        sa.Column("required_approver_roles", _json_type(), nullable=False),
        sa.Column("fallback_when_requester_is", _json_type(), nullable=False),
        sa.Column("threshold_dimension", threshold_dimension_enum, nullable=False),
        sa.PrimaryKeyConstraint("mutation_type"),
    )
    op.create_table(
        "workflow_approval_requests",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("mutation_type", mutation_type_enum, nullable=False),
        sa.Column(
            "status",
            status_enum,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("requested_by", sa.String(length=200), nullable=False),
        sa.Column("approved_by", sa.String(length=200), nullable=True),
        sa.Column("threshold_at_request", sa.Numeric(18, 6), nullable=False),
        sa.Column("threshold_config_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("threshold_dimension", threshold_dimension_enum, nullable=False),
        sa.Column("mutation_payload_canonical", sa.Text(), nullable=False),
        sa.Column("mutation_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("correlation_id", _uuid_type(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approver_ip", sa.String(length=64), nullable=True),
        sa.Column("approver_session_id", sa.String(length=200), nullable=True),
        sa.Column("rejection_reason_code", rejection_reason_enum, nullable=True),
        sa.Column("rejection_reason_text", sa.String(length=1000), nullable=True),
        sa.CheckConstraint(
            "approved_by IS NULL OR requested_by != approved_by",
            name="ck_workflow_approval_requests_distinct_actors",
        ),
        sa.CheckConstraint(
            "("
            "rejection_reason_code IS NULL AND rejection_reason_text IS NULL"
            ") OR ("
            "rejection_reason_code IS NOT NULL AND rejection_reason_text IS NOT NULL "
            "AND LENGTH(rejection_reason_text) >= 8"
            ")",
            name="ck_workflow_approval_requests_rejection_complete",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_workflow_approval_requests_idempotency_key",
        "workflow_approval_requests",
        ["idempotency_key", "requested_by"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
        sqlite_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_workflow_approval_requests_status_expires_at",
        "workflow_approval_requests",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_workflow_approval_requests_correlation_id",
        "workflow_approval_requests",
        ["correlation_id"],
    )
    op.bulk_insert(
        sa.table(
            "approval_policy",
            sa.column("mutation_type", sa.String),
            sa.column("required_approver_roles", sa.JSON),
            sa.column("fallback_when_requester_is", sa.JSON),
            sa.column("threshold_dimension", sa.String),
        ),
        [
            {
                "mutation_type": "deal_create",
                "required_approver_roles": ["risk_manager"],
                "fallback_when_requester_is": {},
                "threshold_dimension": "notional_usd",
            },
            {
                "mutation_type": "deal_award",
                "required_approver_roles": ["risk_manager"],
                "fallback_when_requester_is": {},
                "threshold_dimension": "notional_usd",
            },
            {
                "mutation_type": "hedge_contract_settle",
                "required_approver_roles": ["auditor"],
                "fallback_when_requester_is": {},
                "threshold_dimension": "settlement_amount_usd",
            },
        ],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_workflow_approval_requests_correlation_id",
        table_name="workflow_approval_requests",
    )
    op.drop_index(
        "ix_workflow_approval_requests_status_expires_at",
        table_name="workflow_approval_requests",
    )
    op.drop_index(
        "ux_workflow_approval_requests_idempotency_key",
        table_name="workflow_approval_requests",
    )
    op.drop_table("workflow_approval_requests")
    op.drop_table("approval_policy")
    rejection_reason_enum.drop(op.get_bind(), checkfirst=True)
    threshold_dimension_enum.drop(op.get_bind(), checkfirst=True)
    status_enum.drop(op.get_bind(), checkfirst=True)
    mutation_type_enum.drop(op.get_bind(), checkfirst=True)
