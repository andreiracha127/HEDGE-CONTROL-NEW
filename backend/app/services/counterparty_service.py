from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.counterparty import (
    Counterparty,
    CounterpartyType,
    KycStatus,
    RiskRating,
    SanctionsStatus,
)

# Screening-relevant identity fields. A generic-PATCH change to any of these
# invalidates prior screening evidence (the RFQ gate ``assert_kyc_approved``
# admits on ``kyc_status``), so compliance must fail closed on identity edits.
# Mirrors CommercialPartnerService._IDENTITY_FIELDS (less ``lei``, which the
# hedge Counterparty model does not carry).
_IDENTITY_FIELDS = {"name", "country", "tax_id"}


class CounterpartyService:
    @staticmethod
    def create(session: Session, data: dict, *, commit: bool = True) -> Counterparty:
        cp = Counterparty(
            type=CounterpartyType(data["type"]),
            name=data["name"],
            short_name=data.get("short_name"),
            tax_id=data.get("tax_id"),
            country=data["country"],
            city=data.get("city"),
            address=data.get("address"),
            contact_name=data.get("contact_name"),
            contact_email=data.get("contact_email"),
            contact_phone=data.get("contact_phone"),
            whatsapp_phone=data.get("whatsapp_phone"),
            payment_terms_days=data.get("payment_terms_days") or 30,
            credit_limit_usd=data.get("credit_limit_usd"),
            kyc_status=KycStatus.pending,
            sanctions_status=SanctionsStatus.unscreened,
            risk_rating=RiskRating(data.get("risk_rating", "medium")),
            is_active=data.get("is_active", True),
            notes=data.get("notes"),
        )
        session.add(cp)
        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp

    @staticmethod
    def get_by_id(session: Session, cp_id: UUID) -> Counterparty | None:
        cp = session.get(Counterparty, cp_id)
        if cp and not cp.is_deleted:
            return cp
        return None

    @staticmethod
    def list(
        session: Session,
        *,
        type_filter: str | None = None,
        kyc_status_filter: str | None = None,
        is_active_filter: bool | None = None,
    ):
        query = session.query(Counterparty).filter(Counterparty.is_deleted == False)
        if type_filter:
            query = query.filter(Counterparty.type == CounterpartyType(type_filter))
        if kyc_status_filter:
            query = query.filter(Counterparty.kyc_status == KycStatus(kyc_status_filter))
        if is_active_filter is not None:
            query = query.filter(Counterparty.is_active == is_active_filter)
        return query

    @staticmethod
    def update(
        session: Session, cp: Counterparty, data: dict, *, commit: bool = True
    ) -> Counterparty:
        if "kyc_status" in data:
            raise HTTPException(
                status_code=403,
                detail="kyc_status mutations require the dedicated risk_manager transition endpoint (POST /counterparties/{id}/kyc-status). Generic update path cannot mutate kyc_status.",
            )
        if "sanctions_status" in data:
            raise HTTPException(
                status_code=403,
                detail="sanctions_status mutations require the dedicated sanctions screening/adjudication flow. Generic update path cannot mutate sanctions_status.",
            )
        identity_changed = any(
            key in _IDENTITY_FIELDS and value is not None and getattr(cp, key) != value
            for key, value in data.items()
        )
        for key, value in data.items():
            if value is not None:
                if key == "risk_rating":
                    setattr(cp, key, RiskRating(value))
                else:
                    setattr(cp, key, value)

        # Identity-edit fail-closed reset (governance Authorization invariants):
        # stale screening evidence must not survive an identity change, otherwise
        # the RFQ gate would admit a broker/bank under a never-screened identity.
        # kyc revocation is UNCONDITIONAL on identity change (not gated on prior
        # sanctions state) so the invariant never relies on a reachability argument.
        if identity_changed:
            cp.sanctions_status = SanctionsStatus.unscreened
            if cp.kyc_status is KycStatus.approved:
                cp.kyc_status = KycStatus.pending

        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp

    @staticmethod
    def set_kyc_status(
        session: Session,
        cp_id: UUID,
        *,
        new_status: KycStatus,
    ) -> tuple[Counterparty, KycStatus]:
        stmt = (
            select(Counterparty)
            .where(Counterparty.id == cp_id, Counterparty.is_deleted == False)
            .with_for_update()
        )
        cp = session.execute(stmt).scalar_one_or_none()
        if not cp:
            raise HTTPException(status_code=404, detail="Counterparty not found")
        new_status = KycStatus(getattr(new_status, "value", new_status))
        # Hedge kyc_status is DECOUPLED from sanctions_status (governance.md:529/542:
        # the sanctions-clear-before-approved precondition is commercial-only; hedge
        # kyc is vestigial per :538-540). The universal sanctions control lands in W2
        # (screening writer) + W3 (RFQ gate re-target from kyc -> sanctions); coupling
        # hedge kyc approval to sanctions in W1 has no constitutional basis and would
        # freeze the W1 RFQ gate (which still reads kyc_status) with no W1 path to set
        # sanctions clear. No sanctions precondition is enforced here.
        previous_status = cp.kyc_status
        cp.kyc_status = new_status
        session.flush()
        return cp, previous_status

    @staticmethod
    def soft_delete(session: Session, cp: Counterparty, *, commit: bool = True) -> Counterparty:
        cp.is_deleted = True
        cp.deleted_at = datetime.now(UTC)
        cp.is_active = False
        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp

    @staticmethod
    def check_tax_id_unique(session: Session, tax_id: str, exclude_id: UUID | None = None) -> bool:
        query = session.query(Counterparty).filter(
            Counterparty.tax_id == tax_id,
            Counterparty.is_deleted == False,
        )
        if exclude_id:
            query = query.filter(Counterparty.id != exclude_id)
        return query.first() is None
