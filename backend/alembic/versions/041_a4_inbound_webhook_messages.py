"""Phase A4 PR 2: durable inbound webhook messages.

Revision ID: 041_a4_inbound_webhook_messages
Revises: 040_a4_inbound_webhook_delivery
Create Date: 2026-05-10 00:00:00.000000
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "041_a4_inbound_webhook_messages"
down_revision = "040_a4_inbound_webhook_delivery"
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

    constraints = [
        sa.ForeignKeyConstraint(
            ["delivery_id"],
            ["inbound_webhook_deliveries.id"],
            name="fk_inbound_webhook_messages_delivery_id",
        ),
        sa.UniqueConstraint(
            "provider",
            "provider_message_id",
            name="uq_inbound_webhook_messages_provider_message_id",
        ),
        sa.CheckConstraint(
            "provider IN ('meta', 'twilio')",
            name="ck_inbound_webhook_messages_provider",
        ),
        sa.CheckConstraint(
            "provider_message_id IS NOT NULL AND length(provider_message_id) > 0",
            name="ck_inbound_webhook_messages_provider_message_id_nonempty",
        ),
    ]
    # SQLite test enforcement for processing_status comes from the ORM
    # @validates guard; PostgreSQL gets the durable DB-level CHECK.
    if dialect_name == "postgresql":
        constraints.append(
            sa.CheckConstraint(
                "processing_status IN ('received', 'processing', 'processed', 'duplicate', 'failed')",
                name="ck_inbound_webhook_messages_processing_status",
            )
        )

    op.create_table(
        "inbound_webhook_messages",
        sa.Column("id", _uuid_type(dialect_name), primary_key=True),
        sa.Column("delivery_id", _uuid_type(dialect_name), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("provider_message_id", sa.String(length=128), nullable=False),
        sa.Column("sender_phone", sa.String(length=50), nullable=True),
        sa.Column("sender_name", sa.String(length=200), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("processing_status", sa.String(length=16), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processing_result", _json_type(dialect_name), nullable=True),
        sa.Column("rfq_number", sa.String(length=32), nullable=True),
        sa.Column("rfq_id", _uuid_type(dialect_name), nullable=True),
        sa.Column("quote_id", _uuid_type(dialect_name), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        *constraints,
    )
    op.create_index(
        "ix_inbound_webhook_messages_delivery_id",
        "inbound_webhook_messages",
        ["delivery_id"],
    )
    op.create_index(
        "ix_inbound_webhook_messages_processing_status",
        "inbound_webhook_messages",
        ["processing_status"],
    )
    op.create_index(
        "ix_inbound_webhook_messages_provider_message_id",
        "inbound_webhook_messages",
        ["provider_message_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_inbound_webhook_messages_provider_message_id",
        table_name="inbound_webhook_messages",
    )
    op.drop_index(
        "ix_inbound_webhook_messages_processing_status",
        table_name="inbound_webhook_messages",
    )
    op.drop_index(
        "ix_inbound_webhook_messages_delivery_id",
        table_name="inbound_webhook_messages",
    )
    op.drop_table("inbound_webhook_messages")
