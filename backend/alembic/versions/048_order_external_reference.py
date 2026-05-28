"""order_external_reference

Revision ID: 048_order_external_reference
Revises: 047_finance_pipeline_hb3_hardening
Create Date: 2026-05-28
"""

import sqlalchemy as sa

from alembic import op

revision = "048_order_external_reference"
down_revision = "047_finance_pipeline_hb3_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("external_reference", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "external_reference")
