"""finance_pipeline_hb3_hardening

Revision ID: 047_finance_pipeline_hb3_hardening
Revises: 046_workflow_approval_gate
Create Date: 2026-05-22
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "047_finance_pipeline_hb3_hardening"
down_revision = "046_workflow_approval_gate"
branch_labels = None
depends_on = None


trigger_source_enum = sa.Enum(
    "scheduler",
    "manual",
    name="pipeline_trigger_source",
)
risk_flag_type_enum = sa.Enum(
    "missing_mtm_price",
    "unhedged_exposure_over_guardrail",
    "kyc_regression_with_active_deals",
    "workflow_approval_pending_past_expiry",
    name="pipeline_risk_flag_type",
)
risk_flag_severity_enum = sa.Enum(
    "informational",
    "warning",
    "critical",
    name="pipeline_risk_flag_severity",
)


def _uuid_type() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite")


def _json_type() -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def upgrade() -> None:
    bind = op.get_bind()
    # trigger_source_enum is needed for the ALTER TABLE ADD COLUMN below
    # (auto-create only fires on CREATE TABLE). The other two enums are only
    # referenced in create_table("finance_pipeline_risk_flags") and would
    # double-create here without checkfirst.
    trigger_source_enum.create(bind, checkfirst=True)

    with op.batch_alter_table("finance_pipeline_runs") as batch_op:
        batch_op.add_column(
            sa.Column(
                "triggered_by",
                trigger_source_enum,
                nullable=False,
                server_default="manual",
            )
        )
        batch_op.create_unique_constraint(
            "uq_finance_pipeline_runs_run_date",
            ["run_date"],
        )
    op.create_table(
        "finance_pipeline_risk_flags",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("run_id", _uuid_type(), nullable=False),
        sa.Column("flag_type", risk_flag_type_enum, nullable=False),
        sa.Column("severity", risk_flag_severity_enum, nullable=False),
        sa.Column("subject_entity_type", sa.String(length=64), nullable=False),
        sa.Column("subject_entity_id", _uuid_type(), nullable=True),
        sa.Column("subject_entity_key", sa.String(length=64), nullable=False),
        sa.Column("payload", _json_type(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["run_id"], ["finance_pipeline_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "run_id",
            "subject_entity_key",
            "flag_type",
            name="uq_finance_pipeline_risk_flags_run_subject_type",
        ),
    )
    op.create_index(
        "ix_finance_pipeline_risk_flags_run_id",
        "finance_pipeline_risk_flags",
        ["run_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_finance_pipeline_risk_flags_run_id",
        table_name="finance_pipeline_risk_flags",
    )
    op.drop_table("finance_pipeline_risk_flags")
    with op.batch_alter_table("finance_pipeline_runs") as batch_op:
        batch_op.drop_constraint(
            "uq_finance_pipeline_runs_run_date",
            type_="unique",
        )
        batch_op.drop_column("triggered_by")

    bind = op.get_bind()
    risk_flag_severity_enum.drop(bind, checkfirst=True)
    risk_flag_type_enum.drop(bind, checkfirst=True)
    trigger_source_enum.drop(bind, checkfirst=True)
