from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.auth import require_any_role, require_role
from app.core.database import get_session
from app.core.rate_limit import RATE_LIMIT_MUTATION, limiter
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.schemas.cashflow import (
    CashFlowLedgerEntryRead,
    HedgeContractSettlementCreate,
    HedgeContractSettlementResponse,
)
from app.services.cashflow_ledger_service import (
    SOURCE_EVENT_TYPE,
    ingest_hedge_contract_settlement,
    list_entries_by_contract,
    list_entries_by_event,
)


router = APIRouter()


@router.post(
    "/contracts/{contract_id}/settle",
    response_model=HedgeContractSettlementResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(RATE_LIMIT_MUTATION)
def settle_hedge_contract(
    contract_id: UUID,
    payload: HedgeContractSettlementCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="hedge_contract_settlement",
            event_type="settled",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> HedgeContractSettlementResponse:
    with unit_of_work(session, request=request):
        event, ledger_entries = ingest_hedge_contract_settlement(
            session, contract_id, payload, commit=False
        )
        mark_audit_success(request, event.id)
    return HedgeContractSettlementResponse(
        event=event,
        ledger_entries=[
            CashFlowLedgerEntryRead.model_validate(entry) for entry in ledger_entries
        ],
    )


@router.get(
    "/ledger/hedge-contracts/{contract_id}",
    response_model=list[CashFlowLedgerEntryRead],
)
def list_ledger_entries_for_contract(
    contract_id: UUID,
    start: date | None = Query(None),
    end: date | None = Query(None),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> list[CashFlowLedgerEntryRead]:
    entries = list_entries_by_contract(
        session, contract_id=contract_id, start=start, end=end
    )
    return [CashFlowLedgerEntryRead.model_validate(entry) for entry in entries]


@router.get("/ledger", response_model=list[CashFlowLedgerEntryRead])
def list_ledger_entries_by_event(
    source_event_id: UUID = Query(...),
    source_event_type: str = Query(SOURCE_EVENT_TYPE),
    _: None = Depends(require_any_role("trader", "risk_manager", "auditor")),
    session: Session = Depends(get_session),
) -> list[CashFlowLedgerEntryRead]:
    if source_event_type != SOURCE_EVENT_TYPE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Unsupported source_event_type",
        )
    entries = list_entries_by_event(
        session,
        source_event_id=source_event_id,
        source_event_type=source_event_type,
    )
    return [CashFlowLedgerEntryRead.model_validate(entry) for entry in entries]
