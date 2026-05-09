from __future__ import annotations

import uuid
from datetime import date
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.pl import PLSnapshot
from app.schemas.pl import PLResultResponse
from app.services.pl_calculation_service import compute_pl
from app.utils.provenance import sha256_json


def _price_references_json(pl_result: PLResultResponse) -> list[dict]:
    return [entry.model_dump(mode="json") for entry in pl_result.price_references]


def _compute_inputs_hash(
    *,
    entity_type: str,
    entity_id: UUID,
    period_start: date,
    period_end: date,
    pl_result: PLResultResponse,
    price_references: list[dict],
) -> str:
    return sha256_json(
        {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "period_start": period_start.isoformat(),
            "period_end": period_end.isoformat(),
            "realized_pl": str(pl_result.realized_pl),
            "unrealized_mtm": str(pl_result.unrealized_mtm),
            "price_references": price_references,
        }
    )


def create_pl_snapshot(
    db: Session,
    entity_type: str,
    entity_id: UUID,
    period_start: date,
    period_end: date,
) -> PLSnapshot:
    """Create an immutable P&L snapshot for a given entity and period.

    - Idempotent: same keys + same computed values returns existing snapshot.
    - Conflict: same keys + different computed values raises HTTP 409.
    """
    pl_result: PLResultResponse = compute_pl(
        db, entity_type, entity_id, period_start, period_end
    )
    price_references = _price_references_json(pl_result)
    inputs_hash = _compute_inputs_hash(
        entity_type=entity_type,
        entity_id=entity_id,
        period_start=period_start,
        period_end=period_end,
        pl_result=pl_result,
        price_references=price_references,
    )

    existing = (
        db.query(PLSnapshot)
        .filter(
            PLSnapshot.entity_type == entity_type,
            PLSnapshot.entity_id == entity_id,
            PLSnapshot.period_start == period_start,
            PLSnapshot.period_end == period_end,
        )
        .first()
    )

    if existing is not None:
        if (
            existing.realized_pl == pl_result.realized_pl
            and existing.unrealized_mtm == pl_result.unrealized_mtm
            and existing.price_references == price_references
            and existing.inputs_hash == inputs_hash
        ):
            return existing
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Snapshot conflict: Existing snapshot for entity ({entity_type}, {entity_id}) "
                f"and period ({period_start} to {period_end}) has different values."
            ),
        )

    new_snapshot = PLSnapshot(
        entity_type=entity_type,
        entity_id=entity_id,
        period_start=period_start,
        period_end=period_end,
        realized_pl=pl_result.realized_pl,
        unrealized_mtm=pl_result.unrealized_mtm,
        price_references=price_references,
        inputs_hash=inputs_hash,
        correlation_id=uuid.uuid4(),
    )
    db.add(new_snapshot)
    db.commit()
    db.refresh(new_snapshot)
    return new_snapshot


def get_pl_snapshot(
    db: Session,
    entity_type: str,
    entity_id: UUID,
    period_start: date,
    period_end: date,
) -> PLSnapshot:
    """Retrieve a P&L snapshot by its composite key.

    Raises HTTP 404 if not found.
    """
    snapshot = (
        db.query(PLSnapshot)
        .filter(
            PLSnapshot.entity_type == entity_type,
            PLSnapshot.entity_id == entity_id,
            PLSnapshot.period_start == period_start,
            PLSnapshot.period_end == period_end,
        )
        .first()
    )
    if snapshot is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="P&L snapshot not found",
        )
    return snapshot
