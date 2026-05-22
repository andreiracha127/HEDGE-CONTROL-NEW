from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.precision import quantize_money, quantize_mt, quantize_price
from app.models.contracts import HedgeContract
from app.models.orders import Order

_HEDGE_LINK_TYPES = {"contract", "hedge"}
_ORDER_LINK_TYPES = {"sales_order", "purchase_order"}


def _compute_deal_notional_from_links(session: Session, links: list[dict]) -> Decimal:
    notional = Decimal("0")
    for link in links:
        linked_type = link.get("linked_type")
        if hasattr(linked_type, "value"):
            linked_type = linked_type.value
        linked_id = link.get("linked_id")
        if linked_type in _HEDGE_LINK_TYPES:
            contract = session.get(HedgeContract, UUID(str(linked_id)))
            if contract is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Hedge contract {linked_id} not found",
                )
            if contract.fixed_price_value is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Hedge contract {linked_id} has no fixed_price_value",
                )
            notional += quantize_money(
                quantize_mt(contract.quantity_mt) * quantize_price(contract.fixed_price_value)
            )
        elif linked_type in _ORDER_LINK_TYPES:
            order = session.get(Order, UUID(str(linked_id)))
            if order is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Order {linked_id} not found",
                )
            if order.avg_entry_price is None:
                # Constitutional invariant: no silent fallback. An order
                # without a provable price cannot contribute notional and
                # must hard-fail the gate evaluation rather than silently
                # contribute $0 (which would bypass the institutional
                # threshold check).
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Order {linked_id} has no avg_entry_price",
                )
            notional += quantize_money(
                quantize_mt(order.quantity_mt) * quantize_price(order.avg_entry_price)
            )
        else:
            continue
    return quantize_money(notional)
