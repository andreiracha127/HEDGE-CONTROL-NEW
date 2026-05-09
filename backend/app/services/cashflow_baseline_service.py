from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.cashflow import CashFlowBaselineSnapshot
from app.services.cashflow_analytic_service import compute_cashflow_analytic
from app.utils.provenance import sha256_json


def _canonicalize_snapshot_payload(payload: dict) -> dict:
    if "cashflow_items" in payload and isinstance(payload["cashflow_items"], list):
        payload["cashflow_items"] = sorted(
            payload["cashflow_items"],
            key=lambda item: (item.get("object_type"), item.get("object_id")),
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


def create_cashflow_baseline_snapshot(
    db: Session, as_of_date: date, correlation_id: str
) -> CashFlowBaselineSnapshot:
    existing = (
        db.query(CashFlowBaselineSnapshot)
        .filter(CashFlowBaselineSnapshot.as_of_date == as_of_date)
        .first()
    )

    analytic = compute_cashflow_analytic(db, as_of_date=as_of_date)
    total = Decimal(analytic.total_net_cashflow)
    payload = _canonicalize_snapshot_payload(analytic.model_dump(mode="json"))
    inputs_hash = _compute_inputs_hash(as_of_date, payload, total)

    if existing is not None:
        existing_payload = _canonicalize_snapshot_payload(dict(existing.snapshot_data))
        if (
            existing_payload != payload
            or Decimal(str(existing.total_net_cashflow)) != total
            or (existing.inputs_hash is not None and existing.inputs_hash != inputs_hash)
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
