"""Phase A2 PR-4: outbound evidence + canonical id schema.

Revision ID: 037_rfq_outbound_evidence
Revises: 036_merge_w1_heads
Create Date: 2026-05-09 00:00:00.000000

Closes Phase A2 jury findings J-A2-05, J-A2-07, J-A2-08, J-A2-OPUS-02.

- ``rfq_invitations.sent_at`` and ``rfq_invitations.provider_message_id``
  relax to NULL so the durable-outbox flow (queued row before WhatsApp
  send) can be implemented (J-A2-07).
- ``rfq_invitations.purpose`` enum is added so a single evidence table
  hosts every RFQ outbound (initial invite, refresh, reject_quote,
  award_notify, reject_notify) per J-A2-OPUS-02.
- ``rfq_invitations.failure_reason`` records WhatsApp failure detail.
- ``rfq_quotes.state`` (active|rejected) plus ``rejected_at`` /
  ``rejected_reason`` / ``rejected_by`` replace the previous hard-delete
  on quote rejection so economic evidence is preserved (J-A2-08).

The downgrade is destructive: ``purpose`` / ``failure_reason`` /
``state`` / ``rejected_*`` data is dropped, and the legitimate NULL
values introduced in ``rfq_invitations.sent_at`` /
``provider_message_id`` are backfilled before the NOT NULL constraint
is re-imposed (mirrors the 035 precedent for event_timestamp). The
backfill is consistent with the one-way nature of this rollback.
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "037_rfq_outbound_evidence"
down_revision = "036_merge_w1_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # ── rfq_invitations: relax NOT NULLs first (low risk, no enum work needed)
    op.alter_column(
        "rfq_invitations",
        "sent_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.alter_column(
        "rfq_invitations",
        "provider_message_id",
        existing_type=sa.String(length=128),
        nullable=True,
    )

    # CRITICAL: create the PostgreSQL enum type BEFORE op.add_column
    # references it. Pattern mirrors
    # backend/alembic/versions/017_add_rfq_channel_type_to_counterparty.py:17-18.
    # Skipping this step causes Postgres ALTER TABLE ... ADD COLUMN ... <enum>
    # to fail because the type does not yet exist. checkfirst=True keeps the
    # operation idempotent across re-runs.
    rfq_invitation_purpose = sa.Enum(
        "rfq_invite",
        "refresh",
        "reject_quote",
        "award_notify",
        "reject_notify",
        name="rfq_invitation_purpose",
    )
    rfq_invitation_purpose.create(bind, checkfirst=True)
    op.add_column(
        "rfq_invitations",
        sa.Column(
            "purpose",
            rfq_invitation_purpose,
            nullable=False,
            server_default="rfq_invite",
        ),
    )
    op.add_column(
        "rfq_invitations",
        sa.Column("failure_reason", sa.String(length=256), nullable=True),
    )

    # ── rfq_quotes: state enum + rejection metadata ─────────────────────
    rfq_quote_state = sa.Enum("active", "rejected", name="rfq_quote_state")
    rfq_quote_state.create(bind, checkfirst=True)
    op.add_column(
        "rfq_quotes",
        sa.Column(
            "state",
            rfq_quote_state,
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "rfq_quotes",
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "rfq_quotes",
        sa.Column("rejected_reason", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "rfq_quotes",
        sa.Column("rejected_by", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Drop columns first; only then drop the enum types (otherwise Postgres
    # errors with "cannot drop type ... because other objects depend on it").
    # Mirror 017's drop pattern: sa.Enum(name=...).drop(op.get_bind(), checkfirst=True).
    op.drop_column("rfq_quotes", "rejected_by")
    op.drop_column("rfq_quotes", "rejected_reason")
    op.drop_column("rfq_quotes", "rejected_at")
    op.drop_column("rfq_quotes", "state")
    sa.Enum(name="rfq_quote_state").drop(bind, checkfirst=True)

    op.drop_column("rfq_invitations", "failure_reason")
    op.drop_column("rfq_invitations", "purpose")
    sa.Enum(name="rfq_invitation_purpose").drop(bind, checkfirst=True)

    # Backfill NULL outbox-shape rows BEFORE reasserting NOT NULL.
    # Post-PR-4, queued/failed rows can legitimately have
    # provider_message_id=NULL and sent_at=NULL; ALTER COLUMN ... SET NOT NULL
    # would fail on Postgres with those rows present. Pattern mirrors 035
    # precedent (event_timestamp backfilled from created_at before NOT NULL
    # re-imposed).
    #
    # Downgrade is already destructive (purpose + failure_reason + state +
    # rejected_* data are dropped above), so backfilling sent_at from
    # created_at and provider_message_id from "" is consistent with the
    # one-way nature of this rollback. Operators must accept evidence loss
    # if they choose to downgrade post-deployment.
    op.execute(
        """
        UPDATE rfq_invitations
           SET provider_message_id = ''
         WHERE provider_message_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE rfq_invitations
           SET sent_at = created_at
         WHERE sent_at IS NULL
        """
    )
    op.alter_column(
        "rfq_invitations",
        "provider_message_id",
        existing_type=sa.String(length=128),
        nullable=False,
        server_default="",
    )
    op.alter_column(
        "rfq_invitations",
        "sent_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
