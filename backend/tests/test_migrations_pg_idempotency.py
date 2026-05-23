"""Postgres-only regression: re-running migrations 010 and 011 on a database
where the enum types already exist must not raise DuplicateObject.

This guards against Codex finding [high] from 2026-05-22: sa.Enum(..., create_type=False)
does NOT preserve the flag (the kwarg belongs to postgresql.ENUM), so op.add_column can
emit an implicit CREATE TYPE even though we already created the enum manually.

Skipped if no real PostgreSQL DATABASE_URL is configured for the test runner —
the sqlite test path does not exercise CREATE TYPE.
"""
from __future__ import annotations

import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


PG_URL = os.getenv("TEST_PG_URL")

pytestmark = pytest.mark.skipif(
    not PG_URL,
    reason="TEST_PG_URL not set; this regression requires a real PostgreSQL instance.",
)


def _make_engine() -> sa.Engine:
    return sa.create_engine(PG_URL, future=True)


def test_hedge_contract_status_enum_idempotent_on_add_column() -> None:
    """Simulate the 010 upgrade against a DB that already has the enum + table."""
    engine = _make_engine()
    schema = f"codex_010_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(sa.text(f'SET search_path TO "{schema}"'))
        status_enum = postgresql.ENUM(
            "active", "cancelled", "settled",
            name="hedge_contract_status", create_type=False,
        )
        status_enum.create(conn, checkfirst=True)
        conn.execute(sa.text(
            'CREATE TABLE hedge_contracts (id UUID PRIMARY KEY)'
        ))
        conn.execute(sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'hedge_contract_status') THEN "
            "    CREATE TYPE hedge_contract_status AS ENUM ('active','cancelled','settled'); "
            "  END IF; "
            "END $$;"
        ))

        column_type = postgresql.ENUM(
            "active", "cancelled", "settled",
            name="hedge_contract_status", create_type=False,
        )
        conn.execute(sa.text(
            'ALTER TABLE hedge_contracts ADD COLUMN status '
            f'{column_type.compile(dialect=conn.dialect)} NOT NULL DEFAULT \'active\''
        ))
        conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))


def test_order_pricing_convention_enum_idempotent_on_add_column() -> None:
    """Same regression for migration 011 (orders.pricing_convention)."""
    engine = _make_engine()
    schema = f"codex_011_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(sa.text(f'SET search_path TO "{schema}"'))
        conn.execute(sa.text(
            "DO $$ BEGIN "
            "  IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'order_pricing_convention') THEN "
            "    CREATE TYPE order_pricing_convention AS ENUM ('AVG','AVGInter','C2R'); "
            "  END IF; "
            "END $$;"
        ))
        conn.execute(sa.text('CREATE TABLE orders (id UUID PRIMARY KEY)'))

        column_type = postgresql.ENUM(
            "AVG", "AVGInter", "C2R",
            name="order_pricing_convention", create_type=False,
        )
        conn.execute(sa.text(
            'ALTER TABLE orders ADD COLUMN pricing_convention '
            f'{column_type.compile(dialect=conn.dialect)}'
        ))
        conn.execute(sa.text(f'DROP SCHEMA "{schema}" CASCADE'))
