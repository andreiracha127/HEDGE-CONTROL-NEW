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
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.models.commercial_partner import CommercialPartner
from app.models.counterparty import Counterparty, SanctionsStatus
from app.models.sanctions import (
    AdjudicationDecision,
    SanctionsAdjudication,
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
    # Row-lock the entity for the duration of the transaction: screen()/adjudicate()
    # both mutate sanctions_status, and concurrent calls would otherwise clobber each
    # other (mirrors set_kyc_status with_for_update in counterparty_service.py). On
    # SQLite with_for_update is a no-op; on Postgres it serializes the mutation.
    model = CommercialPartner if partner_type is SanctionsPartnerType.commercial else Counterparty
    entity = session.get(model, partner_id, with_for_update=True)
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
    partner_type: SanctionsPartnerType,
    partner_id: uuid.UUID,
    *,
    actor_sub: str,
    detail: str,
    query_hash: str,
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
                query_hash=query_hash,
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
    settings = get_settings()
    # Honor the feature flag: when screening is disabled the deployment may run
    # without OPENSANCTIONS_API_KEY (the boot validator allows it), so invoking the
    # provider would only manufacture 502s / error rows. Refuse cleanly instead.
    if not settings.sanctions_screening_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "sanctions_screening_disabled", "partner_id": str(partner_id)},
        )
    entity = _load_entity(session, partner_type, partner_id)
    lei = getattr(entity, "lei", None)
    # Computed up front so the error-evidence row carries the same query_hash as a
    # success row would — the audit history can then tie a failure to the exact
    # name/country/tax_id/lei input that was screened.
    query_hash = _query_hash(entity.name, entity.country, entity.tax_id, lei)
    try:
        match = screen_entity(
            name=entity.name, country=entity.country, tax_id=entity.tax_id, lei=lei
        )
    except ScreeningProviderError as exc:
        _record_error_screening(
            partner_type, partner_id, actor_sub=actor_sub, detail=str(exc), query_hash=query_hash
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "sanctions_screening_provider_error", "partner_id": str(partner_id)},
        ) from exc

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
        query_hash=query_hash,
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


def _latest_screening(session: Session, partner_type, partner_id) -> SanctionsScreening | None:
    stmt = (
        select(SanctionsScreening)
        .where(
            SanctionsScreening.partner_type == partner_type,
            SanctionsScreening.partner_id == partner_id,
            SanctionsScreening.status == ScreeningStatus.success,
        )
        .order_by(SanctionsScreening.screened_at.desc())
    )
    return session.execute(stmt).scalars().first()


def _latest_adjudication(
    session: Session, partner_type, partner_id
) -> SanctionsAdjudication | None:
    stmt = (
        select(SanctionsAdjudication)
        .where(
            SanctionsAdjudication.partner_type == partner_type,
            SanctionsAdjudication.partner_id == partner_id,
        )
        .order_by(SanctionsAdjudication.adjudicated_at.desc())
    )
    return session.execute(stmt).scalars().first()


def effective_sanctions_status(session: Session, partner_type, partner_id) -> str | None:
    # Supersession is determined by timestamp comparison (screened_at vs adjudicated_at).
    # Both timestamps are set via datetime.now(UTC) in this service, so they are
    # internally consistent and trusted. The superseded_screening_id FK on
    # SanctionsAdjudication provides forensic linkage for audit purposes; a
    # FK-based supersession read is possible but deferred to a future wave (out of W2 scope).
    screening = _latest_screening(session, partner_type, partner_id)
    adjudication = _latest_adjudication(session, partner_type, partner_id)
    if screening is None and adjudication is None:
        return None
    if adjudication is None:
        return screening.result.value if screening.result else None
    if screening is None:
        return adjudication.decision.value
    # tie-break: an adjudication responds to a screening, so on equal timestamps
    # the adjudication is the later event (adjudication wins).
    if adjudication.adjudicated_at >= screening.screened_at:
        return adjudication.decision.value
    return screening.result.value if screening.result else None


def adjudicate(
    session: Session,
    partner_type: SanctionsPartnerType,
    partner_id: uuid.UUID,
    *,
    decision: AdjudicationDecision,
    reason: str,
    actor_sub: str,
    commit: bool = True,
) -> SanctionsAdjudication:
    entity = _load_entity(session, partner_type, partner_id)
    screening = _latest_screening(session, partner_type, partner_id)
    adjudication = _latest_adjudication(session, partner_type, partner_id)
    latest_is_flagged_screening = (
        screening is not None
        and screening.result is ScreeningResult.flagged
        # tie-break: an adjudication responds to a screening, so on equal timestamps
        # the adjudication is the later event (not adjudicable).
        and (adjudication is None or screening.screened_at > adjudication.adjudicated_at)
    )
    if not latest_is_flagged_screening:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "sanctions_adjudication_invalid_target",
                "partner_id": str(partner_id),
                "reason": "adjudication is valid only against the latest screening while flagged",
            },
        )
    previous_status = entity.sanctions_status
    row = SanctionsAdjudication(
        id=uuid.uuid4(),
        partner_type=partner_type,
        partner_id=partner_id,
        superseded_screening_id=screening.id,
        decision=decision,
        reason=reason,
        adjudicating_actor_sub=actor_sub,
        adjudicated_at=datetime.now(UTC),
    )
    session.add(row)
    entity.sanctions_status = SanctionsStatus(decision.value)
    session.flush()
    AuditTrailService.record(
        session,
        event_id=uuid.uuid4(),
        entity_type=_entity_audit_type(partner_type),
        entity_id=partner_id,
        event_type="sanctions_status_adjudicated",
        payload_raw="",
        payload_obj={
            "partner_type": partner_type.value,
            "partner_id": str(partner_id),
            "previous_status": previous_status.value,
            "new_status": decision.value,
            "superseded_screening_id": str(screening.id),
            "reason": reason,
            "actor_sub": actor_sub,
        },
        commit=False,
    )
    if commit:
        session.commit()
        session.refresh(row)
    return row
