"""Create orders table

Revision ID: 001_create_orders_table
Revises: None
Create Date: 2026-02-01 13:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001_create_orders_table"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# For Postgres, define ENUM instances with create_type=False so SQLAlchemy 2.0+
# does NOT auto-issue CREATE TYPE during op.create_table (we do it explicitly via .create()
# below). Reusing the same instance in the Column avoids the DuplicateObject error.
order_type_enum_pg = postgresql.ENUM("SO", "PO", name="order_type", create_type=False)
price_type_enum_pg = postgresql.ENUM("fixed", "variable", name="price_type", create_type=False)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        order_type_enum_pg.create(bind, checkfirst=True)
        price_type_enum_pg.create(bind, checkfirst=True)
        order_type_col_type = order_type_enum_pg
        price_type_col_type = price_type_enum_pg
    else:
        # SQLite: VARCHAR + CHECK constraint via native_enum=False.
        order_type_col_type = sa.Enum(
            "SO", "PO", name="order_type", native_enum=False, create_constraint=True
        )
        price_type_col_type = sa.Enum(
            "fixed", "variable", name="price_type", native_enum=False, create_constraint=True
        )

    op.create_table(
        "orders",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("order_type", order_type_col_type, nullable=False),
        sa.Column("price_type", price_type_col_type, nullable=False),
        sa.Column("quantity_mt", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("orders")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        price_type_enum_pg.drop(bind, checkfirst=True)
        order_type_enum_pg.drop(bind, checkfirst=True)
