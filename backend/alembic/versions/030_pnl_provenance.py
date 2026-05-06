"""P&L price provenance — DealPNLSnapshot.price_references.

Adds a single nullable JSONB column ``price_references`` to
``deal_pnl_snapshots`` plus a dialect-guarded CHECK that rejects empty
objects on PostgreSQL. The CHECK uses ``jsonb_typeof`` and the
``::jsonb`` cast which are Postgres-specific; SQLite test envs (used by
the project's conftest.py via ``Base.metadata.create_all()``) get
shape enforcement from the ORM-level ``@validates("price_references")``
on :class:`DealPNLSnapshot` instead.

Population semantics
====================
* ``price_references`` is nullable by design.
  * NULL means no market price was consulted (fixed-price-only deal,
    no active hedges) — the honest representation per dispatch §3.4.1.
  * Non-NULL is a dict keyed by commodity, each value a dict with
    ``value`` / ``source`` / ``settlement_date`` keys (Decimal-as-str,
    ISO-date-as-str). One entry per UNIQUE commodity actually
    consumed (deduped — multiple legs of the same commodity → one
    entry).
* No backfill. Pre-existing ``deal_pnl_snapshots`` rows naturally land
  with ``price_references = NULL`` because the column is added
  nullable and no UPDATE is issued.
* ``inputs_hash`` is intentionally NOT modified by this migration.
  The new ``_compute_inputs_hash`` includes ``price_references`` and
  therefore produces a different hash; legacy hashes are sealed
  historical artifacts. Backfilling them from the deal's CURRENT
  ``deal_links`` would silently bind legacy snapshots to today's
  link set and serve stale P&L on subsequent compute_deal_pnl calls
  (per dispatch §3.4.3 — institutionally unsafe, rejected).

Idempotency contract (post-PR-8 only)
=====================================
Re-running ``compute_deal_pnl`` for a deal that has only legacy
(pre-PR-8) snapshot(s) will create a NEW row with the post-PR-8
hash; legacy rows persist alongside as the forensic record.

Revision ID: 030_pnl_provenance
Revises: 029_linkage_overallocation_invariant
Create Date: 2026-05-06 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "030_pnl_provenance"
down_revision: Union[str, None] = "029_linkage_overallocation_invariant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Portable JSON column type — JSONB on Postgres (efficient,
    # indexable, supports GIN), generic JSON on SQLite (TEXT-backed).
    # Same with-variant pattern used by the model column type so DDL
    # emitted by Alembic matches the runtime ORM type.
    portable_json = sa.JSON().with_variant(
        postgresql.JSONB(astext_type=sa.Text()),
        "postgresql",
    )
    op.add_column(
        "deal_pnl_snapshots",
        sa.Column("price_references", portable_json, nullable=True),
    )

    # Dialect-guarded CHECK: Postgres only. The predicate uses
    # jsonb_typeof(...) and ::jsonb literal cast which SQLite does not
    # support; an unguarded CHECK in __table_args__ would break
    # Base.metadata.create_all() in the test conftest. Portable shape
    # enforcement is provided by the ORM-level @validates on the
    # model — runs in BOTH SQLite (tests) and Postgres (prod). This
    # CHECK is the production belt-and-suspenders that catches
    # malformed direct-SQL writes.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "chk_deal_pnl_snapshot_price_references_shape",
            "deal_pnl_snapshots",
            "price_references IS NULL"
            " OR (jsonb_typeof(price_references) = 'object'"
            "     AND price_references <> '{}'::jsonb)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.drop_constraint(
            "chk_deal_pnl_snapshot_price_references_shape",
            "deal_pnl_snapshots",
        )
    op.drop_column("deal_pnl_snapshots", "price_references")
