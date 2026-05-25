"""E2E-specific fixtures. Loaded after backend/tests/conftest.py."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from backend.tests.e2e._fixtures import (
    seed_counterparties,
    seed_lme_calendar,
    seed_westmetall_prices,
    trace_id_factory,
)
from backend.tests.e2e._journey_steps import step_award_quote, step_create_rfq


@pytest.fixture()
def e2e_trace_id() -> str:
    return trace_id_factory()


@pytest.fixture()
def seeded_counterparties(e2e_trace_id: str) -> dict[str, str]:
    today = date.today()
    seed_lme_calendar(today, today)
    seed_westmetall_prices(e2e_trace_id, today, today)
    return seed_counterparties(e2e_trace_id)


@pytest.fixture()
def awarded_rfq(
    e2e_trace_id: str,
    seeded_counterparties: dict[str, str],
) -> dict[str, Any]:
    rfq = step_create_rfq(e2e_trace_id, [seeded_counterparties["supplier"]])
    return step_award_quote(rfq["id"], seeded_counterparties["supplier"])
