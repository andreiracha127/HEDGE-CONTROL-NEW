import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def _load_migration_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "027_order_commodity.py"
    )
    spec = importlib.util.spec_from_file_location("order_commodity_migration", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_order_commodity_migration_backfills_and_enforces_not_null() -> None:
    engine = create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "orders",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("order_type", sa.String(), nullable=False),
        sa.Column("price_type", sa.String(), nullable=False),
        sa.Column("quantity_mt", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    with engine.begin() as conn:
        metadata.create_all(conn)
        conn.execute(
            text(
                "insert into orders "
                "(id, order_type, price_type, quantity_mt, created_at) "
                "values ('order-1', 'SO', 'variable', 100.0, CURRENT_TIMESTAMP), "
                "('order-2', 'PO', 'fixed', 50.0, CURRENT_TIMESTAMP)"
            )
        )

        migration = _load_migration_module()
        context = MigrationContext.configure(conn)
        migration.op = Operations(context)
        migration.upgrade()

        rows = conn.execute(
            text("select commodity, count(*) from orders group by commodity")
        ).all()
        assert rows == [("ALUMINUM", 2)]

        commodity_column = next(
            col
            for col in inspect(conn).get_columns("orders")
            if col["name"] == "commodity"
        )
        assert commodity_column["nullable"] is False

        with pytest.raises(sa.exc.IntegrityError):
            conn.execute(
                text(
                    "insert into orders "
                    "(id, order_type, price_type, quantity_mt, created_at) "
                    "values ('order-3', 'SO', 'variable', 10.0, CURRENT_TIMESTAMP)"
                )
            )
