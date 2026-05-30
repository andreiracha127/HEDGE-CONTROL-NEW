from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.counterparty import KycStatus, RiskRating, SanctionsStatus


class CommercialPartnerKind(str, Enum):
    customer = "customer"
    supplier = "supplier"


class LeiStatus(str, Enum):
    not_provided = "not_provided"
    valid = "valid"
    invalid = "invalid"
    lapsed = "lapsed"
    issued = "issued"
    error = "error"


class CommercialPartnerCreate(BaseModel):
    # NOTE: deliberately omits kyc_status, sanctions_status, and all credit/terms
    # fields -- server forces kyc_status=pending, sanctions_status=unscreened, and
    # credit/terms are set only via the dedicated risk_manager flow.
    kind: CommercialPartnerKind
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
        None, max_length=50, description="WhatsApp number in E.164 format"
    )
    lei: str | None = Field(None, max_length=20)
    risk_rating: RiskRating = RiskRating.medium
    is_active: bool = True
    notes: str | None = None


class CommercialPartnerUpdate(BaseModel):
    # Identity/contact/LEI-input fields ONLY. kyc_status + credit/terms are NOT here;
    # the route additionally rejects any attempt to send them (defense in depth).
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
    lei: str | None = Field(None, max_length=20)
    is_active: bool | None = None
    notes: str | None = None


class CreditApprovalRequest(BaseModel):
    reason: str = Field(min_length=8, max_length=1000)
    # customer fields
    credit_limit: Decimal | None = None
    credit_currency: str | None = Field(None, min_length=3, max_length=3)
    payment_conditions: dict | None = None
    # supplier fields
    approved_value: Decimal | None = None
    approved_currency: str | None = Field(None, min_length=3, max_length=3)
    approved_terms: dict | None = None


class CommercialPartnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: CommercialPartnerKind
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
    lei: str | None = None
    lei_status: LeiStatus
    lei_legal_name: str | None = None
    lei_checked_at: datetime | None = None
    kyc_status: KycStatus
    sanctions_status: SanctionsStatus
    risk_rating: RiskRating
    credit_limit: Decimal | None = None
    credit_currency: str | None = None
    payment_conditions: dict | None = None
    approved_value: Decimal | None = None
    approved_currency: str | None = None
    approved_terms: dict | None = None
    is_active: bool
    notes: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    is_deleted: bool
    deleted_at: datetime | None = None


class CommercialPartnerListResponse(BaseModel):
    items: list[CommercialPartnerRead]
    next_cursor: str | None = Field(None, max_length=256)
