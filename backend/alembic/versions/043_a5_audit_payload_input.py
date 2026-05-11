"""043_a5_audit_payload_input

Revision ID: 043_a5_audit_payload_input
Revises: 042_a4_llm_decision_artifacts
Create Date: 2026-05-11 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "043_a5_audit_payload_input"
down_revision = "042_a4_llm_decision_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "audit_events",
        sa.Column("payload_canonical", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("audit_events", "payload_canonical")
