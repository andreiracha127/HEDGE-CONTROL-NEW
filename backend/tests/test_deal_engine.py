"""Tests for Deal Engine — component 1.5."""

import uuid
from datetime import date

from sqlalchemy.orm import Session

from app.models.counterparty import Counterparty
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.orders import Order, OrderType, PriceType


ENDPOINT = "/deals"


def _create_counterparty(session: Session) -> uuid.UUID:
    cp = Counterparty(
        type="customer", name=f"Cpty-{uuid.uuid4().hex[:6]}", country="BRA"
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp.id


def _create_order(
    session: Session, order_type: OrderType, qty: float = 100.0, price: float = 2500.0
) -> uuid.UUID:
    order = Order(
        order_type=order_type,
        price_type=PriceType.fixed,
        quantity_mt=qty,
        avg_entry_price=price,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order.id


def _create_hedge(
    session: Session, cp_id: uuid.UUID, tons: float = 100.0, premium: float = 5.0
) -> uuid.UUID:
    contract = HedgeContract(
        reference=f"HC-{uuid.uuid4().hex[:8].upper()}",
        counterparty_id=str(cp_id),
        commodity="ALUMINUM",
        quantity_mt=tons,
        fixed_price_value=2450.0,
        fixed_price_unit="USD/MT",
        fixed_leg_side=HedgeLegSide.buy,
        variable_leg_side=HedgeLegSide.sell,
        classification=HedgeClassification.long,
        premium_discount=premium,
        settlement_date=date(2025, 9, 30),
        trade_date=date.today(),
        status=HedgeContractStatus.active,
        source_type="manual",
    )
    session.add(contract)
    session.commit()
    session.refresh(contract)
    return contract.id


def _create_hedge_short(
    session: Session, cp_id: uuid.UUID, tons: float = 100.0, premium: float = 5.0
) -> uuid.UUID:
    """Create a sell/short hedge (compatible with SO direction)."""
    contract = HedgeContract(
        reference=f"HC-{uuid.uuid4().hex[:8].upper()}",
        counterparty_id=str(cp_id),
        commodity="ALUMINUM",
        quantity_mt=tons,
        fixed_price_value=2450.0,
        fixed_price_unit="USD/MT",
        fixed_leg_side=HedgeLegSide.sell,
        variable_leg_side=HedgeLegSide.buy,
        classification=HedgeClassification.short,
        premium_discount=premium,
        settlement_date=date(2025, 9, 30),
        trade_date=date.today(),
        status=HedgeContractStatus.active,
        source_type="manual",
    )
    session.add(contract)
    session.commit()
    session.refresh(contract)
    return contract.id


# -----------------------------------------------------------------------
# CREATE DEAL
# -----------------------------------------------------------------------


class TestCreateDeal:
    def test_create_deal_success(self, client):
        payload = {"name": "Deal Alpha", "commodity": "ALUMINUM"}
        r = client.post(ENDPOINT, json=payload)
        assert r.status_code == 201
        body = r.json()
        assert body["name"] == "Deal Alpha"
        assert body["commodity"] == "ALUMINUM"
        assert body["status"] == "open"
        assert body["reference"].startswith("D-")
        assert body["total_physical_tons"] == "0.000"
        assert body["total_hedge_tons"] == "0.000"
        assert body["hedge_ratio"] == "0.00"

    def test_create_deal_with_initial_links(self, client, session):
        so_id = _create_order(session, OrderType.sales, 200.0)
        payload = {
            "name": "Deal Beta",
            "commodity": "ALUMINUM",
            "links": [
                {"linked_type": "sales_order", "linked_id": str(so_id)},
            ],
        }
        r = client.post(ENDPOINT, json=payload)
        assert r.status_code == 201
        body = r.json()
        assert body["total_physical_tons"] == "200.000"


# -----------------------------------------------------------------------
# LIST
# -----------------------------------------------------------------------


class TestListDeals:
    def test_list_empty(self, client):
        r = client.get(ENDPOINT)
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_list_returns_created(self, client):
        client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        client.post(ENDPOINT, json={"name": "D2", "commodity": "COPPER"})
        r = client.get(ENDPOINT)
        assert len(r.json()["items"]) == 2

    def test_list_filter_by_commodity(self, client):
        client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        client.post(ENDPOINT, json={"name": "D2", "commodity": "COPPER"})
        r = client.get(ENDPOINT, params={"commodity": "COPPER"})
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["commodity"] == "COPPER"


# -----------------------------------------------------------------------
# GET DETAIL
# -----------------------------------------------------------------------


class TestGetDeal:
    def test_get_by_id(self, client):
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        r2 = client.get(f"{ENDPOINT}/{deal_id}")
        assert r2.status_code == 200
        body = r2.json()
        assert body["id"] == deal_id
        assert body["links"] == []
        assert body["latest_pnl"] is None

    def test_get_not_found(self, client):
        r = client.get(f"{ENDPOINT}/{uuid.uuid4()}")
        assert r.status_code == 404


# -----------------------------------------------------------------------
# ADD / REMOVE LINKS
# -----------------------------------------------------------------------


class TestDealLinks:
    def test_add_link(self, client, session):
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(session, OrderType.sales, 150.0)
        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={
                "linked_type": "sales_order",
                "linked_id": str(so_id),
            },
        )
        assert r2.status_code == 201
        assert r2.json()["linked_type"] == "sales_order"

        # Verify deal tons updated
        r3 = client.get(f"{ENDPOINT}/{deal_id}")
        assert r3.json()["total_physical_tons"] == "150.000"

    def test_add_duplicate_link_fails(self, client, session):
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(session, OrderType.sales)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={
                "linked_type": "sales_order",
                "linked_id": str(so_id),
            },
        )
        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={
                "linked_type": "sales_order",
                "linked_id": str(so_id),
            },
        )
        assert r2.status_code == 409

    def test_remove_link(self, client, session):
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(session, OrderType.sales, 100.0)
        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={
                "linked_type": "sales_order",
                "linked_id": str(so_id),
            },
        )
        link_id = r2.json()["id"]
        r3 = client.delete(f"{ENDPOINT}/{deal_id}/links/{link_id}")
        assert r3.status_code == 204

        # Verify tons reset
        r4 = client.get(f"{ENDPOINT}/{deal_id}")
        assert r4.json()["total_physical_tons"] == "0.000"

    def test_hedge_link_updates_hedge_tons(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]

        # Add variable-price sales order (only variable orders can be hedged)
        so = Order(
            order_type=OrderType.sales,
            price_type=PriceType.variable,
            quantity_mt=200.0,
        )
        session.add(so)
        session.commit()
        session.refresh(so)
        so_id = so.id

        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={
                "linked_type": "sales_order",
                "linked_id": str(so_id),
            },
        )

        # Add sell/short hedge (matches SO direction)
        hedge_id = _create_hedge_short(session, cp_id, tons=100.0)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={
                "linked_type": "hedge",
                "linked_id": str(hedge_id),
            },
        )

        r3 = client.get(f"{ENDPOINT}/{deal_id}")
        body = r3.json()
        assert body["total_hedge_tons"] == "100.000"
        assert body["hedge_ratio"] == "0.50"
        assert body["status"] == "partially_hedged"


