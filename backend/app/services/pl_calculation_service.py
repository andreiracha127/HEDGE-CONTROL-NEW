from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.cashflow import CashFlowLedgerEntry
from app.models.contracts import HedgeContract, HedgeContractStatus
from app.schemas.pl import PLResultResponse, PriceReferenceEntry
from app.services.cashflow_ledger_service import SOURCE_EVENT_TYPE
from app.services.mtm_contract_service import compute_mtm_for_contract


def compute_pl(
    db: Session,
    entity_type: str,
    entity_id: UUID,
    period_start: date,
    period_end: date,
) -> PLResultResponse:
    """Compute P&L for a given entity over an explicit period.

    `realized_pl` is computed deterministically from the cashflow ledger for
    HEDGE_CONTRACT_SETTLED events within the period.

    `unrealized_mtm` is computed as point-in-time MTM at `period_end` using D-1
    cash settlement prices (hard-fail if missing).
    """
    if period_end < period_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="period_end must be greater than or equal to period_start",
        )

    if entity_type == "order":
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail="Realized cashflow ledger not implemented for orders",
        )

    if entity_type != "hedge_contract":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="entity_type must be 'hedge_contract' or 'order'",
        )

    ledger_entries = (
        db.query(CashFlowLedgerEntry)
        .filter(
            CashFlowLedgerEntry.hedge_contract_id == entity_id,
            CashFlowLedgerEntry.source_event_type == SOURCE_EVENT_TYPE,
            CashFlowLedgerEntry.cashflow_date >= period_start,
            CashFlowLedgerEntry.cashflow_date <= period_end,
        )
        .order_by(CashFlowLedgerEntry.cashflow_date.asc(), CashFlowLedgerEntry.created_at.asc())
        .all()
    )

    realized_pl = Decimal("0")
    price_references: list[PriceReferenceEntry] = []
    seen_references: set[tuple[str, str, date, str]] = set()

    def _append_reference(entry: PriceReferenceEntry) -> None:
        key = (
            entry.symbol,
            entry.source,
            entry.settlement_date,
            str(entry.value),
        )
        if key not in seen_references:
            seen_references.add(key)
            price_references.append(entry)

    for entry in ledger_entries:
        amount = Decimal(str(entry.amount))
        if entry.direction == "IN":
            realized_pl += amount
        elif entry.direction == "OUT":
            realized_pl -= amount
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unsupported ledger direction: {entry.direction}",
            )
        if (
            entry.price_source is not None
            and entry.price_symbol is not None
            and entry.price_settlement_date is not None
            and entry.price_value is not None
        ):
            _append_reference(
                PriceReferenceEntry(
                    symbol=entry.price_symbol,
                    source=entry.price_source,
                    settlement_date=entry.price_settlement_date,
                    value=Decimal(str(entry.price_value)),
                )
            )

    contract = db.get(HedgeContract, entity_id)
    if not contract:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hedge contract not found")

    if contract.status != HedgeContractStatus.active:
        unrealized_mtm = Decimal("0")
    else:
        mtm = compute_mtm_for_contract(db, contract_id=entity_id, as_of_date=period_end)
        unrealized_mtm = Decimal(mtm.mtm_value)
        _append_reference(
            PriceReferenceEntry(
                symbol=mtm.price_quote.symbol,
                source=mtm.price_quote.source,
                settlement_date=mtm.price_quote.settlement_date,
                value=mtm.price_quote.value,
            )
        )

    return PLResultResponse(
        realized_pl=realized_pl,
        unrealized_mtm=unrealized_mtm,
        price_references=price_references,
    )
