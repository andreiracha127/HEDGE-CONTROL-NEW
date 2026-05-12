"""043_a5_audit_payload_input

Revision ID: 043_a5_audit_payload_input
Revises: 042_a4_llm_decision_artifacts
Create Date: 2026-05-11 00:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "043_a5_audit_payload_input"
down_revision = "042_a4_llm_decision_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent (Codex P2 on PR #61): the audit history preservation
    # policy (J-A5-04) means revision 015 may leave the audit_events
    # table — and any later columns added on top — present even after a
    # downgrade. A bare ADD COLUMN would fail on duplicate when the
    # operator then re-runs `alembic upgrade head`. Detect the column and
    # skip if it already exists.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("audit_events")}
    if "payload_canonical" not in columns:
        op.add_column(
            "audit_events",
            sa.Column("payload_canonical", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    # Append-only institutional invariant (J-A5-04, extended by Codex P2 on
    # PR #61): payload_canonical stores the canonical JSON payload that
    # AuditTrailService.verify_event() needs to recompute and validate the
    # HMAC checksum. Dropping the column on a full rollback would silently
    # destroy the verification evidence even though revision 015's
    # downgrade preserves the rows themselves — the rollback could land
    # the database with intact audit rows that are no longer verifiable.
    #
    # Mirroring the 015 policy, this downgrade is intentionally a no-op.
    # Operators that truly need to remove the column must do so by hand
    # AFTER archiving audit_events out-of-band; that deliberate, logged
    # action is the only supported path.
    #
    # See docs/audits/2026-05-11-phase-a5-jury-verdict.md (J-A5-04) and
    # the round-trip regression in
    # backend/tests/test_audit_migration_non_destructive.py.
    pass
