"""Unit tests for OrderService (A.2).

Exercises all business logic now extracted into the service layer,
ensuring the route can stay thin.
"""

import uuid

import pytest
from fastapi import status
from sqlalchemy.orm import Session

from app.models.orders import Order, OrderType, PriceType, SoPoLink
from app.schemas.orders import (
    PurchaseOrderCreate,
    SalesOrderCreate,
    SoPoLinkCreate,
)
from app.services.order_service import OrderService


# ── helpers ──────────────────────────────────────────────────────────────


def _so_payload(**kw) -> SalesOrderCreate:
    defaults = {"commodity": "ALUMINUM", "price_type": "fixed", "quantity_mt": 100.0}
    defaults.update(kw)
    return SalesOrderCreate(**defaults)


def _po_payload(**kw) -> PurchaseOrderCreate:
    defaults = {"commodity": "ALUMINUM", "price_type": "fixed", "quantity_mt": 50.0}
    defaults.update(kw)
    return PurchaseOrderCreate(**defaults)


# ── Sales Order creation ─────────────────────────────────────────────────


def test_create_sales_order_fixed(session: Session) -> None:
    order = OrderService.create_sales_order(session, _so_payload())
    assert order.order_type == OrderType.sales
    assert order.price_type == PriceType.fixed
    assert order.quantity_mt == 100.0
    assert order.id is not None


def test_create_sales_order_variable_no_convention(session: Session) -> None:
    order = OrderService.create_sales_order(session, _so_payload(price_type="variable"))
    assert order.order_type == OrderType.sales
    assert order.pricing_convention is None
    assert order.avg_entry_price is None


def test_create_sales_order_variable_with_convention(session: Session) -> None:
    order = OrderService.create_sales_order(
        session,
        _so_payload(
            price_type="variable",
            pricing_convention="AVG",
            avg_entry_price=2350.0,
        ),
    )
    assert order.pricing_convention is not None
    assert order.avg_entry_price == 2350.0


def test_create_sales_order_variable_convention_without_price_ok(
    session: Session,
) -> None:
    """Variable order with convention but no price is valid — price determined later by market."""
    order = OrderService.create_sales_order(
        session, _so_payload(price_type="variable", pricing_convention="AVG")
    )
    assert order.pricing_convention is not None
    assert order.avg_entry_price is None


def test_create_sales_order_variable_mismatched_avg_fails(session: Session) -> None:
    with pytest.raises(Exception) as exc_info:
        OrderService.create_sales_order(
            session, _so_payload(price_type="variable", avg_entry_price=2350.0)
        )
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


# ── Purchase Order creation ──────────────────────────────────────────────


def test_create_purchase_order_fixed(session: Session) -> None:
    order = OrderService.create_purchase_order(session, _po_payload())
    assert order.order_type == OrderType.purchase
    assert order.price_type == PriceType.fixed
    assert order.quantity_mt == 50.0


def test_create_purchase_order_variable_with_convention(session: Session) -> None:
    order = OrderService.create_purchase_order(
        session,
        _po_payload(
            price_type="variable",
            pricing_convention="C2R",
            avg_entry_price=2400.0,
        ),
    )
    assert order.order_type == OrderType.purchase
    assert order.avg_entry_price == 2400.0


# ── Default values ───────────────────────────────────────────────────────


def test_order_defaults_currency_usd(session: Session) -> None:
    order = OrderService.create_sales_order(session, _so_payload())
    assert order.currency == "USD"


def test_order_custom_currency(session: Session) -> None:
    order = OrderService.create_sales_order(session, _so_payload(currency="EUR"))
    assert order.currency == "EUR"


def test_order_optional_fields(session: Session) -> None:
    order = OrderService.create_sales_order(
        session,
        _so_payload(
            delivery_terms="CIF Rotterdam",
            payment_terms_days=60,
            notes="test note",
        ),
    )
    assert order.delivery_terms == "CIF Rotterdam"
    assert order.payment_terms_days == 60
    assert order.notes == "test note"


# ── list_orders ──────────────────────────────────────────────────────────


def test_list_returns_created(session: Session) -> None:
    OrderService.create_sales_order(session, _so_payload())
    OrderService.create_purchase_order(session, _po_payload())
    result = OrderService.list_orders(session)
    assert len(result.items) == 2


def test_list_filter_by_order_type(session: Session) -> None:
    OrderService.create_sales_order(session, _so_payload())
    OrderService.create_purchase_order(session, _po_payload())
    result = OrderService.list_orders(session, order_type="SO")
    assert len(result.items) == 1
    assert all(o.order_type == "SO" for o in result.items)


def test_list_filter_by_price_type(session: Session) -> None:
    OrderService.create_sales_order(session, _so_payload(price_type="variable"))
    OrderService.create_purchase_order(session, _po_payload(price_type="fixed"))
    result = OrderService.list_orders(session, price_type="fixed")
    assert len(result.items) == 1
    assert result.items[0].price_type == "fixed"


