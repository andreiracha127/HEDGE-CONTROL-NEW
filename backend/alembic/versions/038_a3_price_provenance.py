"""Phase A3 Wave 1: price provenance + decimal cash settlement prices.

Revision ID: 038_a3_price_provenance
Revises: 037_rfq_outbound_evidence
Create Date: 2026-05-09 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "038_a3_price_provenance"
down_revision = "037_rfq_outbound_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        out_of_scale = bind.execute(
            sa.text(
                "SELECT COUNT(*) FROM cash_settlement_prices "
                "WHERE scale(price_usd::numeric) > 6"
            )
        ).scalar()
        if out_of_scale > 0:
            raise RuntimeError(
                f"Refusing to convert {out_of_scale} rows with > 6 fractional digits; "
                "manual review required before migration can proceed."
            )
        op.alter_column(
            "cash_settlement_prices",
            "price_usd",
            existing_type=sa.Float(),
            type_=sa.Numeric(18, 6),
            existing_nullable=False,
            postgresql_using="price_usd::numeric",
        )

    with op.batch_alter_table("mtm_snapshots") as batch:
        batch.add_column(sa.Column("price_source", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("price_symbol", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("price_settlement_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("inputs_hash", sa.String(length=64), nullable=True))
        batch.create_check_constraint(
            "ck_mtm_snapshots_provenance_all_or_none",
            "(price_source IS NULL AND price_symbol IS NULL AND price_settlement_date IS NULL AND inputs_hash IS NULL) "
            "OR (price_source IS NOT NULL AND price_symbol IS NOT NULL AND price_settlement_date IS NOT NULL AND inputs_hash IS NOT NULL)",
        )

    pl_json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    with op.batch_alter_table("pl_snapshots") as batch:
        batch.add_column(sa.Column("price_references", pl_json_type, nullable=True))
        batch.add_column(sa.Column("inputs_hash", sa.String(length=64), nullable=True))
        batch.create_check_constraint(
            "ck_pl_snapshots_provenance_all_or_none",
            "(price_references IS NULL AND inputs_hash IS NULL) "
            "OR (price_references IS NOT NULL AND inputs_hash IS NOT NULL)",
        )

    with op.batch_alter_table("cashflow_baseline_snapshots") as batch:
        batch.add_column(sa.Column("inputs_hash", sa.String(length=64), nullable=True))

    with op.batch_alter_table("cashflow_ledger_entries") as batch:
        batch.add_column(sa.Column("price_source", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("price_symbol", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("price_settlement_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("price_value", sa.Numeric(18, 6), nullable=True))
        batch.create_check_constraint(
            "ck_cashflow_ledger_entries_provenance_all_or_none",
            "(price_source IS NULL AND price_symbol IS NULL AND price_settlement_date IS NULL AND price_value IS NULL) "
            "OR (price_source IS NOT NULL AND price_symbol IS NOT NULL AND price_settlement_date IS NOT NULL AND price_value IS NOT NULL)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    with op.batch_alter_table("cashflow_ledger_entries") as batch:
        batch.drop_constraint(
            "ck_cashflow_ledger_entries_provenance_all_or_none", type_="check"
        )
        batch.drop_column("price_value")
        batch.drop_column("price_settlement_date")
        batch.drop_column("price_symbol")
        batch.drop_column("price_source")

    with op.batch_alter_table("cashflow_baseline_snapshots") as batch:
        batch.drop_column("inputs_hash")

    with op.batch_alter_table("pl_snapshots") as batch:
        batch.drop_constraint("ck_pl_snapshots_provenance_all_or_none", type_="check")
        batch.drop_column("inputs_hash")
        batch.drop_column("price_references")

    with op.batch_alter_table("mtm_snapshots") as batch:
        batch.drop_constraint("ck_mtm_snapshots_provenance_all_or_none", type_="check")
        batch.drop_column("inputs_hash")
        batch.drop_column("price_settlement_date")
        batch.drop_column("price_symbol")
        batch.drop_column("price_source")

    if bind.dialect.name == "postgresql":
        op.alter_column(
            "cash_settlement_prices",
            "price_usd",
            existing_type=sa.Numeric(18, 6),
            type_=sa.Float(),
            existing_nullable=False,
            postgresql_using="price_usd::double precision",
        )
