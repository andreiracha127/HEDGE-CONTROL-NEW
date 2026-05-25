"""Audit HMAC chain integrity checks."""

from __future__ import annotations

from typing import Any

from backend.tests.e2e._journey_steps import step_read_audit_trail
from backend.tests.e2e._personas import as_auditor, as_risk_manager


def test_audit_events_have_checksums_and_signatures(awarded_rfq: dict[str, Any]) -> None:
    events = step_read_audit_trail(entity_type="rfq", entity_id=awarded_rfq["id"])
    assert events
    assert all(event["checksum"] for event in events)
    assert all(event["signature"] for event in events)


def test_audit_event_verify_endpoint_accepts_signed_event(
    awarded_rfq: dict[str, Any],
) -> None:
    event = step_read_audit_trail(entity_type="rfq", entity_id=awarded_rfq["id"])[0]
    with as_auditor() as client:
        response = client.get(f"/audit/events/{event['id']}/verify")
        assert response.status_code == 200, response.text
        assert response.json()["valid"] is True


def test_audit_surface_is_append_only_for_human_roles(awarded_rfq: dict[str, Any]) -> None:
    event = step_read_audit_trail(entity_type="rfq", entity_id=awarded_rfq["id"])[0]
    with as_risk_manager() as client:
        response = client.delete(f"/audit/events/{event['id']}")
        assert response.status_code == 405


def test_rfq_created_and_awarded_events_are_present(awarded_rfq: dict[str, Any]) -> None:
    events = step_read_audit_trail(entity_type="rfq", entity_id=awarded_rfq["id"])
    assert {event["event_type"] for event in events} >= {"created", "awarded"}


def test_audit_payloads_are_reconstructable(awarded_rfq: dict[str, Any]) -> None:
    events = step_read_audit_trail(entity_type="rfq", entity_id=awarded_rfq["id"])
    assert all(event["payload"] is not None for event in events)
