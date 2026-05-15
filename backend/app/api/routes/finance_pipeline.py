"""Routes for Finance Pipeline."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.auth import get_current_actor_sub, require_any_role, require_role
from app.core.database import get_session
from app.api.dependencies.audit import audit_event, mark_audit_success
from app.api.dependencies.uow import unit_of_work
from app.schemas.finance_pipeline import (
    PipelineRunDetailRead,
    PipelineRunListResponse,
    PipelineRunRead,
    TriggerPipelineRequest,
)
from app.services.finance_pipeline_service import FinancePipelineService

router = APIRouter()


@router.post(
    "/run", response_model=PipelineRunRead, status_code=status.HTTP_201_CREATED
)
def trigger_pipeline(
    body: TriggerPipelineRequest,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="finance_pipeline_run",
            event_type="manual_run_triggered",
        )
    ),
    db: Session = Depends(get_session),
    __: None = Depends(require_role("risk_manager")),
    actor_sub: str = Depends(get_current_actor_sub),
) -> PipelineRunRead:
    with unit_of_work(db, request=request):
        run = FinancePipelineService.run_daily_pipeline(
            db, body.run_date, commit=False
        )
        mark_audit_success(request, run.id, metadata={"actor_sub": actor_sub})
    return run


@router.get("/runs", response_model=PipelineRunListResponse)
def list_runs(
    limit: int = 50,
    db: Session = Depends(get_session),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
):
    runs = FinancePipelineService.list_runs(db, limit=limit)
    return {"items": runs}


@router.get("/runs/{run_id}", response_model=PipelineRunDetailRead)
def get_run_detail(
    run_id: uuid.UUID,
    db: Session = Depends(get_session),
    _: None = Depends(require_any_role("risk_manager", "auditor")),
):
    run = FinancePipelineService.get_run(db, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline run not found"
        )
    return run
