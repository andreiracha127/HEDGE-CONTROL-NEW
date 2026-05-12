from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.counterparty import (
    Counterparty,
    CounterpartyType,
    KycStatus,
    SanctionsStatus,
    RiskRating,
)


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
            kyc_status=KycStatus(data.get("kyc_status", "pending")),
            sanctions_status=SanctionsStatus(data.get("sanctions_status", "clear")),
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
            query = query.filter(
                Counterparty.kyc_status == KycStatus(kyc_status_filter)
            )
        if is_active_filter is not None:
            query = query.filter(Counterparty.is_active == is_active_filter)
        return query

    @staticmethod
    def update(
        session: Session, cp: Counterparty, data: dict, *, commit: bool = True
    ) -> Counterparty:
        for key, value in data.items():
            if value is not None:
                if key == "kyc_status":
                    setattr(cp, key, KycStatus(value))
                elif key == "sanctions_status":
                    setattr(cp, key, SanctionsStatus(value))
                elif key == "risk_rating":
                    setattr(cp, key, RiskRating(value))
                else:
                    setattr(cp, key, value)
        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp

    @staticmethod
    def soft_delete(
        session: Session, cp: Counterparty, *, commit: bool = True
    ) -> Counterparty:
        cp.is_deleted = True
        cp.deleted_at = datetime.now(timezone.utc)
        cp.is_active = False
        session.flush()
        if commit:
            session.commit()
            session.refresh(cp)
        return cp

    @staticmethod
    def check_tax_id_unique(
        session: Session, tax_id: str, exclude_id: UUID | None = None
    ) -> bool:
        query = session.query(Counterparty).filter(
            Counterparty.tax_id == tax_id,
            Counterparty.is_deleted == False,
        )
        if exclude_id:
            query = query.filter(Counterparty.id != exclude_id)
        return query.first() is None
