"""Full institutional E2E narrative smoke."""

from __future__ import annotations

from typing import Any

from backend.tests.e2e._journey_steps import (
    step_link_contract,
    step_read_audit_trail,
)


def test_full_rfq_award_contract_audit_journey(awarded_rfq: dict[str, Any]) -> None:
    contract = step_link_contract(awarded_rfq["id"])
    assert contract["rfq_id"] == awarded_rfq["id"]
    assert contract["fixed_price_value"] is not None
    assert contract["quantity_mt"] == awarded_rfq["quantity_mt"]

    rfq_events = step_read_audit_trail(entity_type="rfq", entity_id=awarded_rfq["id"])
    assert {event["event_type"] for event in rfq_events} >= {"created", "awarded"}
