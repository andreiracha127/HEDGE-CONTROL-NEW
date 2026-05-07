from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session, joinedload

from app.core.auth import require_any_role, require_role
from app.core.database import get_session
from app.core.pagination import paginate
from app.core.rate_limit import RATE_LIMIT_MUTATION, limiter
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.models.quotes import RFQQuote
from app.models.rfqs import RFQ, RFQDirection, RFQIntent, RFQState, RFQStateEvent
from app.schemas.rfq import (
    RFQCreate,
    RFQAwardRequest,
    RFQAwardQuoteRequest,
    RFQCancelRequest,
    RFQListResponse,
    RFQQuoteCreate,
    RFQQuoteRead,
    RFQRefreshRequest,
    RFQRefreshCounterpartyRequest,
    RFQRejectRequest,
    RFQRejectQuoteRequest,
    RFQRead,
    RFQInvitationRead,
    RFQStateEventRead,
    RFQTextPreviewRequest,
    RFQTextPreviewResponse,
    RFQUserActionBase,
    SpreadRankingRead,
    TradeRankingFailureCode,
    TradeRankingRead,
)
from app.api.routes.ws import manager as ws_manager
from app.services.rfq_service import RFQService

router = APIRouter()


def _build_rfq_read(session: Session, rfq_id: UUID) -> RFQRead:
    """Build a full RFQRead response including invitations."""
    rfq = RFQService.get(session, rfq_id)
    invitations = RFQService.get_invitations(session, rfq_id)
    rfq_read = RFQRead.model_validate(rfq)
    rfq_read.invitations = [RFQInvitationRead.model_validate(i) for i in invitations]
    return rfq_read


