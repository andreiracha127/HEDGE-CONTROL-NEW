from decimal import Decimal

from app.core.auth import get_current_user
from app.main import app
from app.services import sanctions_screening_service as svc
from app.services.opensanctions_client import MatchResult


def _as(role):
    app.dependency_overrides[get_current_user] = lambda: {"sub": f"{role}-1", "roles": [role]}


def _make_broker(client):
    _as("risk_manager")
    r = client.post("/counterparties", json={"type": "broker", "name": "Marex", "country": "GBR"})
    assert r.status_code == 201
    return r.json()["id"]


def test_risk_manager_screens_hedge(client, monkeypatch):
    monkeypatch.setattr(
        svc,
        "screen_entity",
        lambda **kw: MatchResult(Decimal("0.10"), 0, [], None, "logic-v2"),
    )
    cid = _make_broker(client)
    _as("risk_manager")
    r = client.post(f"/counterparties/{cid}/screen")
    assert r.status_code == 200
    assert r.json()["result"] == "clear"
    app.dependency_overrides.pop(get_current_user, None)


def test_trader_screen_hedge_is_404(client):
    cid = _make_broker(client)
    _as("trader")
    r = client.post(f"/counterparties/{cid}/screen")
    assert r.status_code == 404
    app.dependency_overrides.pop(get_current_user, None)


def test_auditor_cannot_screen_hedge(client):
    # auditor is read-only; screening is a write and must be denied at the gate.
    cid = _make_broker(client)
    _as("auditor")
    r = client.post(f"/counterparties/{cid}/screen")
    assert r.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)
