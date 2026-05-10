"""Phase A4 PR 1: inbound webhook delivery evidence.

Revision ID: 040_a4_inbound_webhook_delivery
Revises: 039_a3_cashflow_baseline_archive
Create Date: 2026-05-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "040_a4_inbound_webhook_delivery"
down_revision = "039_a3_cashflow_baseline_archive"
branch_labels = None
depends_on = None


def _uuid_type(dialect_name: str):
    if dialect_name == "postgresql":
        return postgresql.UUID(as_uuid=True)
    return sa.String(length=36)


def _json_type(dialect_name: str):
    if dialect_name == "postgresql":
        return postgresql.JSONB(none_as_null=True)
    return sa.JSON(none_as_null=True)


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    op.create_table(
        "inbound_webhook_deliveries",
        sa.Column("id", _uuid_type(dialect_name), primary_key=True),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_message_id", sa.String(length=128), nullable=True),
        sa.Column("sender_phone", sa.String(length=50), nullable=True),
        sa.Column("raw_body", sa.Text(), nullable=True),
        sa.Column("raw_form", _json_type(dialect_name), nullable=True),
        sa.Column("headers", _json_type(dialect_name), nullable=False),
        sa.Column("signature_base_url", sa.Text(), nullable=True),
        sa.Column("signature_present", sa.Boolean(), nullable=False),
        sa.Column("signature_verified", sa.Boolean(), nullable=False),
        sa.Column("signature_status", sa.String(length=16), nullable=False),
        sa.Column("parse_status", sa.String(length=16), nullable=False),
        sa.Column("messages_extracted", sa.Integer(), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider IN ('meta', 'twilio')",
            name="ck_inbound_webhook_deliveries_provider",
        ),
        sa.CheckConstraint(
            "signature_status IN ('missing', 'verified', 'invalid', 'bypassed')",
            name="ck_inbound_webhook_deliveries_signature_status",
        ),
        sa.CheckConstraint(
            "parse_status IN ('received', 'parsed', 'parse_failed')",
            name="ck_inbound_webhook_deliveries_parse_status",
        ),
        sa.CheckConstraint(
            "((provider = 'meta' AND raw_body IS NOT NULL AND raw_form IS NULL) "
            "OR (provider = 'twilio' AND raw_body IS NULL AND raw_form IS NOT NULL))",
            name="ck_inbound_webhook_deliveries_provider_raw_capture",
        ),
        sa.CheckConstraint(
            "((provider = 'meta' AND signature_base_url IS NULL) "
            "OR (provider = 'twilio' AND signature_base_url IS NOT NULL))",
            name="ck_inbound_webhook_deliveries_signature_base_url",
        ),
        sa.CheckConstraint(
            "((parse_status IN ('received', 'parse_failed') AND messages_extracted IS NULL) "
            "OR (parse_status = 'parsed' AND messages_extracted IS NOT NULL))",
            name="ck_inbound_webhook_deliveries_message_count",
        ),
    )
    op.create_index(
        "ix_inbound_webhook_deliveries_provider_message_id",
        "inbound_webhook_deliveries",
        ["provider_message_id"],
    )
    op.create_index(
        "ix_inbound_webhook_deliveries_received_at",
        "inbound_webhook_deliveries",
        ["received_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inbound_webhook_deliveries_received_at",
        table_name="inbound_webhook_deliveries",
    )
    op.drop_index(
        "ix_inbound_webhook_deliveries_provider_message_id",
        table_name="inbound_webhook_deliveries",
    )
    op.drop_table("inbound_webhook_deliveries")
