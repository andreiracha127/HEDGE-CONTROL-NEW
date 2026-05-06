"""PR-8 (J-A1-01) — migration boundary for ``030_pnl_provenance``.

Asserts the institutional-safety properties from dispatch §3.4.3:
* ``price_references`` is added as a nullable column.
* Pre-existing ``deal_pnl_snapshots`` rows have their ``inputs_hash``
  byte-equal before and after the migration (NO backfill — backfilling
  from the deal's CURRENT ``deal_links`` would silently bind legacy
  snapshots to today's link set and serve stale P&L).
* Re-running ``compute_deal_pnl`` post-upgrade for a deal whose only
  snapshot is legacy (pre-PR-8 hash format) creates a NEW row alongside
  the legacy one — both persist as the forensic record.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import date
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "030_pnl_provenance.py"
    )
    spec = importlib.util.spec_from_file_location("pnl_provenance_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def _legacy_inputs_hash_format(
    deal_id: uuid.UUID, snapshot_date: date, link_ids: list[uuid.UUID]
) -> str:
    """Reproduce the pre-PR-8 hash format (no price_references key)."""
    import hashlib

    data = json.dumps(
        {
            "deal_id": str(deal_id),
            "snapshot_date": str(snapshot_date),
            "links": sorted(str(lid) for lid in link_ids),
        },
        sort_keys=True,
    )
    return hashlib.sha256(data.encode()).hexdigest()


def test_030_adds_nullable_price_references_and_preserves_inputs_hash() -> None:
    """Direct migration test on a synthetic SQLite schema.

    Builds only the ``deal_pnl_snapshots`` table at its pre-028 shape,
    inserts a legacy row, runs the migration, asserts:
    1. ``price_references`` column was added as nullable.
    2. The legacy row's ``inputs_hash`` is BYTE-EQUAL pre/post upgrade.
    3. The legacy row's ``price_references`` is NULL (no backfill).
    """
    engine = create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "deal_pnl_snapshots",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("deal_id", sa.String(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("physical_revenue", sa.Numeric(18, 6), nullable=True),
        sa.Column("physical_cost", sa.Numeric(18, 6), nullable=True),
        sa.Column("hedge_pnl_realized", sa.Numeric(18, 6), nullable=True),
        sa.Column("hedge_pnl_mtm", sa.Numeric(18, 6), nullable=True),
        sa.Column("total_pnl", sa.Numeric(18, 6), nullable=True),
        sa.Column("inputs_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    legacy_deal_id = uuid.uuid4()
    legacy_link_id = uuid.uuid4()
    legacy_hash = _legacy_inputs_hash_format(
        legacy_deal_id, date(2026, 1, 15), [legacy_link_id]
    )

    with engine.begin() as conn:
        metadata.create_all(conn)
        conn.execute(
            sa.text(
                "INSERT INTO deal_pnl_snapshots "
                "(id, deal_id, snapshot_date, total_pnl, inputs_hash, created_at) "
                "VALUES (:id, :did, :sd, :tp, :hash, CURRENT_TIMESTAMP)"
            ),
            {
                "id": str(uuid.uuid4()),
                "did": str(legacy_deal_id),
                "sd": "2026-01-15",
                "tp": 12345.678901,
                "hash": legacy_hash,
            },
        )

        # Capture pre-migration state.
        pre_rows = conn.execute(
            sa.text("SELECT id, inputs_hash FROM deal_pnl_snapshots")
        ).all()
        assert len(pre_rows) == 1
        pre_row_id, pre_hash = pre_rows[0]
        assert pre_hash == legacy_hash

        # Run upgrade.
        migration = _load_migration_module()
        context = MigrationContext.configure(conn)
        migration.op = Operations(context)
        migration.upgrade()

        # ── (1) column added, nullable ──
        cols = {
            col["name"]: col for col in inspect(conn).get_columns("deal_pnl_snapshots")
        }
        assert "price_references" in cols
        assert cols["price_references"]["nullable"] is True

        # ── (2) inputs_hash BYTE-EQUAL pre/post ──
        post = conn.execute(
            sa.text(
                "SELECT inputs_hash, price_references FROM deal_pnl_snapshots "
                "WHERE id = :id"
            ),
            {"id": pre_row_id},
        ).one()
        assert post.inputs_hash == pre_hash, (
            "PR-8 dispatch §3.4.3 violation: legacy inputs_hash was modified by "
            "the migration. Backfilling from current deal_links is institutionally "
            "unsafe and is forbidden."
        )

        # ── (3) legacy row's price_references is NULL (no backfill) ──
        assert post.price_references is None


def test_030_legacy_snapshot_unreachable_by_post_pr8_hash_lookup() -> None:
    """Re-running compute_deal_pnl for a deal whose only snapshot has the
    legacy hash format creates a NEW row; legacy is preserved.

    This uses the test-harness in-memory SQLite (driven by conftest's
    Base.metadata.create_all) so the model column already exists. We
    insert a legacy snapshot with a synthetic legacy-format hash, then
    invoke compute_deal_pnl and assert two rows exist.
    """
    from app.core.database import SessionLocal
    from app.models.contracts import (
        HedgeClassification,
        HedgeContract,
        HedgeContractStatus,
        HedgeLegSide,
    )
    from app.models.counterparty import Counterparty
    from app.models.deal import Deal, DealLink, DealLinkedType, DealPNLSnapshot
    from app.models.orders import Order, OrderType, PriceType
    from app.services.deal_engine import DealEngineService

    with SessionLocal() as session:
        # Build minimal deal with one fixed-price PO (no market price needed).
        deal = Deal(
            reference="D-LEGACY01",
            name="Legacy",
            commodity="ALUMINUM",
        )
        session.add(deal)
        session.commit()
        session.refresh(deal)

        po = Order(
            order_type=OrderType.purchase,
            price_type=PriceType.fixed,
            commodity="ALUMINUM",
            quantity_mt=100,
            avg_entry_price=2400,
        )
        session.add(po)
        session.commit()
        session.refresh(po)

        link = DealLink(
            deal_id=deal.id,
            linked_type=DealLinkedType.purchase_order,
            linked_id=po.id,
        )
        session.add(link)
        session.commit()
        session.refresh(link)

        # Insert a synthetic LEGACY snapshot with the OLD-format hash.
        legacy_hash = _legacy_inputs_hash_format(
            deal.id, date(2026, 2, 1), [link.id]
        )
        legacy = DealPNLSnapshot(
            deal_id=deal.id,
            snapshot_date=date(2026, 2, 1),
            physical_revenue=0,
            physical_cost=240000,
            hedge_pnl_realized=0,
            hedge_pnl_mtm=0,
            total_pnl=-240000,
            inputs_hash=legacy_hash,
            price_references=None,  # column exists but legacy never populated
        )
        session.add(legacy)
        session.commit()

        # Now run compute_deal_pnl — the post-PR-8 hash has the
        # additional ``price_references`` key (None for fixed-only),
        # producing a different SHA256 from the legacy_hash.
        new_snap = DealEngineService.compute_deal_pnl(
            session, deal.id, date(2026, 2, 1)
        )

        assert new_snap.inputs_hash != legacy_hash
        all_snaps = (
            session.query(DealPNLSnapshot)
            .filter(DealPNLSnapshot.deal_id == deal.id)
            .all()
        )
        assert len(all_snaps) == 2  # legacy preserved, new created
        legacy_post = (
            session.query(DealPNLSnapshot)
            .filter(DealPNLSnapshot.inputs_hash == legacy_hash)
            .one()
        )
        # Legacy row's hash unchanged.
        assert legacy_post.inputs_hash == legacy_hash
