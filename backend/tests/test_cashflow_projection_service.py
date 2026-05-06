"""Unit tests for cashflow_projection_service.compute_cashflow_projection."""

from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.orders import Order, OrderType, PriceType
from app.schemas.cashflow import ProjectionInstrumentType
from app.services.cashflow_projection_service import compute_cashflow_projection


# ── helpers ──────────────────────────────────────────────────────────────

FUTURE = date.today() + timedelta(days=30)
PAST = date.today() - timedelta(days=30)
TODAY = date.today()

MARKET_PRICE_PATCH = "app.services.cashflow_projection_service._get_market_price"


def _make_order(
    session,
    *,
    order_type,
    price_type,
    quantity_mt,
    avg_entry_price=None,
    delivery_date_end=None,
    delivery_date_start=None,
    deleted_at=None,
    commodity="ALUMINUM",
):
    o = Order(
        order_type=order_type,
        price_type=price_type,
        commodity=commodity,
        quantity_mt=quantity_mt,
        avg_entry_price=avg_entry_price,
        delivery_date_end=delivery_date_end,
        delivery_date_start=delivery_date_start,
        deleted_at=deleted_at,
    )
    session.add(o)
    session.commit()
    session.refresh(o)
    return o


def _make_contract(
    session,
    *,
    commodity="LME_AL",
    quantity_mt=10.0,
    fixed_price_value=2500.0,
    fixed_leg_side=HedgeLegSide.buy,
    variable_leg_side=HedgeLegSide.sell,
    classification=HedgeClassification.long,
    status=HedgeContractStatus.active,
    settlement_date=None,
    deleted_at=None,
):
    c = HedgeContract(
        commodity=commodity,
        quantity_mt=quantity_mt,
        fixed_price_value=fixed_price_value,
        fixed_leg_side=fixed_leg_side,
        variable_leg_side=variable_leg_side,
        classification=classification,
        status=status,
        settlement_date=settlement_date,
        deleted_at=deleted_at,
    )
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


# ── empty state ──────────────────────────────────────────────────────────


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_empty_projection_returns_zero_summary(mock_mp, session):
    result = compute_cashflow_projection(session, TODAY)
    assert result.items == []
    assert result.summary.total_inflows == Decimal("0")
    assert result.summary.total_outflows == Decimal("0")
    assert result.summary.net_cashflow == Decimal("0")
    assert result.summary.instrument_count == 0
    assert result.as_of_date == TODAY


