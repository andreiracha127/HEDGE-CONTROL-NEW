from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import require_any_role, require_role
from app.core.database import get_session
from app.core.rate_limit import RATE_LIMIT_MUTATION, limiter
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.schemas.mtm import MTMResultResponse, MTMSnapshotCreate, MTMSnapshotResponse
from app.services.mtm_contract_service import compute_mtm_for_contract
from app.services.mtm_order_service import compute_mtm_for_order
from app.services.mtm_snapshot_service import (
    create_mtm_snapshot_for_contract,
    create_mtm_snapshot_for_order,
    get_mtm_snapshot as _get_mtm_snapshot,
)


router = APIRouter()


@router.get("/hedge-contracts/{contract_id}", response_model=MTMResultResponse)
def get_mtm_for_hedge_contract(
    contract_id: UUID,
    as_of_date: date = Query(...),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> MTMResultResponse:
    return compute_mtm_for_contract(
        session, contract_id=contract_id, as_of_date=as_of_date
    )


@router.get("/orders/{order_id}", response_model=MTMResultResponse)
def get_mtm_for_order(
    order_id: UUID,
    as_of_date: date = Query(...),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> MTMResultResponse:
    return compute_mtm_for_order(session, order_id=order_id, as_of_date=as_of_date)


@router.post(
    "/snapshots",
    response_model=MTMSnapshotResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(RATE_LIMIT_MUTATION)
def create_mtm_snapshot(
    payload: MTMSnapshotCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="mtm_snapshot",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> MTMSnapshotResponse:
    with unit_of_work(session, request=request):
        if payload.object_type.value == "hedge_contract":
            snapshot = create_mtm_snapshot_for_contract(
                session,
                contract_id=UUID(payload.object_id),
                as_of_date=payload.as_of_date,
                correlation_id=payload.correlation_id,
                commit=False,
            )
        elif payload.object_type.value == "order":
            snapshot = create_mtm_snapshot_for_order(
                session,
                order_id=UUID(payload.object_id),
                as_of_date=payload.as_of_date,
                correlation_id=payload.correlation_id,
                commit=False,
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported object_type"
            )
        mark_audit_success(request, snapshot.id)
    return MTMSnapshotResponse.model_validate(snapshot)


@router.get("/snapshots", response_model=MTMSnapshotResponse)
def get_mtm_snapshot(
    object_type: MTMObjectType,
    object_id: UUID,
    as_of_date: date,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> MTMSnapshotResponse:
    snapshot = _get_mtm_snapshot(
        session, object_type=object_type, object_id=object_id, as_of_date=as_of_date
    )
    return MTMSnapshotResponse.model_validate(snapshot)
