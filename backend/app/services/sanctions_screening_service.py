"""Domain-agnostic sanctions screening + adjudication orchestration.

Writes immutable ``sanctions_screenings`` / ``sanctions_adjudications`` rows,
sets the entity ``sanctions_status``, and emits HMAC audit events. Reuses the
``kyc_gate`` dual-session pattern to record provider-error evidence that
survives the request ``unit_of_work`` rollback.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select  # noqa: F401
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.commercial_partner import CommercialPartner
from app.models.counterparty import Counterparty, SanctionsStatus
from app.models.sanctions import (
    AdjudicationDecision,  # noqa: F401
    SanctionsAdjudication,  # noqa: F401
    SanctionsPartnerType,
    SanctionsScreening,
    ScreeningResult,
    ScreeningStatus,
)
from app.services.audit_trail_service import AuditTrailService
from app.services.opensanctions_client import ScreeningProviderError, screen_entity

_PROVIDER = "opensanctions"


def map_score_to_result(
    top_score: Decimal, review_threshold: Decimal, hard_threshold: Decimal
) -> ScreeningResult:
    if top_score >= hard_threshold:
        return ScreeningResult.blocked
    if top_score >= review_threshold:
        return ScreeningResult.flagged
    return ScreeningResult.clear


def _load_entity(session: Session, partner_type: SanctionsPartnerType, partner_id: uuid.UUID):
    if partner_type is SanctionsPartnerType.commercial:
        entity = session.get(CommercialPartner, partner_id)
    else:
        entity = session.get(Counterparty, partner_id)
    if entity is None or entity.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Partner not found")
    return entity


def _entity_audit_type(partner_type: SanctionsPartnerType) -> str:
    return (
        "commercial_partner" if partner_type is SanctionsPartnerType.commercial else "counterparty"
    )


def _query_hash(name, country, tax_id, lei) -> str:
    canonical = json.dumps(
        {"name": name, "country": country, "tax_id": tax_id, "lei": lei}, sort_keys=True
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _record_error_screening(
    partner_type: SanctionsPartnerType, partner_id: uuid.UUID, *, actor_sub: str, detail: str
) -> None:
    error_session = SessionLocal()
    try:
        error_session.add(
            SanctionsScreening(
                id=uuid.uuid4(),
                partner_type=partner_type,
                partner_id=partner_id,
                screened_at=datetime.now(UTC),
                provider=_PROVIDER,
                algorithm="logic-v2",
                dataset_version=None,
                query_hash="",
                top_score=None,
                match_count=0,
                matches_json=None,
                result=None,
                actor_sub=actor_sub,
                status=ScreeningStatus.error,
                error_detail=detail[:2000],
            )
        )
        error_session.commit()
    finally:
        error_session.close()


def screen(
    session: Session,
    partner_type: SanctionsPartnerType,
    partner_id: uuid.UUID,
    *,
    actor_sub: str,
    commit: bool = True,
) -> SanctionsScreening:
    entity = _load_entity(session, partner_type, partner_id)
    lei = getattr(entity, "lei", None)
    try:
        match = screen_entity(
            name=entity.name, country=entity.country, tax_id=entity.tax_id, lei=lei
        )
    except ScreeningProviderError as exc:
        _record_error_screening(partner_type, partner_id, actor_sub=actor_sub, detail=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "sanctions_screening_provider_error", "partner_id": str(partner_id)},
        ) from exc

    settings = get_settings()
    result = map_score_to_result(
        match.top_score, settings.sanctions_review_threshold, settings.sanctions_hard_threshold
    )
    previous_status = entity.sanctions_status
    screening = SanctionsScreening(
        id=uuid.uuid4(),
        partner_type=partner_type,
        partner_id=partner_id,
        screened_at=datetime.now(UTC),
        provider=_PROVIDER,
        algorithm=match.algorithm,
        dataset_version=match.dataset_version,
        query_hash=_query_hash(entity.name, entity.country, entity.tax_id, lei),
        top_score=match.top_score,
        match_count=match.match_count,
        matches_json=match.matches,
        result=result,
        actor_sub=actor_sub,
        status=ScreeningStatus.success,
        error_detail=None,
    )
    session.add(screening)
    entity.sanctions_status = SanctionsStatus(result.value)
    session.flush()
    AuditTrailService.record(
        session,
        event_id=uuid.uuid4(),
        entity_type=_entity_audit_type(partner_type),
        entity_id=partner_id,
        event_type="sanctions_status_changed",
        payload_raw="",
        payload_obj={
            "partner_type": partner_type.value,
            "partner_id": str(partner_id),
            "previous_status": previous_status.value,
            "new_status": result.value,
            "screening_id": str(screening.id),
            "top_score": str(match.top_score),
            "result": result.value,
            "actor_sub": actor_sub,
        },
        commit=False,
    )
    if commit:
        session.commit()
        session.refresh(screening)
    return screening
