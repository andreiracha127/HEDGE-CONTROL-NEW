import pytest

from app.core.auth import get_current_user
from app.main import app
from app.services import lei_validation_service as svc
from app.services.gleif_client import GleifRecord


@pytest.fixture(autouse=True)
def _clear_auth_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _as(role):
    app.dependency_overrides[get_current_user] = lambda: {"sub": f"{role}-1", "roles": [role]}


def _make_partner(client, lei="5493001KJTIIGC8Y1R12"):
    _as("trader")
    r = client.post(
        "/commercial-partners",
        json={"kind": "customer", "name": "Acme", "country": "BRA", "lei": lei},
    )
    assert r.status_code == 201
    return r.json()["id"]


def test_trader_validates_lei(client, monkeypatch):
    monkeypatch.setattr(
        svc,
        "fetch_lei_record",
        lambda lei: GleifRecord("ISSUED", "Acme", "en", "ACTIVE"),
    )
    pid = _make_partner(client)
    _as("trader")
    r = client.post(f"/commercial-partners/{pid}/validate-lei")
    assert r.status_code == 200
    assert r.json()["lei_status"] == "issued"


def test_gleif_error_returns_200_with_error_status(client, monkeypatch):
    from app.services.gleif_client import GleifLookupError

    def boom(lei):
        raise GleifLookupError("down")

    monkeypatch.setattr(svc, "fetch_lei_record", boom)
    pid = _make_partner(client)
    _as("risk_manager")
    r = client.post(f"/commercial-partners/{pid}/validate-lei")
    assert r.status_code == 200  # WARN-not-block: informational error, not a 5xx
    assert r.json()["lei_status"] == "error"
    assert r.json()["warnings"]


def test_auditor_cannot_validate_lei(client):
    pid = _make_partner(client)
    _as("auditor")
    r = client.post(f"/commercial-partners/{pid}/validate-lei")
    assert r.status_code == 403


def test_validate_lei_for_unknown_partner_returns_404(client):
    import uuid

    _as("trader")
    r = client.post(f"/commercial-partners/{uuid.uuid4()}/validate-lei")
    assert r.status_code == 404
