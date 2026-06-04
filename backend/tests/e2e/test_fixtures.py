"""Unit-level tests for the E2E seed helpers."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

import pytest

from backend.tests.e2e._fixtures import (
    seed_counterparties,
    seed_lme_calendar,
    seed_westmetall_prices,
    trace_id_factory,
)


def test_seed_counterparties_returns_one_per_type() -> None:
    trace_id = trace_id_factory()
    ids = seed_counterparties(trace_id)
    assert set(ids.keys()) == {"customer", "supplier", "broker", "bank"}
    assert all(UUID(v) for v in ids.values())


def test_seed_counterparties_is_idempotent() -> None:
    trace_id = trace_id_factory()
    first = seed_counterparties(trace_id)
    second = seed_counterparties(trace_id)
    assert first == second


def test_seed_westmetall_prices_rejects_floats() -> None:
    trace_id = trace_id_factory()
    today = date.today()
    with pytest.raises(TypeError, match="Decimal"):
        seed_westmetall_prices(trace_id, today, today, raw_floats=True)


def test_seed_lme_calendar_covers_range() -> None:
    today = date.today()
    seed_lme_calendar(today - timedelta(days=10), today + timedelta(days=10))
