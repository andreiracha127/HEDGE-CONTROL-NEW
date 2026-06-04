import pytest

from app.core.database import SessionLocal
from app.models.audit import AuditEvent
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind, LeiStatus
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus
from app.services import lei_validation_service as svc
from app.services.gleif_client import GleifLookupError, GleifRecord

VALID = "5493001KJTIIGC8Y1R12"
BAD_CHECKSUM = "984500F1F2E3D4C5B6A7"


def _partner(session, *, name="Bloomberg Finance L.P.", lei=VALID) -> CommercialPartner:
    cp = CommercialPartner(
        kind=CommercialPartnerKind.customer,
        name=name,
        country="USA",
        lei=lei,
        lei_status=LeiStatus.not_provided,
        kyc_status=KycStatus.pending,
        sanctions_status=SanctionsStatus.unscreened,
        risk_rating=RiskRating.medium,
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def _record(status_="ISSUED", legal_name="Bloomberg Finance L.P."):
    return GleifRecord(
        registration_status=status_,
        legal_name=legal_name,
        legal_name_language="en",
        entity_status="ACTIVE",
    )


def test_issued_sets_issued_and_persists_name_and_audits(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("ISSUED"))
    with SessionLocal() as session:
        cp = _partner(session)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm-1", commit=True)
        assert result.lei_status is LeiStatus.issued
        assert result.lei_legal_name == "Bloomberg Finance L.P."
        assert result.lei_checked_at is not None
        assert warnings == []
        ev = (
            session.query(AuditEvent)
            .filter(AuditEvent.event_type == "commercial_partner_lei_validated")
            .filter(AuditEvent.entity_id == cp.id)
            .one()
        )
        assert ev.payload["new_status"] == "issued"


def test_lapsed_maps_lapsed(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("LAPSED"))
    with SessionLocal() as session:
        cp = _partner(session)
        result, _ = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.lapsed


def test_other_status_maps_lapsed_with_warning(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("RETIRED"))
    with SessionLocal() as session:
        cp = _partner(session)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.lapsed
        assert any("RETIRED" in w for w in warnings)


def test_checksum_fail_sets_invalid_and_skips_gleif(monkeypatch):
    def must_not_call(lei):
        raise AssertionError("GLEIF must not be called when the checksum fails")

    monkeypatch.setattr(svc, "fetch_lei_record", must_not_call)
    with SessionLocal() as session:
        cp = _partner(session, lei=BAD_CHECKSUM)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.invalid
        assert any("checksum" in w.lower() for w in warnings)


def test_404_sets_invalid_with_warning(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: None)
    with SessionLocal() as session:
        cp = _partner(session)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.invalid
        assert any("not found" in w.lower() for w in warnings)


def test_gleif_error_sets_error_and_does_not_raise(monkeypatch):
    def boom(lei):
        raise GleifLookupError("down")

    monkeypatch.setattr(svc, "fetch_lei_record", boom)
    with SessionLocal() as session:
        cp = _partner(session)
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.error
        assert any("GLEIF lookup failed" in w for w in warnings)


def test_gleif_error_preserves_previous_lei_legal_name(monkeypatch):
    """On a GLEIF outage, a previously stored lei_legal_name must not be erased."""
    monkeypatch.setattr(
        svc, "fetch_lei_record", lambda lei: _record("ISSUED", legal_name="Bloomberg Finance L.P.")
    )
    with SessionLocal() as session:
        cp = _partner(session)
        cp_id = cp.id
        result, _ = svc.validate_lei(session, cp_id, actor_sub="rm", commit=True)
        assert result.lei_legal_name == "Bloomberg Finance L.P."

    def boom(lei):
        raise GleifLookupError("down")

    monkeypatch.setattr(svc, "fetch_lei_record", boom)
    with SessionLocal() as session:
        result, _warnings = svc.validate_lei(session, cp_id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.error
        assert result.lei_legal_name == "Bloomberg Finance L.P."


def test_name_mismatch_warns_without_changing_status(monkeypatch):
    monkeypatch.setattr(
        svc, "fetch_lei_record", lambda lei: _record("ISSUED", legal_name="Totally Different Co")
    )
    with SessionLocal() as session:
        cp = _partner(session, name="Acme Customer Ltda")
        result, warnings = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.issued
        assert any("differs from partner name" in w for w in warnings)


def test_null_lei_sets_not_provided(monkeypatch):
    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("ISSUED"))
    with SessionLocal() as session:
        cp = _partner(session, lei=None)
        result, _ = svc.validate_lei(session, cp.id, actor_sub="rm", commit=True)
        assert result.lei_status is LeiStatus.not_provided


def test_missing_partner_404(monkeypatch):
    import uuid

    monkeypatch.setattr(svc, "fetch_lei_record", lambda lei: _record("ISSUED"))
    with SessionLocal() as session:
        with pytest.raises(Exception) as exc:
            svc.validate_lei(session, uuid.uuid4(), actor_sub="rm")
        assert getattr(exc.value, "status_code", None) == 404
