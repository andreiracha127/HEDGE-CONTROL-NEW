from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CounterpartyType(str, Enum):
    broker = "broker"
    bank_br = "bank_br"
    customer = "customer"
    supplier = "supplier"


class KycStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    expired = "expired"
    rejected = "rejected"


class SanctionsStatus(str, Enum):
    clear = "clear"
    flagged = "flagged"
    blocked = "blocked"


class RiskRating(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class CounterpartyCreate(BaseModel):
    type: CounterpartyType
    name: str = Field(..., max_length=200)
    short_name: str | None = Field(None, max_length=50)
    tax_id: str | None = Field(None, max_length=50)
    country: str = Field(..., min_length=3, max_length=3)
    city: str | None = Field(None, max_length=100)
    address: str | None = None
    contact_name: str | None = Field(None, max_length=200)
    contact_email: str | None = Field(None, max_length=200)
    contact_phone: str | None = Field(None, max_length=50)
    whatsapp_phone: str | None = Field(
        None,
        max_length=50,
        description="WhatsApp number in E.164 format, e.g. +5511999999999",
    )
    payment_terms_days: int = 30
    credit_limit_usd: float | None = None
    sanctions_status: SanctionsStatus = SanctionsStatus.clear
    risk_rating: RiskRating = RiskRating.medium
    is_active: bool = True
    notes: str | None = None


class CounterpartyUpdate(BaseModel):
    name: str | None = Field(None, max_length=200)
    short_name: str | None = Field(None, max_length=50)
    tax_id: str | None = Field(None, max_length=50)
    country: str | None = Field(None, min_length=3, max_length=3)
    city: str | None = Field(None, max_length=100)
    address: str | None = None
    contact_name: str | None = Field(None, max_length=200)
    contact_email: str | None = Field(None, max_length=200)
    contact_phone: str | None = Field(None, max_length=50)
    whatsapp_phone: str | None = Field(None, max_length=50)
    credit_limit_usd: float | None = None
    sanctions_status: SanctionsStatus | None = None
    risk_rating: RiskRating | None = None
    is_active: bool | None = None
    notes: str | None = None


class KycStatusTransitionRequest(BaseModel):
    new_status: KycStatus
    reason: str = Field(min_length=8, max_length=512)


class CounterpartyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    type: CounterpartyType
    name: str
    short_name: str | None = None
    tax_id: str | None = None
    country: str
    city: str | None = None
    address: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    whatsapp_phone: str | None = None
    payment_terms_days: int | None = None
    credit_limit_usd: float | None = None
    kyc_status: KycStatus
    sanctions_status: SanctionsStatus
    risk_rating: RiskRating
    is_active: bool
    notes: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    is_deleted: bool
    deleted_at: datetime | None = None


class CounterpartyListResponse(BaseModel):
    items: list[CounterpartyRead]
    next_cursor: str | None = Field(None, max_length=256)
