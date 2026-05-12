from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import require_any_role
from app.core.database import get_session
from app.core.pagination import paginate
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.models.counterparty import Counterparty
from app.schemas.counterparty import (
    CounterpartyCreate,
    CounterpartyListResponse,
    CounterpartyRead,
    CounterpartyUpdate,
)
from app.services.counterparty_service import CounterpartyService

router = APIRouter()


@router.post("", response_model=CounterpartyRead, status_code=status.HTTP_201_CREATED)
def create_counterparty(
    payload: CounterpartyCreate,
    request: Request,
    audit: None = Depends(
        audit_event(entity_type="counterparty", event_type="created")
    ),
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    _ = audit
    if payload.tax_id and not CounterpartyService.check_tax_id_unique(
        session, payload.tax_id
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="tax_id already exists",
        )
    with unit_of_work(session, request=request):
        cp = CounterpartyService.create(session, payload.model_dump(), commit=False)
        mark_audit_success(request, cp.id)
    return CounterpartyRead.model_validate(cp)


@router.get("", response_model=CounterpartyListResponse)
def list_counterparties(
    type: str | None = Query(None, description="Filter by type"),
    kyc_status: str | None = Query(None, description="Filter by KYC status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CounterpartyListResponse:
    query = CounterpartyService.list(
        session,
        type_filter=type,
        kyc_status_filter=kyc_status,
        is_active_filter=is_active,
    )
    items, next_cursor = paginate(
        query,
        created_at_col=Counterparty.created_at,
        id_col=Counterparty.id,
        cursor=cursor,
        limit=limit,
    )
    return CounterpartyListResponse(
        items=[CounterpartyRead.model_validate(cp) for cp in items],
        next_cursor=next_cursor,
    )


@router.get("/{counterparty_id}", response_model=CounterpartyRead)
def get_counterparty(
    counterparty_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    cp = CounterpartyService.get_by_id(session, counterparty_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found"
        )
    return CounterpartyRead.model_validate(cp)


@router.patch("/{counterparty_id}", response_model=CounterpartyRead)
def update_counterparty(
    counterparty_id: UUID,
    payload: CounterpartyUpdate,
    request: Request,
    audit: None = Depends(
        audit_event(entity_type="counterparty", event_type="updated")
    ),
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    _ = audit
    cp = CounterpartyService.get_by_id(session, counterparty_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found"
        )
    update_data = payload.model_dump(exclude_unset=True)
    if "tax_id" in update_data and update_data["tax_id"] is not None:
        if not CounterpartyService.check_tax_id_unique(
            session, update_data["tax_id"], exclude_id=cp.id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="tax_id already exists",
            )
    with unit_of_work(session, request=request):
        cp = CounterpartyService.update(session, cp, update_data, commit=False)
        mark_audit_success(request, cp.id)
    return CounterpartyRead.model_validate(cp)


@router.delete("/{counterparty_id}", response_model=CounterpartyRead)
def delete_counterparty(
    counterparty_id: UUID,
    request: Request,
    audit: None = Depends(
        audit_event(entity_type="counterparty", event_type="deleted")
    ),
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    _ = audit
    cp = CounterpartyService.get_by_id(session, counterparty_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found"
        )
    with unit_of_work(session, request=request):
        cp = CounterpartyService.soft_delete(session, cp, commit=False)
        mark_audit_success(request, cp.id)
    return CounterpartyRead.model_validate(cp)
