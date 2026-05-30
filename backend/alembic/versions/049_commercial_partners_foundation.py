"""commercial_partners_foundation

Creates commercial_partners + sanctions_screenings + sanctions_adjudications,
migrates customer/supplier rows out of counterparties (UUID-reuse, fail-closed
reset), runs two pre-move HALT validations, repoints orders FK, and restricts
counterparties to hedge types.

Revision ID: 049_commercial_partners_foundation
Revises: 048_order_external_reference
Create Date: 2026-05-29
"""

import json

import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "049_commercial_partners_foundation"
down_revision = "048_order_external_reference"
branch_labels = None
depends_on = None


# --- enum objects (auto-created by create_table on PG; CHECKs on SQLite) ---
commercial_partner_kind = sa.Enum("customer", "supplier", name="commercial_partner_kind")
commercial_kyc_status = sa.Enum(
    "pending", "approved", "expired", "rejected", name="commercial_kyc_status"
)
commercial_sanctions_status = sa.Enum(
    "unscreened", "clear", "flagged", "blocked", name="commercial_sanctions_status"
)
commercial_risk_rating = sa.Enum("low", "medium", "high", name="commercial_risk_rating")
lei_status = sa.Enum(
    "not_provided", "valid", "invalid", "lapsed", "issued", "error", name="lei_status"
)
# Single shared enum object reused across both sanctions tables (mirrors the
# 046_workflow_approval_gate pattern: the same Enum instance used in two
# op.create_table calls is created once on PG — no create_type juggling).
sanctions_partner_type = sa.Enum("commercial", "hedge", name="sanctions_partner_type")
screening_result = sa.Enum("clear", "flagged", "blocked", name="sanctions_screening_result")
screening_status = sa.Enum("success", "error", name="sanctions_screening_status")
adjudication_decision = sa.Enum("clear", "blocked", name="sanctions_adjudication_decision")


def _uuid_type() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True).with_variant(sa.String(length=36), "sqlite")


def _json_type() -> sa.types.TypeEngine:
    return postgresql.JSONB(astext_type=sa.Text()).with_variant(sa.JSON(), "sqlite")


def _counterparty_type_expr(*, is_pg: bool) -> str:
    return "type::text" if is_pg else "type"


def _ids_referencing(bind, table: str, partner_ids: set[str]) -> list[str]:
    """Return counterparty_id values in `table` that fall within partner_ids."""
    rows = bind.execute(
        text(f"SELECT counterparty_id FROM {table} WHERE counterparty_id IS NOT NULL")
    ).fetchall()
    return [str(r[0]) for r in rows if str(r[0]) in partner_ids]


