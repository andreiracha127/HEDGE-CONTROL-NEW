"""Add commodity to orders and backfill implicit Aluminum data.

Revision ID: 027_order_commodity
Revises: 026_classification_invariant
Create Date: 2026-05-06 00:00:00.000000

Before this migration, production orders had no explicit commodity and every
derived exposure path implicitly treated them as Aluminum. This migration
preserves that historical behavior by backfilling existing rows to ALUMINUM.
If any pre-migration rows later prove to be heterogeneous commodities, the
operator is responsible for correcting those tags manually with audited data.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "027_order_commodity"
down_revision: Union[str, None] = "026_classification_invariant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("commodity", sa.String(length=64), nullable=True))
    op.execute("UPDATE orders SET commodity = 'ALUMINUM' WHERE commodity IS NULL")
    with op.batch_alter_table("orders") as batch_op:
        batch_op.alter_column(
            "commodity",
            existing_type=sa.String(length=64),
            nullable=False,
        )
    op.create_index("ix_orders_commodity", "orders", ["commodity"])


def downgrade() -> None:
    op.drop_index("ix_orders_commodity", table_name="orders")
    op.drop_column("orders", "commodity")
