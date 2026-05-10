from __future__ import annotations

import importlib.util
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "039_a3_cashflow_baseline_archive.py"
)

LEGACY_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
BASELINE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
ACTIVE_ID = uuid.UUID("00000000-0000-0000-0000-000000000003")


def _pre_039_table(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "cashflow_baseline_snapshots",
        metadata,
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("as_of_date", sa.Date(), nullable=False),
        sa.Column("snapshot_data", sa.JSON(), nullable=False),
        sa.Column("total_net_cashflow", sa.Numeric(18, 6), nullable=False),
        sa.Column("inputs_hash", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "as_of_date", name="uq_cashflow_baseline_snapshots_as_of_date"
        ),
    )


def _load_migration():
    spec = importlib.util.spec_from_file_location("migration_039", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def _run_migration(connection: sa.Connection, direction: str) -> None:
    migration = _load_migration()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def _create_pre_039_schema(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    _pre_039_table(metadata)
    metadata.create_all(connection)


def _insert_snapshot(
    connection: sa.Connection,
    *,
    row_id: uuid.UUID,
    as_of_date: date,
    snapshot_data: dict,
    total: str = "10.000000",
    inputs_hash: str | None = "a" * 64,
    correlation_id: str = "corr-1",
) -> None:
    table = _pre_039_table(sa.MetaData())
    connection.execute(
        table.insert(),
        {
            "id": row_id,
            "as_of_date": as_of_date,
            "snapshot_data": snapshot_data,
            "total_net_cashflow": Decimal(total),
            "inputs_hash": inputs_hash,
            "correlation_id": correlation_id,
            "created_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
        },
    )


def test_039_revision_metadata_chains_from_038() -> None:
    migration = _load_migration()
    assert migration.revision == "039_a3_cashflow_baseline_archive"
    assert migration.down_revision == "038_a3_price_provenance"


def test_039_sqlite_uuid_values_are_serialized_at_archive_boundary() -> None:
    migration = _load_migration()

    archive_id = migration._archive_snapshot_id(LEGACY_ID, "sqlite")
    restored_char_id = migration._source_snapshot_id(
        str(LEGACY_ID), sa.String(length=32), "sqlite"
    )
    restored_uuid_id = migration._source_snapshot_id(
        str(LEGACY_ID), sa.Uuid(), "sqlite"
    )

    assert archive_id == str(LEGACY_ID)
    assert isinstance(archive_id, str)
    assert restored_char_id == LEGACY_ID.hex
    assert restored_uuid_id == LEGACY_ID


def test_039_upgrade_archives_legacy_and_leaves_new_baseline_active() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_pre_039_schema(connection)
        legacy_payload = {
            "as_of_date": "2026-02-01",
            "cashflow_items": [{"object_type": "order", "object_id": "o-1"}],
            "total_net_cashflow": "10.000000",
        }
        baseline_payload = {
            "view": "baseline",
            "as_of_date": "2026-02-02",
            "unrealized_items": [],
            "realized_ledger_entries": [],
            "reconciliation": {
                "unrealized_total_usd": "0.000000",
                "realized_total_usd": "0.000000",
                "total_net_cashflow": "0.000000",
                "unrealized_item_count": 0,
                "ledger_entry_count": 0,
            },
        }
        _insert_snapshot(
            connection,
            row_id=LEGACY_ID,
            as_of_date=date(2026, 2, 1),
            snapshot_data=legacy_payload,
            total="10.000000",
            correlation_id="legacy-corr",
        )
        _insert_snapshot(
            connection,
            row_id=BASELINE_ID,
            as_of_date=date(2026, 2, 2),
            snapshot_data=baseline_payload,
            total="0.000000",
            correlation_id="baseline-corr",
        )

        _run_migration(connection, "upgrade")

        assert inspect(connection).has_table("cashflow_baseline_snapshot_archives")
        archive_table = sa.Table(
            "cashflow_baseline_snapshot_archives",
            sa.MetaData(),
            autoload_with=connection,
        )
        archive = connection.execute(
            sa.select(
                archive_table.c.original_snapshot_id,
                archive_table.c.as_of_date,
                archive_table.c.snapshot_data,
                archive_table.c.total_net_cashflow,
                archive_table.c.inputs_hash,
                archive_table.c.correlation_id,
                archive_table.c.original_created_at,
                archive_table.c.archive_reason,
            )
        ).mappings().one()
        assert archive["original_snapshot_id"] == str(LEGACY_ID)
        assert archive["as_of_date"] == date(2026, 2, 1)
        assert archive["snapshot_data"] == legacy_payload
        assert archive["total_net_cashflow"] == Decimal("10.000000")
        assert archive["inputs_hash"] == "a" * 64
        assert archive["correlation_id"] == "legacy-corr"
        assert archive["original_created_at"] is not None
        assert (
            archive["archive_reason"]
            == "PR-A3-4 legacy analytic-shaped baseline payload"
        )

        active_ids = {
            row[0]
            for row in connection.execute(
                sa.text("SELECT id FROM cashflow_baseline_snapshots")
            ).all()
        }
        assert active_ids == {BASELINE_ID.hex}


def test_039_downgrade_restores_archived_rows_when_no_active_conflict() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_pre_039_schema(connection)
        legacy_payload = {
            "as_of_date": "2026-02-01",
            "cashflow_items": [{"object_type": "order", "object_id": "o-1"}],
        }
        _insert_snapshot(
            connection,
            row_id=LEGACY_ID,
            as_of_date=date(2026, 2, 1),
            snapshot_data=legacy_payload,
            correlation_id="legacy-corr",
        )
        _run_migration(connection, "upgrade")
        _run_migration(connection, "downgrade")

        snapshot_table = sa.Table(
            "cashflow_baseline_snapshots", sa.MetaData(), autoload_with=connection
        )
        restored = connection.execute(
            sa.select(
                snapshot_table.c.id,
                snapshot_table.c.as_of_date,
                snapshot_table.c.snapshot_data,
                snapshot_table.c.correlation_id,
            )
        ).mappings().one()
        assert restored["id"] == LEGACY_ID.hex
        assert restored["as_of_date"] == date(2026, 2, 1)
        assert restored["snapshot_data"] == legacy_payload
        assert restored["correlation_id"] == "legacy-corr"
        assert not inspect(connection).has_table("cashflow_baseline_snapshot_archives")


def test_039_downgrade_hard_fails_on_active_as_of_conflict() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_pre_039_schema(connection)
        _insert_snapshot(
            connection,
            row_id=LEGACY_ID,
            as_of_date=date(2026, 2, 1),
            snapshot_data={"cashflow_items": []},
        )
        _run_migration(connection, "upgrade")
        _insert_snapshot(
            connection,
            row_id=ACTIVE_ID,
            as_of_date=date(2026, 2, 1),
            snapshot_data={"view": "baseline"},
        )

        with pytest.raises(RuntimeError, match="active baseline snapshot already exists"):
            _run_migration(connection, "downgrade")


def test_039_upgrade_hard_fails_legacy_null_correlation_id_precheck() -> None:
    migration = _load_migration()

    class _Result:
        def scalar(self) -> int:
            return 1

    class _Bind:
        dialect = type("Dialect", (), {"name": "sqlite"})()

        def execute(self, statement):
            assert "correlation_id IS NULL" in str(statement)
            return _Result()

    class _Op:
        def get_bind(self):
            return _Bind()

        def create_table(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("precheck must fail before archive table creation")

    migration.op = _Op()

    with pytest.raises(RuntimeError, match="legacy baseline snapshots with NULL correlation_id"):
        migration.upgrade()


def test_039_downgrade_hard_fails_on_archive_null_correlation_id() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_pre_039_schema(connection)
        metadata = sa.MetaData()
        sa.Table(
            "cashflow_baseline_snapshot_archives",
            metadata,
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("original_snapshot_id", sa.String(length=64), nullable=False),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("snapshot_data", sa.JSON(), nullable=False),
            sa.Column("total_net_cashflow", sa.Numeric(18, 6), nullable=False),
            sa.Column("inputs_hash", sa.String(length=64), nullable=True),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("archive_reason", sa.String(length=128), nullable=False),
        )
        metadata.create_all(connection)
        archive_table = sa.Table(
            "cashflow_baseline_snapshot_archives",
            sa.MetaData(),
            autoload_with=connection,
        )
        connection.execute(
            archive_table.insert(),
            {
                "id": "archive-1",
                "original_snapshot_id": str(LEGACY_ID),
                "as_of_date": date(2026, 2, 1),
                "snapshot_data": {"cashflow_items": []},
                "total_net_cashflow": Decimal("10.000000"),
                "inputs_hash": "a" * 64,
                "correlation_id": None,
                "original_created_at": None,
                "archived_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                "archive_reason": "PR-A3-4 legacy analytic-shaped baseline payload",
            },
        )

        with pytest.raises(RuntimeError, match="archived baseline snapshots with NULL correlation_id"):
            _run_migration(connection, "downgrade")


def test_039_downgrade_hard_fails_on_archive_null_original_created_at() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_pre_039_schema(connection)
        metadata = sa.MetaData()
        sa.Table(
            "cashflow_baseline_snapshot_archives",
            metadata,
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("original_snapshot_id", sa.String(length=64), nullable=False),
            sa.Column("as_of_date", sa.Date(), nullable=False),
            sa.Column("snapshot_data", sa.JSON(), nullable=False),
            sa.Column("total_net_cashflow", sa.Numeric(18, 6), nullable=False),
            sa.Column("inputs_hash", sa.String(length=64), nullable=True),
            sa.Column("correlation_id", sa.String(length=64), nullable=True),
            sa.Column("original_created_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("archive_reason", sa.String(length=128), nullable=False),
        )
        metadata.create_all(connection)
        archive_table = sa.Table(
            "cashflow_baseline_snapshot_archives",
            sa.MetaData(),
            autoload_with=connection,
        )
        connection.execute(
            archive_table.insert(),
            {
                "id": "archive-1",
                "original_snapshot_id": str(LEGACY_ID),
                "as_of_date": date(2026, 2, 1),
                "snapshot_data": {"cashflow_items": []},
                "total_net_cashflow": Decimal("10.000000"),
                "inputs_hash": "a" * 64,
                "correlation_id": "legacy-corr",
                "original_created_at": None,
                "archived_at": datetime(2026, 2, 1, tzinfo=timezone.utc),
                "archive_reason": "PR-A3-4 legacy analytic-shaped baseline payload",
            },
        )

        with pytest.raises(
            RuntimeError, match="archived baseline snapshots with NULL original_created_at"
        ):
            _run_migration(connection, "downgrade")
