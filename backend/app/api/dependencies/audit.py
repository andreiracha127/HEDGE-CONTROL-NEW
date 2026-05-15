from __future__ import annotations

import json
import uuid
from typing import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_session
from app.core.logging import get_logger
from app.core.metrics import audit_events_total
from app.services.audit_trail_service import AuditTrailService, normalize_payload_raw

logger = get_logger()


def mark_audit_success(
    request: Request,
    entity_id: uuid.UUID | None = None,
    *,
    metadata: dict | None = None,
) -> None:
    request.state.audit_should_record = True
    if entity_id is not None:
        request.state.audit_entity_id = entity_id
    if metadata is not None:
        request.state.audit_metadata = metadata


def record_audit_checkpoint(
    request: Request,
    entity_id: uuid.UUID | None = None,
    *,
    metadata: dict | None = None,
) -> None:
    mark_audit_success(request, entity_id, metadata=metadata)
    previous = getattr(request.state, "audit_defer_commit", False)
    request.state.audit_defer_commit = True
    try:
        request.state.audit_commit()
    finally:
        request.state.audit_defer_commit = previous


def _get_state_entity_id(request: Request, _: dict | None) -> uuid.UUID | None:
    return getattr(request.state, "audit_entity_id", None)


def audit_event(
    *,
    entity_type: str,
    entity_id_getter: Callable[[Request, dict | None], uuid.UUID | None] = _get_state_entity_id,
    event_type: str,
) -> Callable:
    """Configure fail-closed route-level audit emission.

    Mutating handlers using this dependency must call ``mark_audit_success()``
    with a durable entity id inside the same ``unit_of_work`` as the mutation.
    Missing ids intentionally fail closed and roll back the enclosing unit.
    """

    async def _dependency(
        request: Request,
        session: Session = Depends(get_session),
    ) -> None:
        payload_bytes = await request.body()
        payload_text = payload_bytes.decode("utf-8") if payload_bytes else "null"
        payload_obj = json.loads(payload_text) if payload_text and payload_text != "null" else None
        payload_canonical, payload_obj = normalize_payload_raw(payload_obj)

        request.state.audit_payload_raw = payload_canonical
        request.state.audit_payload_obj = payload_obj

        def _commit_audit() -> None:
            if not getattr(request.state, "audit_should_record", False):
                return
            if getattr(request.state, "audit_recorded", False):
                return
            entity_id = entity_id_getter(request, payload_obj)
            if entity_id is None:
                logger.error(
                    "audit_event_entity_id_missing",
                    entity_type=entity_type,
                    event_type=event_type,
                    path=str(request.url.path),
                    method=request.method,
                )
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="entity_id missing",
                )
            payload_for_record = payload_obj
            payload_raw = payload_canonical
            metadata = getattr(request.state, "audit_metadata", None)
            if metadata is not None:
                payload_raw, payload_for_record = normalize_payload_raw(
                    {"request": payload_obj, "metadata": metadata}
                )

            AuditTrailService.record(
                session,
                event_id=uuid.uuid4(),
                entity_type=entity_type,
                entity_id=entity_id,
                event_type=event_type,
                payload_raw=payload_raw,
                payload_obj=payload_for_record,
                commit=not getattr(request.state, "audit_defer_commit", False),
            )
            request.state.audit_recorded = True
            audit_events_total.labels(entity_type=entity_type, event_type=event_type).inc()

        request.state.audit_commit = _commit_audit

    return _dependency
