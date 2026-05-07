"""Align linkage over-allocation invariant with live-side lifecycle filter.

Revision ID: 032_linkage_capacity_live_filter
Revises: 031_pnl_snapshot_sequence
Create Date: 2026-05-07 00:00:00.000000

PR-5 codex P1 follow-up to J-A1-OPUS-02. Migration 029 installed
``assert_no_linkage_over_allocation`` to enforce the no-over-allocation
invariant at the DB layer. After PR-5, the read path (snapshots,
reconcile, net exposure, capacity sums in ``LinkageService.create``)
ignores linkages whose **other-side parent** is dead — a soft-deleted
order or a settled / cancelled / soft-deleted hedge contract. The 029
trigger still summed every historical linkage, so the writer would
pass the (live-filtered) Python check and then fail at ``flush()``
with a raw 500 from the trigger instead of the intended 400.

Replace the trigger function so its ``SUM(quantity_mt)`` aggregate
applies the same live-side filter:

  * ``v_order_linked`` counts linkages whose **hedge contract** is live
    (deleted_at IS NULL AND status IN ('active', 'partially_settled'))
  * ``v_contract_linked`` counts linkages whose **source order** is live
    (Order.deleted_at IS NULL)

Mirror of PR-5 §3.5 / §3.9 read-side dual-filter on the DB invariant
side. Service and trigger now agree byte-for-byte on "which linkages
count toward capacity".

Notes:
- ``CREATE OR REPLACE FUNCTION`` on the existing function name is
  enough — triggers reference the function by name, no trigger
  recreation needed.
- Downgrade restores the 029 form (sum every historical linkage).
- SQLite has no triggers (per 029); upgrade/downgrade are no-ops there.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "032_linkage_capacity_live_filter"
down_revision: Union[str, None] = "031_pnl_snapshot_sequence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FUNCTION_LIVE_FILTER_SQL = """
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
            -- PR-5 codex P1: count only linkages whose HEDGE side is live.
            -- A linkage to a settled / cancelled / soft-deleted hedge is
            -- invisible to every read path (§3.4 / §3.5 / §3.9 / §3.10),
            -- so its quantity is logically free; the writer must agree.
            SELECT COALESCE(SUM(l.quantity_mt), 0) INTO v_order_linked
            FROM hedge_order_linkages l
            JOIN hedge_contracts c ON c.id = l.contract_id
            WHERE l.order_id = p_order_id
              AND c.deleted_at IS NULL
              AND c.status IN ('active', 'partially_settled');
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
            -- PR-5 codex P1: count only linkages whose ORDER side is live.
            SELECT COALESCE(SUM(l.quantity_mt), 0) INTO v_contract_linked
            FROM hedge_order_linkages l
            JOIN orders o ON o.id = l.order_id
            WHERE l.contract_id = p_contract_id
              AND o.deleted_at IS NULL;
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


_FUNCTION_LEGACY_SQL = """
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


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite has no triggers (per 029); the application-layer defense
        # in LinkageService.create covers the test path.
        return
    op.execute(_FUNCTION_LIVE_FILTER_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(_FUNCTION_LEGACY_SQL)
