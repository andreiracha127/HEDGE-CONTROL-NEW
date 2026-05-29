from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.database import SessionLocal
from app.models.commercial_partner import (
    CommercialPartner,
    CommercialPartnerKind,
    LeiStatus,
)
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus


def test_commercial_partner_defaults_are_fail_closed():
    with SessionLocal() as session:
        cp = CommercialPartner(
            kind=CommercialPartnerKind.customer,
            name="Acme Co",
            country="BRA",
        )
        session.add(cp)
        session.commit()
        session.refresh(cp)
        assert isinstance(cp.id, uuid.UUID)
        assert cp.kyc_status is KycStatus.pending
        assert cp.sanctions_status is SanctionsStatus.unscreened
        assert cp.lei_status is LeiStatus.not_provided
        assert cp.risk_rating is RiskRating.medium
        assert cp.is_active is True
        assert cp.is_deleted is False


def test_commercial_partner_supplier_cannot_carry_customer_credit_fields():
    with SessionLocal() as session:
        cp = CommercialPartner(
            kind=CommercialPartnerKind.supplier,
            name="Bad Supplier",
            country="BRA",
            credit_limit=Decimal("1000.00"),  # customer-only field — CHECK must reject
        )
        session.add(cp)
        with pytest.raises(IntegrityError):
            session.commit()


def test_sanctions_tables_exist_and_accept_rows():
    from datetime import datetime, timezone

    from app.models.sanctions import (
        AdjudicationDecision,
        SanctionsAdjudication,
        SanctionsPartnerType,
        SanctionsScreening,
        ScreeningResult,
        ScreeningStatus,
    )

    with SessionLocal() as session:
        partner_id = uuid.uuid4()
        screening = SanctionsScreening(
            partner_type=SanctionsPartnerType.commercial,
            partner_id=partner_id,
            screened_at=datetime.now(timezone.utc),
            provider="opensanctions",
            algorithm="logic-v2",
            query_hash="deadbeef",
            match_count=0,
            result=ScreeningResult.clear,
            actor_sub="risk-1",
            status=ScreeningStatus.success,
        )
        session.add(screening)
        session.commit()
        session.refresh(screening)

        adj = SanctionsAdjudication(
            partner_type=SanctionsPartnerType.commercial,
            partner_id=partner_id,
            superseded_screening_id=screening.id,
            decision=AdjudicationDecision.clear,
            reason="false positive, confirmed",
            adjudicating_actor_sub="risk-1",
            adjudicated_at=datetime.now(timezone.utc),
        )
        session.add(adj)
        session.commit()
        assert screening.status is ScreeningStatus.success
        assert adj.decision is AdjudicationDecision.clear


def test_commercial_partner_create_schema_rejects_kyc_and_credit_fields():
    from app.schemas.commercial_partner import CommercialPartnerCreate

    # kyc_status / credit fields are NOT part of the create schema at all
    payload = CommercialPartnerCreate(kind="customer", name="Acme", country="BRA")
    dumped = payload.model_dump()
    assert "kyc_status" not in dumped
    assert "credit_limit" not in dumped
    assert "approved_value" not in dumped


def test_credit_approval_request_parses_decimal():
    from decimal import Decimal

    from app.schemas.commercial_partner import CreditApprovalRequest

    req = CreditApprovalRequest(credit_limit="12345.67", credit_currency="USD")
    assert req.credit_limit == Decimal("12345.67")


def _new_partner(session, kind=CommercialPartnerKind.customer, **overrides):
    cp = CommercialPartner(
        kind=kind, name=overrides.pop("name", "Acme"), country="BRA", **overrides
    )
    session.add(cp)
    session.commit()
    session.refresh(cp)
    return cp


def test_service_update_rejects_kyc_status():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session)
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.update(session, cp, {"kyc_status": "approved"})
        assert exc.value.status_code == 403


def test_service_update_rejects_credit_fields():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session)
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.update(session, cp, {"credit_limit": "10.00"})
        assert exc.value.status_code == 403


def test_service_identity_edit_resets_compliance_fail_closed():
    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session)
        cp.sanctions_status = SanctionsStatus.clear
        cp.kyc_status = KycStatus.approved
        session.commit()
        CommercialPartnerService.update(session, cp, {"name": "Acme Renamed"})
        assert cp.sanctions_status is SanctionsStatus.unscreened
        assert cp.kyc_status is KycStatus.pending


def test_service_kyc_approve_blocked_unless_sanctions_clear():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session)  # sanctions_status defaults to unscreened
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.set_kyc_status(
                session, cp.id, new_status=KycStatus.approved
            )
        assert exc.value.status_code == 422

        cp.sanctions_status = SanctionsStatus.clear
        session.commit()
        updated, previous = CommercialPartnerService.set_kyc_status(
            session, cp.id, new_status=KycStatus.approved
        )
        assert updated.kyc_status is KycStatus.approved
        assert previous is KycStatus.pending


def test_service_approve_credit_customer_decimal_roundtrip():
    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session, kind=CommercialPartnerKind.customer)
        cp2, changed, previous, new_values = CommercialPartnerService.approve_credit(
            session, cp, {"credit_limit": Decimal("12345.67"), "credit_currency": "USD"}
        )
        session.refresh(cp2)
        assert cp2.credit_limit == Decimal("12345.67")
        assert "credit_limit" in changed


def test_service_approve_credit_rejects_cross_kind_fields():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session, kind=CommercialPartnerKind.customer)
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.approve_credit(
                session, cp, {"approved_value": Decimal("1.00")}  # supplier field on a customer
            )
        assert exc.value.status_code == 422
