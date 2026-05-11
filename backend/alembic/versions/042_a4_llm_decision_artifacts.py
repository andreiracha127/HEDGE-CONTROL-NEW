"""Phase A4 PR 3: LLM decision artifacts.

Revision ID: 042_a4_llm_decision_artifacts
Revises: 041_a4_inbound_webhook_messages
Create Date: 2026-05-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "042_a4_llm_decision_artifacts"
down_revision = "041_a4_inbound_webhook_messages"
branch_labels = None
depends_on = None


def _uuid_type(dialect_name: str):
    if dialect_name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def _json_type(_dialect_name: str):
    return sa.JSON(none_as_null=True).with_variant(
        postgresql.JSONB(none_as_null=True),
        "postgresql",
    )


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    check_constraints = [
        sa.CheckConstraint(
            "final_decision IN ('allow_mutation', 'deny_no_mutation')",
            name="ck_llm_decision_artifacts_final_decision",
        ),
    ]
    if dialect_name == "postgresql":
        check_constraints.append(
            sa.CheckConstraint(
                "final_status IN ('auto_quote_created', 'counterparty_declined', "
                "'counterparty_question', 'needs_human_review', 'llm_unavailable', "
                "'hallucinated_price_blocked', 'duplicate_quote_skipped', "
                "'auto_quote_skipped_incomplete', "
                "'auto_quote_skipped_invalid_payload', 'auto_quote_failed')",
                name="ck_llm_decision_artifacts_final_status",
            )
        )

    op.create_table(
        "llm_decision_artifacts",
        sa.Column("id", _uuid_type(dialect_name), primary_key=True),
        sa.Column("inbound_message_id", _uuid_type(dialect_name), nullable=False),
        sa.Column("delivery_id", _uuid_type(dialect_name), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_message_id", sa.String(length=128), nullable=False),
        sa.Column("rfq_id", _uuid_type(dialect_name), nullable=True),
        sa.Column("quote_id", _uuid_type(dialect_name), nullable=True),
        sa.Column("counterparty_id", _uuid_type(dialect_name), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("llm_provider", sa.String(length=32), nullable=False),
        sa.Column("classification_model", sa.String(length=128), nullable=True),
        sa.Column("parse_model", sa.String(length=128), nullable=True),
        sa.Column("classification_prompt", _json_type(dialect_name), nullable=True),
        sa.Column("classification_raw_response", sa.Text(), nullable=True),
        sa.Column("classification_parsed", _json_type(dialect_name), nullable=True),
        sa.Column("classification_error", sa.Text(), nullable=True),
        sa.Column("parse_prompt", _json_type(dialect_name), nullable=True),
        sa.Column("parse_raw_response", sa.Text(), nullable=True),
        sa.Column("parse_parsed", _json_type(dialect_name), nullable=True),
        sa.Column("parse_error", sa.Text(), nullable=True),
        sa.Column("input_snapshot", _json_type(dialect_name), nullable=False),
        sa.Column("guard_outcomes", _json_type(dialect_name), nullable=False),
        sa.Column("final_decision", sa.String(length=32), nullable=False),
        sa.Column("final_status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["inbound_message_id"],
            ["inbound_webhook_messages.id"],
            name="fk_llm_decision_artifacts_inbound_message_id",
        ),
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["inbound_webhook_deliveries.id"],
            name="fk_llm_decision_artifacts_delivery_id",
        ),
        sa.ForeignKeyConstraint(
            ["rfq_id"],
            ["rfqs.id"],
            name="fk_llm_decision_artifacts_rfq_id",
        ),
        sa.ForeignKeyConstraint(
            ["quote_id"],
            ["rfq_quotes.id"],
            name="fk_llm_decision_artifacts_quote_id",
        ),
        sa.ForeignKeyConstraint(
            ["counterparty_id"],
            ["counterparties.id"],
            name="fk_llm_decision_artifacts_counterparty_id",
        ),
        sa.UniqueConstraint(
            "inbound_message_id",
            "attempt_number",
            name="uq_llm_decision_artifacts_inbound_message_attempt",
        ),
        *check_constraints,
    )
    op.create_index(
        "ix_llm_decision_artifacts_inbound_message_id",
        "llm_decision_artifacts",
        ["inbound_message_id"],
    )
    op.create_index(
        "ix_llm_decision_artifacts_delivery_id",
        "llm_decision_artifacts",
        ["delivery_id"],
    )
    op.create_index(
        "ix_llm_decision_artifacts_rfq_id",
        "llm_decision_artifacts",
        ["rfq_id"],
    )
    op.create_index(
        "ix_llm_decision_artifacts_quote_id",
        "llm_decision_artifacts",
        ["quote_id"],
    )
    op.create_index(
        "ix_llm_decision_artifacts_provider_message_id",
        "llm_decision_artifacts",
        ["provider", "provider_message_id"],
    )
    op.create_index(
        "ix_llm_decision_artifacts_final_status",
        "llm_decision_artifacts",
        ["final_status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_llm_decision_artifacts_final_status",
        table_name="llm_decision_artifacts",
    )
    op.drop_index(
        "ix_llm_decision_artifacts_provider_message_id",
        table_name="llm_decision_artifacts",
    )
    op.drop_index(
        "ix_llm_decision_artifacts_quote_id",
        table_name="llm_decision_artifacts",
    )
    op.drop_index(
        "ix_llm_decision_artifacts_rfq_id",
        table_name="llm_decision_artifacts",
    )
    op.drop_index(
        "ix_llm_decision_artifacts_delivery_id",
        table_name="llm_decision_artifacts",
    )
    op.drop_index(
        "ix_llm_decision_artifacts_inbound_message_id",
        table_name="llm_decision_artifacts",
    )
    op.drop_table("llm_decision_artifacts")
