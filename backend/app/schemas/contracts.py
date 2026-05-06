from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.contracts import HedgeContractStatus
from app.schemas._types import MTQuantity, Price


class HedgeLegSide(str, Enum):
    buy = "buy"
    sell = "sell"


class HedgeLegPriceType(str, Enum):
    fixed = "fixed"
    variable = "variable"


class HedgeClassification(str, Enum):
    long = "long"
    short = "short"


class HedgeLeg(BaseModel):
    side: HedgeLegSide = Field(..., description="Leg side (buy or sell)")
    price_type: HedgeLegPriceType = Field(
        ..., description="Leg price type (fixed or variable)"
    )


class HedgeContractCreate(BaseModel):
    commodity: str = Field(..., description="Commodity identifier", max_length=50)
    quantity_mt: MTQuantity = Field(..., description="Quantity in metric tons (MT)")
    legs: list[HedgeLeg] = Field(
        ..., description="Exactly two legs: one fixed, one variable"
    )
    counterparty_id: str | None = Field(None, max_length=100)
    fixed_price_value: Price | None = None
    fixed_price_unit: str | None = Field(None, max_length=32)
    float_pricing_convention: str | None = Field(None, max_length=64)
    premium_discount: Price | None = None
    pricing_period_month: int | None = Field(
        None, ge=1, le=12, description="Reference month for avg"
    )
    pricing_period_year: int | None = Field(None, description="Reference year for avg")
    fixing_date: date | None = Field(None, description="Fixing date for c2r")
    avg_computation_days: int | None = Field(
        None, ge=1, description="Computation days for avginter"
    )
    settlement_date: date | None = None
    prompt_date: date | None = None
    trade_date: date | None = None
    source_type: str | None = Field(None, max_length=20)
    notes: str | None = None

    @model_validator(mode="after")
    def validate_structure(self) -> "HedgeContractCreate":
        if self.quantity_mt <= 0:
            raise ValueError("quantity_mt must be greater than zero")
        if len(self.legs) != 2:
            raise ValueError("hedge contract must have exactly two legs")
        fixed_legs = [
            leg for leg in self.legs if leg.price_type == HedgeLegPriceType.fixed
        ]
        variable_legs = [
            leg for leg in self.legs if leg.price_type == HedgeLegPriceType.variable
        ]
        if len(fixed_legs) != 1 or len(variable_legs) != 1:
            raise ValueError(
                "hedge contract must have exactly one fixed leg and one variable leg"
            )
        return self


class HedgeContractRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str | None = None
    commodity: str = Field(..., max_length=64)
    quantity_mt: MTQuantity
    rfq_id: UUID | None = None
    rfq_quote_id: UUID | None = None
    counterparty_id: str | None = Field(None, max_length=100)
    fixed_price_value: Price | None = None
    fixed_price_unit: str | None = Field(None, max_length=32)
    float_pricing_convention: str | None = Field(None, max_length=64)
    premium_discount: Price | None = None
    pricing_period_month: int | None = None
    pricing_period_year: int | None = None
    fixing_date: date | None = None
    avg_computation_days: int | None = None
    status: str | None = Field(None, max_length=32)
    fixed_leg_side: HedgeLegSide = Field(
        ..., description="Fixed leg side (buy or sell)"
    )
    variable_leg_side: HedgeLegSide = Field(
        ..., description="Variable leg side (buy or sell)"
    )
    classification: HedgeClassification = Field(
        ..., description="Classification based on fixed leg"
    )
    settlement_date: date | None = None
    prompt_date: date | None = None
    trade_date: date | None = None
    source_type: str | None = None
    source_id: UUID | None = None
    notes: str | None = None
    created_by: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    deleted_at: datetime | None = None


class HedgeContractUpdate(BaseModel):
    """Partial update payload for a hedge contract."""

    quantity_mt: MTQuantity | None = None
    counterparty_id: str | None = Field(None, max_length=100)
    fixed_price_value: Price | None = None
    fixed_price_unit: str | None = Field(None, max_length=32)
    float_pricing_convention: str | None = Field(None, max_length=64)
    premium_discount: Price | None = None
    pricing_period_month: int | None = Field(None, ge=1, le=12)
    pricing_period_year: int | None = None
    fixing_date: date | None = None
    avg_computation_days: int | None = Field(None, ge=1)
    settlement_date: date | None = None
    prompt_date: date | None = None
    notes: str | None = None


class HedgeContractStatusUpdate(BaseModel):
    """Status transition payload."""

    status: HedgeContractStatus = Field(..., description="Target status")


class HedgeContractListResponse(BaseModel):
    items: list[HedgeContractRead]
    next_cursor: str | None = Field(None, max_length=256)


# ---------------------------------------------------------------------------
# Linkages — contract → deals → orders
# ---------------------------------------------------------------------------


class LinkedOrderSummary(BaseModel):
    id: UUID
    linked_type: str  # sales_order | purchase_order
    order_type: str | None = None
    quantity_mt: MTQuantity | None = None
    counterparty_id: str | None = None
    avg_entry_price: Price | None = None
    currency: str | None = None


class LinkedDealSummary(BaseModel):
    id: UUID
    reference: str
    name: str
    status: str
    total_physical_tons: MTQuantity
    total_hedge_tons: MTQuantity
    hedge_ratio: Price
    orders: list[LinkedOrderSummary] = []


class ContractLinkagesResponse(BaseModel):
    contract_id: UUID
    deals: list[LinkedDealSummary] = []
