from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError


def _load_migration():
    path = Path("backend/alembic/versions/038_a3_price_provenance.py")
    spec = importlib.util.spec_from_file_location("migration_038", path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


def test_038_revision_metadata_chains_from_037() -> None:
    migration = _load_migration()
    assert migration.revision == "038_a3_price_provenance"
    assert migration.down_revision == "037_rfq_outbound_evidence"


def _create_pre_038_schema(connection: sa.Connection) -> None:
    metadata = sa.MetaData()
    sa.Table(
        "cash_settlement_prices",
        metadata,
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("price_usd", sa.Float(), nullable=False),
    )
    sa.Table(
        "mtm_snapshots",
        metadata,
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("mtm_value", sa.Numeric(18, 6), nullable=False),
    )
    sa.Table(
        "pl_snapshots",
        metadata,
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("total_pl", sa.Numeric(18, 6), nullable=False),
    )
    sa.Table(
        "cashflow_baseline_snapshots",
        metadata,
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("total_net_cashflow", sa.Numeric(18, 6), nullable=False),
    )
    sa.Table(
        "cashflow_ledger_entries",
        metadata,
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
    )
    metadata.create_all(connection)


def _run_migration(connection: sa.Connection, direction: str) -> None:
    migration = _load_migration()
    context = MigrationContext.configure(connection)
    with Operations.context(context):
        getattr(migration, direction)()


def _columns(connection: sa.Connection, table_name: str) -> set[str]:
    return {column["name"] for column in inspect(connection).get_columns(table_name)}


def test_038_upgrade_and_downgrade_clean() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_pre_038_schema(connection)

        _run_migration(connection, "upgrade")
        assert {
            "price_source",
            "price_symbol",
            "price_settlement_date",
            "inputs_hash",
        }.issubset(_columns(connection, "mtm_snapshots"))
        assert {"price_references", "inputs_hash"}.issubset(
            _columns(connection, "pl_snapshots")
        )
        assert "inputs_hash" in _columns(connection, "cashflow_baseline_snapshots")
        assert {
            "price_source",
            "price_symbol",
            "price_settlement_date",
            "price_value",
        }.issubset(_columns(connection, "cashflow_ledger_entries"))

        with pytest.raises(IntegrityError):
            connection.execute(
                sa.text(
                    "INSERT INTO cashflow_ledger_entries "
                    "(id, amount, price_source) VALUES "
                    "('partial', 1, 'westmetall')"
                )
            )

        _run_migration(connection, "downgrade")
        assert "inputs_hash" not in _columns(connection, "mtm_snapshots")
        assert "price_references" not in _columns(connection, "pl_snapshots")
        assert "inputs_hash" not in _columns(connection, "cashflow_baseline_snapshots")
        assert "price_value" not in _columns(connection, "cashflow_ledger_entries")


def test_038_preflight_rejects_out_of_scale_float_rows() -> None:
    migration = _load_migration()

    class _Result:
        def scalar(self) -> int:
            return 1

    class _Bind:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def execute(self, statement):
            assert "scale(price_usd::numeric) > 6" in str(statement)
            return _Result()

    class _Op:
        def get_bind(self):
            return _Bind()

        def alter_column(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("preflight must fail before ALTER COLUMN")

        def batch_alter_table(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("preflight must fail before batch alter")

    migration.op = _Op()

    with pytest.raises(RuntimeError, match="Refusing to convert 1 rows"):
        migration.upgrade()

    source = Path("backend/alembic/versions/038_a3_price_provenance.py").read_text()
    assert "scale(price_usd::numeric) > 6" in source
    assert "Refusing to convert" in source


def test_038_post_upgrade_insert_with_provenance_survives_downgrade_then_upgrade() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        _create_pre_038_schema(connection)

        _run_migration(connection, "upgrade")
        connection.execute(
            sa.text(
                "INSERT INTO cashflow_ledger_entries "
                "(id, amount, price_source, price_symbol, price_settlement_date, price_value) "
                "VALUES "
                "('ledger-1', 27123.796299, 'westmetall', "
                "'LME_ALU_CASH_SETTLEMENT_DAILY', '2026-01-30', 2585.123457)"
            )
        )

        _run_migration(connection, "downgrade")
        row_count = connection.execute(
            sa.text("SELECT COUNT(*) FROM cashflow_ledger_entries WHERE id = 'ledger-1'")
        ).scalar_one()
        assert row_count == 1

        _run_migration(connection, "upgrade")
        row = connection.execute(
            sa.text(
                "SELECT price_source, price_symbol, price_settlement_date, price_value "
                "FROM cashflow_ledger_entries WHERE id = 'ledger-1'"
            )
        ).one()
        assert row == (None, None, None, None)


def test_038_uses_batch_alter_table_for_new_check_constraints() -> None:
    source = Path("backend/alembic/versions/038_a3_price_provenance.py").read_text()
    assert 'batch_alter_table("mtm_snapshots")' in source
    assert 'batch_alter_table("pl_snapshots")' in source
    assert 'batch_alter_table("cashflow_ledger_entries")' in source
