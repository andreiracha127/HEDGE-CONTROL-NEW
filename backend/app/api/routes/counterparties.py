from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.core.auth import (
    get_current_actor_roles,
    get_current_actor_sub,
    require_any_role,
    require_role,
)
from app.core.database import get_session
from app.core.pagination import paginate
from app.models.counterparty import Counterparty, CounterpartyType
from app.models.sanctions import AdjudicationDecision, SanctionsPartnerType
from app.schemas.counterparty import (
    CounterpartyCreate,
    CounterpartyListResponse,
    CounterpartyRead,
    CounterpartyUpdate,
    KycStatusTransitionRequest,
)
from app.schemas.sanctions import (
    SanctionsAdjudicationRead,
    SanctionsAdjudicationRequest,
    SanctionsScreeningRead,
)
from app.services.counterparty_service import CounterpartyService
from app.services.sanctions_screening_service import adjudicate as adjudicate_sanctions
from app.services.sanctions_screening_service import screen as screen_partner

router = APIRouter()


def _is_trader_only(actor_roles: list[str]) -> bool:
    return set(actor_roles) == {"trader"}


@router.post("", response_model=CounterpartyRead, status_code=status.HTTP_201_CREATED)
def create_counterparty(
    payload: CounterpartyCreate,
    request: Request,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="counterparty", event_type="created")),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    # counterparties is hedge-only after W1: trader has no hedge write access, and
    # customer/supplier partners are managed via /commercial-partners.
    if "risk_manager" not in actor_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Hedge counterparties are risk_manager-only.",
        )
    if payload.type.value in {
        CounterpartyType.customer.value,
        CounterpartyType.supplier.value,
    }:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "customer/supplier partners are managed via /commercial-partners, "
                "not /counterparties (hedge brokers/banks only)."
            ),
        )
    if payload.tax_id and not CounterpartyService.check_tax_id_unique(session, payload.tax_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="tax_id already exists",
        )
    with unit_of_work(session, request=request):
        cp = CounterpartyService.create(session, payload.model_dump(), commit=False)
        mark_audit_success(request, cp.id, metadata={"actor_sub": actor_sub})
    return CounterpartyRead.model_validate(cp)


@router.get("", response_model=CounterpartyListResponse)
def list_counterparties(
    actor_roles: list[str] = Depends(get_current_actor_roles),
    type: str | None = Query(None, description="Filter by type"),
    kyc_status: str | None = Query(None, description="Filter by KYC status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CounterpartyListResponse:
    # counterparties is hedge-only after W1; a trader-only actor has no hedge
    # access and receives an empty list regardless of any type filter.
    if _is_trader_only(actor_roles):
        return CounterpartyListResponse(items=[], next_cursor=None)
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
    actor_roles: list[str] = Depends(get_current_actor_roles),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    cp = CounterpartyService.get_by_id(session, counterparty_id)
    if not cp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    if _is_trader_only(actor_roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    return CounterpartyRead.model_validate(cp)


@router.patch("/{counterparty_id}", response_model=CounterpartyRead)
def update_counterparty(
    counterparty_id: UUID,
    payload: CounterpartyUpdate,
    request: Request,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="counterparty", event_type="updated")),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    cp = CounterpartyService.get_by_id(session, counterparty_id)
    if not cp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    if _is_trader_only(actor_roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    update_data = payload.model_dump(exclude_unset=True)
    if (
        "tax_id" in update_data
        and update_data["tax_id"] is not None
        and not CounterpartyService.check_tax_id_unique(
            session, update_data["tax_id"], exclude_id=cp.id
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="tax_id already exists",
        )
    with unit_of_work(session, request=request):
        cp = CounterpartyService.update(session, cp, update_data, commit=False)
        mark_audit_success(request, cp.id, metadata={"actor_sub": actor_sub})
    return CounterpartyRead.model_validate(cp)


@router.delete("/{counterparty_id}", response_model=CounterpartyRead)
def delete_counterparty(
    counterparty_id: UUID,
    request: Request,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="counterparty", event_type="deleted")),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    cp = CounterpartyService.get_by_id(session, counterparty_id)
    if not cp:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    if _is_trader_only(actor_roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    with unit_of_work(session, request=request):
        cp = CounterpartyService.soft_delete(session, cp, commit=False)
        mark_audit_success(request, cp.id, metadata={"actor_sub": actor_sub})
    return CounterpartyRead.model_validate(cp)


@router.post(
    "/{counterparty_id}/kyc-status",
    response_model=CounterpartyRead,
    status_code=status.HTTP_200_OK,
)
def transition_kyc_status(
    counterparty_id: UUID,
    payload: KycStatusTransitionRequest,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="counterparty", event_type="kyc_status_changed")),
    __: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> CounterpartyRead:
    with unit_of_work(session, request=request):
        cp, previous_status = CounterpartyService.set_kyc_status(
            session, counterparty_id, new_status=payload.new_status
        )
        mark_audit_success(
            request,
            cp.id,
            metadata={
                "actor_sub": actor_sub,
                "previous_status": previous_status.value,
                "new_status": payload.new_status.value,
                "reason": payload.reason,
            },
        )
    return CounterpartyRead.model_validate(cp)


@router.post(
    "/{counterparty_id}/screen",
    response_model=SanctionsScreeningRead,
    status_code=status.HTTP_200_OK,
)
def screen_counterparty(
    counterparty_id: UUID,
    request: Request,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    # auditor is read-only and MUST NOT trigger a screening (a write); trader is
    # admitted to the gate only to receive the existence-hiding 404 below.
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> SanctionsScreeningRead:
    if _is_trader_only(actor_roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    with unit_of_work(session, request=request):
        screening = screen_partner(
            session,
            SanctionsPartnerType.hedge,
            counterparty_id,
            actor_sub=actor_sub,
            commit=False,
        )
    return SanctionsScreeningRead.model_validate(screening)


@router.post(
    "/{counterparty_id}/adjudicate-sanctions",
    response_model=SanctionsAdjudicationRead,
    status_code=status.HTTP_200_OK,
)
def adjudicate_counterparty(
    counterparty_id: UUID,
    payload: SanctionsAdjudicationRequest,
    request: Request,
    actor_roles: list[str] = Depends(get_current_actor_roles),
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> SanctionsAdjudicationRead:
    if _is_trader_only(actor_roles):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Counterparty not found")
    with unit_of_work(session, request=request):
        row = adjudicate_sanctions(
            session,
            SanctionsPartnerType.hedge,
            counterparty_id,
            decision=AdjudicationDecision(payload.decision.value),
            reason=payload.reason,
            actor_sub=actor_sub,
            commit=False,
        )
    return SanctionsAdjudicationRead.model_validate(row)
