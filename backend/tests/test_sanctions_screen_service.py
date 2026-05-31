from decimal import Decimal

import pytest

from app.core.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus
from app.models.sanctions import (
    SanctionsPartnerType,
    SanctionsScreening,
    ScreeningResult,
    ScreeningStatus,
)
from app.services import sanctions_screening_service as svc
from app.services.opensanctions_client import MatchResult, ScreeningProviderError


def _commercial(session) -> CommercialPartner:
    cp = CommercialPartner(
        kind=CommercialPartnerKind.customer,
        name="Rusal",
        country="RUS",
        kyc_status=KycStatus.pending,
        sanctions_status=SanctionsStatus.unscreened,
        risk_rating=RiskRating.medium,
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def _fake_match(score, monkeypatch):
    monkeypatch.setattr(
        svc,
        "screen_entity",
        lambda **kw: MatchResult(
            Decimal(score), 1, [{"score": float(score)}], "2026-05-30", "logic-v2"
        ),
    )


def test_clear_sets_status_and_writes_row_and_audit(monkeypatch):
    _fake_match("0.10", monkeypatch)
    with SessionLocal() as session:
        cp = _commercial(session)
        screening = svc.screen(
            session, SanctionsPartnerType.commercial, cp.id, actor_sub="rm-1", commit=True
        )
        assert screening.status is ScreeningStatus.success
        assert screening.result is ScreeningResult.clear
        session.refresh(cp)
        assert cp.sanctions_status is SanctionsStatus.clear
        ev = (
            session.query(AuditEvent)
            .filter(AuditEvent.event_type == "sanctions_status_changed")
            .filter(AuditEvent.entity_id == cp.id)
            .one()
        )
        assert ev.payload["new_status"] == "clear"


def test_flagged_and_blocked_tiers(monkeypatch):
    for score, expected in [("0.75", SanctionsStatus.flagged), ("0.95", SanctionsStatus.blocked)]:
        _fake_match(score, monkeypatch)
        with SessionLocal() as session:
            cp = _commercial(session)
            svc.screen(session, SanctionsPartnerType.commercial, cp.id, actor_sub="rm", commit=True)
            session.refresh(cp)
            assert cp.sanctions_status is expected


def test_provider_error_records_error_row_and_raises_without_status_change(monkeypatch):
    def boom(**kw):
        raise ScreeningProviderError("down")

    monkeypatch.setattr(svc, "screen_entity", boom)
    with SessionLocal() as session:
        cp = _commercial(session)
        with pytest.raises(Exception) as exc:
            svc.screen(session, SanctionsPartnerType.commercial, cp.id, actor_sub="rm", commit=True)
        assert getattr(exc.value, "status_code", None) == 502
        session.rollback()
        session.refresh(cp)
        assert cp.sanctions_status is SanctionsStatus.unscreened
    with SessionLocal() as check:
        rows = (
            check.query(SanctionsScreening)
            .filter(SanctionsScreening.status == ScreeningStatus.error)
            .all()
        )
        assert len(rows) == 1
        assert rows[0].result is None


def test_missing_entity_404(monkeypatch):
    import uuid

    _fake_match("0.10", monkeypatch)
    with SessionLocal() as session:
        with pytest.raises(Exception) as exc:
            svc.screen(session, SanctionsPartnerType.commercial, uuid.uuid4(), actor_sub="rm")
        assert getattr(exc.value, "status_code", None) == 404
