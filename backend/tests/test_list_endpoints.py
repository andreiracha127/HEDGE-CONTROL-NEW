"""Tests for list endpoints with cursor-based pagination (Item 2.2)."""

import time
from uuid import uuid4
from datetime import datetime, timezone


# ── Helpers ────────────────────────────────────────────────────────────


def _create_order(
    client, route: str = "sales", quantity: float = 10.0, price_type: str = "variable"
):
    """Create an order via the proper /orders/sales or /orders/purchase route."""
    return client.post(
        f"/orders/{route}",
        json={
            "price_type": price_type,
            "quantity_mt": quantity,
        },
    )


def _create_contract(client, side_buy: str = "buy", commodity: str = "LME_AL"):
    return client.post(
        "/contracts/hedge",
        json={
            "commodity": commodity,
            "quantity_mt": 5.0,
            "legs": [
                {"side": side_buy, "price_type": "fixed"},
                {
                    "side": "sell" if side_buy == "buy" else "buy",
                    "price_type": "variable",
                },
            ],
        },
    )


def _create_rfq(
    client,
    intent: str = "GLOBAL_POSITION",
    direction: str = "BUY",
    commodity: str = "LME_AL",
    with_invitation: bool = False,
):
    """Create an RFQ. Uses GLOBAL_POSITION intent to avoid needing commercial exposure."""
    invitations = []
    if with_invitation:
        cp_resp = client.post(
            "/counterparties",
            json={
                "type": "broker",
                "name": f"CP-{uuid4().hex[:8]}",
                "country": "BRA",
                "whatsapp_phone": "+5511999990001",
            },
        )
        assert cp_resp.status_code == 201
        invitations = [{"counterparty_id": cp_resp.json()["id"]}]
    return client.post(
        "/rfqs",
        json={
            "intent": intent,
            "commodity": commodity,
            "quantity_mt": 10.0,
            "delivery_window_start": "2025-01-01",
            "delivery_window_end": "2025-06-30",
            "direction": direction,
            "order_id": None,
            "invitations": invitations,
        },
    )


# ── GET /orders ────────────────────────────────────────────────────────


