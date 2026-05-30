"""Tests for Order enrichment + SoPoLink — component 1.2."""

from uuid import UUID

from app.models.audit import AuditEvent
from app.models.commercial_partner import CommercialPartner
from app.models.counterparty import KycStatus, SanctionsStatus


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
    # After W1, a Purchase Order's counterparty is a commercial supplier;
    # orders.counterparty_id FK → commercial_partners.id.
    cp = client.post(
        "/commercial-partners",
        json={"kind": "supplier", "name": "Sup1", "country": "USA"},
    )
    assert cp.status_code == 201, cp.text
    cp_id = cp.json()["id"]
    # Order binding gate requires approved commercial partners.
    from app.core.database import SessionLocal

    with SessionLocal() as session:
        db_cp = session.get(CommercialPartner, UUID(cp_id))
        db_cp.sanctions_status = SanctionsStatus.clear
        db_cp.kyc_status = KycStatus.approved
        session.commit()
    r = _create_po(client, counterparty_id=cp_id)
    assert r.status_code == 201
    assert r.json()["counterparty_id"] == cp_id


def test_create_so_rejects_unapproved_commercial_partner_and_audits(client, session):
    cp = client.post(
        "/commercial-partners",
        json={"kind": "customer", "name": "Pending Customer", "country": "BRA"},
    )
    assert cp.status_code == 201, cp.text
    cp_id = cp.json()["id"]

    r = _create_so(client, counterparty_id=cp_id)

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "order_rejected_kyc_not_approved"
    event = (
        session.query(AuditEvent)
        .filter(AuditEvent.event_type == "order_rejected_kyc_not_approved")
        .one()
    )
    assert event.entity_type == "commercial_partner"
    assert event.entity_id == UUID(cp_id)
    assert event.signature is not None


def test_create_po_rejects_customer_kind_mismatch(client):
    cp = client.post(
        "/commercial-partners",
        json={"kind": "customer", "name": "Wrong Kind", "country": "BRA"},
    )
    assert cp.status_code == 201, cp.text
    cp_id = cp.json()["id"]

    from app.core.database import SessionLocal

    with SessionLocal() as session:
        db_cp = session.get(CommercialPartner, UUID(cp_id))
        db_cp.sanctions_status = SanctionsStatus.clear
        db_cp.kyc_status = KycStatus.approved
        session.commit()

    r = _create_po(client, counterparty_id=cp_id)

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "order_rejected_kind_mismatch"


def test_create_so_rejects_hedge_counterparty_id_before_commit(client):
    cp = client.post(
        "/counterparties",
        json={"type": "broker", "name": "Broker", "country": "BRA"},
    )
    assert cp.status_code == 201, cp.text

    r = _create_so(client, counterparty_id=cp.json()["id"])

    assert r.status_code == 404


def test_create_so_rejects_missing_commercial_partner(client):
    r = _create_so(client, __skip_default_counterparty=True)

    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "order_rejected_missing_commercial_partner"


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
