from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.orders import Order, OrderPricingConvention, PriceType
from app.schemas.mtm import MTMObjectType, MTMResultResponse
from app.services.price_lookup_service import (
    PriceReferenceUnprovable,
    get_cash_settlement_price_d1_with_provenance,
    resolve_symbol,
)


def compute_mtm_for_order(
    db: Session,
    order_id: UUID,
    as_of_date: date,
) -> MTMResultResponse:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )

    if order.price_type != PriceType.variable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="MTM is not defined for fixed-price orders",
        )

    if order.pricing_convention not in (
        OrderPricingConvention.avg,
        OrderPricingConvention.avginter,
        OrderPricingConvention.c2r,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order pricing_convention is not MTM-eligible",
        )

    if order.avg_entry_price is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Order avg_entry_price is missing",
        )

    try:
        price_quote = get_cash_settlement_price_d1_with_provenance(
            db, symbol=resolve_symbol(order.commodity), as_of_date=as_of_date
        )
    except PriceReferenceUnprovable as exc:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail=str(exc),
        ) from exc
    price_d1 = price_quote.value
    entry_price = Decimal(str(order.avg_entry_price))
    quantity_mt = Decimal(str(order.quantity_mt))

    mtm_value = quantity_mt * (price_d1 - entry_price)

    return MTMResultResponse(
        object_type=MTMObjectType.order,
        object_id=str(order.id),
        as_of_date=as_of_date,
        mtm_value=mtm_value,
        price_d1=price_d1,
        entry_price=entry_price,
        quantity_mt=quantity_mt,
        price_quote=price_quote,
    )
