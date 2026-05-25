"""RBAC matrix checks for the production-readiness journey surface."""

from __future__ import annotations

from typing import Any

import pytest

from backend.tests.e2e._personas import as_auditor, as_risk_manager, as_service, as_trader


def _rfq_payload(counterparty_id: str) -> dict[str, Any]:
    return {
        "intent": "GLOBAL_POSITION",
        "commodity": "LME_AL",
        "quantity_mt": "5.000000",
        "delivery_window_start": "2026-03-01",
        "delivery_window_end": "2026-03-31",
        "direction": "BUY",
        "order_id": None,
        "invitations": [{"counterparty_id": counterparty_id}],
    }


def test_trader_sees_customer_supplier_but_broker_is_hidden(
    seeded_counterparties: dict[str, str],
) -> None:
    with as_trader() as client:
        visible = client.get("/counterparties")
        assert visible.status_code == 200
        visible_types = {item["type"] for item in visible.json()["items"]}
        assert visible_types <= {"customer", "supplier"}

        broker = client.get(f"/counterparties/{seeded_counterparties['broker']}")
        assert broker.status_code == 404


@pytest.mark.parametrize(
    ("persona", "expected"),
    [
        (as_trader, 403),
        (as_risk_manager, 200),
        (as_auditor, 200),
    ],
)
def test_rfq_list_role_matrix(persona, expected: int) -> None:
    with persona() as client:
        response = client.get("/rfqs")
        assert response.status_code == expected


@pytest.mark.parametrize(
    ("persona", "expected"),
    [
        (as_trader, 403),
        (as_risk_manager, 201),
        (as_auditor, 403),
    ],
)
def test_rfq_create_role_matrix(
    persona,
    expected: int,
    seeded_counterparties: dict[str, str],
) -> None:
    with persona() as client:
        response = client.post("/rfqs", json=_rfq_payload(seeded_counterparties["supplier"]))
        assert response.status_code == expected, response.text


@pytest.mark.parametrize(
    ("persona", "expected"),
    [
        (as_trader, 403),
        (as_risk_manager, 403),
        (as_auditor, 200),
    ],
)
def test_audit_events_role_matrix(persona, expected: int) -> None:
    with persona() as client:
        response = client.get("/audit/events")
        assert response.status_code == expected


def test_auditor_cannot_mutate_counterparties() -> None:
    with as_auditor() as client:
        response = client.post(
            "/counterparties",
            json={"type": "customer", "name": "auditor-forbidden", "country": "BRA"},
        )
        assert response.status_code == 403


def test_service_identity_cannot_use_human_rfq_route(
    seeded_counterparties: dict[str, str],
) -> None:
    with as_service("service:westmetall_ingest") as client:
        response = client.post("/rfqs", json=_rfq_payload(seeded_counterparties["supplier"]))
        assert response.status_code == 403
