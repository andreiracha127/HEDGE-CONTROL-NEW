"""Cashflow projection service — forward-looking settlement timeline.

Scans all open instruments with future settlement/delivery dates and projects
the expected cash inflows and outflows:

* Sales Orders (SO)  → inflow  (+qty × price)
* Purchase Orders (PO) → outflow (−qty × price)
* Hedge Contracts     → net of fixed vs. variable leg

For variable-price instruments the latest market price is used as estimate.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus
from app.models.deal import DealLink, DealLinkedType
from app.models.orders import Order, OrderType, PriceType
from app.schemas.cashflow import (
    CashFlowProjectionItem,
    CashFlowProjectionResponse,
    CashFlowProjectionSummary,
    ProjectionInstrumentType,
)
from app.utils.price_reference import PriceQuote, PriceReferenceUnprovable
from app.services.price_lookup_service import (
    get_cash_settlement_price_d1_with_provenance,
    resolve_symbol,
)

logger = logging.getLogger(__name__)


def _get_market_price_quote(
    session: Session, commodity: str, as_of_date: date
) -> PriceQuote:
    """Per-row price lookup. Raises PriceReferenceUnprovable on missing
    settlement; the route boundary translates to HTTP 424. NEVER returns
    None; absence of evidence is institutionally a hard-fail per §2.6.
    """
    try:
        symbol = resolve_symbol(commodity)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_400_BAD_REQUEST:
            raise PriceReferenceUnprovable(
                f"Cannot project: no price-symbol mapping for commodity '{commodity}'"
            ) from exc
        raise
    return get_cash_settlement_price_d1_with_provenance(
        session, symbol=symbol, as_of_date=as_of_date
    )


def _resolve_deal_id(
    session: Session, linked_type: DealLinkedType, linked_id
) -> str | None:
    """Find the deal_id if this instrument is linked to a deal."""
    link = (
        session.query(DealLink)
        .filter(DealLink.linked_type == linked_type, DealLink.linked_id == linked_id)
        .first()
    )
    return str(link.deal_id) if link else None


def _order_settlement_date(order: Order) -> date | None:
    """Best available future date for an order."""
    if order.delivery_date_end:
        return (
            order.delivery_date_end
            if isinstance(order.delivery_date_end, date)
            else None
        )
    if order.delivery_date_start:
        return (
            order.delivery_date_start
            if isinstance(order.delivery_date_start, date)
            else None
        )
    return None


def compute_cashflow_projection(
    session: Session,
    as_of_date: date,
) -> CashFlowProjectionResponse:
    items: list[CashFlowProjectionItem] = []
    # Per-row commodity pricing — no global LME_AL lookup. Each
    # variable-priced row resolves its own commodity via
    # _get_market_price_quote, which raises PriceReferenceUnprovable
    # on absence. The route handler translates to 424.

    # ── Orders (SO + PO) ──
    orders = session.query(Order).filter(Order.deleted_at.is_(None)).all()
    for order in orders:
        settle_dt = _order_settlement_date(order)
        if settle_dt is None or settle_dt < as_of_date:
            continue

        qty = Decimal(str(order.quantity_mt))
        if order.price_type == PriceType.fixed:
            if order.avg_entry_price is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Order {order.id} is fixed-price but avg_entry_price "
                        "is missing; cannot project."
                    ),
                )
            price = Decimal(str(order.avg_entry_price))
            price_src = "fixed"
        else:
            # Variable-price: hard-fail on unprovable, no fallback.
            price_quote = _get_market_price_quote(session, order.commodity, as_of_date)
            price = price_quote.value
            price_src = "market"

        amount = qty * price
        is_so = order.order_type == OrderType.sales

        if is_so:
            instr_type = ProjectionInstrumentType.sales_order
            deal_type = DealLinkedType.sales_order
        else:
            instr_type = ProjectionInstrumentType.purchase_order
            deal_type = DealLinkedType.purchase_order
            amount = -amount

        items.append(
            CashFlowProjectionItem(
                instrument_type=instr_type,
                instrument_id=str(order.id),
                reference="",
                counterparty="",
                commodity=order.commodity,
                settlement_date=settle_dt,
                quantity_mt=qty,
                price_per_mt=price,
                amount_usd=amount,
                price_source=price_src,
                deal_id=_resolve_deal_id(session, deal_type, order.id),
            )
        )

    # ── Hedge Contracts (active / partially_settled, not deleted) ──
    contracts = (
        session.query(HedgeContract)
        .filter(
            HedgeContract.status.in_(
                (
                    HedgeContractStatus.active,
                    HedgeContractStatus.partially_settled,
                )
            ),
            HedgeContract.deleted_at.is_(None),
        )
        .all()
    )
    for contract in contracts:
        if contract.settlement_date is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Contract {contract.id} has no settlement_date; "
                    "cannot project (no inventing as_of_date)."
                ),
            )
        settle_dt = contract.settlement_date
        if settle_dt < as_of_date:
            continue

        if contract.fixed_price_value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Contract {contract.id} has no fixed_price_value; "
                    "cannot project."
                ),
            )

        qty = Decimal(str(contract.quantity_mt))
        fixed_price = Decimal(str(contract.fixed_price_value))

        # Hard-fail on unprovable variable leg; no fallback to fixed_price.
        variable_quote = _get_market_price_quote(session, contract.commodity, as_of_date)
        est_variable = variable_quote.value
        price_src = "market"

        fixed_side = contract.fixed_leg_side.value
        if fixed_side == "buy":
            amount = qty * (est_variable - fixed_price)
        else:
            amount = qty * (fixed_price - est_variable)

        # Determine instrument type from classification
        if contract.classification == HedgeClassification.short:
            instr_type = ProjectionInstrumentType.hedge_sell
        else:
            instr_type = ProjectionInstrumentType.hedge_buy

        items.append(
            CashFlowProjectionItem(
                instrument_type=instr_type,
                instrument_id=str(contract.id),
                reference=contract.reference or "",
                counterparty=contract.counterparty_id or "",
                commodity=contract.commodity,
                settlement_date=settle_dt,
                quantity_mt=qty,
                price_per_mt=fixed_price,
                amount_usd=amount,
                price_source=price_src,
                deal_id=_resolve_deal_id(session, DealLinkedType.contract, contract.id),
            )
        )

    items.sort(key=lambda x: x.settlement_date)

    total_in = sum((it.amount_usd for it in items if it.amount_usd > 0), Decimal("0"))
    total_out = sum((it.amount_usd for it in items if it.amount_usd < 0), Decimal("0"))

    return CashFlowProjectionResponse(
        as_of_date=as_of_date,
        items=items,
        summary=CashFlowProjectionSummary(
            total_inflows=total_in,
            total_outflows=total_out,
            net_cashflow=total_in + total_out,
            instrument_count=len(items),
        ),
    )
