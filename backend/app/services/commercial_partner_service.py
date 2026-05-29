from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.precision import to_decimal
from app.models.commercial_partner import CommercialPartner, CommercialPartnerKind, LeiStatus
from app.models.counterparty import KycStatus, RiskRating, SanctionsStatus

_IDENTITY_FIELDS = {"name", "country", "tax_id", "lei"}
_CREDIT_FIELDS = {
    "credit_limit",
    "credit_currency",
    "payment_conditions",
    "approved_value",
    "approved_currency",
    "approved_terms",
}
_CUSTOMER_CREDIT_FIELDS = {"credit_limit", "credit_currency", "payment_conditions"}
_SUPPLIER_CREDIT_FIELDS = {"approved_value", "approved_currency", "approved_terms"}


class CommercialPartnerService:
    @staticmethod
    def create(session: Session, data: dict, *, commit: bool = True) -> CommercialPartner:
        cp = CommercialPartner(
            kind=CommercialPartnerKind(data["kind"]),
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
            lei=data.get("lei"),
            lei_status=LeiStatus.not_provided,
            kyc_status=KycStatus.pending,  # server-forced, fail-closed
            sanctions_status=SanctionsStatus.unscreened,  # server-forced, fail-closed
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
    def get_by_id(session: Session, cp_id: UUID) -> CommercialPartner | None:
        cp = session.get(CommercialPartner, cp_id)
        if cp and not cp.is_deleted:
            return cp
        return None

    @staticmethod
    def list(
        session: Session,
        *,
        kind_filter: str | None = None,
        kyc_status_filter: str | None = None,
        is_active_filter: bool | None = None,
    ):
        query = session.query(CommercialPartner).filter(
            CommercialPartner.is_deleted == False  # noqa: E712
        )
        if kind_filter:
            query = query.filter(CommercialPartner.kind == CommercialPartnerKind(kind_filter))
        if kyc_status_filter:
            query = query.filter(CommercialPartner.kyc_status == KycStatus(kyc_status_filter))
        if is_active_filter is not None:
            query = query.filter(CommercialPartner.is_active == is_active_filter)
        return query

    @staticmethod
    def update(
        session: Session, cp: CommercialPartner, data: dict, *, commit: bool = True
    ) -> CommercialPartner:
        if "kyc_status" in data:
            raise HTTPException(
                status_code=403,
                detail=(
                    "kyc_status mutations require the dedicated risk_manager "
                    "transition endpoint (POST /commercial-partners/{id}/kyc-status). "
                    "Generic update path cannot mutate kyc_status."
                ),
            )
        if _CREDIT_FIELDS & data.keys():
            raise HTTPException(
                status_code=403,
                detail=(
                    "credit/terms mutations require the dedicated risk_manager "
                    "endpoint (PATCH /commercial-partners/{id}/credit). Generic "
                    "update path cannot mutate credit/terms."
                ),
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
        # stale compliance evidence must not survive an identity change.
        if identity_changed and cp.sanctions_status is not SanctionsStatus.unscreened:
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
        session: Session, cp_id: UUID, *, new_status: KycStatus
    ) -> tuple[CommercialPartner, KycStatus]:
        # The route passes the Pydantic (schema) KycStatus, whose members are NOT
        # identical to the model enum, so coerce by value before the `is` checks below.
        new_status = KycStatus(getattr(new_status, "value", new_status))
        stmt = (
            select(CommercialPartner)
            .where(
                CommercialPartner.id == cp_id,
                CommercialPartner.is_deleted == False,  # noqa: E712
            )
            .with_for_update()
        )
        cp = session.execute(stmt).scalar_one_or_none()
        if not cp:
            raise HTTPException(status_code=404, detail="Commercial partner not found")
        # Transition to approved requires effective clear (governance Status transitions).
        # In W1 the stored sanctions_status already reflects any adjudication (W2 writes it),
        # so the check reads the stored field directly.
        if new_status is KycStatus.approved and cp.sanctions_status is not SanctionsStatus.clear:
            raise HTTPException(
                status_code=422,
                detail=(
                    "kyc_status cannot transition to approved unless the partner's "
                    f"sanctions_status is clear (observed: {cp.sanctions_status.value})."
                ),
            )
        previous_status = cp.kyc_status
        cp.kyc_status = new_status
        session.flush()
        return cp, previous_status

    @staticmethod
    def approve_credit(
        session: Session, cp: CommercialPartner, data: dict, *, commit: bool = True
    ) -> tuple[CommercialPartner, list[str], dict, dict]:
        allowed = (
            _CUSTOMER_CREDIT_FIELDS
            if cp.kind is CommercialPartnerKind.customer
            else _SUPPLIER_CREDIT_FIELDS
        )
        provided = {k: v for k, v in data.items() if v is not None}
        cross_kind = provided.keys() - allowed
        if cross_kind:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{cp.kind.value} partners cannot carry fields {sorted(cross_kind)}; "
                    f"allowed: {sorted(allowed)}"
                ),
            )
        previous_values: dict = {}
        new_values: dict = {}
        changed: list[str] = []
        for key, value in provided.items():
            previous_values[key] = _jsonable(getattr(cp, key))
            stored = to_decimal(value) if key in {"credit_limit", "approved_value"} else value
            setattr(cp, key, stored)
            new_values[key] = _jsonable(stored)
            changed.append(key)
        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp, changed, previous_values, new_values

    @staticmethod
    def soft_delete(
        session: Session, cp: CommercialPartner, *, commit: bool = True
    ) -> CommercialPartner:
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
        query = session.query(CommercialPartner).filter(
            CommercialPartner.tax_id == tax_id,
            CommercialPartner.is_deleted == False,  # noqa: E712
        )
        if exclude_id:
            query = query.filter(CommercialPartner.id != exclude_id)
        return query.first() is None


def _jsonable(value):
    if isinstance(value, Decimal):
        return str(value)
    return value
