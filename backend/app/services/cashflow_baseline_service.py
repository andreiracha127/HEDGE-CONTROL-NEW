from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.precision import quantize_money, quantize_price
from app.models.cashflow import CashFlowBaselineSnapshot, CashFlowLedgerEntry
from app.models.contracts import HedgeContract, HedgeContractStatus
from app.models.orders import Order, OrderPricingConvention, PriceType
from app.schemas.cashflow import CashFlowItem
from app.schemas.mtm import MTMResultResponse
from app.services.mtm_contract_service import compute_mtm_for_contract
from app.services.mtm_order_service import compute_mtm_for_order
from app.utils.provenance import sha256_json


def _canonicalize_snapshot_payload(payload: dict) -> dict:
    if "cashflow_items" in payload and isinstance(payload["cashflow_items"], list):
        # Legacy Analytic-shaped Baseline rows are archived by migration 039.
        # Keep deterministic ordering for conflict checks during any
        # pre-migration/runtime overlap, but do not rewrite this shape into
        # the new Baseline payload.
        payload["cashflow_items"] = sorted(
            payload["cashflow_items"],
            key=lambda item: (item.get("object_type"), item.get("object_id")),
        )
    if "unrealized_items" in payload and isinstance(payload["unrealized_items"], list):
        payload["unrealized_items"] = sorted(
            payload["unrealized_items"],
            key=lambda item: (item.get("object_type"), item.get("object_id")),
        )
    if "realized_ledger_entries" in payload and isinstance(
        payload["realized_ledger_entries"], list
    ):
        payload["realized_ledger_entries"] = sorted(
            payload["realized_ledger_entries"],
            key=lambda item: (
                item.get("cashflow_date"),
                item.get("hedge_contract_id"),
                item.get("leg_id"),
                item.get("source_event_type")
                if item.get("source_event_type") is not None
                else "",
                (0, "")
                if item.get("source_event_id") is None
                else (1, str(item.get("source_event_id"))),
                item.get("id") or "",
            ),
        )
    return payload


def _compute_inputs_hash(as_of_date: date, payload: dict, total: Decimal) -> str:
    return sha256_json(
        {
            "as_of_date": as_of_date.isoformat(),
            "snapshot_data": payload,
            "total_net_cashflow": str(total),
        }
    )


def _signed_ledger_amount(entry: CashFlowLedgerEntry) -> Decimal:
    amount = quantize_money(entry.amount)
    direction = str(entry.direction).upper()
    if direction == "IN":
        return amount
    if direction == "OUT":
        return -amount
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported ledger direction: {entry.direction}",
    )


def _ledger_entry_payload(entry: CashFlowLedgerEntry) -> dict:
    signed_amount = _signed_ledger_amount(entry)
    return {
        "id": str(entry.id),
        "hedge_contract_id": str(entry.hedge_contract_id),
        "source_event_type": entry.source_event_type,
        "source_event_id": str(entry.source_event_id) if entry.source_event_id else None,
        "leg_id": entry.leg_id,
        "cashflow_date": entry.cashflow_date.isoformat(),
        "currency": entry.currency,
        "direction": str(entry.direction).upper(),
        "amount": str(quantize_money(entry.amount)),
        "signed_amount_usd": str(signed_amount),
        "price_source": entry.price_source,
        "price_symbol": entry.price_symbol,
        "price_settlement_date": (
            entry.price_settlement_date.isoformat()
            if entry.price_settlement_date is not None
            else None
        ),
        "price_value": str(entry.price_value) if entry.price_value is not None else None,
    }


def _load_realized_ledger_entries(
    db: Session, as_of_date: date
) -> list[CashFlowLedgerEntry]:
    return (
        db.query(CashFlowLedgerEntry)
        .filter(CashFlowLedgerEntry.cashflow_date <= as_of_date)
        .order_by(
            CashFlowLedgerEntry.cashflow_date.asc(),
            CashFlowLedgerEntry.hedge_contract_id.asc(),
            CashFlowLedgerEntry.leg_id.asc(),
            CashFlowLedgerEntry.source_event_type.asc(),
            CashFlowLedgerEntry.source_event_id.asc().nulls_first(),
            CashFlowLedgerEntry.id.asc(),
        )
        .all()
    )