class TestListOrders:
    def test_empty_list(self, client):
        resp = client.get("/orders")
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["next_cursor"] is None

    def test_list_returns_created_orders(self, client):
        _create_order(client, route="sales")
        _create_order(client, route="purchase")
        resp = client.get("/orders")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    def test_filter_by_order_type(self, client):
        _create_order(client, route="sales")
        _create_order(client, route="purchase")
        resp = client.get("/orders", params={"order_type": "SO"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["order_type"] == "SO"

    def test_filter_by_price_type(self, client):
        _create_order(client, price_type="fixed")
        _create_order(client, price_type="variable")
        resp = client.get("/orders", params={"price_type": "fixed"})
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["price_type"] == "fixed"

    def test_pagination_cursor(self, client):
        for i in range(3):
            _create_order(client)
            if i < 2:
                time.sleep(1.1)  # force distinct created_at (SQLite second precision)
        resp = client.get("/orders", params={"limit": 2})
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["next_cursor"] is not None

        resp2 = client.get(
            "/orders", params={"limit": 2, "cursor": body["next_cursor"]}
        )
        body2 = resp2.json()
        assert len(body2["items"]) == 1
        assert body2["next_cursor"] is None

        # No overlap
        ids_page1 = {i["id"] for i in body["items"]}
        ids_page2 = {i["id"] for i in body2["items"]}
        assert ids_page1.isdisjoint(ids_page2)


# ── GET /contracts/hedge ───────────────────────────────────────────────


class TestListContracts:
    def test_empty_list(self, client):
        resp = client.get("/contracts/hedge")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_list_returns_contracts(self, client):
        _create_contract(client, side_buy="buy")
        _create_contract(client, side_buy="sell")
        resp = client.get("/contracts/hedge")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 2

    def test_filter_by_commodity(self, client):
        _create_contract(client, commodity="LME_AL")
        _create_contract(client, commodity="LME_CU")
        resp = client.get("/contracts/hedge", params={"commodity": "LME_AL"})
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["commodity"] == "LME_AL"

    def test_filter_by_classification(self, client):
        # buy fixed → long, sell fixed → short
        _create_contract(client, side_buy="buy")  # long
        _create_contract(client, side_buy="sell")  # short
        resp = client.get("/contracts/hedge", params={"classification": "long"})
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["classification"] == "long"

    def test_pagination_cursor(self, client):
        for i in range(3):
            _create_contract(client)
            if i < 2:
                time.sleep(1.1)  # force distinct created_at (SQLite second precision)
        resp = client.get("/contracts/hedge", params={"limit": 2})
        body = resp.json()
        assert len(body["items"]) == 2
        assert body["next_cursor"] is not None

        resp2 = client.get(
            "/contracts/hedge", params={"limit": 2, "cursor": body["next_cursor"]}
        )
        body2 = resp2.json()
        assert len(body2["items"]) == 1
        assert body2["next_cursor"] is None


# ── GET /rfqs ──────────────────────────────────────────────────────────


class TestListRFQs:
    def test_empty_list(self, client):
        resp = client.get("/rfqs")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_list_returns_rfqs(self, client):
        r = _create_rfq(client)
        assert r.status_code == 201, r.json()
        resp = client.get("/rfqs")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1

    def test_filter_by_direction(self, client):
        r = _create_rfq(client, direction="BUY")
        assert r.status_code == 201, r.json()
        resp = client.get("/rfqs", params={"direction": "BUY"})
        items = resp.json()["items"]
        assert len(items) >= 1
        assert all(i["direction"] == "BUY" for i in items)


# ── GET /rfqs/{id}/quotes ─────────────────────────────────────────────


class TestListRFQQuotes:
    def test_quotes_empty(self, client):
        create_resp = _create_rfq(client, with_invitation=True)
        assert create_resp.status_code == 201, create_resp.json()
        rfq_id = create_resp.json()["id"]
        resp = client.get(f"/rfqs/{rfq_id}/quotes")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_quotes_after_submit(self, client):
        create_resp = _create_rfq(client, with_invitation=True)
        assert create_resp.status_code == 201, create_resp.json()
        rfq_id = create_resp.json()["id"]
        cp_id = create_resp.json()["invitations"][0]["counterparty_id"]

        # Submit a quote
        quote_resp = client.post(
            f"/rfqs/{rfq_id}/quotes",
            json={
                "rfq_id": rfq_id,
                "counterparty_id": cp_id,
                "fixed_price_value": "2550.000000",
                "fixed_price_unit": "USD/MT",
                "float_pricing_convention": "avg",
                "received_at": "2025-01-15T10:00:00Z",
            },
        )
        assert quote_resp.status_code == 201

        resp = client.get(f"/rfqs/{rfq_id}/quotes")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_quotes_not_found_rfq(self, client):
        fake_id = str(uuid4())
        resp = client.get(f"/rfqs/{fake_id}/quotes")
        assert resp.status_code == 404


# ── GET /linkages ──────────────────────────────────────────────────────


class TestListLinkages:
    def test_empty_list(self, client):
        resp = client.get("/linkages")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_list_with_linkage(self, client):
        order_resp = _create_order(client, route="sales", quantity=100.0)
        assert order_resp.status_code == 201
        order_id = order_resp.json()["id"]

        contract_resp = _create_contract(client, side_buy="sell")  # short → active
        assert contract_resp.status_code == 201
        contract_id = contract_resp.json()["id"]

        link_resp = client.post(
            "/linkages",
            json={
                "order_id": order_id,
                "contract_id": contract_id,
                "quantity_mt": 5.0,
            },
        )
        assert link_resp.status_code == 201

        resp = client.get("/linkages")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    def test_filter_by_order_id(self, client):
        o1 = _create_order(client, route="sales", quantity=100.0)
        o2 = _create_order(client, route="sales", quantity=100.0)
        c1 = _create_contract(client, side_buy="sell")
        c2 = _create_contract(client, side_buy="sell")

        order1_id = o1.json()["id"]
        order2_id = o2.json()["id"]
        contract1_id = c1.json()["id"]
        contract2_id = c2.json()["id"]

        client.post(
            "/linkages",
            json={
                "order_id": order1_id,
                "contract_id": contract1_id,
                "quantity_mt": 2.0,
            },
        )
        client.post(
            "/linkages",
            json={
                "order_id": order2_id,
                "contract_id": contract2_id,
                "quantity_mt": 3.0,
            },
        )

        resp = client.get("/linkages", params={"order_id": order1_id})
        items = resp.json()["items"]
        assert len(items) == 1
        assert items[0]["order_id"] == order1_id
