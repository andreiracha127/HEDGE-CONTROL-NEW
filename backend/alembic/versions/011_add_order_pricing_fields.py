"""Add order pricing fields

Revision ID: 011_add_order_pricing_fields
Revises: 010_add_hedge_contract_status
Create Date: 2026-02-01 20:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011_add_order_pricing_fields"
down_revision: Union[str, None] = "010_add_hedge_contract_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Same postgresql.ENUM instance is reused on the column to prevent SQLAlchemy
        # from emitting a second CREATE TYPE under SA 2.0+ (Codex review 2026-05-22).
        convention_enum_pg = postgresql.ENUM(
            "AVG", "AVGInter", "C2R",
            name="order_pricing_convention", create_type=False,
        )
        convention_enum_pg.create(bind, checkfirst=True)
        op.add_column(
            "orders",
            sa.Column(
                "pricing_convention",
                convention_enum_pg,
                nullable=True,
            ),
        )
    else:
        op.add_column(
            "orders",
            sa.Column("pricing_convention", sa.String(length=32), nullable=True),
        )

    op.add_column("orders", sa.Column("avg_entry_price", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "avg_entry_price")
    op.drop_column("orders", "pricing_convention")

