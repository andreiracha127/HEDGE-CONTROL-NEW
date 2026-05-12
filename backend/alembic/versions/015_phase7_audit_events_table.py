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
    # Idempotent (Codex P2 on PR #61): because downgrade() preserves
    # audit_events and its append-only triggers, an operator who runs
    # `alembic downgrade <pre-015>` followed by `alembic upgrade head`
    # arrives here with the table and triggers already present. A bare
    # CREATE TABLE / CREATE TRIGGER would fail on duplicate objects and
    # force the operator to drop exactly the history the downgrade was
    # trying to preserve. The branches below detect existing objects and
    # skip their creation so the upgrade path tolerates a preserved table.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "audit_events" not in inspector.get_table_names():
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

    dialect = bind.dialect.name
    if dialect == "sqlite":
        # CREATE TRIGGER IF NOT EXISTS is the idiomatic SQLite idempotent form.
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS audit_events_no_update
            BEFORE UPDATE ON audit_events
            BEGIN
                SELECT RAISE(FAIL, 'audit_events is append-only');
            END;
            """
        )
        op.execute(
            """
            CREATE TRIGGER IF NOT EXISTS audit_events_no_delete
            BEFORE DELETE ON audit_events
            BEGIN
                SELECT RAISE(FAIL, 'audit_events is append-only');
            END;
            """
        )
    else:
        # Postgres has no CREATE TRIGGER IF NOT EXISTS; CREATE OR REPLACE
        # FUNCTION is already idempotent, and a preceding DROP TRIGGER IF
        # EXISTS makes the trigger creation re-runnable without dropping
        # any rows (DROP TRIGGER does not touch table contents).
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
            "DROP TRIGGER IF EXISTS audit_events_no_update_delete ON audit_events"
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