@router.get("", response_model=RFQListResponse)
def list_rfqs(
    state: str | None = Query(
        None, description="Filter by state (CREATED, SENT, QUOTED, AWARDED, CLOSED)"
    ),
    intent: str | None = Query(
        None, description="Filter by intent (COMMERCIAL_HEDGE, GLOBAL_POSITION, SPREAD)"
    ),
    direction: str | None = Query(None, description="Filter by direction (BUY, SELL)"),
    commodity: str | None = Query(None, description="Filter by commodity"),
    include_deleted: bool = Query(False, description="Include soft-deleted records"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> RFQListResponse:
    from app.models.rfqs import RFQInvitation

    query = session.query(RFQ).options(joinedload(RFQ.invitations))
    if not include_deleted:
        query = query.filter(RFQ.deleted_at.is_(None))
    if state:
        query = query.filter(RFQ.state == RFQState(state))
    if intent:
        query = query.filter(RFQ.intent == RFQIntent(intent))
    if direction:
        query = query.filter(RFQ.direction == RFQDirection(direction))
    if commodity:
        query = query.filter(RFQ.commodity == commodity)
    items, next_cursor = paginate(
        query,
        created_at_col=RFQ.created_at,
        id_col=RFQ.id,
        cursor=cursor,
        limit=limit,
    )
    rfq_reads = []
    for rfq in items:
        rfq_read = RFQRead.model_validate(rfq)
        rfq_read.invitations = [
            RFQInvitationRead.model_validate(i) for i in rfq.invitations
        ]
        rfq_reads.append(rfq_read)
    return RFQListResponse(items=rfq_reads, next_cursor=next_cursor)


@router.post("", response_model=RFQRead, status_code=status.HTTP_201_CREATED)
@limiter.limit(RATE_LIMIT_MUTATION)
def create_rfq(
    payload: RFQCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQRead:
    rfq = RFQService.create(session, payload)
    session.commit()
    session.refresh(rfq)
    mark_audit_success(request, rfq.id)
    request.state.audit_commit()
    return _build_rfq_read(session, rfq.id)


@router.post("/preview-text", response_model=RFQTextPreviewResponse)
def preview_rfq_text(
    payload: RFQTextPreviewRequest,
    _: None = Depends(require_role("trader")),
) -> RFQTextPreviewResponse:
    """Generate RFQ message text without persisting anything.

    Useful for the trader to review the LME-formatted message before
    actually creating / sending the RFQ.
    """
    from app.services.rfq_engine import (
        Leg,
        OrderInstruction,
        OrderType,
        PriceType,
        RfqTrade,
        Side,
        TradeType,
        compute_trade_ppt_dates,
    )
    from app.services.rfq_message_builder import build_rfq_message, build_pt_summary

    def _to_leg(inp: "RFQLegInput") -> Leg:  # noqa: F821
        order = None
        if inp.order_type is not None:
            order = OrderInstruction(
                order_type=OrderType(inp.order_type.value),
                validity=inp.order_validity,
                limit_price=inp.order_limit_price,
            )
        return Leg(
            side=Side(inp.side.value),
            price_type=PriceType(inp.price_type.value),
            # rfq_engine.Leg/build_rfq_message operate in float for preview
            # text formatting only (non-economic path); coerce at the boundary.
            quantity_mt=float(inp.quantity_mt),
            month_name=inp.month_name,
            year=inp.year,
            start_date=inp.start_date,
            end_date=inp.end_date,
            fixing_date=inp.fixing_date,
            order=order,
        )

    leg1 = _to_leg(payload.leg1)
    leg2 = _to_leg(payload.leg2) if payload.leg2 else None

    trade = RfqTrade(
        trade_type=TradeType(payload.trade_type.value),
        leg1=leg1,
        leg2=leg2,
        sync_ppt=payload.sync_ppt,
    )

    try:
        text = build_rfq_message(
            channel_type=payload.channel_type,
            trade=trade,
            company_header=payload.company_header,
            company_label_for_payoff=payload.company_label_for_payoff,
        )

        text_pt = build_pt_summary(
            trade=trade,
            company_header=payload.company_header,
        )

        ppts = compute_trade_ppt_dates(trade)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return RFQTextPreviewResponse(
        text=text,
        text_en=text,
        text_pt=text_pt,
        leg1_ppt=ppts["leg1_ppt"],
        leg2_ppt=ppts["leg2_ppt"],
        trade_ppt=ppts["trade_ppt"],
    )


@router.get("/{rfq_id}", response_model=RFQRead)
def get_rfq(
    rfq_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> RFQRead:
    return _build_rfq_read(session, rfq_id)


@router.get("/{rfq_id}/quotes", response_model=list[RFQQuoteRead])
def list_rfq_quotes(
    rfq_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> list[RFQQuoteRead]:
    """List all quotes for a specific RFQ."""
    rfq = session.get(RFQ, rfq_id)
    if not rfq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="RFQ not found"
        )
    quotes = (
        session.query(RFQQuote)
        .filter(RFQQuote.rfq_id == rfq_id)
        .order_by(RFQQuote.created_at)
        .all()
    )
    return [RFQQuoteRead.model_validate(q) for q in quotes]


@router.get("/{rfq_id}/state-events", response_model=list[RFQStateEventRead])
def list_rfq_state_events(
    rfq_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> list[RFQStateEventRead]:
    """List all state-transition events for an RFQ (timeline)."""
    rfq = session.get(RFQ, rfq_id)
    if not rfq:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="RFQ not found"
        )
    events = (
        session.query(RFQStateEvent)
        .filter(RFQStateEvent.rfq_id == rfq_id)
        .order_by(RFQStateEvent.created_at)
        .all()
    )
    return [RFQStateEventRead.model_validate(e) for e in events]


@router.post(
    "/{rfq_id}/quotes", response_model=RFQQuoteRead, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RATE_LIMIT_MUTATION)
def create_quote(
    rfq_id: UUID,
    payload: RFQQuoteCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq_quote",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQQuoteRead:
    quote = RFQService.submit_quote(session, rfq_id, payload)
    session.commit()
    session.refresh(quote)
    mark_audit_success(request, quote.id)
    request.state.audit_commit()
    return RFQQuoteRead.model_validate(quote)


@router.get("/{rfq_id}/trade-ranking", response_model=TradeRankingRead)
def get_trade_ranking(
    rfq_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> TradeRankingRead:
    rfq = RFQService.get(session, rfq_id)
    if rfq.intent == RFQIntent.spread:
        return TradeRankingRead(
            rfq_id=rfq_id,
            status="FAILURE",
            failure_code=TradeRankingFailureCode.not_trade_intent,
            failure_reason="Trade ranking is not defined for intent=SPREAD",
            ranking=[],
        )
    latest = RFQService.get_latest_trade_quotes(session, rfq.id)
    return RFQService.compute_trade_ranking(rfq, latest)


@router.get("/{rfq_id}/ranking", response_model=SpreadRankingRead)
def get_spread_ranking(
    rfq_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> SpreadRankingRead:
    rfq = RFQService.get(session, rfq_id)
    return RFQService.compute_spread_ranking(session, rfq)


@router.post("/{rfq_id}/actions/reject", response_model=RFQRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def reject_rfq(
    rfq_id: UUID,
    payload: RFQRejectRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq",
            event_type="rejected",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQRead:
    RFQService.reject(session, rfq_id, payload.user_id)
    session.commit()
    mark_audit_success(request, rfq_id)
    request.state.audit_commit()
    return _build_rfq_read(session, rfq_id)


@router.post("/{rfq_id}/actions/cancel", response_model=RFQRead)
@limiter.limit(RATE_LIMIT_MUTATION)
async def cancel_rfq(
    rfq_id: UUID,
    payload: RFQCancelRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq",
            event_type="cancelled",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQRead:
    """Cancel an RFQ in CREATED or SENT state."""
    RFQService.cancel(session, rfq_id, payload.user_id)
    session.commit()
    mark_audit_success(request, rfq_id)
    request.state.audit_commit()
    await ws_manager.broadcast(
        "rfq",
        str(rfq_id),
        "status_changed",
        {"status": "CLOSED", "reason": "cancelled"},
    )
    return _build_rfq_read(session, rfq_id)


# ─── Per-counterparty / per-quote actions ────────────────────────────────────


@router.post("/{rfq_id}/actions/reject-quote", response_model=RFQRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def reject_quote(
    rfq_id: UUID,
    quote_id: UUID,
    payload: RFQRejectQuoteRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq_quote",
            event_type="quote_rejected",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQRead:
    """Reject a specific counterparty quote without closing the RFQ."""
    RFQService.reject_quote(session, rfq_id, quote_id)
    session.commit()
    mark_audit_success(request, rfq_id)
    request.state.audit_commit()
    return _build_rfq_read(session, rfq_id)


@router.post("/{rfq_id}/actions/refresh-counterparty", response_model=RFQRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def refresh_counterparty(
    rfq_id: UUID,
    payload: RFQRefreshCounterpartyRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq",
            event_type="counterparty_refreshed",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQRead:
    """Re-send invitation to a specific counterparty."""
    RFQService.refresh_counterparty(
        session, rfq_id, payload.counterparty_id, payload.user_id
    )
    session.commit()
    mark_audit_success(request, rfq_id)
    request.state.audit_commit()
    return _build_rfq_read(session, rfq_id)


@router.post("/{rfq_id}/actions/award-quote", response_model=RFQRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def award_quote(
    rfq_id: UUID,
    payload: RFQAwardQuoteRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq",
            event_type="quote_awarded",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQRead:
    """Award a specific quote — creates a contract from this counterparty's quote."""
    RFQService.award_quote(session, rfq_id, payload.quote_id, payload.user_id)
    session.commit()
    mark_audit_success(request, rfq_id)
    request.state.audit_commit()
    return _build_rfq_read(session, rfq_id)


@router.post("/{rfq_id}/actions/refresh", response_model=RFQRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def refresh_rfq(
    rfq_id: UUID,
    payload: RFQRefreshRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq",
            event_type="refreshed",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQRead:
    RFQService.refresh(session, rfq_id, payload.user_id)
    session.commit()
    mark_audit_success(request, rfq_id)
    request.state.audit_commit()
    return _build_rfq_read(session, rfq_id)


@router.post("/{rfq_id}/actions/award", response_model=RFQRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def award_rfq(
    rfq_id: UUID,
    payload: RFQAwardRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq",
            event_type="awarded",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQRead:
    RFQService.award(session, rfq_id, payload.user_id)
    session.commit()
    mark_audit_success(request, rfq_id)
    request.state.audit_commit()
    return _build_rfq_read(session, rfq_id)


@router.patch("/{rfq_id}/archive", response_model=RFQRead)
@limiter.limit(RATE_LIMIT_MUTATION)
def archive_rfq(
    rfq_id: UUID,
    payload: RFQUserActionBase,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="rfq",
            event_type="archived",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> RFQRead:
    rfq = RFQService.archive(session, rfq_id, user_id=payload.user_id)
    session.commit()
    session.refresh(rfq)
    mark_audit_success(request, rfq.id)
    request.state.audit_commit()
    return _build_rfq_read(session, rfq_id)
