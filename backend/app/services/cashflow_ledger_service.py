from __future__ import annotations

import uuid
from decimal import Decimal, ROUND_HALF_EVEN
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.cashflow import CashFlowLedgerEntry, HedgeContractSettlementEvent
from app.models.contracts import HedgeContract, HedgeContractStatus, HedgeLegSide
from app.schemas.cashflow import (
    HedgeContractSettlementCreate,
    HedgeContractSettlementLeg,
    LedgerDirection,
    LedgerLegId,
)
from app.services.price_lookup_service import (
    PriceReferenceUnprovable,
    get_cash_settlement_price_d1_with_provenance,
    resolve_symbol,
)


SOURCE_EVENT_TYPE = "HEDGE_CONTRACT_SETTLED"


def _normalize_decimal(value: Decimal) -> Decimal:
    return Decimal(str(value))


def _decimal_or_none_eq(a: Decimal | None, b: Decimal | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return _normalize_decimal(a) == _normalize_decimal(b)


def _ledger_entry_matches(entry: CashFlowLedgerEntry, expected: dict) -> bool:
    return (
        entry.hedge_contract_id == expected["hedge_contract_id"]
        and entry.source_event_type == expected["source_event_type"]
        and entry.source_event_id == expected["source_event_id"]
        and entry.leg_id == expected["leg_id"]
        and entry.cashflow_date == expected["cashflow_date"]
        and entry.currency == expected["currency"]
        and entry.direction == expected["direction"]
        and _normalize_decimal(entry.amount) == _normalize_decimal(expected["amount"])
        and entry.price_source == expected["price_source"]
        and entry.price_symbol == expected["price_symbol"]
        and entry.price_settlement_date == expected["price_settlement_date"]
        and _decimal_or_none_eq(entry.price_value, expected["price_value"])
    )


def _ledger_entry_matches_payload(
    entry: CashFlowLedgerEntry,
    contract_id: UUID,
    payload: HedgeContractSettlementCreate,
    leg: HedgeContractSettlementLeg,
) -> bool:
    return (
        entry.hedge_contract_id == contract_id
        and entry.source_event_type == SOURCE_EVENT_TYPE
        and entry.source_event_id == payload.source_event_id
        and entry.leg_id == leg.leg_id.value
        and entry.cashflow_date == payload.cashflow_date
        and entry.currency == "USD"
        and entry.direction == leg.direction.value
        and _normalize_decimal(entry.amount) == _normalize_decimal(Decimal(str(leg.amount)))
    )


def _direction_from_side(side: HedgeLegSide) -> LedgerDirection:
    return LedgerDirection.out if side == HedgeLegSide.buy else LedgerDirection.in_


def _build_expected_entry(
    db: Session,
    contract: HedgeContract,
    payload: HedgeContractSettlementCreate,
    leg: HedgeContractSettlementLeg,
) -> dict:
    if contract.fixed_price_value is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Cannot derive settlement: contract {contract.id} has no fixed_price_value",
        )

    scale = Decimal("0.000001")
    quantity = Decimal(str(contract.quantity_mt))
    if leg.leg_id == LedgerLegId.fixed:
        derived_amount = (quantity * Decimal(str(contract.fixed_price_value))).quantize(
            scale, rounding=ROUND_HALF_EVEN
        )
        derived_direction = _direction_from_side(contract.fixed_leg_side)
        provenance = {
            "price_source": None,
            "price_symbol": None,
            "price_settlement_date": None,
            "price_value": None,
        }
    elif leg.leg_id == LedgerLegId.float:
        try:
            settlement_quote = get_cash_settlement_price_d1_with_provenance(
                db,
                symbol=resolve_symbol(contract.commodity),
                as_of_date=payload.cashflow_date,
            )
        except PriceReferenceUnprovable as exc:
            raise HTTPException(
                status_code=status.HTTP_424_FAILED_DEPENDENCY,
                detail=str(exc),
            ) from exc
        derived_amount = (quantity * settlement_quote.value).quantize(
            scale, rounding=ROUND_HALF_EVEN
        )
        derived_direction = _direction_from_side(contract.variable_leg_side)
        provenance = {
            "price_source": settlement_quote.source,
            "price_symbol": settlement_quote.symbol,
            "price_settlement_date": settlement_quote.settlement_date,
            "price_value": settlement_quote.value,
        }
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Unexpected leg_id {leg.leg_id}",
        )

    if leg.direction != derived_direction:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Leg {leg.leg_id.value} direction mismatch: "
                f"derived={derived_direction.value}, payload={leg.direction.value}"
            ),
        )
    if Decimal(str(leg.amount)) != derived_amount:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Leg {leg.leg_id.value} amount mismatch: "
                f"derived={derived_amount}, payload={leg.amount}"
            ),
        )

    return {
        "hedge_contract_id": contract.id,
        "source_event_type": SOURCE_EVENT_TYPE,
        "source_event_id": payload.source_event_id,
        "leg_id": leg.leg_id.value,
        "cashflow_date": payload.cashflow_date,
        "currency": "USD",
        "direction": derived_direction.value,
        "amount": derived_amount,
        **provenance,
    }