# -----------------------------------------------------------------------
# P&L SNAPSHOT
# -----------------------------------------------------------------------


class TestPNLSnapshot:
    def test_pnl_snapshot_basic(self, client, session):
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]

        so_id = _create_order(session, OrderType.sales, 100.0, 2600.0)
        po_id = _create_order(session, OrderType.purchase, 100.0, 2400.0)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "purchase_order", "linked_id": str(po_id)},
        )

        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot", params={"snapshot_date": "2025-07-01"}
        )
        assert r2.status_code == 201
        body = r2.json()
        # revenue = 100 * 2600 = 260000, cost = 100 * 2400 = 240000
        assert body["physical_revenue"] == "260000.000000"
        assert body["physical_cost"] == "240000.000000"
        assert body["total_pnl"] == "20000.000000"

    def test_pnl_snapshot_idempotent(self, client):
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        r2 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot", params={"snapshot_date": "2025-07-01"}
        )
        snap_id_1 = r2.json()["id"]
        r3 = client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot", params={"snapshot_date": "2025-07-01"}
        )
        snap_id_2 = r3.json()["id"]
        assert snap_id_1 == snap_id_2  # same snapshot returned

    def test_pnl_history(self, client):
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot", params={"snapshot_date": "2025-07-01"}
        )
        client.post(
            f"{ENDPOINT}/{deal_id}/pnl-snapshot", params={"snapshot_date": "2025-07-02"}
        )
        r2 = client.get(f"{ENDPOINT}/{deal_id}/pnl-history")
        assert r2.status_code == 200
        assert len(r2.json()["items"]) == 2


# -----------------------------------------------------------------------
# STATUS BASED ON HEDGE RATIO
# -----------------------------------------------------------------------


class TestDealStatus:
    def test_status_open_no_hedges(self, client, session):
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]
        so_id = _create_order(session, OrderType.sales, 100.0)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so_id)},
        )
        r2 = client.get(f"{ENDPOINT}/{deal_id}")
        assert r2.json()["status"] == "open"

    def test_status_fully_hedged(self, client, session):
        cp_id = _create_counterparty(session)
        r = client.post(ENDPOINT, json={"name": "D1", "commodity": "ALUMINUM"})
        deal_id = r.json()["id"]

        # Variable-price SO (only variable orders can be hedged)
        so = Order(
            order_type=OrderType.sales,
            price_type=PriceType.variable,
            quantity_mt=100.0,
        )
        session.add(so)
        session.commit()
        session.refresh(so)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "sales_order", "linked_id": str(so.id)},
        )

        # Sell/short hedge (matches SO direction)
        hedge_id = _create_hedge_short(session, cp_id, tons=100.0)
        client.post(
            f"{ENDPOINT}/{deal_id}/links",
            json={"linked_type": "hedge", "linked_id": str(hedge_id)},
        )

        r2 = client.get(f"{ENDPOINT}/{deal_id}")
        assert r2.json()["status"] == "fully_hedged"
        assert r2.json()["hedge_ratio"] == "1.00"
