from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.core.auth import (
    get_current_actor_sub,
    require_any_role,
    require_role,
)
from app.core.database import get_session
from app.core.pagination import paginate
from app.models.commercial_partner import CommercialPartner
from app.schemas.commercial_partner import (
    CommercialPartnerCreate,
    CommercialPartnerKind,
    CommercialPartnerListResponse,
    CommercialPartnerRead,
    CommercialPartnerUpdate,
    CreditApprovalRequest,
)
from app.schemas.counterparty import KycStatus, KycStatusTransitionRequest
from app.services.commercial_partner_service import CommercialPartnerService

router = APIRouter()

# kyc_status + credit/terms are NOT mutable via the generic PATCH route by ANY actor;
# they change only via the dedicated audited endpoints. CommercialPartnerUpdate omits
# these fields, so the generic PATCH handler inspects the RAW body and refuses with 403
# (governance: explicit refusal, no silent drop).
_PROTECTED_PATCH_FIELDS = {
    "kyc_status",
    "credit_limit",
    "credit_currency",
    "payment_conditions",
    "approved_value",
    "approved_currency",
    "approved_terms",
}


@router.post("", response_model=CommercialPartnerRead, status_code=status.HTTP_201_CREATED)
def create_commercial_partner(
    payload: CommercialPartnerCreate,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="commercial_partner", event_type="created")),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    if payload.tax_id and not CommercialPartnerService.check_tax_id_unique(session, payload.tax_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tax_id already exists")
    with unit_of_work(session, request=request):
        cp = CommercialPartnerService.create(session, payload.model_dump(), commit=False)
        mark_audit_success(request, cp.id, metadata={"actor_sub": actor_sub})
    return CommercialPartnerRead.model_validate(cp)


@router.get("", response_model=CommercialPartnerListResponse)
def list_commercial_partners(
    kind: CommercialPartnerKind | None = Query(None, description="Filter by kind"),
    kyc_status: KycStatus | None = Query(None, description="Filter by KYC status"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CommercialPartnerListResponse:
    query = CommercialPartnerService.list(
        session,
        kind_filter=kind.value if kind else None,
        kyc_status_filter=kyc_status.value if kyc_status else None,
        is_active_filter=is_active,
    )
    items, next_cursor = paginate(
        query,
        created_at_col=CommercialPartner.created_at,
        id_col=CommercialPartner.id,
        cursor=cursor,
        limit=limit,
    )
    return CommercialPartnerListResponse(
        items=[CommercialPartnerRead.model_validate(cp) for cp in items],
        next_cursor=next_cursor,
    )


@router.get("/{commercial_partner_id}", response_model=CommercialPartnerRead)
def get_commercial_partner(
    commercial_partner_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    return CommercialPartnerRead.model_validate(cp)


@router.patch("/{commercial_partner_id}", response_model=CommercialPartnerRead)
def update_commercial_partner(
    commercial_partner_id: UUID,
    payload: CommercialPartnerUpdate,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="commercial_partner", event_type="updated")),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    raw_body = getattr(request.state, "audit_payload_obj", None)
    if isinstance(raw_body, dict) and _PROTECTED_PATCH_FIELDS & raw_body.keys():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "kyc_status and credit/terms are not mutable via generic PATCH; use "
                "POST {id}/kyc-status or PATCH {id}/credit."
            ),
        )
    update_data = payload.model_dump(exclude_unset=True)
    if (
        "tax_id" in update_data
        and update_data["tax_id"] is not None
        and not CommercialPartnerService.check_tax_id_unique(
            session, update_data["tax_id"], exclude_id=cp.id
        )
    ):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tax_id already exists")
    with unit_of_work(session, request=request):
        cp = CommercialPartnerService.update(session, cp, update_data, commit=False)
        mark_audit_success(request, cp.id, metadata={"actor_sub": actor_sub})
    return CommercialPartnerRead.model_validate(cp)


@router.delete("/{commercial_partner_id}", response_model=CommercialPartnerRead)
def delete_commercial_partner(
    commercial_partner_id: UUID,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(audit_event(entity_type="commercial_partner", event_type="deleted")),
    __: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    with unit_of_work(session, request=request):
        cp = CommercialPartnerService.soft_delete(session, cp, commit=False)
        mark_audit_success(request, cp.id, metadata={"actor_sub": actor_sub})
    return CommercialPartnerRead.model_validate(cp)


@router.post(
    "/{commercial_partner_id}/kyc-status",
    response_model=CommercialPartnerRead,
    status_code=status.HTTP_200_OK,
)
def transition_kyc_status(
    commercial_partner_id: UUID,
    payload: KycStatusTransitionRequest,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(
        audit_event(
            entity_type="commercial_partner",
            event_type="commercial_partner_kyc_status_changed",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    with unit_of_work(session, request=request):
        cp, previous_status = CommercialPartnerService.set_kyc_status(
            session, commercial_partner_id, new_status=payload.new_status
        )
        mark_audit_success(
            request,
            cp.id,
            metadata={
                "commercial_partner_id": str(cp.id),
                "previous_status": previous_status.value,
                "new_status": payload.new_status.value,
                "transition_actor_sub": actor_sub,
                "reason": payload.reason,
            },
        )
    return CommercialPartnerRead.model_validate(cp)


@router.patch(
    "/{commercial_partner_id}/credit",
    response_model=CommercialPartnerRead,
    status_code=status.HTTP_200_OK,
)
def approve_credit(
    commercial_partner_id: UUID,
    payload: CreditApprovalRequest,
    request: Request,
    actor_sub: str = Depends(get_current_actor_sub),
    _: None = Depends(
        audit_event(
            entity_type="commercial_partner",
            event_type="commercial_partner_credit_approved",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    session: Session = Depends(get_session),
) -> CommercialPartnerRead:
    cp = CommercialPartnerService.get_by_id(session, commercial_partner_id)
    if not cp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Commercial partner not found"
        )
    data = payload.model_dump(exclude_unset=True)
    reason = data.pop("reason")
    with unit_of_work(session, request=request):
        cp, changed, previous_values, new_values = CommercialPartnerService.approve_credit(
            session, cp, data, commit=False
        )
        mark_audit_success(
            request,
            cp.id,
            metadata={
                "commercial_partner_id": str(cp.id),
                "kind": cp.kind.value,
                "fields_changed": changed,
                "previous_values": previous_values,
                "new_values": new_values,
                "approving_actor_sub": actor_sub,
                "reason": reason,
            },
        )
    return CommercialPartnerRead.model_validate(cp)
