from __future__ import annotations

import uuid
from datetime import UTC
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.auth import get_current_user
from app.core.database import SessionLocal
from app.main import app
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


def test_commercial_partner_credit_columns_use_platform_money_scale():
    assert CommercialPartner.__table__.c.credit_limit.type.scale == 6
    assert CommercialPartner.__table__.c.approved_value.type.scale == 6


def test_sanctions_tables_exist_and_accept_rows():
    from datetime import datetime

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
            screened_at=datetime.now(UTC),
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
            adjudicated_at=datetime.now(UTC),
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

    req = CreditApprovalRequest(
        reason="credit review complete",
        credit_limit="12345.67",
        credit_currency="USD",
    )
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


def test_service_identity_clear_applies_explicit_null_and_resets_compliance():
    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session, tax_id="123456789", lei="5493001KJTIIGC8Y1R12")
        cp.sanctions_status = SanctionsStatus.clear
        cp.kyc_status = KycStatus.approved
        session.commit()

        CommercialPartnerService.update(session, cp, {"tax_id": None, "lei": None})

        assert cp.tax_id is None
        assert cp.lei is None
        assert cp.sanctions_status is SanctionsStatus.unscreened
        assert cp.kyc_status is KycStatus.pending


def test_service_identity_required_null_does_not_reset_compliance():
    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session, name="Acme")
        cp.sanctions_status = SanctionsStatus.clear
        cp.kyc_status = KycStatus.approved
        session.commit()

        CommercialPartnerService.update(session, cp, {"name": None, "country": None})

        assert cp.name == "Acme"
        assert cp.country == "BRA"
        assert cp.sanctions_status is SanctionsStatus.clear
        assert cp.kyc_status is KycStatus.approved


def test_service_kyc_approve_blocked_unless_sanctions_clear():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session)  # sanctions_status defaults to unscreened
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.set_kyc_status(session, cp.id, new_status=KycStatus.approved)
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
        cp.sanctions_status = SanctionsStatus.clear
        cp2, changed, _previous, _new_values = CommercialPartnerService.approve_credit(
            session, cp, {"credit_limit": Decimal("12345.67"), "credit_currency": "USD"}
        )
        session.refresh(cp2)
        assert cp2.credit_limit == Decimal("12345.67")
        assert "credit_limit" in changed


def test_service_approve_credit_applies_explicit_nulls():
    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(
            session,
            kind=CommercialPartnerKind.customer,
            credit_limit=Decimal("12345.670000"),
            credit_currency="USD",
        )
        cp.sanctions_status = SanctionsStatus.clear
        cp2, changed, previous, new_values = CommercialPartnerService.approve_credit(
            session, cp, {"credit_limit": None, "credit_currency": None}
        )
        session.refresh(cp2)
        assert cp2.credit_limit is None
        assert cp2.credit_currency is None
        assert changed == ["credit_limit", "credit_currency"]
        assert previous["credit_limit"] == "12345.670000"
        assert new_values["credit_limit"] is None


def test_service_approve_credit_rejects_cross_kind_fields():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session, kind=CommercialPartnerKind.customer)
        cp.sanctions_status = SanctionsStatus.clear
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.approve_credit(
                session,
                cp,
                {"approved_value": Decimal("1.00")},  # supplier field on a customer
            )
        assert exc.value.status_code == 422


def test_service_approve_credit_requires_clear_sanctions():
    from fastapi import HTTPException

    from app.services.commercial_partner_service import CommercialPartnerService

    with SessionLocal() as session:
        cp = _new_partner(session, kind=CommercialPartnerKind.customer)
        with pytest.raises(HTTPException) as exc:
            CommercialPartnerService.approve_credit(
                session,
                cp,
                {"credit_limit": Decimal("1.00")},
            )

        assert exc.value.status_code == 422
        assert exc.value.detail["code"] == "commercial_partner_credit_rejected_sanctions_not_clear"


def _as_roles(*roles: str, sub: str = "test-user") -> dict:
    return {"sub": sub, "roles": list(roles)}


@pytest.fixture()
def auth_as():
    def _set(*roles: str, sub: str = "test-user") -> None:
        app.dependency_overrides[get_current_user] = lambda: _as_roles(*roles, sub=sub)

    yield _set
    app.dependency_overrides.clear()


