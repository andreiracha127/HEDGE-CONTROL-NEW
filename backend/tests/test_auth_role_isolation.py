"""Item 3.8 – Auth role isolation (negation) tests.

Verifies that endpoints correctly reject users that lack the required roles.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, get_current_user
from app.main import app


# -- helpers ----------------------------------------------------------------


def _client_with_roles(*roles: str) -> TestClient:
    """Return a TestClient whose auth override exposes *only* the given roles."""
    app.dependency_overrides[get_current_user] = lambda: {"roles": list(roles)}
    client = TestClient(app)
    client.headers.update({CSRF_HEADER_NAME: "test-csrf-token"})
    client.cookies.set(CSRF_COOKIE_NAME, "test-csrf-token")
    return client


# -- Order routes: require trader -------------------------------------------


@pytest.mark.parametrize("role", ["auditor", "risk_manager"])
@pytest.mark.parametrize("path", ["/orders/sales", "/orders/purchase"])
def test_non_trader_cannot_create_order(role: str, path: str) -> None:
    """auditor and risk_manager are the full non-trader human-role set."""
    c = _client_with_roles(role)
    resp = c.post(path, json={"price_type": "fixed", "quantity_mt": 1.0})
    assert resp.status_code == 403


# -- RFQ creation: require trader -------------------------------------------


def test_auditor_cannot_create_rfq() -> None:
    c = _client_with_roles("auditor")
    resp = c.post(
        "/rfqs",
        json={
            "intent": "GLOBAL_POSITION",
            "commodity": "LME_AL",
            "quantity_mt": 5.0,
            "delivery_window_start": "2026-03-01",
            "delivery_window_end": "2026-03-31",
            "direction": "BUY",
            "order_id": None,
            "invitations": [],
        },
    )
    assert resp.status_code == 403


# -- P&L read: require risk_manager or auditor ------------------------------


def test_trader_cannot_read_pl() -> None:
    c = _client_with_roles("trader")
    resp = c.get(
        "/pl/hedge_contract/00000000-0000-0000-0000-000000000001",
        params={"period_start": "2026-01-01", "period_end": "2026-12-31"},
    )
    assert resp.status_code == 403


def test_trader_cannot_read_pl_snapshots() -> None:
    c = _client_with_roles("trader")
    resp = c.get(
        "/pl/snapshots",
        params={
            "entity_type": "hedge_contract",
            "entity_id": "00000000-0000-0000-0000-000000000001",
            "period_start": "2026-01-01",
            "period_end": "2026-12-31",
        },
    )
    assert resp.status_code == 403


# -- Scenario: require risk_manager or auditor ------------------------------


def test_trader_cannot_run_scenario() -> None:
    c = _client_with_roles("trader")
    resp = c.post(
        "/scenario/what-if/run",
        json={
            "adjustments": [],
            "snapshot_date": "2026-03-15",
        },
    )
    assert resp.status_code == 403


# -- Order listing: accessible to all three roles --------------------------


@pytest.mark.parametrize("role", ["trader", "risk_manager", "auditor"])
def test_all_roles_can_list_orders(role: str) -> None:
    c = _client_with_roles(role)
    resp = c.get("/orders")
    assert resp.status_code == 200


# -- Settlement: require trader --------------------------------------------


def test_auditor_cannot_settle_contract() -> None:
    """Settlement is trader-only per the governance authorization matrix."""
    c = _client_with_roles("auditor")
    resp = c.post(
        "/cashflow/contracts/00000000-0000-0000-0000-000000000001/settle",
        json={
            "source_event_id": "00000000-0000-0000-0000-000000000002",
            "cashflow_date": "2026-03-15",
            "currency": "USD",
            "legs": [
                {"leg_id": "FIXED", "direction": "IN", "amount": "100.00"},
                {"leg_id": "FLOAT", "direction": "OUT", "amount": "90.00"},
            ],
        },
    )
    assert resp.status_code == 403
