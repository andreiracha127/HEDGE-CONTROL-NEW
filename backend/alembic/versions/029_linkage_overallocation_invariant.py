"""Enforce HedgeOrderLinkage no-over-allocation invariant.

Revision ID: 029_linkage_overallocation_invariant
Revises: 028_reconciliation_run
Create Date: 2026-05-06 00:00:00.000000

Layer 2 of the PR-4 linkage hardening defense (J-A1-03). Installs a single
SQL helper plus three triggers on PostgreSQL that re-aggregate linkages and
reject any operation which would push SUM(linkages.quantity_mt) above the
constraining quantity on either side:

1. ``hedge_order_linkages`` INSERT/UPDATE — adding or expanding a linkage
2. ``hedge_contracts`` UPDATE OF quantity_mt — lowering contract qty below
   SUM(linkages)
3. ``orders`` UPDATE OF quantity_mt — lowering order qty below SUM(linkages)

DELETE of ``orders`` / ``hedge_contracts`` while linkages exist is already
blocked by FK ``ondelete=RESTRICT`` on ``hedge_order_linkages`` (see
``models/linkages.py``).

SQLite has no equivalent trigger semantics for cross-row aggregate checks
in CHECK constraints (subqueries are forbidden); the application-layer
defense in ``LinkageService.create`` and ``ContractService.update`` covers
the test path. Production runs PostgreSQL where the institutional guarantee
applies.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "029_linkage_overallocation_invariant"
down_revision: Union[str, None] = "028_reconciliation_run"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FUNCTION_SQL = """
-- Locks parent rows (orders, hedge_contracts) BEFORE aggregating linkages so
-- the SUM(quantity_mt) snapshot is consistent against ALL concurrent writers,
-- not just service callers. This is the load-bearing institutional invariant:
-- two concurrent transactions cannot each pass the capacity check against a
-- snapshot that omits the other's uncommitted linkage row, because the second
-- transaction blocks on the parent-row lock until the first commits/rolls
-- back. The aggregate is then re-read with the new linkage visible. Service
-- callers already hold these row locks via with_for_update(); direct-SQL
-- paths (admin/import) acquire them here so the DB invariant holds for ANY
-- writer, not just LinkageService.
CREATE OR REPLACE FUNCTION assert_no_linkage_over_allocation(
    p_order_id uuid,
    p_contract_id uuid
) RETURNS void AS $$
DECLARE
    v_order_qty numeric;
    v_contract_qty numeric;
    v_order_linked numeric;
    v_contract_linked numeric;
BEGIN
    IF p_order_id IS NOT NULL THEN
        -- Serialize concurrent writers against the same parent order row
        -- BEFORE reading the aggregate. Held until commit/rollback.
        PERFORM 1 FROM orders WHERE id = p_order_id FOR UPDATE;
        SELECT quantity_mt INTO v_order_qty
        FROM orders WHERE id = p_order_id;
        IF v_order_qty IS NOT NULL THEN
            SELECT COALESCE(SUM(quantity_mt), 0) INTO v_order_linked
            FROM hedge_order_linkages WHERE order_id = p_order_id;
            IF v_order_linked > v_order_qty THEN
                RAISE EXCEPTION
                    'Linkage over-allocation: order % linked=% exceeds qty=%',
                    p_order_id, v_order_linked, v_order_qty
                USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    END IF;

    IF p_contract_id IS NOT NULL THEN
        -- Serialize concurrent writers against the same parent contract row
        -- BEFORE reading the aggregate. Held until commit/rollback.
        PERFORM 1 FROM hedge_contracts WHERE id = p_contract_id FOR UPDATE;
        SELECT quantity_mt INTO v_contract_qty
        FROM hedge_contracts WHERE id = p_contract_id;
        IF v_contract_qty IS NOT NULL THEN
            SELECT COALESCE(SUM(quantity_mt), 0) INTO v_contract_linked
            FROM hedge_order_linkages WHERE contract_id = p_contract_id;
            IF v_contract_linked > v_contract_qty THEN
                RAISE EXCEPTION
                    'Linkage over-allocation: contract % linked=% exceeds qty=%',
                    p_contract_id, v_contract_linked, v_contract_qty
                USING ERRCODE = 'check_violation';
            END IF;
        END IF;
    END IF;
END;
$$ LANGUAGE plpgsql;
"""

_LINKAGE_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION trg_linkage_assert_capacity()
RETURNS trigger AS $$
BEGIN
    PERFORM assert_no_linkage_over_allocation(NEW.order_id, NEW.contract_id);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_CONTRACT_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION trg_contract_qty_assert_capacity()
RETURNS trigger AS $$
BEGIN
    IF NEW.quantity_mt IS DISTINCT FROM OLD.quantity_mt THEN
        PERFORM assert_no_linkage_over_allocation(NULL, NEW.id);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_ORDER_TRIGGER_FN = """
CREATE OR REPLACE FUNCTION trg_order_qty_assert_capacity()
RETURNS trigger AS $$
BEGIN
    IF NEW.quantity_mt IS DISTINCT FROM OLD.quantity_mt THEN
        PERFORM assert_no_linkage_over_allocation(NEW.id, NULL);
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""

_LINKAGE_TRIGGER = """
CREATE CONSTRAINT TRIGGER hedge_order_linkages_assert_capacity
AFTER INSERT OR UPDATE ON hedge_order_linkages
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION trg_linkage_assert_capacity();
"""

_CONTRACT_TRIGGER = """
CREATE CONSTRAINT TRIGGER hedge_contracts_qty_assert_capacity
AFTER UPDATE OF quantity_mt ON hedge_contracts
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION trg_contract_qty_assert_capacity();
"""

_ORDER_TRIGGER = """
CREATE CONSTRAINT TRIGGER orders_qty_assert_capacity
AFTER UPDATE OF quantity_mt ON orders
DEFERRABLE INITIALLY IMMEDIATE
FOR EACH ROW EXECUTE FUNCTION trg_order_qty_assert_capacity();
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite / other engines: rely on application-layer defense in
        # LinkageService.create + ContractService.update. Skip silently.
        return

    op.execute(_FUNCTION_SQL)
    op.execute(_LINKAGE_TRIGGER_FN)
    op.execute(_CONTRACT_TRIGGER_FN)
    op.execute(_ORDER_TRIGGER_FN)
    op.execute(_LINKAGE_TRIGGER)
    op.execute(_CONTRACT_TRIGGER)
    op.execute(_ORDER_TRIGGER)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(
        "DROP TRIGGER IF EXISTS orders_qty_assert_capacity ON orders;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS hedge_contracts_qty_assert_capacity "
        "ON hedge_contracts;"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS hedge_order_linkages_assert_capacity "
        "ON hedge_order_linkages;"
    )
    op.execute("DROP FUNCTION IF EXISTS trg_order_qty_assert_capacity();")
    op.execute("DROP FUNCTION IF EXISTS trg_contract_qty_assert_capacity();")
    op.execute("DROP FUNCTION IF EXISTS trg_linkage_assert_capacity();")
    op.execute(
        "DROP FUNCTION IF EXISTS assert_no_linkage_over_allocation("
        "uuid, uuid);"
    )
