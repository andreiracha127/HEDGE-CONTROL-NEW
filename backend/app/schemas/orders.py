from datetime import date, datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas._types import MTQuantity, Price


class OrderType(str, Enum):
    sales = "SO"
    purchase = "PO"


class PriceType(str, Enum):
    fixed = "fixed"
    variable = "variable"


class OrderPricingConvention(str, Enum):
    avg = "AVG"
    avginter = "AVGInter"
    c2r = "C2R"


class PricingType(str, Enum):
    fixed = "fixed"
    average = "average"
    avginter = "avginter"
    fix = "fix"
    c2r = "c2r"


class OrderBase(BaseModel):
    price_type: PriceType = Field(..., description="Fixed or variable pricing")
    quantity_mt: MTQuantity = Field(..., description="Quantity in metric tons (MT)")
    pricing_convention: OrderPricingConvention | None = Field(
        None, description="Required only for variable orders (AVG, AVGInter, C2R)"
    )
    avg_entry_price: Price | None = Field(
        None, description="Fixed price value (USD/MT) — required when price_type=fixed"
    )
    counterparty_name: str | None = Field(
        None, max_length=200, description="Client or supplier name (free text)"
    )
    reference_month: str | None = Field(
        None,
        max_length=7,
        description="Reference month yyyy-MM — required for AVG convention",
    )
    observation_date_start: date | None = Field(
        None, description="Observation window start — required for AVGInter convention"
    )
    observation_date_end: date | None = Field(
        None, description="Observation window end — required for AVGInter convention"
    )
    fixing_date: date | None = Field(
        None, description="Fixing date — required for C2R convention"
    )
    counterparty_id: UUID | None = Field(None, description="FK to counterparties")
    pricing_type: PricingType | None = Field(None, description="Pricing type detail")
    delivery_terms: str | None = Field(
        None, max_length=50, description="e.g. CIF Rotterdam"
    )
    delivery_date_start: date | None = Field(None, description="Delivery window start")
    delivery_date_end: date | None = Field(None, description="Delivery window end")
    payment_terms_days: int | None = Field(None, description="Payment terms in days")
    currency: str = Field("USD", max_length=3, description="ISO 4217 currency code")
    notes: str | None = Field(None, description="Free-form notes")


class SalesOrderCreate(OrderBase):
    pass


class PurchaseOrderCreate(OrderBase):
    pass


class OrderRead(OrderBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_type: OrderType
    created_at: datetime
    deleted_at: datetime | None = None


class OrderListResponse(BaseModel):
    items: list[OrderRead]
    next_cursor: str | None = Field(None, max_length=256)


# --- SoPoLink schemas ---


class SoPoLinkCreate(BaseModel):
    sales_order_id: UUID
    purchase_order_id: UUID
    linked_tons: MTQuantity = Field(..., gt=0)


class SoPoLinkRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    sales_order_id: UUID
    purchase_order_id: UUID
    linked_tons: MTQuantity
    created_at: datetime


class SoPoLinkListResponse(BaseModel):
    items: list[SoPoLinkRead]
    next_cursor: str | None = Field(None, max_length=256)
