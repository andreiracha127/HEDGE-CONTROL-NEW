from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.contracts import HedgeContract, HedgeContractStatus
from app.schemas.mtm import MTMObjectType, MTMResultResponse
from app.services.price_lookup_service import (
    PriceReferenceUnprovable,
    get_cash_settlement_price_d1_with_provenance,
    resolve_symbol,
)


def compute_mtm_for_contract(
    db: Session, contract_id: UUID, as_of_date: date
) -> MTMResultResponse:
    contract = db.get(HedgeContract, contract_id)
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hedge contract not found"
        )

    if contract.status not in (
        HedgeContractStatus.active,
        HedgeContractStatus.partially_settled,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hedge contract is not active or partially settled",
        )

    if contract.fixed_price_value is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hedge contract entry_price is missing",
        )

    symbol = resolve_symbol(contract.commodity)
    try:
        price_quote = get_cash_settlement_price_d1_with_provenance(
            db, symbol=symbol, as_of_date=as_of_date
        )
    except PriceReferenceUnprovable as exc:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail=str(exc),
        ) from exc
    price_d1 = price_quote.value
    entry_price = Decimal(str(contract.fixed_price_value))
    quantity_mt = Decimal(str(contract.quantity_mt))

    mtm_value = quantity_mt * (price_d1 - entry_price)

    return MTMResultResponse(
        object_type=MTMObjectType.hedge_contract,
        object_id=str(contract.id),
        as_of_date=as_of_date,
        mtm_value=mtm_value,
        price_d1=price_d1,
        entry_price=entry_price,
        quantity_mt=quantity_mt,
        price_quote=price_quote,
    )
