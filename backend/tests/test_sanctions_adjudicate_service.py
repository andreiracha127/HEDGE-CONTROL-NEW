import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus
from app.models.sanctions import (
    AdjudicationDecision,
    SanctionsPartnerType,
    SanctionsScreening,
    ScreeningResult,
    ScreeningStatus,
)
from app.services import sanctions_screening_service as svc


def _partner(session) -> CommercialPartner:
    cp = CommercialPartner(
        kind=CommercialPartnerKind.customer,
        name="X",
        country="BRA",
        kyc_status=KycStatus.pending,
        sanctions_status=SanctionsStatus.flagged,
        risk_rating=RiskRating.medium,
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def _screening(
    session, pid, result, *, when, status_=ScreeningStatus.success
) -> SanctionsScreening:
    s = SanctionsScreening(
        id=uuid.uuid4(),
        partner_type=SanctionsPartnerType.commercial,
        partner_id=pid,
        screened_at=when,
        provider="opensanctions",
        algorithm="logic-v2",
        query_hash="h",
        top_score=Decimal("0.75"),
        match_count=1,
        matches_json=[],
        result=result,
        actor_sub="rm",
        status=status_,
    )
    session.add(s)
    session.commit()
    return s


def test_adjudicate_flagged_to_clear():
    with SessionLocal() as session:
        cp = _partner(session)
        _screening(session, cp.id, ScreeningResult.flagged, when=datetime.now(UTC))
        adj = svc.adjudicate(
            session,
            SanctionsPartnerType.commercial,
            cp.id,
            decision=AdjudicationDecision.clear,
            reason="false positive match",
            actor_sub="rm-1",
        )
        assert adj.decision is AdjudicationDecision.clear
        session.refresh(cp)
        assert cp.sanctions_status is SanctionsStatus.clear
        ev = (
            session.query(AuditEvent)
            .filter(
                AuditEvent.event_type == "sanctions_status_adjudicated",
                AuditEvent.entity_id == cp.id,
            )
            .one()
        )
        assert ev.payload["new_status"] == "clear"


def test_reject_when_latest_not_flagged():
    with SessionLocal() as session:
        cp = _partner(session)
        _screening(session, cp.id, ScreeningResult.blocked, when=datetime.now(UTC))
        with pytest.raises(Exception) as exc:
            svc.adjudicate(
                session,
                SanctionsPartnerType.commercial,
                cp.id,
                decision=AdjudicationDecision.clear,
                reason="should fail here",
                actor_sub="rm",
            )
        assert getattr(exc.value, "status_code", None) == 422


def test_reject_when_flagged_superseded_by_newer_blocked():
    with SessionLocal() as session:
        cp = _partner(session)
        now = datetime.now(UTC)
        _screening(session, cp.id, ScreeningResult.flagged, when=now - timedelta(hours=2))
        _screening(session, cp.id, ScreeningResult.blocked, when=now)
        with pytest.raises(Exception) as exc:
            svc.adjudicate(
                session,
                SanctionsPartnerType.commercial,
                cp.id,
                decision=AdjudicationDecision.clear,
                reason="stale flagged abuse",
                actor_sub="rm",
            )
        assert getattr(exc.value, "status_code", None) == 422


def test_effective_status_latest_event_wins():
    with SessionLocal() as session:
        cp = _partner(session)
        now = datetime.now(UTC)
        _screening(session, cp.id, ScreeningResult.flagged, when=now)
        eff = svc.effective_sanctions_status(session, SanctionsPartnerType.commercial, cp.id)
        assert eff == "flagged"
