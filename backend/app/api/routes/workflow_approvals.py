from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.dependencies.uow import unit_of_work
from app.core.auth import (
    get_current_actor_roles,
    get_current_actor_sub,
    require_any_role,
)
from app.core.database import get_session
from app.core.pagination import paginate
from app.models.workflow_approval import ApprovalStatus, WorkflowApprovalRequest
from app.schemas.cashflow import HedgeContractSettlementCreate
from app.schemas.workflow_approval import (
    WorkflowApprovalConsumeRequest,
    WorkflowApprovalListResponse,
    WorkflowApprovalRejectRequest,
    WorkflowApprovalRequestRead,
)
from app.services.cashflow_ledger_service import ingest_hedge_contract_settlement
from app.services.deal_engine import DealEngineService
from app.services.rfq_service import RFQService
from app.services.workflow_approval_service import (
    consume_request,
    grant_request,
    reject_request,
    supersede_request,
)

router = APIRouter()


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=WorkflowApprovalListResponse)
def list_workflow_approvals(
    status_filter: ApprovalStatus | None = Query(None, alias="status"),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> dict:
    query = session.query(WorkflowApprovalRequest)
    if status_filter is not None:
        query = query.filter(WorkflowApprovalRequest.status == status_filter)
    items, next_cursor = paginate(
        query,
        created_at_col=WorkflowApprovalRequest.created_at,
        id_col=WorkflowApprovalRequest.id,
        cursor=cursor,
        limit=limit,
    )
    return {"items": items, "next_cursor": next_cursor}


@router.get("/{approval_id}", response_model=WorkflowApprovalRequestRead)
def get_workflow_approval(
    approval_id: UUID,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> WorkflowApprovalRequest:
    row = session.get(WorkflowApprovalRequest, approval_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Approval not found")
    return row


@router.post("/{approval_id}/grant", response_model=WorkflowApprovalRequestRead)
def grant_workflow_approval(
    approval_id: UUID,
    request: Request,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    actor_sub: str = Depends(get_current_actor_sub),
    actor_roles: list[str] = Depends(get_current_actor_roles),
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
    session: Session = Depends(get_session),
) -> WorkflowApprovalRequest:
    with unit_of_work(session, request=request):
        row = grant_request(
            session,
            approval_id,
            actor_sub,
            set(actor_roles),
            _client_ip(request),
            x_session_id,
        )
    return row


@router.post("/{approval_id}/reject", response_model=WorkflowApprovalRequestRead)
def reject_workflow_approval(
    approval_id: UUID,
    payload: WorkflowApprovalRejectRequest,
    request: Request,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    actor_sub: str = Depends(get_current_actor_sub),
    actor_roles: list[str] = Depends(get_current_actor_roles),
    x_session_id: str | None = Header(None, alias="X-Session-Id"),
    session: Session = Depends(get_session),
) -> WorkflowApprovalRequest:
    with unit_of_work(session, request=request):
        row = reject_request(
            session,
            approval_id,
            actor_sub,
            set(actor_roles),
            _client_ip(request),
            x_session_id,
            payload.reason_code,
            payload.reason_text,
        )
    return row


@router.post("/{approval_id}/supersede", response_model=WorkflowApprovalRequestRead)
def supersede_workflow_approval(
    approval_id: UUID,
    request: Request,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
) -> WorkflowApprovalRequest:
    with unit_of_work(session, request=request):
        row = supersede_request(session, approval_id, actor_sub)
    return row


@router.post("/{approval_id}/consume", response_model=WorkflowApprovalRequestRead)
def consume_workflow_approval(
    approval_id: UUID,
    payload: WorkflowApprovalConsumeRequest,
    request: Request,
    _: None = Depends(require_any_role("risk_manager", "auditor")),
    actor_sub: str = Depends(get_current_actor_sub),
    session: Session = Depends(get_session),
) -> WorkflowApprovalRequest:
    def _executor(consume_payload: object) -> object:
        row = session.get(WorkflowApprovalRequest, approval_id)
        if row is None:
            raise RuntimeError("approval row disappeared during consume")
        data = dict(consume_payload)
        if row.mutation_type.value == "deal_create":
            return DealEngineService.create_deal(session, data)
        if row.mutation_type.value == "deal_award":
            return RFQService.award(session, UUID(str(data["rfq_id"])), actor_sub)
        if row.mutation_type.value == "hedge_contract_settle":
            contract_id = UUID(str(data["contract_id"]))
            settle_payload = HedgeContractSettlementCreate.model_validate(data["payload"])
            return ingest_hedge_contract_settlement(
                session, contract_id, settle_payload, commit=False
            )
        raise RuntimeError(f"Unsupported mutation_type {row.mutation_type.value}")

    with unit_of_work(session, request=request):
        row, _ = consume_request(session, approval_id, actor_sub, payload.payload, _executor)
    return row
