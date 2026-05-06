"""Tests for Order enrichment + SoPoLink — component 1.2."""

from uuid import uuid4


def _create_so(client, **overrides):
    data = {"price_type": "fixed", "quantity_mt": 100.0, **overrides}
    return client.post("/orders/sales", json=data)


def _create_po(client, **overrides):
    data = {"price_type": "fixed", "quantity_mt": 80.0, **overrides}
    return client.post("/orders/purchase", json=data)


def test_create_so_with_new_fields(client):
    r = _create_so(
        client,
        delivery_terms="CIF Rotterdam",
        payment_terms_days=60,
        currency="EUR",
        notes="Test note",
    )
    assert r.status_code == 201
    body = r.json()
    assert body["delivery_terms"] == "CIF Rotterdam"
    assert body["payment_terms_days"] == 60
    assert body["currency"] == "EUR"
    assert body["notes"] == "Test note"


def test_create_po_with_counterparty(client):
    # Create a counterparty first
    cp = client.post(
        "/counterparties", json={"type": "supplier", "name": "Sup1", "country": "USA"}
    )
    cp_id = cp.json()["id"]
    r = _create_po(client, counterparty_id=cp_id)
    assert r.status_code == 201
    assert r.json()["counterparty_id"] == cp_id


def test_order_defaults_currency_usd(client):
    r = _create_so(client)
    assert r.status_code == 201
    assert r.json()["currency"] == "USD"


def test_create_sopo_link(client):
    so = _create_so(client).json()
    po = _create_po(client).json()
    r = client.post(
        "/orders/links",
        json={
            "sales_order_id": so["id"],
            "purchase_order_id": po["id"],
            "linked_tons": 50.0,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["sales_order_id"] == so["id"]
    assert body["purchase_order_id"] == po["id"]
    assert float(body["linked_tons"]) == 50.0


def test_sopo_link_validates_so_type(client):
    po1 = _create_po(client).json()
    po2 = _create_po(client).json()
    r = client.post(
        "/orders/links",
        json={
            "sales_order_id": po1["id"],  # wrong type
            "purchase_order_id": po2["id"],
            "linked_tons": 10.0,
        },
    )
    assert r.status_code == 400


def test_sopo_link_validates_po_type(client):
    so1 = _create_so(client).json()
    so2 = _create_so(client).json()
    r = client.post(
        "/orders/links",
        json={
            "sales_order_id": so1["id"],
            "purchase_order_id": so2["id"],  # wrong type
            "linked_tons": 10.0,
        },
    )
    assert r.status_code == 400


def test_sopo_link_duplicate_rejected(client):
    so = _create_so(client).json()
    po = _create_po(client).json()
    client.post(
        "/orders/links",
        json={
            "sales_order_id": so["id"],
            "purchase_order_id": po["id"],
            "linked_tons": 20.0,
        },
    )
    r = client.post(
        "/orders/links",
        json={
            "sales_order_id": so["id"],
            "purchase_order_id": po["id"],
            "linked_tons": 30.0,
        },
    )
    assert r.status_code == 409


def test_list_sopo_links(client):
    so = _create_so(client).json()
    po = _create_po(client).json()
    client.post(
        "/orders/links",
        json={
            "sales_order_id": so["id"],
            "purchase_order_id": po["id"],
            "linked_tons": 10.0,
        },
    )
    r = client.get("/orders/links")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1
