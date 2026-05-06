"""Item 3.6 – Order unit tests.

Covers sales and purchase order creation, validation rules,
listing, and retrieval.
"""

import uuid


# -- helpers ----------------------------------------------------------------


def _so_variable(client, **kw):
    payload = {"price_type": "variable", "quantity_mt": 10.0, **kw}
    return client.post("/orders/sales", json=payload)


def _po_fixed(client, **kw):
    payload = {"price_type": "fixed", "quantity_mt": 5.0, **kw}
    return client.post("/orders/purchase", json=payload)


# -- tests ------------------------------------------------------------------


def test_create_sales_order_variable_without_convention(client) -> None:
    """SO variable without pricing_convention/avg_entry_price is valid."""
    resp = _so_variable(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["order_type"] == "SO"
    assert data["price_type"] == "variable"
    assert float(data["quantity_mt"]) == 10.0
    assert data["pricing_convention"] is None
    assert data["avg_entry_price"] is None
    assert "id" in data
    assert "created_at" in data


def test_create_sales_order_variable_with_convention(client) -> None:
    """SO variable with pricing_convention + avg_entry_price is valid."""
    resp = _so_variable(
        client,
        pricing_convention="AVG",
        avg_entry_price=2350.0,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["pricing_convention"] == "AVG"
    assert float(data["avg_entry_price"]) == 2350.0


def test_create_purchase_order_fixed(client) -> None:
    """PO with fixed pricing is valid."""
    resp = _po_fixed(client)
    assert resp.status_code == 201
    data = resp.json()
    assert data["order_type"] == "PO"
    assert data["price_type"] == "fixed"
    assert float(data["quantity_mt"]) == 5.0


def test_variable_convention_without_avg_entry_price_ok(client) -> None:
    """pricing_convention without avg_entry_price is valid — price determined later by market."""
    resp = _so_variable(client, pricing_convention="AVG")
    assert resp.status_code == 201
    data = resp.json()
    assert data["pricing_convention"] == "AVG"
    assert data["avg_entry_price"] is None


def test_variable_avg_entry_price_without_convention_fails(client) -> None:
    """avg_entry_price without pricing_convention → 400."""
    resp = _so_variable(client, avg_entry_price=2350.0)
    assert resp.status_code == 400
    assert "pricing_convention" in resp.json()["detail"].lower()


def test_get_order_by_id(client) -> None:
    """Created order is retrievable by UUID."""
    create_resp = _po_fixed(client)
    order_id = create_resp.json()["id"]
    get_resp = client.get(f"/orders/{order_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == order_id


def test_get_order_not_found(client) -> None:
    """GET non-existent order → 404."""
    resp = client.get(f"/orders/{uuid.uuid4()}")
    assert resp.status_code == 404


def test_list_orders_returns_created(client) -> None:
    """Listed orders include what was just created."""
    _so_variable(client)
    _po_fixed(client)
    resp = client.get("/orders")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 2


def test_list_orders_filter_by_type(client) -> None:
    """order_type filter returns the correct subset."""
    _so_variable(client)
    _po_fixed(client)
    resp_so = client.get("/orders", params={"order_type": "SO"})
    assert resp_so.status_code == 200
    assert all(o["order_type"] == "SO" for o in resp_so.json()["items"])
    assert len(resp_so.json()["items"]) == 1


def test_list_orders_filter_by_price_type(client) -> None:
    """price_type filter returns the correct subset."""
    _so_variable(client)
    _po_fixed(client)
    resp = client.get("/orders", params={"price_type": "fixed"})
    assert resp.status_code == 200
    assert all(o["price_type"] == "fixed" for o in resp.json()["items"])
    assert len(resp.json()["items"]) == 1


def test_purchase_order_variable_with_convention(client) -> None:
    """PO variable with all pricing fields is valid."""
    resp = client.post(
        "/orders/purchase",
        json={
            "price_type": "variable",
            "quantity_mt": 8.0,
            "pricing_convention": "C2R",
            "avg_entry_price": 2400.0,
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["order_type"] == "PO"
    assert data["pricing_convention"] == "C2R"
    assert float(data["avg_entry_price"]) == 2400.0


def test_order_accepts_decimal_strings(client) -> None:
    resp = client.post(
        "/orders/sales",
        json={
            "price_type": "fixed",
            "quantity_mt": "10.125",
            "avg_entry_price": "2500.123456",
        },
    )

    assert resp.status_code == 201
    data = resp.json()
    assert data["quantity_mt"] == "10.125"
    assert data["avg_entry_price"] == "2500.123456"
