"""Cluster 1 PR-CL1-1: DealEngine skips archived linked entities."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.contracts import (
    HedgeClassification,
    HedgeContract,
    HedgeContractStatus,
    HedgeLegSide,
)
from app.models.counterparty import Counterparty
from app.models.deal import Deal, DealLink, DealLinkedType, DealPNLSnapshot
from app.models.market_data import CashSettlementPrice
from app.models.orders import Order, OrderType, PriceType
from app.services.deal_engine import DealEngineService
from app.services.exposure_engine import ExposureEngineService
from app.services.price_lookup_service import PriceReferenceUnprovable


SNAPSHOT_DATE = date(2026, 2, 2)
PRIOR_BUSINESS_DAY = date(2026, 1, 30)


def _create_deal(session: Session, *, name: str = "ArchivedTraversal") -> Deal:
    deal = Deal(
        reference=f"D-{uuid.uuid4().hex[:8].upper()}",
        name=name,
        commodity="ALUMINUM",
    )
    session.add(deal)
    session.commit()
    session.refresh(deal)
    return deal


def _create_order(
    session: Session,
    order_type: OrderType,
    *,
    commodity: str = "ALUMINUM",
    qty: Decimal = Decimal("10"),
    price: Decimal = Decimal("2500"),
    price_type: PriceType = PriceType.fixed,
    archived: bool = False,
) -> Order:
    order = Order(
        order_type=order_type,
        price_type=price_type,
        commodity=commodity,
        quantity_mt=qty,
        avg_entry_price=price,
        deleted_at=datetime.now(timezone.utc) if archived else None,
    )
    session.add(order)
    session.commit()
    session.refresh(order)
    return order


def _create_counterparty(session: Session) -> Counterparty:
    cp = Counterparty(
        type="customer",
        name=f"Cpty-{uuid.uuid4().hex[:6]}",
        country="BRA",
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def _create_hedge(
    session: Session,
    *,
    commodity: str = "ALUMINUM",
    qty: Decimal = Decimal("100"),
    fixed_price: Decimal = Decimal("2450"),
    classification: HedgeClassification = HedgeClassification.short,
    archived: bool = False,
) -> HedgeContract:
    cp = _create_counterparty(session)
    fixed_side = (
        HedgeLegSide.buy
        if classification == HedgeClassification.long
        else HedgeLegSide.sell
    )
    variable_side = (
        HedgeLegSide.sell
        if fixed_side == HedgeLegSide.buy
        else HedgeLegSide.buy
    )
    contract = HedgeContract(
        reference=f"HC-{uuid.uuid4().hex[:8].upper()}",
        counterparty_id=str(cp.id),
        commodity=commodity,
        quantity_mt=qty,
        fixed_price_value=fixed_price,
        fixed_price_unit="USD/MT",
        fixed_leg_side=fixed_side,
        variable_leg_side=variable_side,
        classification=classification,
        premium_discount=Decimal("0"),
        settlement_date=date(2026, 9, 30),
        trade_date=date(2026, 1, 1),
        status=HedgeContractStatus.active,
        source_type="manual",
        deleted_at=datetime.now(timezone.utc) if archived else None,
    )
    session.add(contract)
    session.commit()
    session.refresh(contract)
    return contract


def _link(
    session: Session,
    deal: Deal,
    linked_type: DealLinkedType,
    linked_id: uuid.UUID,
) -> DealLink:
    link = DealLink(
        deal_id=deal.id,
        linked_type=linked_type,
        linked_id=linked_id,
    )
    session.add(link)
    session.commit()
    session.refresh(link)
    return link


def _insert_price(
    session: Session,
    *,
    symbol: str,
    price_usd: Decimal,
    settlement_date: date = PRIOR_BUSINESS_DAY,
) -> None:
    session.add(
        CashSettlementPrice(
            source="westmetall",
            symbol=symbol,
            settlement_date=settlement_date,
            price_usd=price_usd,
            source_url="https://example.test/source",
            html_sha256="0" * 64,
            fetched_at=datetime.now(timezone.utc),
        )
    )
    session.commit()


def test_compute_deal_pnl_excludes_archived_variable_order(session: Session) -> None:
    # Guard row: if the archived COPPER order leaks into price collection,
    # the snapshot will expose COPPER in price_references and overstate revenue.
    _insert_price(
        session, symbol="LME_CU_CASH_SETTLEMENT_DAILY", price_usd=Decimal("9100")
    )
    deal = _create_deal(session)
    live_order = _create_order(
        session, OrderType.sales, qty=Decimal("10"), price=Decimal("2500")
    )
    archived_order = _create_order(
        session,
        OrderType.sales,
        commodity="COPPER",
        qty=Decimal("7"),
        price_type=PriceType.variable,
        archived=True,
    )
    _link(session, deal, DealLinkedType.sales_order, live_order.id)
    _link(session, deal, DealLinkedType.sales_order, archived_order.id)

    snap = DealEngineService.compute_deal_pnl(session, deal.id, SNAPSHOT_DATE)

    assert snap.physical_revenue == Decimal("25000.000000")
    assert "COPPER" not in (snap.price_references or {})


def test_compute_deal_pnl_excludes_archived_hedge_contract(session: Session) -> None:
    _insert_price(
        session, symbol="LME_ALU_CASH_SETTLEMENT_DAILY", price_usd=Decimal("2700")
    )
    deal = _create_deal(session)
    live_order = _create_order(
        session, OrderType.sales, qty=Decimal("100"), price=Decimal("2500")
    )
    archived_hedge = _create_hedge(session, archived=True)
    _link(session, deal, DealLinkedType.sales_order, live_order.id)
    _link(session, deal, DealLinkedType.hedge, archived_hedge.id)

    snap = DealEngineService.compute_deal_pnl(session, deal.id, SNAPSHOT_DATE)

    assert snap.physical_revenue == Decimal("250000.000000")
    assert snap.physical_cost == Decimal("0")
    assert snap.hedge_pnl_realized == Decimal("0")
    assert snap.hedge_pnl_mtm == Decimal("0")
    assert snap.total_pnl == Decimal("250000.000000")


def test_compute_deal_pnl_raises_409_when_all_links_archived(
    session: Session,
) -> None:
    deal = _create_deal(session)
    archived_sales = _create_order(
        session, OrderType.sales, qty=Decimal("10"), archived=True
    )
    archived_purchase = _create_order(
        session, OrderType.purchase, qty=Decimal("5"), archived=True
    )
    _link(session, deal, DealLinkedType.sales_order, archived_sales.id)
    _link(session, deal, DealLinkedType.purchase_order, archived_purchase.id)
    before_count = session.query(DealPNLSnapshot).filter_by(deal_id=deal.id).count()

    with pytest.raises(HTTPException) as exc:
        DealEngineService.compute_deal_pnl(session, deal.id, SNAPSHOT_DATE)

    assert exc.value.status_code == 409
    assert "no live linked entities" in str(exc.value.detail)
    after_count = session.query(DealPNLSnapshot).filter_by(deal_id=deal.id).count()
    assert after_count == before_count


def test_compute_pnl_breakdown_raises_409_when_all_links_archived(
    session: Session,
) -> None:
    deal = _create_deal(session)
    archived_sales = _create_order(
        session, OrderType.sales, qty=Decimal("10"), archived=True
    )
    archived_purchase = _create_order(
        session, OrderType.purchase, qty=Decimal("5"), archived=True
    )
    _link(session, deal, DealLinkedType.sales_order, archived_sales.id)
    _link(session, deal, DealLinkedType.purchase_order, archived_purchase.id)

    with pytest.raises(HTTPException) as exc:
        DealEngineService.compute_pnl_breakdown(session, [deal.id], SNAPSHOT_DATE)

    assert exc.value.status_code == 409
    assert "no live linked entities" in str(exc.value.detail)


def test_compute_pnl_breakdown_excludes_archived_order(session: Session) -> None:
    deal = _create_deal(session)
    live_order = _create_order(
        session, OrderType.sales, qty=Decimal("10"), price=Decimal("2500")
    )
    archived_order = _create_order(
        session,
        OrderType.sales,
        commodity="COPPER",
        qty=Decimal("7"),
        price=Decimal("9100"),
        archived=True,
    )
    _link(session, deal, DealLinkedType.sales_order, live_order.id)
    _link(session, deal, DealLinkedType.sales_order, archived_order.id)

    result = DealEngineService.compute_pnl_breakdown(
        session, [deal.id], SNAPSHOT_DATE
    )

    assert len(result["deals"]) == 1
    deal_row = result["deals"][0]
    assert deal_row["physical_revenue"] == Decimal("25000.000000")
    assert deal_row["total_pnl"] == Decimal("25000.000000")
    assert [item["id"] for item in deal_row["physical_items"]] == [live_order.id]
    assert result["totals"]["physical_revenue"] == Decimal("25000.000000")


def test_recompute_tons_excludes_archived_order_via_public_add_link(
    session: Session,
) -> None:
    deal = _create_deal(session)
    live_order = _create_order(session, OrderType.sales, qty=Decimal("10"))
    archived_order = _create_order(session, OrderType.sales, qty=Decimal("7"))
    _link(session, deal, DealLinkedType.sales_order, live_order.id)
    _link(session, deal, DealLinkedType.sales_order, archived_order.id)
    DealEngineService._recompute_tons(session, deal)
    assert deal.total_physical_tons == Decimal("17.000")

    archived_order.deleted_at = datetime.now(timezone.utc)
    extra_live_order = _create_order(session, OrderType.purchase, qty=Decimal("3"))
    DealEngineService.add_link(
        session, deal.id, DealLinkedType.purchase_order.value, extra_live_order.id
    )

    session.refresh(deal)
    assert deal.total_physical_tons == Decimal("13.000")
    assert deal.total_hedge_tons == Decimal("0.000")


def test_exposure_and_deal_pnl_converge_after_order_archive(
    session: Session,
) -> None:
    _insert_price(
        session, symbol="LME_ALU_CASH_SETTLEMENT_DAILY", price_usd=Decimal("2700")
    )
    _insert_price(
        session, symbol="LME_CU_CASH_SETTLEMENT_DAILY", price_usd=Decimal("9100")
    )
    deal = _create_deal(session)
    live_order = _create_order(
        session,
        OrderType.sales,
        commodity="ALUMINUM",
        qty=Decimal("10"),
        price_type=PriceType.variable,
    )
    archived_order = _create_order(
        session,
        OrderType.sales,
        commodity="COPPER",
        qty=Decimal("7"),
        price_type=PriceType.variable,
        archived=True,
    )
    _link(session, deal, DealLinkedType.sales_order, live_order.id)
    _link(session, deal, DealLinkedType.sales_order, archived_order.id)

    ExposureEngineService.reconcile_from_orders(session)
    exposure_rows = ExposureEngineService.compute_net_exposure(session)
    snap = DealEngineService.compute_deal_pnl(session, deal.id, SNAPSHOT_DATE)

    assert {row["commodity"] for row in exposure_rows} == {"ALUMINUM"}
    assert snap.physical_revenue == Decimal("27000.000000")
    assert "ALUMINUM" in (snap.price_references or {})
    assert "COPPER" not in (snap.price_references or {})


def test_compute_deal_pnl_partial_price_failure_raises_unprovable(
    session: Session,
) -> None:
    _insert_price(
        session, symbol="LME_ALU_CASH_SETTLEMENT_DAILY", price_usd=Decimal("2700")
    )
    deal = _create_deal(session)
    live_order = _create_order(
        session,
        OrderType.sales,
        commodity="ALUMINUM",
        qty=Decimal("10"),
        price_type=PriceType.variable,
    )
    live_hedge_without_quote = _create_hedge(
        session,
        commodity="COPPER",
        qty=Decimal("5"),
        fixed_price=Decimal("9000"),
    )
    _link(session, deal, DealLinkedType.sales_order, live_order.id)
    _link(session, deal, DealLinkedType.hedge, live_hedge_without_quote.id)
    before_count = session.query(DealPNLSnapshot).filter_by(deal_id=deal.id).count()

    with pytest.raises(PriceReferenceUnprovable):
        DealEngineService.compute_deal_pnl(session, deal.id, SNAPSHOT_DATE)

    after_count = session.query(DealPNLSnapshot).filter_by(deal_id=deal.id).count()
    assert after_count == before_count


def test_unarchived_order_returns_to_deal_pnl(session: Session) -> None:
    deal = _create_deal(session)
    order = _create_order(
        session, OrderType.sales, qty=Decimal("10"), price=Decimal("2500")
    )
    _link(session, deal, DealLinkedType.sales_order, order.id)
    order.deleted_at = datetime.now(timezone.utc)
    session.commit()

    with pytest.raises(HTTPException):
        DealEngineService.compute_deal_pnl(session, deal.id, SNAPSHOT_DATE)

    order.deleted_at = None
    session.commit()

    snap = DealEngineService.compute_deal_pnl(session, deal.id, SNAPSHOT_DATE)

    assert snap.physical_revenue == Decimal("25000.000000")
