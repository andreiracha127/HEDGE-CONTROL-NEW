from decimal import Decimal

from app.core.auth import get_current_user
from app.main import app
from app.services import sanctions_screening_service as svc
from app.services.opensanctions_client import MatchResult


def _as(role):
    app.dependency_overrides[get_current_user] = lambda: {"sub": f"{role}-1", "roles": [role]}


def _make_partner(client, kind="customer"):
    _as("trader")
    r = client.post("/commercial-partners", json={"kind": kind, "name": "Rusal", "country": "RUS"})
    assert r.status_code == 201
    return r.json()["id"]


def test_trader_can_screen_commercial(client, monkeypatch):
    monkeypatch.setattr(
        svc,
        "screen_entity",
        lambda **kw: MatchResult(Decimal("0.10"), 0, [], None, "logic-v2"),
    )
    pid = _make_partner(client)
    _as("trader")
    r = client.post(f"/commercial-partners/{pid}/screen")
    assert r.status_code == 200
    assert r.json()["result"] == "clear"
    app.dependency_overrides.pop(get_current_user, None)


def test_trader_cannot_adjudicate(client):
    pid = _make_partner(client)
    _as("trader")
    r = client.post(
        f"/commercial-partners/{pid}/adjudicate-sanctions",
        json={"decision": "clear", "reason": "trader not allowed"},
    )
    assert r.status_code == 403
    app.dependency_overrides.pop(get_current_user, None)


def test_risk_manager_adjudicates_flagged(client, monkeypatch):
    monkeypatch.setattr(
        svc,
        "screen_entity",
        lambda **kw: MatchResult(Decimal("0.75"), 1, [{"score": 0.75}], None, "logic-v2"),
    )
    pid = _make_partner(client)
    _as("risk_manager")
    assert client.post(f"/commercial-partners/{pid}/screen").json()["result"] == "flagged"
    r = client.post(
        f"/commercial-partners/{pid}/adjudicate-sanctions",
        json={"decision": "clear", "reason": "confirmed false positive"},
    )
    assert r.status_code == 200
    assert r.json()["decision"] == "clear"
    app.dependency_overrides.pop(get_current_user, None)
