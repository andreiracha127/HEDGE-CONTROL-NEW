"""Decimal primitives for MT and price.

Type-only migration with preflight data-loss assertion; refuses silent
rounding. precision/scale match existing `Exposure.original_tons` policy.

Revision ID: 025_decimal_primitives
Revises: 024
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025_decimal_primitives"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MT_COLUMNS = (
    ("orders", "quantity_mt"),
    ("hedge_contracts", "quantity_mt"),
    ("hedge_order_linkages", "quantity_mt"),
)
PRICE_COLUMNS = (
    ("orders", "avg_entry_price"),
    ("hedge_contracts", "fixed_price_value"),
    ("hedge_contracts", "premium_discount"),
)


def _assert_no_loss(table: str, col: str, scale: int) -> None:
    result = op.get_bind().execute(
        sa.text(
            f"""
            SELECT COUNT(*) AS n,
                   COALESCE(MAX(scale_decimals), 0) AS max_scale
            FROM (
                SELECT length(split_part(({col})::text, '.', 2)) AS scale_decimals
                FROM {table}
                WHERE {col} IS NOT NULL
            ) AS sub
            WHERE scale_decimals > :scale
            """
        ),
        {"scale": scale},
    ).one()
    if result.n > 0:
        raise RuntimeError(
            f"{table}.{col}: {result.n} rows have more than {scale} fractional "
            f"digits (max observed = {result.max_scale}). Refusing to migrate "
            f"with silent rounding. Resolve the data first or pick a wider scale."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table, col in MT_COLUMNS:
        _assert_no_loss(table, col, 3)
    for table, col in PRICE_COLUMNS:
        _assert_no_loss(table, col, 6)

    op.alter_column(
        "orders",
        "quantity_mt",
        existing_type=sa.Float(),
        type_=sa.Numeric(15, 3),
        existing_nullable=False,
        postgresql_using="quantity_mt::numeric",
    )
    op.alter_column(
        "orders",
        "avg_entry_price",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 6),
        existing_nullable=True,
        postgresql_using="avg_entry_price::numeric",
    )
    op.alter_column(
        "hedge_contracts",
        "quantity_mt",
        existing_type=sa.Float(),
        type_=sa.Numeric(15, 3),
        existing_nullable=False,
        postgresql_using="quantity_mt::numeric",
    )
    op.alter_column(
        "hedge_contracts",
        "fixed_price_value",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 6),
        existing_nullable=True,
        postgresql_using="fixed_price_value::numeric",
    )
    op.alter_column(
        "hedge_contracts",
        "premium_discount",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 6),
        existing_nullable=True,
        postgresql_using="premium_discount::numeric",
    )
    op.alter_column(
        "hedge_order_linkages",
        "quantity_mt",
        existing_type=sa.Float(),
        type_=sa.Numeric(15, 3),
        existing_nullable=False,
        postgresql_using="quantity_mt::numeric",
    )
    op.alter_column(
        "exposures",
        "price_per_ton",
        existing_type=sa.Numeric(15, 2),
        type_=sa.Numeric(18, 6),
        existing_nullable=True,
    )
    for col in (
        "physical_revenue",
        "physical_cost",
        "hedge_pnl_realized",
        "hedge_pnl_mtm",
        "total_pnl",
    ):
        op.alter_column(
            "deal_pnl_snapshots",
            col,
            existing_type=sa.Numeric(15, 2),
            type_=sa.Numeric(18, 6),
            existing_nullable=True,
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for col in (
        "physical_revenue",
        "physical_cost",
        "hedge_pnl_realized",
        "hedge_pnl_mtm",
        "total_pnl",
    ):
        op.alter_column(
            "deal_pnl_snapshots",
            col,
            existing_type=sa.Numeric(18, 6),
            type_=sa.Numeric(15, 2),
            existing_nullable=True,
        )
    op.alter_column(
        "exposures",
        "price_per_ton",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Numeric(15, 2),
        existing_nullable=True,
    )
    op.alter_column(
        "hedge_order_linkages",
        "quantity_mt",
        existing_type=sa.Numeric(15, 3),
        type_=sa.Float(),
        existing_nullable=False,
        postgresql_using="quantity_mt::double precision",
    )
    op.alter_column(
        "hedge_contracts",
        "premium_discount",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Float(),
        existing_nullable=True,
        postgresql_using="premium_discount::double precision",
    )
    op.alter_column(
        "hedge_contracts",
        "fixed_price_value",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Float(),
        existing_nullable=True,
        postgresql_using="fixed_price_value::double precision",
    )
    op.alter_column(
        "hedge_contracts",
        "quantity_mt",
        existing_type=sa.Numeric(15, 3),
        type_=sa.Float(),
        existing_nullable=False,
        postgresql_using="quantity_mt::double precision",
    )
    op.alter_column(
        "orders",
        "avg_entry_price",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Float(),
        existing_nullable=True,
        postgresql_using="avg_entry_price::double precision",
    )
    op.alter_column(
        "orders",
        "quantity_mt",
        existing_type=sa.Numeric(15, 3),
        type_=sa.Float(),
        existing_nullable=False,
        postgresql_using="quantity_mt::double precision",
    )
