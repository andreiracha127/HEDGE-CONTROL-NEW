from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_actor_sub, require_any_role, require_role
from app.core.database import get_session
from app.core.rate_limit import RATE_LIMIT_MUTATION, limiter
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.schemas.contracts import (
    ContractLinkagesResponse,
    HedgeContractCreate,
    HedgeContractListResponse,
    HedgeContractRead,
    HedgeContractStatusUpdate,
    HedgeContractUpdate,
    LinkedDealSummary,
    LinkedOrderSummary,
)
from app.models.deal import Deal, DealLink, DealLinkedType
from app.models.orders import Order
from app.services.contract_service import ContractService

router = APIRouter()


@router.post(
    "/hedge", response_model=HedgeContractRead, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RATE_LIMIT_MUTATION)
def create_hedge_contract(
    payload: HedgeContractCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="hedge_contract",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
    actor_sub: str = Depends(get_current_actor_sub),
) -> HedgeContractRead:
    with unit_of_work(session, request=request):
        contract = ContractService.create(session, payload, created_by=actor_sub)
        mark_audit_success(request, contract.id, metadata={"actor_sub": actor_sub})
    return HedgeContractRead.model_validate(contract)


@router.get("/hedge", response_model=HedgeContractListResponse)
def list_hedge_contracts(
    status_filter: str | None = Query(
        None,
        alias="status",
        description="Filter by status (active, cancelled, settled)",
    ),
    classification: str | None = Query(
        None, description="Filter by classification (long or short)"
    ),
    commodity: str | None = Query(None, description="Filter by commodity"),
    include_deleted: bool = Query(False, description="Include soft-deleted records"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> HedgeContractListResponse:
    return ContractService.list(
        session,
        status_filter=status_filter,
        classification=classification,
        commodity=commodity,
        include_deleted=include_deleted,
        cursor=cursor,
        limit=limit,
    )


@router.get("/hedge/{contract_id}", response_model=HedgeContractRead)
def get_hedge_contract(
    contract_id: UUID,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> HedgeContractRead:
    contract = ContractService.get_by_id(session, contract_id)
    return HedgeContractRead.model_validate(contract)


@router.patch("/hedge/{contract_id}/archive", response_model=HedgeContractRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def archive_hedge_contract(
    contract_id: UUID,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="hedge_contract",
            event_type="archived",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
) -> HedgeContractRead:
    with unit_of_work(session, request=request):
        contract = ContractService.archive(session, contract_id)
        mark_audit_success(request, contract.id, metadata={"actor_sub": actor_sub})
    return HedgeContractRead.model_validate(contract)


# -----------------------------------------------------------------------
# PATCH update
# -----------------------------------------------------------------------


@router.patch("/hedge/{contract_id}", response_model=HedgeContractRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def update_hedge_contract(
    contract_id: UUID,
    payload: HedgeContractUpdate,
    request: Request,
    _: None = Depends(audit_event(entity_type="hedge_contract", event_type="updated")),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
) -> HedgeContractRead:
    with unit_of_work(session, request=request):
        contract = ContractService.update(session, contract_id, payload)
        mark_audit_success(request, contract.id, metadata={"actor_sub": actor_sub})
    return HedgeContractRead.model_validate(contract)


# -----------------------------------------------------------------------
# PATCH status transition
# -----------------------------------------------------------------------


@router.patch("/hedge/{contract_id}/status", response_model=HedgeContractRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def update_hedge_contract_status(
    contract_id: UUID,
    payload: HedgeContractStatusUpdate,
    request: Request,
    _: None = Depends(
        audit_event(entity_type="hedge_contract", event_type="status_changed")
    ),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
) -> HedgeContractRead:
    with unit_of_work(session, request=request):
        contract = ContractService.transition_status(session, contract_id, payload)
        mark_audit_success(request, contract.id, metadata={"actor_sub": actor_sub})
    return HedgeContractRead.model_validate(contract)


# -----------------------------------------------------------------------
# DELETE (soft delete + cancel)
# -----------------------------------------------------------------------


@router.delete("/hedge/{contract_id}", response_model=HedgeContractRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def delete_hedge_contract(
    contract_id: UUID,
    request: Request,
    _: None = Depends(audit_event(entity_type="hedge_contract", event_type="deleted")),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
) -> HedgeContractRead:
    with unit_of_work(session, request=request):
        contract = ContractService.delete(session, contract_id)
        mark_audit_success(request, contract.id, metadata={"actor_sub": actor_sub})
    return HedgeContractRead.model_validate(contract)


# -----------------------------------------------------------------------
# GET linkages  (deals + orders linked to this contract)
# -----------------------------------------------------------------------


@router.get("/hedge/{contract_id}/linkages", response_model=ContractLinkagesResponse)
def get_contract_linkages(
    contract_id: UUID,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> ContractLinkagesResponse:
    """Return deals and their linked orders for a given hedge contract."""
    # 1) Find all DealLinks pointing to this contract
    links = (
        session.query(DealLink)
        .filter(
            DealLink.linked_type.in_([DealLinkedType.hedge, DealLinkedType.contract]),
            DealLink.linked_id == contract_id,
        )
        .all()
    )

    deal_ids = list({lk.deal_id for lk in links})

    deals_out: list[LinkedDealSummary] = []
    for deal_id in deal_ids:
        deal = session.get(Deal, deal_id)
        if deal is None:
            continue

        # 2) Get order links for this deal
        order_links = (
            session.query(DealLink)
            .filter(
                DealLink.deal_id == deal_id,
                DealLink.linked_type.in_(
                    [DealLinkedType.sales_order, DealLinkedType.purchase_order]
                ),
            )
            .all()
        )

        orders_out: list[LinkedOrderSummary] = []
        for ol in order_links:
            order = session.get(Order, ol.linked_id)
            if order is None:
                continue
            orders_out.append(
                LinkedOrderSummary(
                    id=order.id,
                    linked_type=ol.linked_type.value,
                    order_type=order.order_type.value if order.order_type else None,
                    quantity_mt=float(order.quantity_mt) if order.quantity_mt else None,
                    counterparty_id=str(order.counterparty_id)
                    if order.counterparty_id
                    else None,
                    avg_entry_price=float(order.avg_entry_price)
                    if order.avg_entry_price
                    else None,
                    currency=order.currency,
                )
            )

        deals_out.append(
            LinkedDealSummary(
                id=deal.id,
                reference=deal.reference,
                name=deal.name,
                status=deal.status.value,
                total_physical_tons=float(deal.total_physical_tons),
                total_hedge_tons=float(deal.total_hedge_tons),
                hedge_ratio=float(deal.hedge_ratio),
                orders=orders_out,
            )
        )

    return ContractLinkagesResponse(contract_id=contract_id, deals=deals_out)
