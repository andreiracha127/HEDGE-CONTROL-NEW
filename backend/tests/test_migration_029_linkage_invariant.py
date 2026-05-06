"""Migration tests for the HedgeOrderLinkage over-allocation invariant.

Codex P2 (PR-4): the trigger from migration 029 only protects future writes
— it never scans existing aggregates. If production already contains an
over-allocated linkage from the very race this migration is fixing,
installing the trigger silently leaves the DB in a state that violates the
new invariant. The next ``reconcile`` call (or any UPDATE on a parent row)
would hard-fail at runtime.

The migration must therefore preflight: aggregate ALL linkages on both the
order side AND the contract side, and refuse to install the trigger if any
parent already has SUM(linkages.quantity_mt) > parent.quantity_mt. The
operator owns remediation — auto-UPDATE/DELETE of dirty linkages would
silently reshape production data, which §2.6 forbids.

This test is PG-only because ``upgrade()`` early-returns on SQLite
(no triggers, no preflight — no race possible without concurrent SQL).
"""

from __future__ import annotations

import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from app.core.database import engine as production_engine

_IS_POSTGRES = production_engine.dialect.name == "postgresql"


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "029_linkage_overallocation_invariant.py"
    )
    spec = importlib.util.spec_from_file_location(
        "linkage_overallocation_invariant_migration", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not _IS_POSTGRES,
    reason=(
        "Migration 029 preflight + trigger install runs only on PostgreSQL; "
        "SQLite path is a no-op (no triggers, no preflight)."
    ),
)
def test_preflight_refuses_when_existing_linkages_already_over_allocate() -> None:
    """Codex P2 — installing the trigger over dirty data must hard-fail.

    Insert dirty rows directly via raw SQL (bypassing both the service AND
    any future trigger) BEFORE invoking ``upgrade()``: an order with
    quantity_mt=10 plus two linkages summing to 12 → over-allocation = 2.
    The migration's preflight aggregate must raise RuntimeError naming the
    offending order_id so the operator can remediate without spelunking.
    """
    migration = _load_migration_module()

    order_id = uuid.uuid4()
    contract_id = uuid.uuid4()
    link_a_id = uuid.uuid4()
    link_b_id = uuid.uuid4()

    with production_engine.begin() as conn:
        # Drop the trigger first (if a previous test or upgrade already
        # installed it) so dirty rows can be inserted without the trigger
        # rejecting them — we want to exercise the PREFLIGHT path, not the
        # trigger path. Idempotent.
        conn.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS hedge_order_linkages_assert_capacity "
                "ON hedge_order_linkages"
            )
        )
        conn.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS hedge_contracts_qty_assert_capacity "
                "ON hedge_contracts"
            )
        )
        conn.execute(
            sa.text(
                "DROP TRIGGER IF EXISTS orders_qty_assert_capacity ON orders"
            )
        )

        # Seed parent rows: order qty=10, contract qty=10.
        conn.execute(
            sa.text(
                "INSERT INTO orders "
                "(id, order_type, price_type, commodity, quantity_mt, "
                "created_at) "
                "VALUES (:id, 'SO', 'variable', 'ALUMINUM', 10.000, "
                "CURRENT_TIMESTAMP)"
            ),
            {"id": str(order_id)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO hedge_contracts "
                "(id, commodity, quantity_mt, fixed_leg_side, "
                "variable_leg_side, classification, status, reference) "
                "VALUES (:id, 'ALUMINUM', 10.000, 'sell', 'buy', 'short', "
                "'active', :ref)"
            ),
            {"id": str(contract_id), "ref": f"HC-MIG028-{uuid.uuid4().hex[:6]}"},
        )
        # Dirty: 7 + 5 = 12 > 10 (over-allocation = 2).
        conn.execute(
            sa.text(
                "INSERT INTO hedge_order_linkages "
                "(id, order_id, contract_id, quantity_mt) "
                "VALUES (:id, :oid, :cid, 7.000)"
            ),
            {"id": str(link_a_id), "oid": str(order_id), "cid": str(contract_id)},
        )
        conn.execute(
            sa.text(
                "INSERT INTO hedge_order_linkages "
                "(id, order_id, contract_id, quantity_mt) "
                "VALUES (:id, :oid, :cid, 5.000)"
            ),
            {"id": str(link_b_id), "oid": str(order_id), "cid": str(contract_id)},
        )

    try:
        # Invoke upgrade() against a real bind. The Operations context lets
        # the migration's op.execute(...) calls reach the real engine.
        with production_engine.begin() as conn:
            context = MigrationContext.configure(conn)
            migration.op = Operations(context)
            with pytest.raises(RuntimeError) as exc_info:
                migration.upgrade()

        msg = str(exc_info.value)
        assert "refuses to install" in msg
        assert str(order_id) in msg
        # Contract is also over-allocated (same dirty linkages).
        assert str(contract_id) in msg
        assert "over_allocation=2" in msg

        # Cleanup: delete dirty rows, then re-run upgrade — must succeed
        # and install the triggers.
        with production_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "DELETE FROM hedge_order_linkages WHERE id IN (:a, :b)"
                ),
                {"a": str(link_a_id), "b": str(link_b_id)},
            )
            conn.execute(
                sa.text("DELETE FROM hedge_contracts WHERE id = :id"),
                {"id": str(contract_id)},
            )
            conn.execute(
                sa.text("DELETE FROM orders WHERE id = :id"),
                {"id": str(order_id)},
            )

        with production_engine.begin() as conn:
            context = MigrationContext.configure(conn)
            migration.op = Operations(context)
            # Should NOT raise — preflight is clean.
            migration.upgrade()

        # Trigger was installed.
        with production_engine.connect() as conn:
            installed = conn.execute(
                sa.text(
                    "SELECT 1 FROM pg_trigger "
                    "WHERE tgname = 'hedge_order_linkages_assert_capacity'"
                )
            ).scalar()
            assert installed == 1
    finally:
        # Best-effort cleanup so the test is rerunnable.
        with production_engine.begin() as conn:
            conn.execute(
                sa.text(
                    "DELETE FROM hedge_order_linkages WHERE id IN (:a, :b)"
                ),
                {"a": str(link_a_id), "b": str(link_b_id)},
            )
            conn.execute(
                sa.text("DELETE FROM hedge_contracts WHERE id = :id"),
                {"id": str(contract_id)},
            )
            conn.execute(
                sa.text("DELETE FROM orders WHERE id = :id"),
                {"id": str(order_id)},
            )


