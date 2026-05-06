"""Migration tests for the HedgeContract classification invariant."""

from __future__ import annotations

import importlib
import logging
from pathlib import Path

from sqlalchemy import Column, MetaData, String, Table, create_engine, select


def test_migration_backfill_autocorrects_drift_and_logs(caplog) -> None:
    spec = importlib.util.spec_from_file_location(
        "classification_invariant_migration",
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "026_classification_invariant.py",
    )
    assert spec is not None
    assert spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata = MetaData()
    hedge_contracts = Table(
        "hedge_contracts",
        metadata,
        Column("id", String, primary_key=True),
        Column("fixed_leg_side", String, nullable=False),
        Column("classification", String, nullable=False),
    )
    metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            hedge_contracts.insert(),
            [
                {
                    "id": "consistent",
                    "fixed_leg_side": "buy",
                    "classification": "long",
                },
                {
                    "id": "drifted",
                    "fixed_leg_side": "sell",
                    "classification": "long",
                },
            ],
        )

    with caplog.at_level(logging.WARNING):
        with engine.begin() as conn:
            corrected = migration._backfill_inconsistent_classifications(conn)

    with engine.connect() as conn:
        rows = {
            row.id: row.classification
            for row in conn.execute(select(hedge_contracts)).all()
        }

    assert corrected == 1
    assert rows == {"consistent": "long", "drifted": "short"}
    assert "classification invariant backfill corrected 1 hedge_contracts rows" in (
        caplog.text
    )
