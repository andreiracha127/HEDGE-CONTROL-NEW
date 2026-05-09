from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.cashflow import CashFlowBaselineSnapshot
from app.models.market_data import CashSettlementPrice
from app.services.cashflow_baseline_service import create_cashflow_baseline_snapshot


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


def _create_variable_sales_order(client, avg_entry_price: float) -> str:
    response = client.post(
        "/orders/sales",
        json={
            "price_type": "variable",
            "quantity_mt": 5.0,
            "pricing_convention": "AVG",
            "avg_entry_price": avg_entry_price,
        },
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_snapshot_creation_is_idempotent(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        first = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-1")
        second = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-2")
        assert first.id == second.id


def test_snapshot_conflict_returns_409(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-1")
        snapshot.total_net_cashflow = Decimal("999.0")
        session.commit()

    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-2")
        assert exc.value.status_code == 409


def test_query_existing_snapshot(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    response = client.post(
        "/cashflow/baseline/snapshots",
        json={"as_of_date": "2026-02-01", "correlation_id": "c-1"},
    )
    assert response.status_code == 201

    get_resp = client.get("/cashflow/baseline/snapshots", params={"as_of_date": "2026-02-01"})
    assert get_resp.status_code == 200
    assert get_resp.json()["as_of_date"] == "2026-02-01"


def test_propagate_424_if_d1_price_missing(client) -> None:
    _create_variable_sales_order(client, avg_entry_price=100.0)
    with SessionLocal() as session:
        with pytest.raises(HTTPException) as exc:
            create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 1), correlation_id="c-1")
        assert exc.value.status_code == 424


def test_cashflow_baseline_inputs_hash_is_deterministic(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        first = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 2), correlation_id="c-1")
        second = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 2), correlation_id="c-2")
        assert second.id == first.id
        assert second.inputs_hash == first.inputs_hash
        assert len(first.inputs_hash) == 64


def test_cashflow_baseline_per_row_provenance_quadruple_inside_snapshot_data(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(session, as_of_date=date(2026, 2, 2), correlation_id="c-1")
        item = snapshot.snapshot_data["cashflow_items"][0]
        assert item["price_source"] == "westmetall"
        assert item["price_symbol"] == "LME_ALU_CASH_SETTLEMENT_DAILY"
        assert item["price_settlement_date"] == "2026-01-30"
        assert item["price_value"] == "110.000000"
