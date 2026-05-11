from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.auth import require_role
from app.core.database import get_session
from app.schemas.audit import AuditEventListResponse, AuditEventRead
from app.services.audit_trail_service import (
    AuditTrailService,
    _get_signing_key,
)


router = APIRouter()


class AuditVerifyResponse(BaseModel):
    event_id: UUID
    valid: bool
    detail: str


@router.get("/events", response_model=AuditEventListResponse)
def list_audit_events(
    entity_type: str | None = Query(None),
    entity_id: UUID | None = Query(None),
    start: datetime | None = Query(None),
    end: datetime | None = Query(None),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    _: None = Depends(require_role("auditor")),
    session: Session = Depends(get_session),
) -> AuditEventListResponse:
    rows, next_cursor = AuditTrailService.list_events(
        session,
        entity_type=entity_type,
        entity_id=entity_id,
        start=start,
        end=end,
        cursor=cursor,
        limit=limit,
    )

    return AuditEventListResponse(
        events=[AuditEventRead.model_validate(row) for row in rows],
        next_cursor=next_cursor,
    )


@router.get("/events/{event_id}/verify", response_model=AuditVerifyResponse)
def verify_audit_event(
    event_id: UUID,
    _: None = Depends(require_role("auditor")),
    session: Session = Depends(get_session),
) -> AuditVerifyResponse:
    """Verify the HMAC signature of an audit event."""
    event = AuditTrailService.get_event(session, event_id)

    key = _get_signing_key()
    if key is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AUDIT_SIGNING_KEY not configured — verification unavailable",
        )

    if event.signature is None:
        return AuditVerifyResponse(
            event_id=event_id,
            valid=False,
            detail="Event was recorded without a signature",
        )

    valid, detail = AuditTrailService.verify_event(event, key)
    return AuditVerifyResponse(
        event_id=event_id,
        valid=valid,
        detail=detail,
    )
