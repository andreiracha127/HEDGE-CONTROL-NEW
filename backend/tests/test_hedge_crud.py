"""Tests for unified Hedge Contract CRUD — component 1.4 (post-unification).

All hedge CRUD now goes through /contracts/hedge endpoints.
"""

import uuid

from sqlalchemy.orm import Session

from app.models.counterparty import Counterparty


ENDPOINT = "/contracts/hedge"


def _create_counterparty(session: Session) -> uuid.UUID:
    """Insert a counterparty directly and return its id."""
    cp = Counterparty(
        type="customer",
        name=f"Cpty-{uuid.uuid4().hex[:6]}",
        country="BRA",
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp.id


def _make_contract_payload(
    counterparty_id: uuid.UUID | None = None, **overrides
) -> dict:
    """Build a valid HedgeContractCreate payload with two legs."""
    base = {
        "commodity": "ALUMINUM",
        "quantity_mt": 100.0,
        "legs": [
            {"side": "buy", "price_type": "fixed"},
            {"side": "sell", "price_type": "variable"},
        ],
        "fixed_price_value": 2450.50,
        "fixed_price_unit": "USD/MT",
        "settlement_date": "2025-09-30",
        "notes": "test contract",
    }
    if counterparty_id:
        base["counterparty_id"] = str(counterparty_id)
    base.update(overrides)
    return base


# -----------------------------------------------------------------------
# CREATE
# -----------------------------------------------------------------------


class TestCreateHedgeContract:
    def test_create_success(self, client, session):
        cp_id = _create_counterparty(session)
        payload = _make_contract_payload(cp_id)
        r = client.post(ENDPOINT, json=payload)
        assert r.status_code == 201
        body = r.json()
        assert body["commodity"] == "ALUMINUM"
        assert float(body["quantity_mt"]) == 100.0
        assert float(body["fixed_price_value"]) == 2450.50
        assert body["status"] == "active"
        assert body["reference"].startswith("HC-")
        assert body["classification"] == "long"
        assert body["fixed_leg_side"] == "buy"
        assert body["variable_leg_side"] == "sell"
        assert body["source_type"] == "manual"

    def test_create_short_classification(self, client, session):
        cp_id = _create_counterparty(session)
        payload = _make_contract_payload(
            cp_id,
            legs=[
                {"side": "sell", "price_type": "fixed"},
                {"side": "buy", "price_type": "variable"},
            ],
        )
        r = client.post(ENDPOINT, json=payload)
        assert r.status_code == 201
        assert r.json()["classification"] == "short"

    def test_create_invalid_zero_quantity(self, client, session):
        payload = _make_contract_payload(quantity_mt=0.0)
        r = client.post(ENDPOINT, json=payload)
        assert r.status_code == 422

    def test_create_invalid_one_leg(self, client, session):
        payload = _make_contract_payload(
            legs=[{"side": "buy", "price_type": "fixed"}],
        )
        r = client.post(ENDPOINT, json=payload)
        assert r.status_code == 422


# -----------------------------------------------------------------------
# LIST
# -----------------------------------------------------------------------


class TestListHedgeContracts:
    def test_list_empty(self, client):
        r = client.get(ENDPOINT)
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_list_returns_created(self, client, session):
        cp_id = _create_counterparty(session)
        client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        client.post(ENDPOINT, json=_make_contract_payload(cp_id, commodity="COPPER"))
        r = client.get(ENDPOINT)
        assert r.status_code == 200
        assert len(r.json()["items"]) == 2

    def test_list_filter_by_commodity(self, client, session):
        cp_id = _create_counterparty(session)
        client.post(ENDPOINT, json=_make_contract_payload(cp_id, commodity="ALUMINUM"))
        client.post(ENDPOINT, json=_make_contract_payload(cp_id, commodity="COPPER"))
        r = client.get(ENDPOINT, params={"commodity": "COPPER"})
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["commodity"] == "COPPER"

    def test_list_filter_by_status(self, client, session):
        cp_id = _create_counterparty(session)
        client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        r = client.get(ENDPOINT, params={"status": "active"})
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["status"] == "active"

        r2 = client.get(ENDPOINT, params={"status": "settled"})
        assert r2.json()["items"] == []

    def test_list_filter_by_classification(self, client, session):
        cp_id = _create_counterparty(session)
        client.post(ENDPOINT, json=_make_contract_payload(cp_id))  # long
        r = client.get(ENDPOINT, params={"classification": "long"})
        assert len(r.json()["items"]) == 1
        r2 = client.get(ENDPOINT, params={"classification": "short"})
        assert r2.json()["items"] == []


# -----------------------------------------------------------------------
# GET BY ID
# -----------------------------------------------------------------------


class TestGetHedgeContract:
    def test_get_by_id(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        r2 = client.get(f"{ENDPOINT}/{contract_id}")
        assert r2.status_code == 200
        assert r2.json()["id"] == contract_id

    def test_get_not_found(self, client):
        r = client.get(f"{ENDPOINT}/{uuid.uuid4()}")
        assert r.status_code == 404


# -----------------------------------------------------------------------
# UPDATE (PATCH)
# -----------------------------------------------------------------------


class TestUpdateHedgeContract:
    def test_patch_contract(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        r2 = client.patch(
            f"{ENDPOINT}/{contract_id}",
            json={"notes": "Updated note", "quantity_mt": 120.0},
        )
        assert r2.status_code == 200
        assert r2.json()["notes"] == "Updated note"
        assert float(r2.json()["quantity_mt"]) == 120.0

    def test_patch_not_found(self, client):
        r = client.patch(f"{ENDPOINT}/{uuid.uuid4()}", json={"notes": "x"})
        assert r.status_code == 404

    def test_patch_empty_body(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        r2 = client.patch(f"{ENDPOINT}/{contract_id}", json={})
        assert r2.status_code == 400


# -----------------------------------------------------------------------
# STATUS TRANSITIONS
# -----------------------------------------------------------------------


class TestStatusTransitions:
    def test_valid_transition_active_to_settled(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        r2 = client.patch(
            f"{ENDPOINT}/{contract_id}/status", json={"status": "settled"}
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "settled"

    def test_valid_transition_active_to_partially_settled(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        r2 = client.patch(
            f"{ENDPOINT}/{contract_id}/status",
            json={"status": "partially_settled"},
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "partially_settled"

    def test_invalid_transition_settled_to_active(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        client.patch(f"{ENDPOINT}/{contract_id}/status", json={"status": "settled"})
        r2 = client.patch(f"{ENDPOINT}/{contract_id}/status", json={"status": "active"})
        assert r2.status_code == 409

    def test_invalid_transition_cancelled_to_settled(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        client.patch(f"{ENDPOINT}/{contract_id}/status", json={"status": "cancelled"})
        r2 = client.patch(
            f"{ENDPOINT}/{contract_id}/status", json={"status": "settled"}
        )
        assert r2.status_code == 409

    def test_transition_partially_settled_to_settled(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        client.patch(
            f"{ENDPOINT}/{contract_id}/status",
            json={"status": "partially_settled"},
        )
        r2 = client.patch(
            f"{ENDPOINT}/{contract_id}/status", json={"status": "settled"}
        )
        assert r2.status_code == 200
        assert r2.json()["status"] == "settled"


# -----------------------------------------------------------------------
# DELETE (soft delete + cancel)
# -----------------------------------------------------------------------


class TestDeleteHedgeContract:
    def test_delete_soft_deletes(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        r2 = client.delete(f"{ENDPOINT}/{contract_id}")
        assert r2.status_code == 200
        assert r2.json()["status"] == "cancelled"
        assert r2.json()["deleted_at"] is not None
        # Should not appear in default list
        r3 = client.get(ENDPOINT)
        assert all(c["id"] != contract_id for c in r3.json()["items"])

    def test_delete_appears_with_include_deleted(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        client.delete(f"{ENDPOINT}/{contract_id}")
        r2 = client.get(ENDPOINT, params={"include_deleted": True})
        ids = [c["id"] for c in r2.json()["items"]]
        assert contract_id in ids

    def test_delete_already_deleted_returns_409(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json=_make_contract_payload(cp_id))
        contract_id = r.json()["id"]
        client.delete(f"{ENDPOINT}/{contract_id}")
        r2 = client.delete(f"{ENDPOINT}/{contract_id}")
        assert r2.status_code == 409

    def test_delete_not_found(self, client):
        r = client.delete(f"{ENDPOINT}/{uuid.uuid4()}")
        assert r.status_code == 404
