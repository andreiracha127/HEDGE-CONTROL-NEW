"""Create reconciliation_runs table — durable anchor for reconcile audit rows.

Revision ID: 028_reconciliation_run
Revises: 027_order_commodity
Create Date: 2026-05-06 00:00:00.000000

Each ``POST /exposures/reconcile`` invocation persists one row of
``reconciliation_runs`` to anchor its signed audit event. See PR-7.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "028_reconciliation_run"
down_revision: Union[str, None] = "027_order_commodity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        uuid_type = sa.dialects.postgresql.UUID(as_uuid=True)
    else:
        # SQLite (test) — store UUID as 36-char string.
        uuid_type = sa.String(length=36)

    op.create_table(
        "reconciliation_runs",
        sa.Column("id", uuid_type, primary_key=True),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "succeeded",
                "failed",
                name="reconciliation_run_status",
            ),
            nullable=False,
            server_default="running",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "rows_created", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "rows_updated", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.String(length=512), nullable=True),
    )
    op.create_index(
        "ix_reconciliation_runs_started_at",
        "reconciliation_runs",
        ["started_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reconciliation_runs_started_at", table_name="reconciliation_runs"
    )
    op.drop_table("reconciliation_runs")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        sa.Enum(name="reconciliation_run_status").drop(bind, checkfirst=True)
