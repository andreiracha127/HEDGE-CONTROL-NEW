from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import require_any_role, require_role
from app.core.database import get_session
from app.core.rate_limit import RATE_LIMIT_MUTATION, limiter
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.schemas.pl import PLResultResponse, PLSnapshotCreate, PLSnapshotResponse
from app.services.pl_calculation_service import compute_pl
from app.services.pl_snapshot_service import create_pl_snapshot, get_pl_snapshot


router = APIRouter()


@router.get("/{entity_type}/{entity_id}", response_model=PLResultResponse)
def get_pl(
    entity_type: str,
    entity_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> PLResultResponse:
    return compute_pl(session, entity_type, entity_id, period_start, period_end)


@router.post(
    "/snapshots", response_model=PLSnapshotResponse, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RATE_LIMIT_MUTATION)
def post_pl_snapshot(
    snapshot_in: PLSnapshotCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="pl_snapshot",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> PLSnapshotResponse:
    with unit_of_work(session, request=request):
        snapshot = create_pl_snapshot(
            db=session,
            entity_type=snapshot_in.entity_type,
            entity_id=snapshot_in.entity_id,
            period_start=snapshot_in.period_start,
            period_end=snapshot_in.period_end,
            commit=False,
        )
        mark_audit_success(request, snapshot.id)
    return PLSnapshotResponse.model_validate(snapshot)


@router.get("/snapshots", response_model=PLSnapshotResponse)
def get_pl_snapshot(
    entity_type: str,
    entity_id: UUID,
    period_start: date = Query(...),
    period_end: date = Query(...),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> PLSnapshotResponse:
    snapshot = get_pl_snapshot(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        period_start=period_start,
        period_end=period_end,
    )
    return PLSnapshotResponse.model_validate(snapshot)
