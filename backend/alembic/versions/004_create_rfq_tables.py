"""Create RFQ tables

Revision ID: 004_create_rfq_tables
Revises: 003_create_hedge_order_linkages_table
Create Date: 2026-02-01 15:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004_create_rfq_tables"
down_revision: Union[str, None] = "003_create_hedge_order_linkages_table"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Postgres ENUM instances with create_type=False — we call .create() explicitly below
# and reuse the same instances in the Columns to avoid SQLAlchemy 2.0+ DuplicateObject
# (the implicit second CREATE TYPE during op.create_table).
rfq_intent_enum_pg = postgresql.ENUM(
    "COMMERCIAL_HEDGE", "GLOBAL_POSITION", name="rfq_intent", create_type=False
)
rfq_direction_enum_pg = postgresql.ENUM("BUY", "SELL", name="rfq_direction", create_type=False)
rfq_state_enum_pg = postgresql.ENUM(
    "CREATED", "SENT", "QUOTED", name="rfq_state", create_type=False
)
rfq_invitation_channel_enum_pg = postgresql.ENUM(
    "email",
    "api",
    "whatsapp",
    "bank",
    "broker",
    "other",
    name="rfq_invitation_channel",
    create_type=False,
)
rfq_invitation_status_enum_pg = postgresql.ENUM(
    "queued", "sent", "failed", name="rfq_invitation_status", create_type=False
)


def _enum_for(is_postgres: bool, pg_enum, members, name):
    """Return the column type: reuse the PG enum instance, or build a SQLite-friendly Enum.

    Migrations 001 and 002 use an inline if/else for this same dispatch because they
    each declare only two enums. This file declares five (rfq_intent, rfq_direction,
    rfq_state, rfq_invitation_channel, rfq_invitation_status), so the helper earns
    its keep — inline would cost ~20 lines of near-identical boilerplate. The
    cross-file pattern divergence is intentional, not an oversight.
    """
    if is_postgres:
        return pg_enum
    return sa.Enum(*members, name=name, native_enum=False, create_constraint=True)


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"
    if is_postgres:
        rfq_intent_enum_pg.create(bind, checkfirst=True)
        rfq_direction_enum_pg.create(bind, checkfirst=True)
        rfq_state_enum_pg.create(bind, checkfirst=True)
        rfq_invitation_channel_enum_pg.create(bind, checkfirst=True)
        rfq_invitation_status_enum_pg.create(bind, checkfirst=True)

    intent_t = _enum_for(
        is_postgres, rfq_intent_enum_pg, ["COMMERCIAL_HEDGE", "GLOBAL_POSITION"], "rfq_intent"
    )
    direction_t = _enum_for(is_postgres, rfq_direction_enum_pg, ["BUY", "SELL"], "rfq_direction")
    state_t = _enum_for(is_postgres, rfq_state_enum_pg, ["CREATED", "SENT", "QUOTED"], "rfq_state")
    channel_t = _enum_for(
        is_postgres,
        rfq_invitation_channel_enum_pg,
        ["email", "api", "whatsapp", "bank", "broker", "other"],
        "rfq_invitation_channel",
    )
    invite_status_t = _enum_for(
        is_postgres,
        rfq_invitation_status_enum_pg,
        ["queued", "sent", "failed"],
        "rfq_invitation_status",
    )

    op.create_table(
        "rfq_sequences",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
    )

    op.create_table(
        "rfqs",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("rfq_number", sa.String(length=32), nullable=False, unique=True),
        sa.Column("intent", intent_t, nullable=False),
        sa.Column("commodity", sa.String(length=64), nullable=False),
        sa.Column("quantity_mt", sa.Float(), nullable=False),
        sa.Column("delivery_window_start", sa.Date(), nullable=False),
        sa.Column("delivery_window_end", sa.Date(), nullable=False),
        sa.Column("direction", direction_t, nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=True),
        sa.Column("commercial_active_mt", sa.Float(), nullable=False),
        sa.Column("commercial_passive_mt", sa.Float(), nullable=False),
        sa.Column("commercial_net_mt", sa.Float(), nullable=False),
        sa.Column("commercial_reduction_applied_mt", sa.Float(), nullable=False),
        sa.Column("exposure_snapshot_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", state_t, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
    )

    op.create_table(
        "rfq_invitations",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("rfq_id", sa.Uuid(), nullable=False),
        sa.Column("rfq_number", sa.String(length=32), nullable=False),
        sa.Column("recipient_id", sa.String(length=64), nullable=False),
        sa.Column("recipient_name", sa.String(length=128), nullable=False),
        sa.Column("channel", channel_t, nullable=False),
        sa.Column("message_body", sa.Text(), nullable=False),
        sa.Column("provider_message_id", sa.String(length=128), nullable=False),
        sa.Column("send_status", invite_status_t, nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["rfq_id"], ["rfqs.id"], ondelete="RESTRICT"),
    )

    op.create_table(
        "rfq_state_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("rfq_id", sa.Uuid(), nullable=False),
        sa.Column("from_state", state_t, nullable=False),
        sa.Column("to_state", state_t, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["rfq_id"], ["rfqs.id"], ondelete="RESTRICT"),
    )


def downgrade() -> None:
    op.drop_table("rfq_state_events")
    op.drop_table("rfq_invitations")
    op.drop_table("rfqs")
    op.drop_table("rfq_sequences")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        rfq_invitation_status_enum_pg.drop(bind, checkfirst=True)
        rfq_invitation_channel_enum_pg.drop(bind, checkfirst=True)
        rfq_state_enum_pg.drop(bind, checkfirst=True)
        rfq_direction_enum_pg.drop(bind, checkfirst=True)
        rfq_intent_enum_pg.drop(bind, checkfirst=True)
