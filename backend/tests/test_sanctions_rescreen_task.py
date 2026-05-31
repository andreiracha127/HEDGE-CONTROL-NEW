from decimal import Decimal

from app.core.database import SessionLocal
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind
from app.models.counterparty import (
    Counterparty,
    CounterpartyType,
    KycStatus,
    RiskRating,
    SanctionsStatus,
)
from app.models.sanctions import SanctionsScreening, ScreeningStatus
from app.services import sanctions_screening_service as svc
from app.services.opensanctions_client import MatchResult, ScreeningProviderError
from app.tasks.sanctions_rescreen_task import run_sanctions_rescreen_daily


def _seed():
    with SessionLocal() as s:
        s.add(
            CommercialPartner(
                kind=CommercialPartnerKind.customer,
                name="C",
                country="BRA",
                kyc_status=KycStatus.pending,
                sanctions_status=SanctionsStatus.unscreened,
                risk_rating=RiskRating.medium,
            )
        )
        s.add(
            Counterparty(
                type=CounterpartyType.broker,
                name="B",
                country="GBR",
                kyc_status=KycStatus.pending,
                sanctions_status=SanctionsStatus.unscreened,
                risk_rating=RiskRating.medium,
            )
        )
        s.commit()


def test_rescreens_both_domains(monkeypatch):
    _seed()
    monkeypatch.setattr(
        svc,
        "screen_entity",
        lambda **kw: MatchResult(Decimal("0.05"), 0, [], None, "logic-v2"),
    )
    summary = run_sanctions_rescreen_daily()
    assert summary["screened"] == 2
    assert summary["errors"] == 0
    with SessionLocal() as s:
        rows = (
            s.query(SanctionsScreening)
            .filter(SanctionsScreening.status == ScreeningStatus.success)
            .all()
        )
        assert len(rows) == 2


def test_continues_on_per_entity_error(monkeypatch):
    _seed()
    calls = {"n": 0}

    def flaky(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise ScreeningProviderError("down")
        return MatchResult(Decimal("0.05"), 0, [], None, "logic-v2")

    monkeypatch.setattr(svc, "screen_entity", flaky)
    summary = run_sanctions_rescreen_daily()
    assert summary["screened"] == 1
    assert summary["errors"] == 1


def test_skips_entirely_when_screening_disabled(monkeypatch):
    monkeypatch.setattr(svc.get_settings(), "sanctions_screening_enabled", False)

    def must_not_call(**kw):
        raise AssertionError("provider must not be invoked when screening is disabled")

    monkeypatch.setattr(svc, "screen_entity", must_not_call)
    _seed()
    summary = run_sanctions_rescreen_daily()
    assert summary.get("skipped") is True
    assert summary["screened"] == 0
    assert summary["errors"] == 0
