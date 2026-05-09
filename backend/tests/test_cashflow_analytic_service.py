from datetime import date, datetime, timezone
import uuid

import pytest
from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus, HedgeLegSide
from app.models.market_data import CashSettlementPrice
from app.services.cashflow_analytic_service import compute_cashflow_analytic


def _insert_price(settlement_date: date, price_usd: float) -> None:
    with SessionLocal() as session:
        session.add(
            CashSettlementPrice(
                source="westmetall",
                symbol="LME_ALU_CASH_SETTLEMENT_DAILY",
                settlement_date=settlement_date,
                price_usd=price_usd,
                source_url="https://example.test/source",
                html_sha256="0" * 64,
                fetched_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
        )
        session.commit()


def _insert_active_contract(quantity_mt: float, entry_price: float) -> uuid.UUID:
    with SessionLocal() as session:
        contract = HedgeContract(
            commodity="LME_AL",
            quantity_mt=quantity_mt,
            fixed_leg_side=HedgeLegSide.buy,
            variable_leg_side=HedgeLegSide.sell,
            classification=HedgeClassification.long,
            fixed_price_value=entry_price,
            fixed_price_unit="USD/MT",
            float_pricing_convention="avg",
            status=HedgeContractStatus.active,
        )
        session.add(contract)
        session.commit()
        session.refresh(contract)
        return contract.id


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


def test_aggregate_hedge_contract_cashflows(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract_id = _insert_active_contract(quantity_mt=5.0, entry_price=100.0)

    with SessionLocal() as session:
        response = compute_cashflow_analytic(session, as_of_date=date(2026, 2, 1))
        ids = {item.object_id for item in response.cashflow_items if item.object_type == "hedge_contract"}
        assert str(contract_id) in ids
        assert response.total_net_cashflow != 0


def test_aggregate_order_cashflows(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    order_id = _create_variable_sales_order(client, "AVG", avg_entry_price=100.0)

    with SessionLocal() as session:
        response = compute_cashflow_analytic(session, as_of_date=date(2026, 2, 1))
        ids = {item.object_id for item in response.cashflow_items if item.object_type == "order"}
        assert order_id in ids


def test_exclude_fixed_price_orders(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    fixed_id = _create_fixed_sales_order(client)

    with SessionLocal() as session:
        response = compute_cashflow_analytic(session, as_of_date=date(2026, 2, 1))
        ids = {item.object_id for item in response.cashflow_items}
        assert fixed_id not in ids


def test_missing_d1_price_propagates_http_424(client) -> None:
    _create_variable_sales_order(client, "AVG", avg_entry_price=100.0)
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            compute_cashflow_analytic(session, as_of_date=date(2026, 2, 1))
        assert exc.value.status_code == 424


def test_compute_cashflow_analytic_populates_provenance_on_priced_items(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    contract_id = _insert_active_contract(quantity_mt=5.0, entry_price=100.0)

    with SessionLocal() as session:
        response = compute_cashflow_analytic(session, as_of_date=date(2026, 2, 2))
        item = next(item for item in response.cashflow_items if item.object_id == str(contract_id))
        assert item.price_source == "westmetall"
        assert item.price_symbol == "LME_ALU_CASH_SETTLEMENT_DAILY"
        assert item.price_settlement_date == date(2026, 1, 30)
        assert item.price_value == 110


def test_compute_cashflow_analytic_leaves_provenance_none_for_non_priced_items(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    fixed_id = _create_fixed_sales_order(client)

    with SessionLocal() as session:
        response = compute_cashflow_analytic(session, as_of_date=date(2026, 2, 2))
        ids = {item.object_id for item in response.cashflow_items}
        assert fixed_id not in ids
        assert all(
            item.price_source is None
            or (
                item.price_symbol is not None
                and item.price_settlement_date is not None
                and item.price_value is not None
            )
            for item in response.cashflow_items
        )
