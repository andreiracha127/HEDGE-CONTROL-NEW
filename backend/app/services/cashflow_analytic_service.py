from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.contracts import HedgeContract, HedgeContractStatus
from app.models.orders import Order, OrderPricingConvention, PriceType
from app.schemas.cashflow import CashFlowAnalyticResponse, CashFlowItem
from app.services.mtm_contract_service import compute_mtm_for_contract
from app.services.mtm_order_service import compute_mtm_for_order


def compute_cashflow_analytic(db: Session, as_of_date: date) -> CashFlowAnalyticResponse:
    items: list[CashFlowItem] = []

    contracts = (
        db.query(HedgeContract)
        .filter(HedgeContract.status == HedgeContractStatus.active)
        .order_by(HedgeContract.created_at.asc())
        .all()
    )
    for contract in contracts:
        mtm = compute_mtm_for_contract(db, contract_id=contract.id, as_of_date=as_of_date)
        items.append(
            CashFlowItem(
                object_type=mtm.object_type.value,
                object_id=mtm.object_id,
                settlement_date=as_of_date,
                amount_usd=Decimal(mtm.mtm_value),
                mtm_value=Decimal(mtm.mtm_value),
                price_source=mtm.price_quote.source,
                price_symbol=mtm.price_quote.symbol,
                price_settlement_date=mtm.price_quote.settlement_date,
                price_value=mtm.price_quote.value,
            )
        )

    orders = (
        db.query(Order)
        .filter(
            Order.price_type == PriceType.variable,
            Order.pricing_convention.in_(
                (OrderPricingConvention.avg, OrderPricingConvention.avginter, OrderPricingConvention.c2r)
            ),
        )
        .order_by(Order.created_at.asc())
        .all()
    )
    for order in orders:
        mtm = compute_mtm_for_order(db, order_id=order.id, as_of_date=as_of_date)
        items.append(
            CashFlowItem(
                object_type=mtm.object_type.value,
                object_id=mtm.object_id,
                settlement_date=as_of_date,
                amount_usd=Decimal(mtm.mtm_value),
                mtm_value=Decimal(mtm.mtm_value),
                price_source=mtm.price_quote.source,
                price_symbol=mtm.price_quote.symbol,
                price_settlement_date=mtm.price_quote.settlement_date,
                price_value=mtm.price_quote.value,
            )
        )

    total = sum((item.amount_usd for item in items), Decimal("0"))
    return CashFlowAnalyticResponse(as_of_date=as_of_date, cashflow_items=items, total_net_cashflow=total)
