"""044_drop_deal_lifecycle_fields

Revision ID: 044_drop_deal_lifecycle_fields
Revises: 043_a5_audit_payload_input
Create Date: 2026-05-14 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "044_drop_deal_lifecycle_fields"
down_revision = "043_a5_audit_payload_input"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("deals", "deleted_at")
    op.drop_column("deals", "is_deleted")


def downgrade() -> None:
    op.add_column(
        "deals",
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "deals",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
