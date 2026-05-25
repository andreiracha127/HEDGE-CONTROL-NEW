"""Smoke tests for journey step primitives."""

from __future__ import annotations

import re
from datetime import date

from backend.tests.e2e._fixtures import (
    seed_counterparties,
    seed_lme_calendar,
    seed_westmetall_prices,
    trace_id_factory,
)
from backend.tests.e2e._journey_steps import (
    step_award_quote,
    step_create_rfq,
    step_read_audit_trail,
)


def _seed_full(trace_id: str) -> dict[str, str]:
    today = date.today()
    seed_lme_calendar(today, today)
    seed_westmetall_prices(trace_id, today, today)
    return seed_counterparties(trace_id)


def test_step_create_rfq_returns_canonical_id() -> None:
    trace_id = trace_id_factory()
    cps = _seed_full(trace_id)
    rfq = step_create_rfq(trace_id, [cps["supplier"]])
    assert re.match(r"^RFQ-\d{4}-\d{6}$", rfq["canonical_id"]), rfq


def test_step_award_quote_advances_state() -> None:
    trace_id = trace_id_factory()
    cps = _seed_full(trace_id)
    rfq = step_create_rfq(trace_id, [cps["supplier"]])
    awarded = step_award_quote(rfq["id"], cps["supplier"])
    assert awarded["state"] == "CLOSED"
    assert awarded["contract_ids"]


def test_step_read_audit_trail_returns_signed_chain() -> None:
    trace_id = trace_id_factory()
    cps = _seed_full(trace_id)
    rfq = step_create_rfq(trace_id, [cps["supplier"]])
    events = step_read_audit_trail(entity_type="rfq", entity_id=rfq["id"])
    assert len(events) >= 1
    assert all(e.get("signature") for e in events)
