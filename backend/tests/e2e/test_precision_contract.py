"""Precision contract checks for economic E2E surfaces."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.models.market_data import CashSettlementPrice
from app.services.westmetall_cash_settlement import SOURCE_WESTMETALL, SYMBOL_DAILY
from backend.tests.e2e._fixtures import seed_westmetall_prices, trace_id_factory


def test_seeded_westmetall_prices_are_decimal_not_float() -> None:
    trace_id = trace_id_factory()
    today = date.today()
    seed_westmetall_prices(trace_id, today, today)
    session = SessionLocal()
    try:
        row = (
            session.query(CashSettlementPrice)
            .filter(
                CashSettlementPrice.source == SOURCE_WESTMETALL,
                CashSettlementPrice.symbol == SYMBOL_DAILY,
                CashSettlementPrice.settlement_date == today,
            )
            .one()
        )
        assert isinstance(row.price_usd, Decimal)
        assert str(row.price_usd) == "2450.000000"
    finally:
        session.close()


def test_raw_float_seed_path_is_rejected() -> None:
    today = date.today()
    with pytest.raises(TypeError, match="Decimal"):
        seed_westmetall_prices(trace_id_factory(), today, today, raw_floats=True)


def test_awarded_contract_preserves_fixed_point_string(awarded_rfq) -> None:
    assert awarded_rfq["contract_ids"]
    assert Decimal(awarded_rfq["quantity_mt"]) == Decimal("5.000000")