def test_list_excludes_deleted_by_default(session: Session) -> None:
    order = OrderService.create_sales_order(session, _so_payload())
    OrderService.archive(session, order.id)
    result = OrderService.list_orders(session)
    assert len(result.items) == 0


def test_list_includes_deleted_when_requested(session: Session) -> None:
    order = OrderService.create_sales_order(session, _so_payload())
    OrderService.archive(session, order.id)
    result = OrderService.list_orders(session, include_deleted=True)
    assert len(result.items) == 1


def test_list_respects_limit(session: Session) -> None:
    for _ in range(5):
        OrderService.create_sales_order(session, _so_payload())
    result = OrderService.list_orders(session, limit=2)
    assert len(result.items) == 2


# ── get_by_id ────────────────────────────────────────────────────────────


def test_get_by_id_returns_order(session: Session) -> None:
    order = OrderService.create_sales_order(session, _so_payload())
    fetched = OrderService.get_by_id(session, order.id)
    assert fetched.id == order.id


def test_get_by_id_raises_404(session: Session) -> None:
    with pytest.raises(Exception) as exc_info:
        OrderService.get_by_id(session, uuid.uuid4())
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ── archive ──────────────────────────────────────────────────────────────


def test_archive_sets_deleted_at(session: Session) -> None:
    order = OrderService.create_sales_order(session, _so_payload())
    archived = OrderService.archive(session, order.id)
    assert archived.deleted_at is not None


def test_archive_already_archived_raises_409(session: Session) -> None:
    order = OrderService.create_sales_order(session, _so_payload())
    OrderService.archive(session, order.id)
    with pytest.raises(Exception) as exc_info:
        OrderService.archive(session, order.id)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT


def test_archive_nonexistent_raises_404(session: Session) -> None:
    with pytest.raises(Exception) as exc_info:
        OrderService.archive(session, uuid.uuid4())
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# ── SO↔PO Links ──────────────────────────────────────────────────────────


def _make_so_po(session: Session):
    so = OrderService.create_sales_order(session, _so_payload())
    po = OrderService.create_purchase_order(session, _po_payload())
    return so, po


def test_create_sopo_link(session: Session) -> None:
    so, po = _make_so_po(session)
    link = OrderService.create_sopo_link(
        session,
        SoPoLinkCreate(
            sales_order_id=so.id,
            purchase_order_id=po.id,
            linked_tons=25.0,
        ),
    )
    assert link.sales_order_id == so.id
    assert link.purchase_order_id == po.id
    assert float(link.linked_tons) == 25.0


def test_sopo_link_validates_so_type(session: Session) -> None:
    po1 = OrderService.create_purchase_order(session, _po_payload())
    po2 = OrderService.create_purchase_order(session, _po_payload())
    with pytest.raises(Exception) as exc_info:
        OrderService.create_sopo_link(
            session,
            SoPoLinkCreate(
                sales_order_id=po1.id,
                purchase_order_id=po2.id,
                linked_tons=10.0,
            ),
        )
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_sopo_link_validates_po_type(session: Session) -> None:
    so1 = OrderService.create_sales_order(session, _so_payload())
    so2 = OrderService.create_sales_order(session, _so_payload())
    with pytest.raises(Exception) as exc_info:
        OrderService.create_sopo_link(
            session,
            SoPoLinkCreate(
                sales_order_id=so1.id,
                purchase_order_id=so2.id,
                linked_tons=10.0,
            ),
        )
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_sopo_link_duplicate_raises_409(session: Session) -> None:
    so, po = _make_so_po(session)
    payload = SoPoLinkCreate(
        sales_order_id=so.id,
        purchase_order_id=po.id,
        linked_tons=10.0,
    )
    OrderService.create_sopo_link(session, payload)
    with pytest.raises(Exception) as exc_info:
        OrderService.create_sopo_link(session, payload)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT


def test_sopo_link_nonexistent_so_raises_400(session: Session) -> None:
    po = OrderService.create_purchase_order(session, _po_payload())
    with pytest.raises(Exception) as exc_info:
        OrderService.create_sopo_link(
            session,
            SoPoLinkCreate(
                sales_order_id=uuid.uuid4(),
                purchase_order_id=po.id,
                linked_tons=10.0,
            ),
        )
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_list_sopo_links(session: Session) -> None:
    so, po = _make_so_po(session)
    OrderService.create_sopo_link(
        session,
        SoPoLinkCreate(
            sales_order_id=so.id,
            purchase_order_id=po.id,
            linked_tons=10.0,
        ),
    )
    result = OrderService.list_sopo_links(session)
    assert len(result.items) == 1
