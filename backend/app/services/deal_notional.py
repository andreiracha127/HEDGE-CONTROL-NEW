from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.precision import quantize_money, quantize_mt, quantize_price
from app.models.contracts import HedgeContract


def _compute_deal_notional_from_links(session: Session, links: list[dict]) -> Decimal:
    notional = Decimal("0")
    for link in links:
        linked_type = link.get("linked_type")
        if hasattr(linked_type, "value"):
            linked_type = linked_type.value
        if linked_type not in {"contract", "hedge"}:
            continue
        linked_id = link.get("linked_id")
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
    return quantize_money(notional)

