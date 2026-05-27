"""fase1_core_domain

Revision ID: 88c13cd6dd8e
Revises: 016
Create Date: 2026-03-02 14:16:13.794639

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "88c13cd6dd8e"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# ---------------------------------------------------------------------------
# Enum definitions (PostgreSQL named enums)
# ---------------------------------------------------------------------------
counterparty_type = sa.Enum("customer", "supplier", "broker", name="counterparty_type")
kyc_status = sa.Enum("pending", "approved", "expired", "rejected", name="kyc_status")
sanctions_status = sa.Enum("clear", "flagged", "blocked", name="sanctions_status")
risk_rating = sa.Enum("low", "medium", "high", name="risk_rating")
pricing_type = sa.Enum("fixed", "average", "avginter", "fix", "c2r", name="pricing_type")

exposure_direction = sa.Enum("long", "short", name="exposure_direction")
exposure_source_type = sa.Enum("sales_order", "purchase_order", name="exposure_source_type")
exposure_status = sa.Enum(
    "open", "partially_hedged", "fully_hedged", "cancelled", name="exposure_status"
)
hedge_task_action = sa.Enum("hedge_new", "increase", "decrease", "cancel", name="hedge_task_action")
hedge_task_status = sa.Enum("pending", "executed", "cancelled", name="hedge_task_status")

hedge_direction = sa.Enum("buy", "sell", name="hedge_direction")
hedge_status = sa.Enum("active", "partially_settled", "settled", "cancelled", name="hedge_status")
hedge_source_type = sa.Enum("rfq_award", "manual", "auto", name="hedge_source_type")

deal_status = sa.Enum(
    "open", "partially_hedged", "fully_hedged", "settled", "closed", name="deal_status"
)
deal_linked_type = sa.Enum(
    "sales_order", "purchase_order", "hedge", "contract", name="deal_linked_type"
)

pipeline_run_status = sa.Enum(
    "running", "completed", "failed", "partial", name="pipeline_run_status"
)
pipeline_step_status = sa.Enum(
    "pending", "running", "completed", "failed", "skipped", name="pipeline_step_status"
)


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. counterparties (no FK deps)
    # ------------------------------------------------------------------
    op.create_table(
        "counterparties",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("type", counterparty_type, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("short_name", sa.String(50), nullable=True),
        sa.Column("tax_id", sa.String(50), nullable=True, unique=True),
        sa.Column("country", sa.String(3), nullable=False),
        sa.Column("city", sa.String(100), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.String(200), nullable=True),
        sa.Column("contact_email", sa.String(200), nullable=True),
        sa.Column("contact_phone", sa.String(50), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("credit_limit_usd", sa.Numeric(15, 2), nullable=True),
        sa.Column("kyc_status", kyc_status, nullable=False, server_default="pending"),
        sa.Column("sanctions_status", sanctions_status, nullable=False, server_default="clear"),
        sa.Column("risk_rating", risk_rating, nullable=False, server_default="medium"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 2. orders — add Phase-1 columns
    # ------------------------------------------------------------------
    # pricing_type is only referenced via ALTER TABLE ADD COLUMN below — SQLAlchemy's
    # auto-create only fires on CREATE TABLE, so create the enum explicitly first.
    pricing_type.create(op.get_bind(), checkfirst=True)
    op.add_column("orders", sa.Column("counterparty_id", sa.UUID(as_uuid=True), nullable=True))
    op.add_column("orders", sa.Column("pricing_type", pricing_type, nullable=True))
    op.add_column("orders", sa.Column("delivery_terms", sa.String(50), nullable=True))
    op.add_column("orders", sa.Column("delivery_date_start", sa.Date(), nullable=True))
    op.add_column("orders", sa.Column("delivery_date_end", sa.Date(), nullable=True))
    op.add_column("orders", sa.Column("payment_terms_days", sa.Integer(), nullable=True))
    op.add_column(
        "orders",
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
    )
    op.add_column("orders", sa.Column("notes", sa.Text(), nullable=True))
    op.create_foreign_key(
        "fk_orders_counterparty_id",
        "orders",
        "counterparties",
        ["counterparty_id"],
        ["id"],
    )

    # ------------------------------------------------------------------
    # 3. so_po_links (FK → orders × 2)
    # ------------------------------------------------------------------
    op.create_table(
        "so_po_links",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "sales_order_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column(
            "purchase_order_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("orders.id"),
            nullable=False,
        ),
        sa.Column("linked_tons", sa.Numeric(15, 3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("sales_order_id", "purchase_order_id", name="uq_sopo_link"),
    )

    # ------------------------------------------------------------------
    # 4. exposures (no FK deps)
    # ------------------------------------------------------------------
    op.create_table(
        "exposures",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("commodity", sa.String(20), nullable=False),
        sa.Column("direction", exposure_direction, nullable=False),
        sa.Column("source_type", exposure_source_type, nullable=False),
        sa.Column("source_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("original_tons", sa.Numeric(15, 3), nullable=False),
        sa.Column("open_tons", sa.Numeric(15, 3), nullable=False),
        sa.Column("price_per_ton", sa.Numeric(15, 2), nullable=True),
        sa.Column("settlement_month", sa.String(7), nullable=True),
        sa.Column("status", exposure_status, nullable=False, server_default="open"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 5. contract_exposures (FK → exposures, hedge_contracts)
    # ------------------------------------------------------------------
    op.create_table(
        "contract_exposures",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "exposure_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("exposures.id"),
            nullable=False,
        ),
        sa.Column(
            "contract_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("hedge_contracts.id"),
            nullable=False,
        ),
        sa.Column("allocated_tons", sa.Numeric(15, 3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # 6. hedge_exposures (FK → exposures; hedge_id has no DB FK)
    # ------------------------------------------------------------------
    op.create_table(
        "hedge_exposures",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "exposure_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("exposures.id"),
            nullable=False,
        ),
        sa.Column("hedge_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("allocated_tons", sa.Numeric(15, 3), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # 7. hedge_tasks (FK → exposures)
    # ------------------------------------------------------------------
    op.create_table(
        "hedge_tasks",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "exposure_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("exposures.id"),
            nullable=False,
        ),
        sa.Column("recommended_tons", sa.Numeric(15, 3), nullable=False),
        sa.Column("recommended_action", hedge_task_action, nullable=False),
        sa.Column("status", hedge_task_status, nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 8. hedges (FK → counterparties, hedge_contracts)
    # ------------------------------------------------------------------
    op.create_table(
        "hedges",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference", sa.String(50), nullable=False, unique=True),
        sa.Column(
            "counterparty_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("counterparties.id"),
            nullable=False,
        ),
        sa.Column("commodity", sa.String(20), nullable=False),
        sa.Column("direction", hedge_direction, nullable=False),
        sa.Column("tons", sa.Numeric(15, 3), nullable=False),
        sa.Column("price_per_ton", sa.Numeric(15, 2), nullable=False),
        sa.Column("premium_discount", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("prompt_date", sa.Date(), nullable=True),
        sa.Column("trade_date", sa.Date(), nullable=False),
        sa.Column("status", hedge_status, nullable=False, server_default="active"),
        sa.Column("source_type", hedge_source_type, nullable=False),
        sa.Column("source_id", sa.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "contract_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("hedge_contracts.id"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 9. deals (no FK deps)
    # ------------------------------------------------------------------
    op.create_table(
        "deals",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("reference", sa.String(50), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("commodity", sa.String(20), nullable=False),
        sa.Column("status", deal_status, nullable=False, server_default="open"),
        sa.Column("total_physical_tons", sa.Numeric(15, 3), nullable=False, server_default="0"),
        sa.Column("total_hedge_tons", sa.Numeric(15, 3), nullable=False, server_default="0"),
        sa.Column("hedge_ratio", sa.Numeric(5, 2), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ------------------------------------------------------------------
    # 10. deal_links (FK → deals)
    # ------------------------------------------------------------------
    op.create_table(
        "deal_links",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "deal_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("deals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("linked_type", deal_linked_type, nullable=False),
        sa.Column("linked_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("deal_id", "linked_type", "linked_id", name="uq_deal_link"),
    )

    # ------------------------------------------------------------------
    # 11. deal_pnl_snapshots (FK → deals)
    # ------------------------------------------------------------------
    op.create_table(
        "deal_pnl_snapshots",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "deal_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("deals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("physical_revenue", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("physical_cost", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("hedge_pnl_realized", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("hedge_pnl_mtm", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("total_pnl", sa.Numeric(15, 2), nullable=False, server_default="0"),
        sa.Column("inputs_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # 12. finance_pipeline_runs (no FK deps)
    # ------------------------------------------------------------------
    op.create_table(
        "finance_pipeline_runs",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("status", pipeline_run_status, nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("steps_completed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("steps_total", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("inputs_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ------------------------------------------------------------------
    # 13. finance_pipeline_steps (FK → finance_pipeline_runs)
    # ------------------------------------------------------------------
    op.create_table(
        "finance_pipeline_steps",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("finance_pipeline_runs.id"),
            nullable=False,
        ),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("step_name", sa.String(50), nullable=False),
        sa.Column("status", pipeline_step_status, nullable=False, server_default="pending"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("records_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    # Drop tables in reverse order of creation (respecting FK deps)
    op.drop_table("finance_pipeline_steps")
    op.drop_table("finance_pipeline_runs")
    op.drop_table("deal_pnl_snapshots")
    op.drop_table("deal_links")
    op.drop_table("deals")
    op.drop_table("hedges")
    op.drop_table("hedge_tasks")
    op.drop_table("hedge_exposures")
    op.drop_table("contract_exposures")
    op.drop_table("exposures")
    op.drop_table("so_po_links")

    # Remove Phase-1 columns from orders
    op.drop_constraint("fk_orders_counterparty_id", "orders", type_="foreignkey")
    op.drop_column("orders", "notes")
    op.drop_column("orders", "currency")
    op.drop_column("orders", "payment_terms_days")
    op.drop_column("orders", "delivery_date_end")
    op.drop_column("orders", "delivery_date_start")
    op.drop_column("orders", "delivery_terms")
    op.drop_column("orders", "pricing_type")
    op.drop_column("orders", "counterparty_id")

    op.drop_table("counterparties")

    # Drop enums
    pipeline_step_status.drop(op.get_bind(), checkfirst=True)
    pipeline_run_status.drop(op.get_bind(), checkfirst=True)
    deal_linked_type.drop(op.get_bind(), checkfirst=True)
    deal_status.drop(op.get_bind(), checkfirst=True)
    hedge_source_type.drop(op.get_bind(), checkfirst=True)
    hedge_status.drop(op.get_bind(), checkfirst=True)
    hedge_direction.drop(op.get_bind(), checkfirst=True)
    hedge_task_status.drop(op.get_bind(), checkfirst=True)
    hedge_task_action.drop(op.get_bind(), checkfirst=True)
    exposure_status.drop(op.get_bind(), checkfirst=True)
    exposure_source_type.drop(op.get_bind(), checkfirst=True)
    exposure_direction.drop(op.get_bind(), checkfirst=True)
    pricing_type.drop(op.get_bind(), checkfirst=True)
    risk_rating.drop(op.get_bind(), checkfirst=True)
    sanctions_status.drop(op.get_bind(), checkfirst=True)
    kyc_status.drop(op.get_bind(), checkfirst=True)
    counterparty_type.drop(op.get_bind(), checkfirst=True)
