from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_actor_sub, require_any_role, require_role
from app.core.database import get_session
from app.core.rate_limit import RATE_LIMIT_MUTATION, limiter
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.schemas.cashflow import (
    CashFlowAnalyticResponse,
    CashFlowBaselineSnapshotCreate,
    CashFlowBaselineSnapshotResponse,
    CashFlowProjectionResponse,
)
from app.services.cashflow_analytic_service import compute_cashflow_analytic
from app.services.cashflow_baseline_service import (
    create_cashflow_baseline_snapshot,
    get_cashflow_baseline_snapshot,
)
from app.services.cashflow_projection_service import compute_cashflow_projection
from app.utils.price_reference import PriceReferenceUnprovable


router = APIRouter()


@router.get("/analytic", response_model=CashFlowAnalyticResponse)
def get_cashflow_analytic(
    as_of_date: date = Query(...),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CashFlowAnalyticResponse:
    return compute_cashflow_analytic(session, as_of_date=as_of_date)


@router.post(
    "/baseline/snapshots",
    response_model=CashFlowBaselineSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(RATE_LIMIT_MUTATION)
def create_baseline_snapshot(
    payload: CashFlowBaselineSnapshotCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="cashflow_baseline_snapshot",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
) -> CashFlowBaselineSnapshotResponse:
    with unit_of_work(session, request=request):
        snapshot = create_cashflow_baseline_snapshot(
            session,
            as_of_date=payload.as_of_date,
            correlation_id=payload.correlation_id,
            commit=False,
        )
        mark_audit_success(request, snapshot.id, metadata={"actor_sub": actor_sub})
    return CashFlowBaselineSnapshotResponse.model_validate(snapshot)


@router.get("/projection", response_model=CashFlowProjectionResponse)
def get_cashflow_projection(
    as_of_date: date = Query(...),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CashFlowProjectionResponse:
    try:
        return compute_cashflow_projection(session, as_of_date=as_of_date)
    except PriceReferenceUnprovable as exc:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY, detail=str(exc),
        ) from exc


@router.get("/baseline/snapshots", response_model=CashFlowBaselineSnapshotResponse)
def get_baseline_snapshot(
    as_of_date: date = Query(...),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CashFlowBaselineSnapshotResponse:
    snapshot = get_cashflow_baseline_snapshot(session, as_of_date=as_of_date)
    return CashFlowBaselineSnapshotResponse.model_validate(snapshot)