def _cashflow_item_from_mtm(
    mtm: MTMResultResponse, as_of_date: date
) -> CashFlowItem:
    mtm_value = quantize_money(mtm.mtm_value)
    if mtm.price_quote is None:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY,
            detail=f"MTM result for {mtm.object_id} has no price provenance",
        )
    return CashFlowItem(
        object_type=mtm.object_type.value,
        object_id=mtm.object_id,
        settlement_date=as_of_date,
        amount_usd=mtm_value,
        mtm_value=mtm_value,
        price_source=mtm.price_quote.source,
        price_symbol=mtm.price_quote.symbol,
        price_settlement_date=mtm.price_quote.settlement_date,
        price_value=quantize_price(mtm.price_quote.value),
    )


def _build_unrealized_items(db: Session, as_of_date: date) -> list[CashFlowItem]:
    items: list[CashFlowItem] = []

    contracts = (
        db.query(HedgeContract)
        .filter(
            HedgeContract.status.in_(
                (
                    HedgeContractStatus.active,
                    HedgeContractStatus.partially_settled,
                )
            ),
            HedgeContract.deleted_at.is_(None),
        )
        .order_by(HedgeContract.created_at.asc(), HedgeContract.id.asc())
        .all()
    )
    for contract in contracts:
        mtm = compute_mtm_for_contract(
            db, contract_id=contract.id, as_of_date=as_of_date
        )
        items.append(_cashflow_item_from_mtm(mtm, as_of_date))

    orders = (
        db.query(Order)
        .filter(
            Order.price_type == PriceType.variable,
            Order.pricing_convention.in_(
                (
                    OrderPricingConvention.avg,
                    OrderPricingConvention.avginter,
                    OrderPricingConvention.c2r,
                )
            ),
            Order.deleted_at.is_(None),
        )
        .order_by(Order.created_at.asc(), Order.id.asc())
        .all()
    )
    for order in orders:
        mtm = compute_mtm_for_order(db, order_id=order.id, as_of_date=as_of_date)
        items.append(_cashflow_item_from_mtm(mtm, as_of_date))

    return items


def create_cashflow_baseline_snapshot(
    db: Session, as_of_date: date, correlation_id: str
) -> CashFlowBaselineSnapshot:
    existing = (
        db.query(CashFlowBaselineSnapshot)
        .filter(CashFlowBaselineSnapshot.as_of_date == as_of_date)
        .first()
    )

    unrealized_items = _build_unrealized_items(db, as_of_date)
    realized_entries = _load_realized_ledger_entries(db, as_of_date)

    unrealized_total = quantize_money(
        sum((item.amount_usd for item in unrealized_items), Decimal("0"))
    )
    realized_amounts = [_signed_ledger_amount(entry) for entry in realized_entries]
    realized_payload = [_ledger_entry_payload(entry) for entry in realized_entries]
    realized_total = quantize_money(sum(realized_amounts, Decimal("0")))
    total = quantize_money(unrealized_total + realized_total)

    payload = _canonicalize_snapshot_payload(
        {
            "view": "baseline",
            "as_of_date": as_of_date.isoformat(),
            "unrealized_items": [
                item.model_dump(mode="json") for item in unrealized_items
            ],
            "realized_ledger_entries": realized_payload,
            "reconciliation": {
                "unrealized_total_usd": str(unrealized_total),
                "realized_total_usd": str(realized_total),
                "total_net_cashflow": str(total),
                "unrealized_item_count": len(unrealized_items),
                "ledger_entry_count": len(realized_payload),
            },
        }
    )
    inputs_hash = _compute_inputs_hash(as_of_date, payload, total)

    if existing is not None:
        if existing.snapshot_data is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="CashFlow baseline snapshot missing snapshot_data",
            )
        if existing.total_net_cashflow is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="CashFlow baseline snapshot missing total_net_cashflow",
            )
        existing_payload = _canonicalize_snapshot_payload(dict(existing.snapshot_data))
        if existing_payload.get("view") != "baseline":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="CashFlow baseline snapshot uses legacy payload shape",
            )
        if existing.inputs_hash is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="CashFlow baseline snapshot missing inputs_hash",
            )
        if (
            existing_payload != payload
            or Decimal(str(existing.total_net_cashflow)) != total
            or existing.inputs_hash != inputs_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="CashFlow baseline snapshot conflict",
            )
        return existing

    snapshot = CashFlowBaselineSnapshot(
        as_of_date=as_of_date,
        snapshot_data=payload,
        total_net_cashflow=total,
        inputs_hash=inputs_hash,
        correlation_id=correlation_id,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


def get_cashflow_baseline_snapshot(
    db: Session, as_of_date: date
) -> CashFlowBaselineSnapshot:
    snapshot = (
        db.query(CashFlowBaselineSnapshot)
        .filter(CashFlowBaselineSnapshot.as_of_date == as_of_date)
        .first()
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Baseline snapshot not found",
        )
    return snapshot
