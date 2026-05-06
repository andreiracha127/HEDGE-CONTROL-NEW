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


# ---------------------------------------------------------------------------
# Per-entry shape assertion function (Postgres only).
#
# A bare CHECK on JSONB can only verify "non-empty object" — it cannot iterate
# and validate per-key structure. Codex P2 correctly identified that direct
# SQL writes (production repairs, imports, hot-fixes) bypass the ORM
# @validates and would have persisted malformed audit evidence like
# ``{"ALUMINUM": {"value": "2700"}}`` (missing source + settlement_date) or
# entries with numeric ``value`` instead of stringified Decimal.
#
# CHECK constraints CANNOT contain subqueries, but CAN call IMMUTABLE
# functions. We define ``_assert_price_references_shape(jsonb)`` once and
# reference it from the CHECK. ``STRICT`` makes NULL input return NULL —
# Postgres treats CHECKs returning NULL as satisfied, which preserves the
# documented "NULL price_references is legitimately valid" contract.
# ---------------------------------------------------------------------------
_ASSERT_FUNCTION_NAME = "_assert_price_references_shape"

_ASSERT_FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION {_ASSERT_FUNCTION_NAME}(payload jsonb)
RETURNS boolean
LANGUAGE plpgsql
IMMUTABLE
STRICT
AS $$
DECLARE
    commodity text;
    entry jsonb;
BEGIN
    -- STRICT means NULL input never reaches here, but keep an explicit
    -- guard so direct SELECT calls behave the same way.
    IF payload IS NULL THEN
        RETURN TRUE;
    END IF;
    IF jsonb_typeof(payload) <> 'object' THEN
        RETURN FALSE;
    END IF;
    -- Empty object is ambiguous with NULL — forbidden by dispatch §3.4.1.
    IF payload = '{{}}'::jsonb THEN
        RETURN FALSE;
    END IF;
    FOR commodity, entry IN SELECT * FROM jsonb_each(payload) LOOP
        IF jsonb_typeof(entry) <> 'object' THEN
            RETURN FALSE;
        END IF;
        IF NOT (entry ? 'value' AND entry ? 'source' AND entry ? 'settlement_date') THEN
            RETURN FALSE;
        END IF;
        IF jsonb_typeof(entry->'value') <> 'string' THEN
            RETURN FALSE;
        END IF;
        IF jsonb_typeof(entry->'source') <> 'string' THEN
            RETURN FALSE;
        END IF;
        IF jsonb_typeof(entry->'settlement_date') <> 'string' THEN
            RETURN FALSE;
        END IF;
        -- Codex P2 (2026-05-06, follow-up): settlement_date must be a
        -- real ISO calendar date. The original CHECK only verified the
        -- JSON type was string, so a direct-SQL repair/import could
        -- persist ``"settlement_date": "not-a-date"`` and bypass the
        -- ORM validator, violating the documented ISO-date provenance
        -- contract (dispatch §3.4.1).
        --
        -- Layer 1 — anchored ISO regex fast-path (cheap, rejects
        -- ``2026/05/05``, ``05-05-2026``, single-digit ``2026-5-5``).
        IF (entry->>'settlement_date') !~ '^\\d{{4}}-\\d{{2}}-\\d{{2}}$' THEN
            RETURN FALSE;
        END IF;
        -- Layer 2 — load-bearing calendar validity via ::date cast.
        -- The regex alone accepts ``2026-13-45`` (digits match but
        -- month/day are nonsense); the cast rejects impossible months
        -- (``2026-13-01``), impossible days (``2026-02-30``), and the
        -- zero-date (``0000-00-00``). Belt-and-suspenders.
        BEGIN
            PERFORM (entry->>'settlement_date')::date;
        EXCEPTION WHEN others THEN
            RETURN FALSE;
        END;
        -- Codex P2 (2026-05-06): the producer (compute_deal_pnl ->
        -- quantize_price -> str(Decimal)) only ever emits canonical
        -- fixed-point decimal strings. Reject anything a direct-SQL
        -- repair/import might smuggle in: scientific notation, NaN,
        -- Infinity, leading +, leading/trailing dots, whitespace, or
        -- arbitrary text. Anchored from start and end like the
        -- settlement_date regex above.
        IF (entry->>'value') !~ '^-?\\d+(\\.\\d+)?$' THEN
            RETURN FALSE;
        END IF;
    END LOOP;
    RETURN TRUE;
END;
$$;
"""

_DROP_ASSERT_FUNCTION_SQL = f"DROP FUNCTION IF EXISTS {_ASSERT_FUNCTION_NAME}(jsonb);"


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

    # Dialect-guarded CHECK: Postgres only. The predicate calls an
    # IMMUTABLE STRICT plpgsql function that iterates jsonb_each and
    # validates per-entry shape (Codex P2). SQLite test envs (used by
    # the project's conftest.py via Base.metadata.create_all()) get
    # shape enforcement from the ORM-level @validates("price_references")
    # on DealPNLSnapshot instead — keeping this CHECK off SQLite is
    # required because plpgsql functions don't exist there.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Function FIRST, then the CHECK that depends on it.
        op.execute(_ASSERT_FUNCTION_SQL)
        op.create_check_constraint(
            "chk_deal_pnl_snapshot_price_references_shape",
            "deal_pnl_snapshots",
            f"{_ASSERT_FUNCTION_NAME}(price_references)",
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # CHECK FIRST (depends on the function), then drop the function.
        op.drop_constraint(
            "chk_deal_pnl_snapshot_price_references_shape",
            "deal_pnl_snapshots",
        )
        op.execute(_DROP_ASSERT_FUNCTION_SQL)
    op.drop_column("deal_pnl_snapshots", "price_references")
