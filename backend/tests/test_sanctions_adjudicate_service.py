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
    SanctionsAdjudication,
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


def test_reject_when_latest_is_clear():
    with SessionLocal() as session:
        cp = _partner(session)
        _screening(session, cp.id, ScreeningResult.clear, when=datetime.now(UTC))
        with pytest.raises(Exception) as exc:
            svc.adjudicate(
                session,
                SanctionsPartnerType.commercial,
                cp.id,
                decision=AdjudicationDecision.blocked,
                reason="clear not adjudicable",
                actor_sub="rm",
            )
        assert getattr(exc.value, "status_code", None) == 422


def test_reject_when_adjudication_ties_screening_timestamp():
    # exact-timestamp tie: adjudication is treated as the later event -> not adjudicable
    with SessionLocal() as session:
        cp = _partner(session)
        ts = datetime.now(UTC)
        scr = _screening(session, cp.id, ScreeningResult.flagged, when=ts)
        session.add(
            SanctionsAdjudication(
                id=uuid.uuid4(),
                partner_type=SanctionsPartnerType.commercial,
                partner_id=cp.id,
                superseded_screening_id=scr.id,
                decision=AdjudicationDecision.clear,
                reason="prior adjudication",
                adjudicating_actor_sub="rm",
                adjudicated_at=ts,
            )
        )
        session.commit()
        with pytest.raises(Exception) as exc:
            svc.adjudicate(
                session,
                SanctionsPartnerType.commercial,
                cp.id,
                decision=AdjudicationDecision.clear,
                reason="tie should reject",
                actor_sub="rm",
            )
        assert getattr(exc.value, "status_code", None) == 422


def test_readjudicate_after_fresh_flagged_screening():
    # screen->flagged, adjudicate->clear, NEW screen->flagged (newer) -> adjudicable again.
    # Use explicit past/future offsets so the new screening is unambiguously newer than
    # the adjudication regardless of wall-clock resolution.
    with SessionLocal() as session:
        cp = _partner(session)
        base = datetime.now(UTC)
        _screening(session, cp.id, ScreeningResult.flagged, when=base - timedelta(hours=3))
        svc.adjudicate(
            session,
            SanctionsPartnerType.commercial,
            cp.id,
            decision=AdjudicationDecision.clear,
            reason="first adjudication ok",
            actor_sub="rm",
        )
        # New screening is strictly in the future (+1 h) relative to any possible
        # adjudicated_at timestamp, so screened_at > adjudicated_at is guaranteed.
        # A real screen() that returns flagged also sets the stored status to flagged;
        # the _screening helper only inserts the row, so set the status explicitly.
        _screening(session, cp.id, ScreeningResult.flagged, when=base + timedelta(hours=1))
        cp.sanctions_status = SanctionsStatus.flagged
        session.commit()
        adj2 = svc.adjudicate(
            session,
            SanctionsPartnerType.commercial,
            cp.id,
            decision=AdjudicationDecision.blocked,
            reason="second adjudication ok",
            actor_sub="rm",
        )
        assert adj2.decision is AdjudicationDecision.blocked
        session.refresh(cp)
        assert cp.sanctions_status is SanctionsStatus.blocked


def test_adjudicate_hedge_counterparty():
    from app.models.counterparty import Counterparty, CounterpartyType

    with SessionLocal() as session:
        cp = Counterparty(
            type=CounterpartyType.broker,
            name="Marex",
            country="GBR",
            kyc_status=KycStatus.pending,
            sanctions_status=SanctionsStatus.flagged,
            risk_rating=RiskRating.medium,
        )
        session.add(cp)
        session.commit()
        session.refresh(cp)
        # screening row for the hedge partner
        session.add(
            SanctionsScreening(
                id=uuid.uuid4(),
                partner_type=SanctionsPartnerType.hedge,
                partner_id=cp.id,
                screened_at=datetime.now(UTC),
                provider="opensanctions",
                algorithm="logic-v2",
                query_hash="h",
                top_score=Decimal("0.75"),
                match_count=1,
                matches_json=[],
                result=ScreeningResult.flagged,
                actor_sub="rm",
                status=ScreeningStatus.success,
            )
        )
        session.commit()
        adj = svc.adjudicate(
            session,
            SanctionsPartnerType.hedge,
            cp.id,
            decision=AdjudicationDecision.clear,
            reason="hedge false positive",
            actor_sub="rm-1",
        )
        assert adj.decision is AdjudicationDecision.clear
        session.refresh(cp)
        assert cp.sanctions_status is SanctionsStatus.clear


def test_reject_adjudication_after_identity_reset():
    # An identity edit resets sanctions_status -> unscreened while the old flagged
    # screening row remains; adjudicating that stale hit must be refused (422) so a
    # never-screened new identity cannot be cleared/blocked without re-screening.
    with SessionLocal() as session:
        cp = _partner(session)
        _screening(session, cp.id, ScreeningResult.flagged, when=datetime.now(UTC))
        cp.sanctions_status = SanctionsStatus.unscreened  # simulate identity-reset
        session.commit()
        with pytest.raises(Exception) as exc:
            svc.adjudicate(
                session,
                SanctionsPartnerType.commercial,
                cp.id,
                decision=AdjudicationDecision.clear,
                reason="stale flagged after identity reset",
                actor_sub="rm",
            )
        assert getattr(exc.value, "status_code", None) == 422
