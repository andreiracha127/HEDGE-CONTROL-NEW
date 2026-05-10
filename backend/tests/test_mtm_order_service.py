from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.market_data import CashSettlementPrice
from app.models.mtm import MTMObjectType, MTMSnapshot
from app.models.orders import Order, OrderPricingConvention, OrderType, PriceType
from app.services.mtm_order_service import compute_mtm_for_order
from app.services.mtm_snapshot_service import create_mtm_snapshot_for_order
from app.services.price_lookup_service import resolve_symbol


def _insert_price(symbol: str, settlement_date: date, price_usd: float) -> None:
    with SessionLocal() as session:
        session.add(
            CashSettlementPrice(
                source="westmetall",
                symbol=symbol,
                settlement_date=settlement_date,
                price_usd=price_usd,
                source_url="https://example.test/source",
                html_sha256="0" * 64,
                fetched_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()


def _create_variable_sales_order(client, convention: str, avg_entry_price: float) -> str:
    response = client.post(
        "/orders/sales",
        json={
            "price_type": "variable",
            "quantity_mt": 5.0,
            "pricing_convention": convention,
            "avg_entry_price": avg_entry_price,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def _create_fixed_sales_order(client) -> str:
    response = client.post("/orders/sales", json={"price_type": "fixed", "quantity_mt": 5.0})
    assert response.status_code == 201
    return response.json()["id"]


def _insert_variable_order(
    commodity: str,
    quantity_mt: Decimal = Decimal("10.0"),
    avg_entry_price: Decimal = Decimal("9000.0"),
) -> UUID:
    with SessionLocal() as session:
        order = Order(
            order_type=OrderType.sales,
            price_type=PriceType.variable,
            commodity=commodity,
            quantity_mt=quantity_mt,
            pricing_convention=OrderPricingConvention.avg,
            avg_entry_price=avg_entry_price,
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        return order.id


def test_mtm_for_avg_order(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", settlement_date=date(2026, 1, 30), price_usd=110.0)
    order_id = _create_variable_sales_order(client, "AVG", avg_entry_price=100.0)

    with SessionLocal() as session:
        result = compute_mtm_for_order(session, order_id=UUID(order_id), as_of_date=date(2026, 2, 1))
        assert result.object_type.value == MTMObjectType.order.value
        assert result.price_d1 == Decimal("110.0")
        assert result.entry_price == Decimal("100.0")
        assert result.mtm_value == Decimal("50.00")


def test_mtm_for_c2r_order(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", settlement_date=date(2026, 1, 30), price_usd=90.0)
    order_id = _create_variable_sales_order(client, "C2R", avg_entry_price=100.0)

    with SessionLocal() as session:
        result = compute_mtm_for_order(session, order_id=UUID(order_id), as_of_date=date(2026, 2, 1))
        assert result.mtm_value == Decimal("-50.00")


def test_compute_mtm_for_order_uses_order_commodity_not_default() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", settlement_date=date(2026, 1, 30), price_usd=2400.0)
    _insert_price("LME_CU_CASH_SETTLEMENT_DAILY", settlement_date=date(2026, 1, 30), price_usd=9500.0)
    order_id = _insert_variable_order(
        commodity="COPPER",
        quantity_mt=Decimal("10.0"),
        avg_entry_price=Decimal("9000.0"),
    )

    with SessionLocal() as session:
        result = compute_mtm_for_order(session, order_id=order_id, as_of_date=date(2026, 2, 1))

    assert result.price_quote is not None
    assert result.price_quote.symbol == resolve_symbol("COPPER")
    assert result.price_d1 == Decimal("9500.0")
    assert result.mtm_value == Decimal("5000.00")


def test_compute_mtm_for_order_function_signature_does_not_accept_commodity_kwarg() -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", settlement_date=date(2026, 1, 30), price_usd=2400.0)
    order_id = _insert_variable_order(
        commodity="ALUMINUM",
        quantity_mt=Decimal("10.0"),
        avg_entry_price=Decimal("2300.0"),
    )

    with SessionLocal() as session:
        with pytest.raises(TypeError):
            compute_mtm_for_order(
                session,
                order_id=order_id,
                as_of_date=date(2026, 2, 1),
                commodity="LME_AL",
            )


def test_exclude_fixed_price_orders(client) -> None:
    order_id = _create_fixed_sales_order(client)
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            compute_mtm_for_order(session, order_id=UUID(order_id), as_of_date=date(2026, 2, 1))
        assert exc.value.status_code == 409


def test_missing_d1_price_hard_fails_424(client) -> None:
    order_id = _create_variable_sales_order(client, "AVGInter", avg_entry_price=100.0)
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            compute_mtm_for_order(session, order_id=UUID(order_id), as_of_date=date(2026, 2, 1))
        assert exc.value.status_code == 424


def test_snapshot_creation_for_order_idempotent(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", settlement_date=date(2026, 1, 30), price_usd=110.0)
    order_id = _create_variable_sales_order(client, "AVG", avg_entry_price=100.0)

    with SessionLocal() as session:
        first = create_mtm_snapshot_for_order(
            session, order_id=UUID(order_id), as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )
        second = create_mtm_snapshot_for_order(
            session, order_id=UUID(order_id), as_of_date=date(2026, 2, 1), correlation_id="c-2"
        )
        assert first.id == second.id


def test_snapshot_conflict_for_order_409(client) -> None:
    _insert_price("LME_ALU_CASH_SETTLEMENT_DAILY", settlement_date=date(2026, 1, 30), price_usd=110.0)
    order_id = _create_variable_sales_order(client, "AVG", avg_entry_price=100.0)
    order_uuid = UUID(order_id)

    with SessionLocal() as session:
        session.add(
            MTMSnapshot(
                object_type=MTMObjectType.order,
                object_id=order_uuid,
                as_of_date=date(2026, 2, 1),
                mtm_value=Decimal("999.0"),
                price_d1=Decimal("110.0"),
                entry_price=Decimal("100.0"),
                quantity_mt=Decimal("5.0"),
                correlation_id="c-x",
            )
        )
        session.commit()

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            create_mtm_snapshot_for_order(session, order_id=order_uuid, as_of_date=date(2026, 2, 1), correlation_id="c-y")
        assert exc.value.status_code == 409
