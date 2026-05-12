"""Revision ID: 015_phase7_audit_events_table
Revises: 014_phase5_step1_cashflow_ledger

Create audit_events table for append-only audit trail.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# Revision identifiers, used by Alembic
revision = "015_phase7_audit_events_table"
down_revision = "014_phase5_step1_cashflow_ledger"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("timestamp_utc", sa.TIMESTAMP(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("entity_type", sa.Text, nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.Text, nullable=False),
        sa.Column("payload", sa.JSON, nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.LargeBinary, nullable=True),
    )

    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(
            """
            CREATE TRIGGER audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(FAIL, 'audit_events is append-only');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(FAIL, 'audit_events is append-only');
            END;
            """
        )
    else:
        op.execute(
            """
            CREATE OR REPLACE FUNCTION audit_events_no_update_delete()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'audit_events is append-only';
            END;
            $$ LANGUAGE plpgsql;
            """
        )
        op.execute(
            """
            CREATE TRIGGER audit_events_no_update_delete
            BEFORE UPDATE OR DELETE ON audit_events
            FOR EACH ROW EXECUTE FUNCTION audit_events_no_update_delete();
            """
        )


def downgrade():
    # Append-only institutional invariant (J-A5-04):
    # audit_events captures evidence the regulator and the institution may
    # need to reconstruct historical state. A destructive downgrade — either
    # dropping the table or dropping the append-only enforcement triggers —
    # would silently erase or weaken that evidence. There is no operational
    # scenario in which losing audit history is acceptable, including a
    # rollback past this revision.
    #
    # Therefore this downgrade is intentionally a no-op:
    #
    #   * audit_events table is preserved with all rows intact;
    #   * append-only triggers (UPDATE/DELETE rejection) are preserved;
    #   * operators that need to roll back schema below this point must
    #     first export and archive audit_events out-of-band, then drop the
    #     table by hand. That deliberate, logged action is the only
    #     supported path.
    #
    # See docs/audits/2026-05-11-phase-a5-jury-verdict.md (J-A5-04) and the
    # backend/tests/test_audit_migration_non_destructive.py regression.
    pass