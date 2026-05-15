from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_actor_sub, require_any_role, require_role
from app.core.database import get_session
from app.core.rate_limit import RATE_LIMIT_MUTATION, limiter
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.schemas.linkages import (
    HedgeOrderLinkageCreate,
    HedgeOrderLinkageListResponse,
    HedgeOrderLinkageRead,
)
from app.services.linkage_service import LinkageService

router = APIRouter()


@router.get("", response_model=HedgeOrderLinkageListResponse)
def list_linkages(
    order_id: UUID | None = Query(None, description="Filter by order ID"),
    contract_id: UUID | None = Query(None, description="Filter by contract ID"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> HedgeOrderLinkageListResponse:
    items, next_cursor = LinkageService.list_linkages(
        session,
        order_id=order_id,
        contract_id=contract_id,
        cursor=cursor,
        limit=limit,
    )
    return HedgeOrderLinkageListResponse(
        items=[HedgeOrderLinkageRead.model_validate(lnk) for lnk in items],
        next_cursor=next_cursor,
    )


@router.post(
    "", response_model=HedgeOrderLinkageRead, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RATE_LIMIT_MUTATION)
def create_linkage(
    payload: HedgeOrderLinkageCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="linkage",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
) -> HedgeOrderLinkageRead:
    with unit_of_work(session, request=request):
        linkage = LinkageService.create(
            session, payload.order_id, payload.contract_id, payload.quantity_mt
        )
        mark_audit_success(request, linkage.id, metadata={"actor_sub": actor_sub})
    return HedgeOrderLinkageRead.model_validate(linkage)


@router.get("/{linkage_id}", response_model=HedgeOrderLinkageRead)
def get_linkage(
    linkage_id: UUID,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> HedgeOrderLinkageRead:
    linkage = LinkageService.get_by_id(session, linkage_id)
    return HedgeOrderLinkageRead.model_validate(linkage)
