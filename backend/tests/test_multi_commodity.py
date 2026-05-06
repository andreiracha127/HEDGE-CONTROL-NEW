"""Tests for multi-commodity price-symbol resolution (Item 2.3).

Validates that:
* ``resolve_symbol`` maps every known commodity correctly and rejects unknowns.
* ``compute_mtm_for_contract`` uses the contract's own commodity to pick the
  right cash-settlement symbol (copper instead of aluminium, etc.).
* ``compute_mtm_for_order`` honours the explicit *commodity* parameter.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
import uuid

import pytest
from fastapi import HTTPException

from app.core.database import SessionLocal
from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.market_data import CashSettlementPrice
from app.models.orders import Order, OrderType, PriceType
from app.services.price_lookup_service import COMMODITY_SYMBOL_MAP, resolve_symbol
from app.services.mtm_contract_service import compute_mtm_for_contract
from app.services.mtm_order_service import compute_mtm_for_order


# ── helpers ────────────────────────────────────────────────────────────
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


def _insert_contract(
    commodity: str,
    quantity_mt: float,
    entry_price: float,
    status: HedgeContractStatus = HedgeContractStatus.active,
) -> uuid.UUID:
    with SessionLocal() as session:
        contract = HedgeContract(
            commodity=commodity,
            quantity_mt=quantity_mt,
            fixed_leg_side=HedgeLegSide.buy,
            variable_leg_side=HedgeLegSide.sell,
            classification=HedgeClassification.long,
            fixed_price_value=entry_price,
            fixed_price_unit="USD/MT",
            float_pricing_convention="avg",
            status=status,
        )
        session.add(contract)
        session.commit()
        session.refresh(contract)
        return contract.id


def _insert_order(quantity_mt: float, avg_entry_price: float) -> uuid.UUID:
    with SessionLocal() as session:
        order = Order(
            order_type=OrderType.sales,
            price_type=PriceType.variable,
            commodity="LME_AL",
            quantity_mt=quantity_mt,
            pricing_convention="avg",
            avg_entry_price=avg_entry_price,
        )
        session.add(order)
        session.commit()
        session.refresh(order)
        return order.id


# ── resolve_symbol unit tests ─────────────────────────────────────────
class TestResolveSymbol:
    @pytest.mark.parametrize(
        "commodity,expected_symbol", list(COMMODITY_SYMBOL_MAP.items())
    )
    def test_known_commodities(self, commodity: str, expected_symbol: str) -> None:
        assert resolve_symbol(commodity) == expected_symbol

    def test_unknown_commodity_raises_400(self) -> None:
        with pytest.raises(HTTPException) as exc:
            resolve_symbol("UNKNOWN_METAL")
        assert exc.value.status_code == 400
        assert "UNKNOWN_METAL" in exc.value.detail


# ── MTM contract with different commodities ───────────────────────────
class TestMTMContractMultiCommodity:
    """compute_mtm_for_contract must resolve symbol from contract.commodity."""

    def test_copper_contract_uses_copper_symbol(self) -> None:
        """A copper contract must look up LME_CU_CASH_SETTLEMENT_DAILY."""
        cu_symbol = COMMODITY_SYMBOL_MAP["LME_CU"]
        _insert_price(
            symbol=cu_symbol, settlement_date=date(2026, 1, 31), price_usd=9500.0
        )
        contract_id = _insert_contract(
            commodity="LME_CU",
            quantity_mt=10.0,
            entry_price=9000.0,
        )
        with SessionLocal() as session:
            result = compute_mtm_for_contract(
                session, contract_id=contract_id, as_of_date=date(2026, 2, 1)
            )
        assert result.price_d1 == Decimal("9500.0")
        assert result.mtm_value == Decimal("5000.00")  # 10 * (9500 - 9000)

    def test_zinc_contract_uses_zinc_symbol(self) -> None:
        zn_symbol = COMMODITY_SYMBOL_MAP["LME_ZN"]
        _insert_price(
            symbol=zn_symbol, settlement_date=date(2026, 1, 31), price_usd=2800.0
        )
        contract_id = _insert_contract(
            commodity="LME_ZN",
            quantity_mt=20.0,
            entry_price=2700.0,
        )
        with SessionLocal() as session:
            result = compute_mtm_for_contract(
                session, contract_id=contract_id, as_of_date=date(2026, 2, 1)
            )
        assert result.price_d1 == Decimal("2800.0")
        assert result.mtm_value == Decimal("2000.00")  # 20 * (2800 - 2700)

    def test_missing_price_for_commodity_424(self) -> None:
        """No price row for nickel → 424."""
        contract_id = _insert_contract(
            commodity="LME_NI",
            quantity_mt=5.0,
            entry_price=18000.0,
        )
        with SessionLocal() as session:
            with pytest.raises(HTTPException) as exc:
                compute_mtm_for_contract(
                    session, contract_id=contract_id, as_of_date=date(2026, 2, 1)
                )
        assert exc.value.status_code == 424


# ── MTM order with explicit commodity ─────────────────────────────────
class TestMTMOrderMultiCommodity:
    """compute_mtm_for_order honours the *commodity* parameter."""

    def test_order_with_copper_commodity(self) -> None:
        cu_symbol = COMMODITY_SYMBOL_MAP["LME_CU"]
        _insert_price(
            symbol=cu_symbol, settlement_date=date(2026, 1, 31), price_usd=9500.0
        )
        order_id = _insert_order(quantity_mt=10.0, avg_entry_price=9000.0)
        with SessionLocal() as session:
            result = compute_mtm_for_order(
                session,
                order_id=order_id,
                as_of_date=date(2026, 2, 1),
                commodity="LME_CU",
            )
        assert result.price_d1 == Decimal("9500.0")
        assert result.mtm_value == Decimal("5000.00")

    def test_order_default_commodity_is_aluminium(self) -> None:
        al_symbol = COMMODITY_SYMBOL_MAP["LME_AL"]
        _insert_price(
            symbol=al_symbol, settlement_date=date(2026, 1, 31), price_usd=2400.0
        )
        order_id = _insert_order(quantity_mt=10.0, avg_entry_price=2300.0)
        with SessionLocal() as session:
            result = compute_mtm_for_order(
                session,
                order_id=order_id,
                as_of_date=date(2026, 2, 1),
            )
        assert result.price_d1 == Decimal("2400.0")
        assert result.mtm_value == Decimal("1000.00")  # 10 * (2400 - 2300)

    def test_order_with_unknown_commodity_raises_400(self) -> None:
        order_id = _insert_order(quantity_mt=10.0, avg_entry_price=100.0)
        with SessionLocal() as session:
            with pytest.raises(HTTPException) as exc:
                compute_mtm_for_order(
                    session,
                    order_id=order_id,
                    as_of_date=date(2026, 2, 1),
                    commodity="NOPE",
                )
        assert exc.value.status_code == 400
