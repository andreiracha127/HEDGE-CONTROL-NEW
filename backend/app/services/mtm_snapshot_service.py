from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.mtm import MTMObjectType, MTMSnapshot
from app.schemas.mtm import MTMResultResponse
from app.services.mtm_contract_service import compute_mtm_for_contract
from app.services.mtm_order_service import compute_mtm_for_order
from app.utils.provenance import sha256_json


def _as_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _compute_inputs_hash(computed: MTMResultResponse) -> str:
    if computed.price_quote is None:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="MTM price provenance is missing",
        )
    return sha256_json(
        {
            "as_of_date": computed.as_of_date.isoformat(),
            "object_type": computed.object_type.value,
            "object_id": str(computed.object_id),
            "entry_price": str(computed.entry_price),
            "quantity_mt": str(computed.quantity_mt),
            "price_value": str(computed.price_quote.value),
            "price_source": computed.price_quote.source,
            "price_settlement_date": computed.price_quote.settlement_date.isoformat(),
            "symbol": computed.price_quote.symbol,
        }
    )


def _snapshot_matches(snapshot: MTMSnapshot, computed: MTMResultResponse, inputs_hash: str) -> bool:
    if computed.price_quote is None:
        return False
    values_match = (
        _as_decimal(snapshot.mtm_value) == _as_decimal(computed.mtm_value)
        and _as_decimal(snapshot.price_d1) == _as_decimal(computed.price_d1)
        and _as_decimal(snapshot.entry_price) == _as_decimal(computed.entry_price)
        and _as_decimal(snapshot.quantity_mt) == _as_decimal(computed.quantity_mt)
    )
    if not values_match:
        return False
    legacy_null_provenance = (
        snapshot.price_source is None
        and snapshot.price_symbol is None
        and snapshot.price_settlement_date is None
        and snapshot.inputs_hash is None
    )
    if legacy_null_provenance:
        return True
    return (
        snapshot.price_source == computed.price_quote.source
        and snapshot.price_symbol == computed.price_quote.symbol
        and snapshot.price_settlement_date == computed.price_quote.settlement_date
        and snapshot.inputs_hash == inputs_hash
    )


def create_mtm_snapshot_for_contract(
    db: Session,
    contract_id: UUID,
    as_of_date: date,
    correlation_id: str,
    *,
    commit: bool = True,
) -> MTMSnapshot:
    existing = (
        db.query(MTMSnapshot)
        .filter(
            MTMSnapshot.object_type == MTMObjectType.hedge_contract,
            MTMSnapshot.object_id == contract_id,
            MTMSnapshot.as_of_date == as_of_date,
        )
        .first()
    )

    computed = compute_mtm_for_contract(
        db, contract_id=contract_id, as_of_date=as_of_date
    )
    inputs_hash = _compute_inputs_hash(computed)

    if existing is not None:
        if not _snapshot_matches(existing, computed, inputs_hash):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="MTM snapshot conflict"
            )
        return existing

    snapshot = MTMSnapshot(
        object_type=MTMObjectType.hedge_contract,
        object_id=contract_id,
        as_of_date=as_of_date,
        mtm_value=_as_decimal(computed.mtm_value),
        price_d1=_as_decimal(computed.price_d1),
        entry_price=_as_decimal(computed.entry_price),
        quantity_mt=_as_decimal(computed.quantity_mt),
        price_source=computed.price_quote.source,
        price_symbol=computed.price_quote.symbol,
        price_settlement_date=computed.price_quote.settlement_date,
        inputs_hash=inputs_hash,
        correlation_id=correlation_id,
    )
    db.add(snapshot)
    if commit:
        db.commit()
        db.refresh(snapshot)
    else:
        db.flush()
    return snapshot


def create_mtm_snapshot_for_order(
    db: Session,
    order_id: UUID,
    as_of_date: date,
    correlation_id: str,
    *,
    commit: bool = True,
) -> MTMSnapshot:
    existing = (
        db.query(MTMSnapshot)
        .filter(
            MTMSnapshot.object_type == MTMObjectType.order,
            MTMSnapshot.object_id == order_id,
            MTMSnapshot.as_of_date == as_of_date,
        )
        .first()
    )

    computed = compute_mtm_for_order(db, order_id=order_id, as_of_date=as_of_date)
    inputs_hash = _compute_inputs_hash(computed)

    if existing is not None:
        if not _snapshot_matches(existing, computed, inputs_hash):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="MTM snapshot conflict"
            )
        return existing

    snapshot = MTMSnapshot(
        object_type=MTMObjectType.order,
        object_id=order_id,
        as_of_date=as_of_date,
        mtm_value=_as_decimal(computed.mtm_value),
        price_d1=_as_decimal(computed.price_d1),
        entry_price=_as_decimal(computed.entry_price),
        quantity_mt=_as_decimal(computed.quantity_mt),
        price_source=computed.price_quote.source,
        price_symbol=computed.price_quote.symbol,
        price_settlement_date=computed.price_quote.settlement_date,
        inputs_hash=inputs_hash,
        correlation_id=correlation_id,
    )
    db.add(snapshot)
    if commit:
        db.commit()
        db.refresh(snapshot)
    else:
        db.flush()
    return snapshot


def get_mtm_snapshot(
    db: Session,
    object_type: MTMObjectType,
    object_id: UUID,
    as_of_date: date,
) -> MTMSnapshot:
    snapshot = (
        db.query(MTMSnapshot)
        .filter(
            MTMSnapshot.object_type == object_type,
            MTMSnapshot.object_id == object_id,
            MTMSnapshot.as_of_date == as_of_date,
        )
        .first()
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="MTM snapshot not found"
        )
    return snapshot
