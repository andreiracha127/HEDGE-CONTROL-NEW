from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core.database import SessionLocal
from app.models.cashflow import CashFlowBaselineSnapshot
from app.models.cashflow import CashFlowLedgerEntry
from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus, HedgeLegSide
from app.models.market_data import CashSettlementPrice
from app.models.orders import Order, OrderPricingConvention, OrderType, PriceType
from app.models.pl import PLSnapshot


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


def _insert_contract(quantity_mt: float, entry_price: float) -> uuid4:
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


def _insert_order(quantity_mt: float) -> uuid4:
    with SessionLocal() as session:
        order = Order(
            order_type=OrderType.sales,
            price_type=PriceType.variable,
            quantity_mt=quantity_mt,
            pricing_convention=OrderPricingConvention.avg,
            avg_entry_price=100.0,
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        return order.id


def test_scenario_run_returns_outputs(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 31), price_usd=110.0)
    contract_id = _insert_contract(quantity_mt=5.0, entry_price=100.0)

    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [],
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert "commercial_exposure_snapshot" in data
    assert "global_exposure_snapshot" in data
    assert "mtm_snapshot" in data
    assert "cashflow_snapshot" in data
    assert "pl_snapshot" in data
    assert any(item["object_id"] == str(contract_id) for item in data["mtm_snapshot"])


def test_price_override_changes_mtm(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 31), price_usd=110.0)
    contract_id = _insert_contract(quantity_mt=5.0, entry_price=100.0)

    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [
                {
                    "delta_type": "add_cash_settlement_price_override",
                    "symbol": symbol,
                    "settlement_date": "2026-01-31",
                    "price_usd": "120.0"
                }
            ],
        },
    )
    assert response.status_code == 200
    mtm_item = next(item for item in response.json()["mtm_snapshot"] if item["object_id"] == str(contract_id))
    assert mtm_item["price_d1"] == "120.0"


def test_add_unlinked_contract_affects_global_exposure(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 31), price_usd=110.0)

    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [
                {
                    "delta_type": "add_unlinked_hedge_contract",
                    "contract_id": str(uuid4()),
                    "quantity_mt": "10",
                    "fixed_leg_side": "buy",
                    "variable_leg_side": "sell",
                    "fixed_price_value": "100",
                    "fixed_price_unit": "USD/MT",
                    "float_pricing_convention": "avg"
                }
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()["global_exposure_snapshot"]
    assert float(data["hedge_long_mt"]) == 10.0


def test_adjust_order_quantity_changes_exposure(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 31), price_usd=110.0)
    order_id = _insert_order(quantity_mt=5.0)

    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [
                {"delta_type": "adjust_order_quantity_mt", "order_id": str(order_id), "new_quantity_mt": "10"}
            ],
        },
    )
    assert response.status_code == 200
    data = response.json()["commercial_exposure_snapshot"]
    assert float(data["commercial_active_mt"]) == 10.0


def test_scenario_does_not_persist(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 31), price_usd=110.0)
    contract_id = _insert_contract(quantity_mt=5.0, entry_price=100.0)

    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [],
        },
    )
    assert response.status_code == 200

    with SessionLocal() as session:
        assert session.query(HedgeContract).filter(HedgeContract.id == contract_id).count() == 1
        assert session.query(CashFlowLedgerEntry).count() == 0
        assert session.query(PLSnapshot).count() == 0
        assert session.query(CashFlowBaselineSnapshot).count() == 0


def test_missing_price_hard_fails(client) -> None:
    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [],
        },
    )
    assert response.status_code == 424


def test_invalid_period_rejected(client) -> None:
    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-02-01",
            "period_end": "2026-01-01",
            "deltas": [],
        },
    )
    assert response.status_code == 422


def test_scenario_is_deterministic(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 31), price_usd=110.0)

    payload = {
        "as_of_date": "2026-02-01",
        "period_start": "2026-01-01",
        "period_end": "2026-01-31",
        "deltas": [],
    }
    first = client.post("/scenario/what-if/run", json=payload)
    second = client.post("/scenario/what-if/run", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json()


def test_virtual_contract_id_collision_is_409(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 31), price_usd=110.0)
    contract_id = _insert_contract(quantity_mt=5.0, entry_price=100.0)

    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [
                {
                    "delta_type": "add_unlinked_hedge_contract",
                    "contract_id": str(contract_id),
                    "quantity_mt": "10",
                    "fixed_leg_side": "buy",
                    "variable_leg_side": "sell",
                    "fixed_price_value": "100",
                    "fixed_price_unit": "USD/MT",
                    "float_pricing_convention": "avg"
                }
            ],
        },
    )
    assert response.status_code == 409


def test_adjust_order_unknown_id_is_404(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 31), price_usd=110.0)

    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [
                {"delta_type": "adjust_order_quantity_mt", "order_id": str(uuid4()), "new_quantity_mt": "10"}
            ],
        },
    )
    assert response.status_code == 404
