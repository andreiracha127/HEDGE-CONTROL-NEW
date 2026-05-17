"""market_data_governance_columns

Revision ID: 045_market_data_governance_columns
Revises: 044_drop_deal_lifecycle_fields
Create Date: 2026-05-16
"""

from alembic import op
import sqlalchemy as sa


revision = "045_market_data_governance_columns"
down_revision = "044_drop_deal_lifecycle_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cash_settlement_prices",
        sa.Column(
            "is_canonical",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.create_table(
        "market_data_sequence_tracker",
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("instrument", sa.String(length=64), nullable=False),
        sa.Column("last_sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("provider", "instrument"),
    )


def downgrade() -> None:
    op.drop_table("market_data_sequence_tracker")
    op.drop_column("cash_settlement_prices", "is_canonical")
