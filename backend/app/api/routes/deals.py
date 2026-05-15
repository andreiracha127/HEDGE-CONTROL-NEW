"""Routes for Deal Engine (component 1.5)."""

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_actor_sub, require_any_role, require_role
from app.core.database import get_session
from app.core.pagination import paginate
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.models.deal import Deal, DealLink, DealLinkedType
from app.schemas.deal import (
    DealCreate,
    DealDetailRead,
    DealLinkCreate,
    DealLinkRead,
    DealListResponse,
    DealPNLHistoryResponse,
    DealPNLSnapshotRead,
    DealRead,
    PnlBreakdownRequest,
    PnlBreakdownResponse,
)
from app.services.deal_engine import DealEngineService
from app.services.price_lookup_service import PriceReferenceUnprovable

router = APIRouter()


# ── PriceReferenceUnprovable → 424 mapping ────────────────────────────
# Governance "Projection invariants" (docs/governance.md:152) binds:
# "Hard-fail propagation: price reference unprovable -> HTTP 424".
# 422 is reserved by governance for distinct cases (missing zero-default
# economics, missing settlement_date; governance lines 155-157).
# cashflow.py and scenario.py already map this exception to 424; this
# helper brings deals.py into alignment.
def _raise_price_unprovable(exc: PriceReferenceUnprovable) -> None:
    raise HTTPException(
        status_code=status.HTTP_424_FAILED_DEPENDENCY,
        detail=str(exc),
    )


_PRICE_UNPROVABLE_RESPONSES = {
    status.HTTP_424_FAILED_DEPENDENCY: {
        "description": "Price reference unprovable",
    },
}


# ------------------------------------------------------------------
# Static paths first
# ------------------------------------------------------------------


@router.get("/by-linked-entity", response_model=DealRead)
def find_deal_by_linked_entity(
    linked_type: str = Query(..., description="e.g. sales_order, purchase_order"),
    linked_id: UUID = Query(...),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
):
    """Find the deal that contains a given linked entity (order or contract)."""
    try:
        resolved_type = DealLinkedType(linked_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid linked_type: {linked_type}",
        )
    link = (
        session.query(DealLink)
        .filter(DealLink.linked_type == resolved_type, DealLink.linked_id == linked_id)
        .first()
    )
    if not link:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No deal found for the given entity.",
        )
    deal = session.get(Deal, link.deal_id)
    if not deal:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Deal not found.",
        )
    return deal


@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
def create_deal(
    body: DealCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="deal",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
):
    data = body.model_dump()
    # Convert enum values in links
    if data.get("links"):
        for link in data["links"]:
            if hasattr(link.get("linked_type"), "value"):
                link["linked_type"] = link["linked_type"].value
    with unit_of_work(session, request=request):
        deal = DealEngineService.create_deal(session, data)
        mark_audit_success(request, deal.id, metadata={"actor_sub": actor_sub})
    return deal


@router.get("", response_model=DealListResponse)
def list_deals(
    commodity: Optional[str] = Query(None),
    status_filter: Optional[str] = Query(None, alias="status"),
    cursor: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
):
    q = DealEngineService.list_deals(session, commodity, status_filter)
    items, next_cursor = paginate(
        q,
        created_at_col=Deal.created_at,
        id_col=Deal.id,
        cursor=cursor,
        limit=limit,
    )
    return {"items": items, "next_cursor": next_cursor}


@router.post(
    "/pnl-breakdown",
    response_model=PnlBreakdownResponse,
    responses=_PRICE_UNPROVABLE_RESPONSES,
)
def pnl_breakdown(
    body: PnlBreakdownRequest,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
):
    """Compute P&L breakdown for one, many, or all deals."""
    try:
        result = DealEngineService.compute_pnl_breakdown(
            session, body.deal_ids, body.snapshot_date
        )
    except PriceReferenceUnprovable as exc:
        _raise_price_unprovable(exc)
    return result


# ------------------------------------------------------------------
# Path-parameter routes
# ------------------------------------------------------------------


@router.get("/{deal_id}", response_model=DealDetailRead)
def get_deal(
    deal_id: UUID,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
):
    return DealEngineService.get_detail(session, deal_id)


@router.post(
    "/{deal_id}/links", response_model=DealLinkRead, status_code=status.HTTP_201_CREATED
)
def add_link(
    deal_id: UUID,
    body: DealLinkCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="deal_link",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
):
    with unit_of_work(session, request=request):
        link = DealEngineService.add_link(
            session, deal_id, body.linked_type.value, body.linked_id
        )
        mark_audit_success(request, link.id, metadata={"actor_sub": actor_sub})
    return link


@router.delete("/{deal_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_link(
    deal_id: UUID,
    link_id: UUID,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="deal_link",
            event_type="deleted",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
):
    with unit_of_work(session, request=request):
        DealEngineService.remove_link(session, deal_id, link_id)
        # Service returns None — anchor the audit on the path parameter
        # (canonical id of the entity that was just deleted).
        mark_audit_success(request, link_id, metadata={"actor_sub": actor_sub})
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{deal_id}/pnl-snapshot",
    response_model=DealPNLSnapshotRead,
    status_code=status.HTTP_201_CREATED,
    responses=_PRICE_UNPROVABLE_RESPONSES,
)
def trigger_pnl_snapshot(
    deal_id: UUID,
    request: Request,
    snapshot_date: date = Query(default=None),
    _: None = Depends(
        audit_event(
            entity_type="deal_pnl_snapshot",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
):
    if snapshot_date is None:
        snapshot_date = date.today()
    try:
        with unit_of_work(session, request=request):
            snapshot = DealEngineService.compute_deal_pnl(
                session, deal_id, snapshot_date
            )
            mark_audit_success(request, snapshot.id, metadata={"actor_sub": actor_sub})
    except PriceReferenceUnprovable as exc:
        _raise_price_unprovable(exc)
    return snapshot


@router.get("/{deal_id}/pnl-history", response_model=DealPNLHistoryResponse)
def pnl_history(
    deal_id: UUID,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
):
    snapshots = DealEngineService.get_pnl_history(session, deal_id)
    return {"items": snapshots}