# ── orders ───────────────────────────────────────────────────────────────


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_fixed_sales_order_inflow(mock_mp, session):
    """Fixed SO → positive amount = qty × fixed_price."""
    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        quantity_mt=100,
        avg_entry_price=2500,
        delivery_date_end=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.instrument_type == ProjectionInstrumentType.sales_order
    assert item.amount_usd == Decimal("250000")
    assert item.price_source == "fixed"
    assert item.settlement_date == FUTURE


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_fixed_purchase_order_outflow(mock_mp, session):
    """Fixed PO → negative amount."""
    _make_order(
        session,
        order_type=OrderType.purchase,
        price_type=PriceType.fixed,
        quantity_mt=50,
        avg_entry_price=2400,
        delivery_date_end=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 1
    assert result.items[0].instrument_type == ProjectionInstrumentType.purchase_order
    assert result.items[0].amount_usd == Decimal("-120000")


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2600"))
def test_variable_order_uses_market_price(mock_mp, session):
    """Variable-price SO uses market price when available."""
    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.variable,
        quantity_mt=10,
        delivery_date_end=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 1
    assert result.items[0].price_per_mt == Decimal("2600")
    assert result.items[0].amount_usd == Decimal("26000")
    assert result.items[0].price_source == "market"


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_variable_order_fallback_to_entry_price(mock_mp, session):
    """Variable-price with no market → fallback to avg_entry_price."""
    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.variable,
        quantity_mt=10,
        avg_entry_price=2300,
        delivery_date_end=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert result.items[0].price_source == "entry"
    assert result.items[0].amount_usd == Decimal("23000")


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_order_past_settlement_excluded(mock_mp, session):
    """Orders with delivery date in the past are excluded."""
    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        quantity_mt=10,
        avg_entry_price=2500,
        delivery_date_end=PAST,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 0


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_order_no_delivery_date_excluded(mock_mp, session):
    """Orders with no delivery dates are excluded."""
    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        quantity_mt=10,
        avg_entry_price=2500,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 0


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_deleted_order_excluded(mock_mp, session):
    """Soft-deleted orders are excluded."""
    from datetime import datetime, timezone

    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        quantity_mt=10,
        avg_entry_price=2500,
        delivery_date_end=FUTURE,
        deleted_at=datetime.now(timezone.utc),
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 0


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_order_uses_delivery_start_when_no_end(mock_mp, session):
    """Falls back to delivery_date_start when delivery_date_end absent."""
    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        quantity_mt=5,
        avg_entry_price=2000,
        delivery_date_start=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 1
    assert result.items[0].settlement_date == FUTURE


# ── hedge contracts ──────────────────────────────────────────────────────


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2700"))
def test_contract_buy_side_net(mock_mp, session):
    """Buy fixed-leg: net = qty × (market - fixed)."""
    _make_contract(
        session,
        quantity_mt=10,
        fixed_price_value=2500,
        fixed_leg_side=HedgeLegSide.buy,
        classification=HedgeClassification.long,
        settlement_date=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.instrument_type == ProjectionInstrumentType.hedge_buy
    # buy: qty * (market - fixed) = 10 * (2700 - 2500) = 2000
    assert item.amount_usd == Decimal("2000")
    assert item.price_source == "market"


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2700"))
def test_contract_sell_side_net(mock_mp, session):
    """Sell fixed-leg: net = qty × (fixed - market)."""
    _make_contract(
        session,
        quantity_mt=10,
        fixed_price_value=2500,
        fixed_leg_side=HedgeLegSide.sell,
        variable_leg_side=HedgeLegSide.buy,
        classification=HedgeClassification.short,
        settlement_date=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 1
    item = result.items[0]
    assert item.instrument_type == ProjectionInstrumentType.hedge_sell
    # sell: qty * (fixed - market) = 10 * (2500 - 2700) = -2000
    assert item.amount_usd == Decimal("-2000")


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_contract_no_market_uses_fixed_price(mock_mp, session):
    """When market price unavailable, net is zero (variable = fixed)."""
    _make_contract(
        session,
        quantity_mt=10,
        fixed_price_value=2500,
        fixed_leg_side=HedgeLegSide.buy,
        settlement_date=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 1
    # buy: qty * (fixed - fixed) = 0
    assert result.items[0].amount_usd == Decimal("0")
    assert result.items[0].price_source == "entry"


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2600"))
def test_contract_partially_settled_included(mock_mp, session):
    """partially_settled contracts are included."""
    _make_contract(
        session, status=HedgeContractStatus.partially_settled, settlement_date=FUTURE
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 1


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2600"))
def test_contract_settled_excluded(mock_mp, session):
    """Settled contracts are excluded."""
    _make_contract(session, status=HedgeContractStatus.settled, settlement_date=FUTURE)
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 0


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2600"))
def test_contract_cancelled_excluded(mock_mp, session):
    """Cancelled contracts are excluded."""
    _make_contract(
        session, status=HedgeContractStatus.cancelled, settlement_date=FUTURE
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 0


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2600"))
def test_contract_past_settlement_excluded(mock_mp, session):
    """Contracts with settlement_date in the past are excluded."""
    _make_contract(session, settlement_date=PAST)
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 0


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2600"))
def test_contract_deleted_excluded(mock_mp, session):
    """Soft-deleted contracts are excluded."""
    from datetime import datetime, timezone

    _make_contract(
        session, settlement_date=FUTURE, deleted_at=datetime.now(timezone.utc)
    )
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 0


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2600"))
def test_contract_no_settlement_date_uses_as_of(mock_mp, session):
    """Contract with no settlement_date uses as_of_date — excluded when
    as_of_date == today because settle_dt < as_of_date is false only for
    future as_of dates."""
    _make_contract(session, settlement_date=None)
    # as_of_date == today, contract settlement = today → NOT excluded (settle_dt < as_of is false)
    result = compute_cashflow_projection(session, TODAY)
    assert len(result.items) == 1


# ── summary & sorting ───────────────────────────────────────────────────


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_summary_aggregation(mock_mp, session):
    """Summary totals correctly sum inflows and outflows."""
    far_future = date.today() + timedelta(days=60)
    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        quantity_mt=100,
        avg_entry_price=2500,
        delivery_date_end=FUTURE,
    )
    _make_order(
        session,
        order_type=OrderType.purchase,
        price_type=PriceType.fixed,
        quantity_mt=50,
        avg_entry_price=2400,
        delivery_date_end=far_future,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert result.summary.total_inflows == Decimal("250000")
    assert result.summary.total_outflows == Decimal("-120000")
    assert result.summary.net_cashflow == Decimal("130000")
    assert result.summary.instrument_count == 2


@patch(MARKET_PRICE_PATCH, return_value=None)
def test_items_sorted_by_settlement_date(mock_mp, session):
    """Items are sorted chronologically by settlement_date."""
    far_future = date.today() + timedelta(days=60)
    # Insert far-future first, near-future second
    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        quantity_mt=10,
        avg_entry_price=100,
        delivery_date_end=far_future,
    )
    _make_order(
        session,
        order_type=OrderType.purchase,
        price_type=PriceType.fixed,
        quantity_mt=10,
        avg_entry_price=100,
        delivery_date_end=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert result.items[0].settlement_date == FUTURE
    assert result.items[1].settlement_date == far_future


# ── mixed instruments ────────────────────────────────────────────────────


@patch(MARKET_PRICE_PATCH, return_value=Decimal("2600"))
def test_mixed_orders_and_contracts(mock_mp, session):
    """Both orders and contracts appear in the projection."""
    _make_order(
        session,
        order_type=OrderType.sales,
        price_type=PriceType.fixed,
        quantity_mt=10,
        avg_entry_price=2500,
        delivery_date_end=FUTURE,
    )
    _make_contract(
        session,
        quantity_mt=5,
        fixed_price_value=2500,
        fixed_leg_side=HedgeLegSide.buy,
        settlement_date=FUTURE,
    )
    result = compute_cashflow_projection(session, TODAY)
    assert result.summary.instrument_count == 2
    types = {it.instrument_type for it in result.items}
    assert ProjectionInstrumentType.sales_order in types
    assert ProjectionInstrumentType.hedge_buy in types
