from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import require_any_role, require_role
from app.core.database import get_session
from app.core.rate_limit import RATE_LIMIT_MUTATION, limiter
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.schemas.orders import (
    OrderListResponse,
    OrderRead,
    PurchaseOrderCreate,
    SalesOrderCreate,
    SoPoLinkCreate,
    SoPoLinkListResponse,
    SoPoLinkRead,
)
from app.services.order_service import OrderService

router = APIRouter()


@router.post("/sales", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_MUTATION)
def create_sales_order(
    payload: SalesOrderCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="order",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> OrderRead:
    with unit_of_work(session, request=request):
        order = OrderService.create_sales_order(session, payload, commit=False)
        mark_audit_success(request, order.id)
    return OrderRead.model_validate(order)


@router.post("/purchase", response_model=OrderRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_MUTATION)
def create_purchase_order(
    payload: PurchaseOrderCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="order",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> OrderRead:
    with unit_of_work(session, request=request):
        order = OrderService.create_purchase_order(session, payload, commit=False)
        mark_audit_success(request, order.id)
    return OrderRead.model_validate(order)


@router.get("", response_model=OrderListResponse)
def list_orders(
    order_type: str | None = Query(None, description="Filter by order type (SO or PO)"),
    price_type: str | None = Query(
        None, description="Filter by price type (fixed or variable)"
    ),
    include_deleted: bool = Query(False, description="Include soft-deleted records"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> OrderListResponse:
    return OrderService.list_orders(
        session,
        order_type=order_type,
        price_type=price_type,
        include_deleted=include_deleted,
        cursor=cursor,
        limit=limit,
    )


# --- SO ↔ PO Link routes (must be before /{order_id} to avoid path conflict) ---


@router.post("/links", response_model=SoPoLinkRead, status_code=status.HTTP_201_CREATED)
def create_sopo_link(
    payload: SoPoLinkCreate,
    request: Request,
    audit: None = Depends(
        audit_event(
            entity_type="sopo_link",
            event_type="created",
        )
    ),
    _user: dict = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> SoPoLinkRead:
    _ = audit
    with unit_of_work(session, request=request):
        link = OrderService.create_sopo_link(session, payload, commit=False)
        mark_audit_success(request, link.id)
    return SoPoLinkRead.model_validate(link)


@router.get("/links", response_model=SoPoLinkListResponse)
def list_sopo_links(
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _user: dict = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> SoPoLinkListResponse:
    return OrderService.list_sopo_links(session, cursor=cursor, limit=limit)


@router.get("/{order_id}", response_model=OrderRead)
def get_order(
    order_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> OrderRead:
    order = OrderService.get_by_id(session, order_id)
    return OrderRead.model_validate(order)


@router.patch("/{order_id}/archive", response_model=OrderRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def archive_order(
    order_id: UUID,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="order",
            event_type="archived",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> OrderRead:
    with unit_of_work(session, request=request):
        order = OrderService.archive(session, order_id, commit=False)
        mark_audit_success(request, order.id)
    return OrderRead.model_validate(order)