def _assert_contract_active(contract: HedgeContract) -> None:
    if contract.status != HedgeContractStatus.active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Hedge contract is not active"
        )


def _validate_currency(payload: HedgeContractSettlementCreate) -> None:
    if payload.currency is not None and payload.currency != "USD":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="currency must be USD",
        )


def _raise_conflict() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT, detail="Settlement ledger conflict"
    )


def _raise_replay_payload_mismatch() -> None:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Settlement payload does not match persisted ledger event",
    )


def _validate_existing_settlement_replay(
    *,
    existing_event: HedgeContractSettlementEvent,
    existing_entries: list[CashFlowLedgerEntry],
    contract_id: UUID,
    payload: HedgeContractSettlementCreate,
) -> None:
    if (
        existing_event.hedge_contract_id != contract_id
        or existing_event.cashflow_date != payload.cashflow_date
        or len(existing_entries) != len(payload.legs)
    ):
        _raise_conflict()

    seen_leg_ids: set[str] = set()
    for leg in payload.legs:
        if leg.leg_id.value in seen_leg_ids:
            _raise_conflict()
        seen_leg_ids.add(leg.leg_id.value)
        match = next(
            (entry for entry in existing_entries if entry.leg_id == leg.leg_id.value),
            None,
        )
        if match is None or not _ledger_entry_matches_payload(
            match, contract_id, payload, leg
        ):
            _raise_replay_payload_mismatch()


def ingest_hedge_contract_settlement(
    db: Session,
    contract_id: UUID,
    payload: HedgeContractSettlementCreate,
    *,
    commit: bool = True,
) -> tuple[HedgeContractSettlementEvent, list[CashFlowLedgerEntry]]:
    contract = db.get(HedgeContract, contract_id)
    if not contract:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Hedge contract not found"
        )

    _validate_currency(payload)

    existing_event = db.get(HedgeContractSettlementEvent, payload.source_event_id)
    existing_entries = (
        db.query(CashFlowLedgerEntry)
        .filter(
            CashFlowLedgerEntry.source_event_type == SOURCE_EVENT_TYPE,
            CashFlowLedgerEntry.source_event_id == payload.source_event_id,
            CashFlowLedgerEntry.leg_id.in_([leg.leg_id.value for leg in payload.legs]),
            CashFlowLedgerEntry.cashflow_date == payload.cashflow_date,
        )
        .all()
    )

    if existing_event is not None:
        _validate_existing_settlement_replay(
            existing_event=existing_event,
            existing_entries=existing_entries,
            contract_id=contract_id,
            payload=payload,
        )
        return existing_event, existing_entries

    if contract.status == HedgeContractStatus.settled:
        _raise_conflict()

    _assert_contract_active(contract)

    if existing_entries:
        _raise_conflict()

    expected_entries = [
        _build_expected_entry(db, contract, payload, leg) for leg in payload.legs
    ]

    settlement_event = HedgeContractSettlementEvent(
        id=payload.source_event_id,
        hedge_contract_id=contract_id,
        cashflow_date=payload.cashflow_date,
    )
    db.add(settlement_event)

    ledger_entries: list[CashFlowLedgerEntry] = []
    for expected in expected_entries:
        entry = CashFlowLedgerEntry(
            id=uuid.uuid4(),
            hedge_contract_id=expected["hedge_contract_id"],
            source_event_type=expected["source_event_type"],
            source_event_id=expected["source_event_id"],
            leg_id=expected["leg_id"],
            cashflow_date=expected["cashflow_date"],
            currency=expected["currency"],
            direction=expected["direction"],
            amount=expected["amount"],
            price_source=expected["price_source"],
            price_symbol=expected["price_symbol"],
            price_settlement_date=expected["price_settlement_date"],
            price_value=expected["price_value"],
        )
        ledger_entries.append(entry)
        db.add(entry)

    contract.status = HedgeContractStatus.settled
    if commit:
        db.commit()
        db.refresh(settlement_event)
        for entry in ledger_entries:
            db.refresh(entry)
    else:
        db.flush()

    return settlement_event, ledger_entries


def list_entries_by_contract(
    db: Session,
    contract_id: UUID,
    start: date | None = None,
    end: date | None = None,
) -> list[CashFlowLedgerEntry]:
    query = db.query(CashFlowLedgerEntry).filter(
        CashFlowLedgerEntry.hedge_contract_id == contract_id
    )
    if start is not None:
        query = query.filter(CashFlowLedgerEntry.cashflow_date >= start)
    if end is not None:
        query = query.filter(CashFlowLedgerEntry.cashflow_date <= end)
    return query.order_by(
        CashFlowLedgerEntry.cashflow_date.asc(),
        CashFlowLedgerEntry.created_at.asc(),
    ).all()


def list_entries_by_event(
    db: Session,
    source_event_id: UUID,
    source_event_type: str = SOURCE_EVENT_TYPE,
) -> list[CashFlowLedgerEntry]:
    return (
        db.query(CashFlowLedgerEntry)
        .filter(
            CashFlowLedgerEntry.source_event_type == source_event_type,
            CashFlowLedgerEntry.source_event_id == source_event_id,
        )
        .order_by(CashFlowLedgerEntry.leg_id.asc())
        .all()
    )
