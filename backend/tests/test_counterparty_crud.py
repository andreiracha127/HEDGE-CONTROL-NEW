"""Tests for Counterparty CRUD — component 1.1."""

import pytest
from uuid import uuid4


ENDPOINT = "/counterparties"

VALID_COUNTERPARTY = {
    "type": "broker",
    "name": "Aluminium Corp",
    "short_name": "AluCorp",
    "tax_id": "BR123456789",
    "country": "BRA",
    "city": "São Paulo",
    "contact_name": "João Silva",
    "contact_email": "joao@alucorp.com",
    "credit_limit_usd": 500000.00,
    "kyc_status": "approved",
    "risk_rating": "low",
}


def test_create_counterparty(client):
    r = client.post(ENDPOINT, json=VALID_COUNTERPARTY)
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Aluminium Corp"
    assert body["type"] == "broker"
    assert body["kyc_status"] == "pending"
    assert body["is_deleted"] is False

    # Now approve it via the transition endpoint
    cp_id = body["id"]
    # Test fixture: directly approve via service to set up the test scenario.
    # Production code path (POST /counterparties/{id}/kyc-status) is covered
    # by tests/test_counterparty_kyc_transition.py.
    r_kyc = client.post(f"{ENDPOINT}/{cp_id}/kyc-status", json={"new_status": "approved", "reason": "RM manually approved via API test"})
    assert r_kyc.status_code == 200
    assert r_kyc.json()["kyc_status"] == "approved"


def test_create_counterparty_defaults(client):
    r = client.post(
        ENDPOINT, json={"type": "broker", "name": "Metal Broker", "country": "USA"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["kyc_status"] == "pending"
    assert body["sanctions_status"] == "unscreened"
    assert body["risk_rating"] == "medium"


def test_list_counterparties(client):
    client.post(ENDPOINT, json={"type": "broker", "name": "C1", "country": "USA"})
    client.post(ENDPOINT, json={"type": "bank_br", "name": "S1", "country": "DEU"})
    r = client.get(ENDPOINT)
    assert r.status_code == 200
    assert len(r.json()["items"]) == 2


def test_list_filter_by_type(client):
    client.post(ENDPOINT, json={"type": "broker", "name": "C1", "country": "USA"})
    client.post(ENDPOINT, json={"type": "bank_br", "name": "S1", "country": "DEU"})
    r = client.get(ENDPOINT, params={"type": "broker"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["type"] == "broker"


def test_list_filter_by_kyc_status(client):
    r1 = client.post(
        ENDPOINT,
        json={
            "type": "broker",
            "name": "C1",
            "country": "USA",
        },
    )
    assert r1.status_code == 201
    cp1_id = r1.json()["id"]
    r_kyc = client.post(f"{ENDPOINT}/{cp1_id}/kyc-status", json={"new_status": "approved", "reason": "RM manually approved via API test"})
    assert r_kyc.status_code == 200

    client.post(
        ENDPOINT,
        json={
            "type": "broker",
            "name": "C2",
            "country": "USA",
        },
    )
    r = client.get(ENDPOINT, params={"kyc_status": "approved"})
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "C1"


def test_get_counterparty(client):
    r1 = client.post(ENDPOINT, json=VALID_COUNTERPARTY)
    cp_id = r1.json()["id"]
    r2 = client.get(f"{ENDPOINT}/{cp_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == cp_id


def test_get_counterparty_not_found(client):
    r = client.get(f"{ENDPOINT}/{uuid4()}")
    assert r.status_code == 404


def test_update_counterparty(client):
    r1 = client.post(ENDPOINT, json=VALID_COUNTERPARTY)
    cp_id = r1.json()["id"]
    r2 = client.patch(
        f"{ENDPOINT}/{cp_id}", json={"name": "New Name", "credit_limit_usd": 1000000.0}
    )
    assert r2.status_code == 200
    assert r2.json()["name"] == "New Name"
    assert r2.json()["credit_limit_usd"] == 1000000.0


def test_soft_delete_counterparty(client):
    r1 = client.post(ENDPOINT, json=VALID_COUNTERPARTY)
    cp_id = r1.json()["id"]
    r2 = client.delete(f"{ENDPOINT}/{cp_id}")
    assert r2.status_code == 200
    assert r2.json()["is_deleted"] is True
    assert r2.json()["deleted_at"] is not None
    # Cannot find after soft delete
    r3 = client.get(f"{ENDPOINT}/{cp_id}")
    assert r3.status_code == 404


def test_duplicate_tax_id_rejected(client):
    client.post(ENDPOINT, json=VALID_COUNTERPARTY)
    r = client.post(ENDPOINT, json={**VALID_COUNTERPARTY, "name": "Other Corp"})
    assert r.status_code == 409
    assert "tax_id" in r.json()["detail"]


def test_update_tax_id_duplicate_rejected(client):
    client.post(ENDPOINT, json=VALID_COUNTERPARTY)
    r2 = client.post(
        ENDPOINT,
        json={
            "type": "bank_br",
            "name": "S2",
            "country": "USA",
            "tax_id": "UNIQUE999",
        },
    )
    cp2_id = r2.json()["id"]
    r3 = client.patch(f"{ENDPOINT}/{cp2_id}", json={"tax_id": "BR123456789"})
    assert r3.status_code == 409


def test_list_filter_by_is_active(client):
    client.post(
        ENDPOINT,
        json={
            "type": "broker",
            "name": "Active",
            "country": "USA",
            "is_active": True,
        },
    )
    client.post(
        ENDPOINT,
        json={
            "type": "broker",
            "name": "Inactive",
            "country": "USA",
            "is_active": False,
        },
    )
    r = client.get(ENDPOINT, params={"is_active": True})
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["name"] == "Active"