def test_preflight_sql_aggregates_match_invariant_on_sqlite() -> None:
    """Portable-SQL smoke test for the preflight SELECT shape.

    The actual ``upgrade()`` early-returns on SQLite, so we can't exercise
    the preflight path end-to-end there. But the two SELECT statements are
    plain ANSI SQL (GROUP BY ... HAVING SUM(...) > parent.quantity_mt) and
    must correctly identify over-allocated parents on any dialect — that
    way we get coverage of the SELECT shape without a live PG instance.
    """
    migration = _load_migration_module()

    sqlite_engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "orders",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("quantity_mt", sa.Numeric(18, 3), nullable=False),
    )
    sa.Table(
        "hedge_contracts",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("quantity_mt", sa.Numeric(18, 3), nullable=False),
    )
    sa.Table(
        "hedge_order_linkages",
        metadata,
        sa.Column("id", sa.String, primary_key=True),
        sa.Column("order_id", sa.String, nullable=False),
        sa.Column("contract_id", sa.String, nullable=False),
        sa.Column("quantity_mt", sa.Numeric(18, 3), nullable=False),
    )
    metadata.create_all(sqlite_engine)

    over_id = "order-over"
    ok_id = "order-ok"
    contract_id = "contract-1"

    with sqlite_engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO orders (id, quantity_mt) VALUES "
                "(:o1, 10.000), (:o2, 10.000)"
            ),
            {"o1": over_id, "o2": ok_id},
        )
        conn.execute(
            sa.text(
                "INSERT INTO hedge_contracts (id, quantity_mt) VALUES "
                "(:c, 100.000)"
            ),
            {"c": contract_id},
        )
        # Over-allocated: 7 + 5 = 12 > 10.
        conn.execute(
            sa.text(
                "INSERT INTO hedge_order_linkages "
                "(id, order_id, contract_id, quantity_mt) "
                "VALUES ('l1', :o, :c, 7.000), ('l2', :o, :c, 5.000)"
            ),
            {"o": over_id, "c": contract_id},
        )
        # Clean: 4 ≤ 10.
        conn.execute(
            sa.text(
                "INSERT INTO hedge_order_linkages "
                "(id, order_id, contract_id, quantity_mt) "
                "VALUES ('l3', :o, :c, 4.000)"
            ),
            {"o": ok_id, "c": contract_id},
        )

    with sqlite_engine.connect() as conn:
        order_violations = conn.execute(
            sa.text(migration._PREFLIGHT_ORDERS_SQL)
        ).fetchall()
        contract_violations = conn.execute(
            sa.text(migration._PREFLIGHT_CONTRACTS_SQL)
        ).fetchall()

    assert len(order_violations) == 1
    assert order_violations[0].order_id == over_id
    assert Decimal(str(order_violations[0].linked_qty)) == Decimal("12.000")
    assert Decimal(str(order_violations[0].order_qty)) == Decimal("10.000")
    # Contract qty=100, total linked=16 → no contract-side violation.
    assert contract_violations == []
