"""Add monotonic ``sequence`` column for DealPNLSnapshot ordering.

Codex P2 (PR #22 follow-up, 2026-05-06): the outage-fallback path in
``compute_deal_pnl`` previously ordered candidate snapshots by
``(created_at DESC, id DESC)``. Codex correctly identified that
``created_at`` is second-precision on SQLite (and tied across rows
written in the same second on Postgres under clock slew) and ``id`` is
a random UUID — neither is strictly monotonic, so the fallback could
return the stale pre-correction snapshot when two rows tied.

This migration introduces a strictly monotonic insertion counter:

* PostgreSQL — explicit ``CREATE SEQUENCE deal_pnl_snapshots_sequence_seq``
  bound to the column via SQLAlchemy ``Sequence(...)``. Existing rows are
  backfilled deterministically via ``ROW_NUMBER() OVER (ORDER BY
  created_at, id)``; the sequence's last value is then realigned to
  ``MAX(sequence)`` so future inserts continue cleanly.
* SQLite — no SEQUENCE objects exist; existing rows are backfilled via a
  correlated subquery that mirrors the same deterministic ordering
  (``created_at, id``). The ORM column ``default=`` (a Python counter on
  the model) populates new rows under SQLite's serialized writes.

The ORDER BY in the production query is then changed to
``sequence DESC`` only — no tiebreaker needed, sequence is monotonic by
construction in both dialects.

Revision ID: 031_pnl_snapshot_sequence
Revises: 030_pnl_provenance
Create Date: 2026-05-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "031_pnl_snapshot_sequence"
down_revision: Union[str, None] = "030_pnl_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_SEQUENCE_NAME = "deal_pnl_snapshots_sequence_seq"
_INDEX_NAME = "ix_deal_pnl_snapshots_sequence"


def upgrade() -> None:
    bind = op.get_bind()

    # Step 1 — add the column nullable to allow deterministic backfill of
    # existing rows before flipping it to NOT NULL.
    op.add_column(
        "deal_pnl_snapshots",
        sa.Column("sequence", sa.BigInteger(), nullable=True),
    )

    if bind.dialect.name == "postgresql":
        # Step 2 (PG) — create the SEQUENCE that will own future inserts.
        op.execute(f"CREATE SEQUENCE IF NOT EXISTS {_SEQUENCE_NAME}")

        # Step 3 (PG) — backfill existing rows in a deterministic order
        # (created_at, id). ROW_NUMBER() guarantees a strictly monotonic
        # assignment that mirrors the SQLite backfill below, so the two
        # dialects agree on which legacy row "wins" for a given
        # (deal_id, snapshot_date).
        op.execute(
            """
            UPDATE deal_pnl_snapshots t
            SET sequence = sub.rn
            FROM (
                SELECT id, ROW_NUMBER() OVER (ORDER BY created_at, id) AS rn
                FROM deal_pnl_snapshots
            ) sub
            WHERE t.id = sub.id
            """
        )

        # Step 4 (PG) — realign the sequence's last value to MAX(sequence)
        # so the next nextval() returns MAX+1. ``setval(name, X)`` sets
        # last_value to X and ``is_called`` to true, so the next call
        # returns X+1. COALESCE handles the empty-table case (no rows to
        # backfill → leave sequence at its default last_value of 0; next
        # call returns 1).
        op.execute(
            f"""
            SELECT setval(
                '{_SEQUENCE_NAME}',
                COALESCE((SELECT MAX(sequence) FROM deal_pnl_snapshots), 1),
                (SELECT MAX(sequence) IS NOT NULL FROM deal_pnl_snapshots)
            )
            """
        )
    else:
        # Step 2-4 (SQLite) — no SEQUENCE objects exist. Backfill via a
        # correlated subquery that produces the same deterministic
        # ordering as the PG ROW_NUMBER() call: rows are ranked by
        # ``created_at`` ascending, with ``id`` as the secondary sort.
        # The ``COUNT(*) ... <= deal_pnl_snapshots.id`` self-join expresses
        # row_number() in pure SQL.
        op.execute(
            """
            UPDATE deal_pnl_snapshots
            SET sequence = (
                SELECT COUNT(*) FROM deal_pnl_snapshots t2
                WHERE (t2.created_at < deal_pnl_snapshots.created_at)
                   OR (t2.created_at = deal_pnl_snapshots.created_at
                       AND t2.id <= deal_pnl_snapshots.id)
            )
            """
        )

    # Step 5 (both dialects) — flip to NOT NULL and add the index used by
    # the outage-fallback ORDER BY.
    op.alter_column("deal_pnl_snapshots", "sequence", nullable=False)
    op.create_index(
        _INDEX_NAME,
        "deal_pnl_snapshots",
        ["sequence"],
    )


def downgrade() -> None:
    op.drop_index(_INDEX_NAME, table_name="deal_pnl_snapshots")
    op.drop_column("deal_pnl_snapshots", "sequence")

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP SEQUENCE IF EXISTS {_SEQUENCE_NAME}")