def test_router_create_and_get_roundtrip(client, auth_as):
    auth_as("trader")
    resp = client.post(
        "/commercial-partners",
        json={"kind": "customer", "name": "Roundtrip Co", "country": "BRA"},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "customer"
    assert body["kyc_status"] == "pending"
    assert body["sanctions_status"] == "unscreened"

    got = client.get(f"/commercial-partners/{body['id']}")
    assert got.status_code == 200


def test_router_list_rejects_invalid_enum_filters(client, auth_as):
    auth_as("trader")

    resp = client.get("/commercial-partners", params={"kind": "bogus"})

    assert resp.status_code == 422


def test_router_reuses_tax_id_after_soft_delete(client, auth_as):
    auth_as("trader")
    payload = {
        "kind": "customer",
        "name": "Reusable Tax Co",
        "country": "BRA",
        "tax_id": "11222333000199",
    }
    created = client.post("/commercial-partners", json=payload)
    assert created.status_code == 201, created.text
    deleted = client.delete(f"/commercial-partners/{created.json()['id']}")
    assert deleted.status_code == 200, deleted.text

    recreated = client.post(
        "/commercial-partners",
        json={**payload, "name": "Reusable Tax Co II"},
    )

    assert recreated.status_code == 201, recreated.text


def test_credit_decimal_is_exact_through_api(client, auth_as):
    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners",
        json={"kind": "customer", "name": "Decimal Co", "country": "BRA"},
    ).json()["id"]
    with SessionLocal() as session:
        cp = session.get(CommercialPartner, uuid.UUID(cp_id))
        cp.sanctions_status = SanctionsStatus.clear
        session.commit()
    resp = client.patch(
        f"/commercial-partners/{cp_id}/credit",
        json={
            "reason": "credit review complete",
            "credit_limit": "12345.67",
            "credit_currency": "USD",
        },
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(str(resp.json()["credit_limit"])) == Decimal("12345.67")  # exact, no float drift


def test_credit_approval_requires_reason_through_api(client, auth_as):
    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners",
        json={"kind": "customer", "name": "No Reason Co", "country": "BRA"},
    ).json()["id"]
    with SessionLocal() as session:
        cp = session.get(CommercialPartner, uuid.UUID(cp_id))
        cp.sanctions_status = SanctionsStatus.clear
        session.commit()

    resp = client.patch(
        f"/commercial-partners/{cp_id}/credit",
        json={"credit_limit": "12345.67", "credit_currency": "USD"},
    )

    assert resp.status_code == 422


def test_credit_decimal_preserves_six_decimal_scale_through_api(client, auth_as):
    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners",
        json={"kind": "customer", "name": "Scale Co", "country": "BRA"},
    ).json()["id"]
    with SessionLocal() as session:
        cp = session.get(CommercialPartner, uuid.UUID(cp_id))
        cp.sanctions_status = SanctionsStatus.clear
        session.commit()
    resp = client.patch(
        f"/commercial-partners/{cp_id}/credit",
        json={
            "reason": "credit review complete",
            "credit_limit": "12345.123456",
            "credit_currency": "USD",
        },
    )
    assert resp.status_code == 200, resp.text
    assert Decimal(str(resp.json()["credit_limit"])) == Decimal("12345.123456")


def test_credit_approved_emits_audit_event(client, auth_as, session):
    from app.models.audit import AuditEvent

    auth_as("risk_manager")
    cp_id = client.post(
        "/commercial-partners",
        json={"kind": "supplier", "name": "Audit Co", "country": "BRA"},
    ).json()["id"]
    cp = session.get(CommercialPartner, uuid.UUID(cp_id))
    cp.sanctions_status = SanctionsStatus.clear
    session.commit()
    resp = client.patch(
        f"/commercial-partners/{cp_id}/credit",
        json={
            "reason": "credit review complete",
            "approved_value": "999.99",
            "approved_currency": "USD",
        },
    )
    assert resp.status_code == 200, resp.text
    events = (
        session.query(AuditEvent)
        .filter(AuditEvent.event_type == "commercial_partner_credit_approved")
        .all()
    )
    assert len(events) >= 1