def _validate_pre_move(bind) -> None:
    type_expr = _counterparty_type_expr(is_pg=bind.dialect.name == "postgresql")
    existing_tables = set(sa.inspect(bind).get_table_names())
    # (a) orders must not reference broker/bank counterparties (pre-fix data artifact).
    hedge_ids = {
        str(r[0])
        for r in bind.execute(
            text(f"SELECT id FROM counterparties WHERE {type_expr} IN ('broker','bank_br')")
        )
    }
    bad_orders = _ids_referencing(bind, "orders", hedge_ids)
    if bad_orders:
        raise RuntimeError(
            "Refusing to migrate: "
            f"{len(bad_orders)} orders reference a hedge (broker/bank) counterparty. "
            "Re-point each affected order to the correct commercial_partner (or void "
            "it) before running this migration. Offending counterparty_id values: "
            f"{sorted(set(bad_orders))}"
        )

    # (b) hedge-domain refs must not reference customer/supplier counterparties.
    commercial_ids = {
        str(r[0])
        for r in bind.execute(
            text(f"SELECT id FROM counterparties WHERE {type_expr} IN ('customer','supplier')")
        )
    }
    offenders: dict[str, list[str]] = {}
    for ref_table in (
        "rfq_invitations",
        "rfq_quotes",
        "hedges",
        "hedge_contracts",
        "llm_decision_artifacts",
    ):
        if ref_table not in existing_tables:
            continue
        hits = _ids_referencing(bind, ref_table, commercial_ids)
        if hits:
            offenders[ref_table] = sorted(set(hits))
    # rfq_state_events stores hedge counterparty ids under differently-named columns
    # (triggering_counterparty_id, and winning_counterparty_ids as a JSON array of
    # ids) — the literal counterparty_id scan above misses them. Scan explicitly so a
    # legacy event referencing a customer/supplier halts cleanly instead of being
    # orphaned by the DELETE.
    if "rfq_state_events" in existing_tables:
        rfq_hits: set[str] = set()
        for trig, winners in bind.execute(
            text(
                "SELECT triggering_counterparty_id, winning_counterparty_ids FROM rfq_state_events"
            )
        ).fetchall():
            if trig is not None and str(trig) in commercial_ids:
                rfq_hits.add(str(trig))
            if winners:
                try:
                    parsed = json.loads(winners)
                except (ValueError, TypeError):
                    parsed = []
                rfq_hits.update(str(w) for w in parsed if str(w) in commercial_ids)
        if rfq_hits:
            offenders["rfq_state_events"] = sorted(rfq_hits)
    if offenders:
        raise RuntimeError(
            "Refusing to migrate: hedge-domain references point at commercial "
            "(customer/supplier) counterparties. Correct these references before "
            f"migration (no silent FK breakage): {offenders}"
        )


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    # 0. Validate FIRST — HALT cleanly before any mutation.
    _validate_pre_move(bind)

    # 1. Add 'unscreened' to the existing hedge sanctions_status enum (PG only).
    #    ALTER TYPE ADD VALUE must commit before the value is used in this same
    #    migration's UPDATE, so run it in an autocommit block.
    if is_pg:
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE sanctions_status ADD VALUE IF NOT EXISTS 'unscreened'")

    # 2. Create the new tables (named enums auto-created on PG).
    op.create_table(
        "commercial_partners",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("kind", commercial_partner_kind, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("short_name", sa.String(length=50), nullable=True),
        sa.Column("tax_id", sa.String(length=50), nullable=True),
        sa.Column("country", sa.String(length=3), nullable=False),
        sa.Column("city", sa.String(length=100), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("contact_name", sa.String(length=200), nullable=True),
        sa.Column("contact_email", sa.String(length=200), nullable=True),
        sa.Column("contact_phone", sa.String(length=50), nullable=True),
        sa.Column("whatsapp_phone", sa.String(length=50), nullable=True),
        sa.Column("lei", sa.String(length=20), nullable=True),
        sa.Column(
            "lei_status",
            lei_status,
            nullable=False,
            server_default=sa.text("'not_provided'"),
        ),
        sa.Column("lei_legal_name", sa.String(length=200), nullable=True),
        sa.Column("lei_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "kyc_status",
            commercial_kyc_status,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "sanctions_status",
            commercial_sanctions_status,
            nullable=False,
            server_default=sa.text("'unscreened'"),
        ),
        sa.Column(
            "risk_rating",
            commercial_risk_rating,
            nullable=False,
            server_default=sa.text("'medium'"),
        ),
        sa.Column("credit_limit", sa.Numeric(18, 6), nullable=True),
        sa.Column("credit_currency", sa.String(length=3), nullable=True),
        sa.Column("payment_conditions", _json_type(), nullable=True),
        sa.Column("approved_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("approved_currency", sa.String(length=3), nullable=True),
        sa.Column("approved_terms", _json_type(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "kind <> 'supplier' OR ("
            "credit_limit IS NULL AND credit_currency IS NULL AND payment_conditions IS NULL)",
            name="ck_commercial_partners_supplier_no_customer_credit",
        ),
        sa.CheckConstraint(
            "kind <> 'customer' OR ("
            "approved_value IS NULL AND approved_currency IS NULL AND approved_terms IS NULL)",
            name="ck_commercial_partners_customer_no_supplier_terms",
        ),
    )
    op.create_index(
        "uq_commercial_partners_tax_id",
        "commercial_partners",
        ["tax_id"],
        unique=True,
        postgresql_where=sa.text("is_deleted = false"),
        sqlite_where=sa.text("is_deleted = 0"),
    )

    op.create_table(
        "sanctions_screenings",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("partner_type", sanctions_partner_type, nullable=False),
        sa.Column("partner_id", _uuid_type(), nullable=False),
        sa.Column("screened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("dataset_version", sa.String(length=64), nullable=True),
        sa.Column("query_hash", sa.String(length=128), nullable=False),
        sa.Column("top_score", sa.Numeric(6, 4), nullable=True),
        sa.Column("match_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("matches_json", _json_type(), nullable=True),
        sa.Column("result", screening_result, nullable=True),
        sa.Column("actor_sub", sa.String(length=200), nullable=False),
        sa.Column("status", screening_status, nullable=False),
        sa.Column("error_detail", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sanctions_screenings_partner",
        "sanctions_screenings",
        ["partner_type", "partner_id", "screened_at"],
    )

    op.create_table(
        "sanctions_adjudications",
        sa.Column("id", _uuid_type(), nullable=False),
        sa.Column("partner_type", sanctions_partner_type, nullable=False),
        sa.Column("partner_id", _uuid_type(), nullable=False),
        sa.Column("superseded_screening_id", _uuid_type(), nullable=False),
        sa.Column("decision", adjudication_decision, nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("adjudicating_actor_sub", sa.String(length=200), nullable=False),
        sa.Column("adjudicated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["superseded_screening_id"],
            ["sanctions_screenings.id"],
            name="fk_sanctions_adjudications_superseded_screening_id",
        ),
    )

    # 3. Copy customer/supplier rows (UUID reuse, kind-mapped credit, fail-closed reset).
    #    On PG, `type` (counterparty_type enum) and `risk_rating` (risk_rating enum) are
    #    DIFFERENT enum types from the target commercial_* enums, so cast via text.
    if is_pg:
        kind_expr = "type::text::commercial_partner_kind"
        rating_expr = "risk_rating::text::commercial_risk_rating"
        # legacy payment_terms_days -> kind-appropriate JSON terms column (no data loss).
        terms_obj = "jsonb_build_object('payment_terms_days', payment_terms_days)"
    else:
        kind_expr = "type"
        rating_expr = "risk_rating"
        terms_obj = "json_object('payment_terms_days', payment_terms_days)"
    op.execute(
        text(
            f"""
            INSERT INTO commercial_partners (
                id, kind, name, short_name, tax_id, country, city, address,
                contact_name, contact_email, contact_phone, whatsapp_phone,
                lei_status, kyc_status, sanctions_status, risk_rating,
                credit_limit, credit_currency, approved_value, approved_currency,
                payment_conditions, approved_terms,
                is_active, notes, created_at, updated_at, is_deleted, deleted_at
            )
            SELECT
                id, {kind_expr}, name, short_name, tax_id, country, city, address,
                contact_name, contact_email, contact_phone, whatsapp_phone,
                'not_provided', 'pending', 'unscreened', {rating_expr},
                CASE WHEN type = 'customer' THEN credit_limit_usd ELSE NULL END,
                CASE WHEN type = 'customer' AND credit_limit_usd IS NOT NULL THEN 'USD' ELSE NULL END,
                CASE WHEN type = 'supplier' THEN credit_limit_usd ELSE NULL END,
                CASE WHEN type = 'supplier' AND credit_limit_usd IS NOT NULL THEN 'USD' ELSE NULL END,
                CASE WHEN type = 'customer' AND payment_terms_days IS NOT NULL
                     THEN {terms_obj} ELSE NULL END,
                CASE WHEN type = 'supplier' AND payment_terms_days IS NOT NULL
                     THEN {terms_obj} ELSE NULL END,
                is_active, notes, created_at, updated_at, is_deleted, deleted_at
            FROM counterparties
            WHERE type IN ('customer', 'supplier')
            """
        )
    )

    # 4. Reset hedge counterparties to pending/unscreened (fail-closed, both domains).
    type_expr = _counterparty_type_expr(is_pg=is_pg)
    op.execute(
        text(
            "UPDATE counterparties SET kyc_status = 'pending', sanctions_status = 'unscreened' "
            f"WHERE {type_expr} IN ('broker','bank_br')"
        )
    )

    # 5. Repoint orders FK (PG only; on SQLite the original FK was created outside a
    #    batch and is not an enforced named constraint, and ids are preserved).
    if is_pg:
        op.drop_constraint("fk_orders_counterparty_id", "orders", type_="foreignkey")
        op.create_foreign_key(
            "fk_orders_counterparty_id",
            "orders",
            "commercial_partners",
            ["counterparty_id"],
            ["id"],
        )

    # 6. Restrict counterparties to hedge: remove migrated customer/supplier rows.
    op.execute(text("DELETE FROM counterparties WHERE type IN ('customer', 'supplier')"))


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        op.drop_constraint("fk_orders_counterparty_id", "orders", type_="foreignkey")
        op.create_foreign_key(
            "fk_orders_counterparty_id",
            "orders",
            "counterparties",
            ["counterparty_id"],
            ["id"],
        )

    op.drop_table("sanctions_adjudications")
    op.drop_index("ix_sanctions_screenings_partner", table_name="sanctions_screenings")
    op.drop_table("sanctions_screenings")
    op.drop_table("commercial_partners")

    if is_pg:
        adjudication_decision.drop(bind, checkfirst=True)
        screening_status.drop(bind, checkfirst=True)
        screening_result.drop(bind, checkfirst=True)
        sanctions_partner_type.drop(bind, checkfirst=True)
        lei_status.drop(bind, checkfirst=True)
        commercial_risk_rating.drop(bind, checkfirst=True)
        commercial_sanctions_status.drop(bind, checkfirst=True)
        commercial_kyc_status.drop(bind, checkfirst=True)
        commercial_partner_kind.drop(bind, checkfirst=True)
    # NOTE: the 'unscreened' value added to the hedge sanctions_status enum is NOT
    # removed — PostgreSQL cannot drop an enum value (mirrors migration 023's note).
    # Migrated customer/supplier counterparties rows are NOT re-created on downgrade;
    # downgrade is structural only.
