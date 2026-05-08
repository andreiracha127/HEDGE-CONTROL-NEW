"""Phase A2 PR-1: complete A1 Decimal substrate on RFQ-side.

Type-only ALTER with preflight loss assertion on the 5 RFQ MT columns and
the rfq_quotes price column. Counterparty FK preflight rejects orphans
without silent rounding/coercion.

Revision ID: 033_rfq_decimal_primitives
Revises: 032_linkage_capacity_live_filter
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "033_rfq_decimal_primitives"
down_revision: Union[str, None] = "032_linkage_capacity_live_filter"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


MT_COLUMNS = (
    ("rfqs", "quantity_mt"),
    ("rfqs", "commercial_active_mt"),
    ("rfqs", "commercial_passive_mt"),
    ("rfqs", "commercial_net_mt"),
    ("rfqs", "commercial_reduction_applied_mt"),
)
PRICE_COLUMNS = (("rfq_quotes", "price_value"),)


def _assert_no_loss(table: str, col: str, scale: int) -> None:
    # Detect rows whose value would round under NUMERIC(_, scale).
    #
    # Earlier this used ``length(split_part((col)::text, '.', 2))``, but
    # Postgres renders ``double precision`` values such as ``1e-05`` in
    # exponential form — there is no decimal point, so split_part returns
    # an empty string and the row passes the preflight even though the
    # subsequent cast to NUMERIC(_, 3/6) silently rounds it to 0.
    #
    # Round-tripping through ``::text::numeric`` lets numeric equality
    # (which ignores trailing zeros) decide losslessness: if rounding to
    # ``scale`` changes the value, casting will too. The
    # ``::text::numeric`` chain (rather than the direct ``::numeric``
    # cast) yields Postgres' shortest-round-trip text form first, which
    # avoids the spurious low-order digits a binary float carries when
    # cast straight to numeric.
    result = op.get_bind().execute(
        sa.text(
            f"""
            WITH cleaned AS (
                SELECT (({col})::text)::numeric AS v
                FROM {table}
                WHERE {col} IS NOT NULL
            )
            SELECT COUNT(*) AS n,
                   COALESCE(
                       MAX(length(split_part(v::text, '.', 2))),
                       0
                   ) AS max_scale
            FROM cleaned
            WHERE v <> round(v, :scale)
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


_UUID_REGEX = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _assert_quote_counterparties_resolvable() -> None:
    bind = op.get_bind()
    invalid = bind.execute(
        sa.text(
            f"""
            SELECT COUNT(*) AS n
            FROM rfq_quotes
            WHERE counterparty_id IS NULL
               OR counterparty_id !~ '{_UUID_REGEX}'
            """
        )
    ).scalar_one()
    if invalid:
        raise RuntimeError(
            f"rfq_quotes.counterparty_id: {invalid} rows hold non-UUID values. "
            "Resolve the data before casting to UUID."
        )

    orphans = bind.execute(
        sa.text(
            """
            SELECT COUNT(*) AS n
            FROM rfq_quotes q
            WHERE NOT EXISTS (
                SELECT 1 FROM counterparties c
                WHERE c.id = q.counterparty_id::uuid
            )
            """
        )
    ).scalar_one()
    if orphans:
        raise RuntimeError(
            f"rfq_quotes.counterparty_id: {orphans} rows reference a "
            "counterparty that does not exist. Refusing to add the FK with "
            "orphans present."
        )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table, col in MT_COLUMNS:
        _assert_no_loss(table, col, 3)
    for table, col in PRICE_COLUMNS:
        _assert_no_loss(table, col, 6)

    _assert_quote_counterparties_resolvable()

    for table, col in MT_COLUMNS:
        op.alter_column(
            table,
            col,
            existing_type=sa.Float(),
            type_=sa.Numeric(15, 3),
            existing_nullable=False,
            postgresql_using=f"{col}::numeric",
        )
    op.alter_column(
        "rfq_quotes",
        "price_value",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 6),
        existing_nullable=False,
        postgresql_using="price_value::numeric",
    )

    op.alter_column(
        "rfq_quotes",
        "counterparty_id",
        existing_type=sa.String(length=64),
        type_=postgresql.UUID(as_uuid=True),
        existing_nullable=False,
        postgresql_using="counterparty_id::uuid",
    )
    op.create_foreign_key(
        "fk_rfq_quotes_counterparty",
        "rfq_quotes",
        "counterparties",
        ["counterparty_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.drop_constraint(
        "fk_rfq_quotes_counterparty", "rfq_quotes", type_="foreignkey"
    )
    op.alter_column(
        "rfq_quotes",
        "counterparty_id",
        existing_type=postgresql.UUID(as_uuid=True),
        type_=sa.String(length=64),
        existing_nullable=False,
        postgresql_using="counterparty_id::text",
    )
    op.alter_column(
        "rfq_quotes",
        "price_value",
        existing_type=sa.Numeric(18, 6),
        type_=sa.Float(),
        existing_nullable=False,
        postgresql_using="price_value::double precision",
    )
    for table, col in reversed(MT_COLUMNS):
        op.alter_column(
            table,
            col,
            existing_type=sa.Numeric(15, 3),
            type_=sa.Float(),
            existing_nullable=False,
            postgresql_using=f"{col}::double precision",
        )
