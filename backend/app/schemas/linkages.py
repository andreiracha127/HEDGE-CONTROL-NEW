from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas._types import MTQuantity


class HedgeOrderLinkageCreate(BaseModel):
    order_id: UUID = Field(..., description="Linked order ID")
    contract_id: UUID = Field(..., description="Linked hedge contract ID")
    quantity_mt: MTQuantity = Field(..., description="Linked quantity in MT")

    @model_validator(mode="after")
    def validate_quantity(self) -> "HedgeOrderLinkageCreate":
        if self.quantity_mt <= 0:
            raise ValueError("quantity_mt must be greater than zero")
        return self


class HedgeOrderLinkageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    contract_id: UUID
    quantity_mt: MTQuantity
    created_at: datetime


class HedgeOrderLinkageListResponse(BaseModel):
    items: list[HedgeOrderLinkageRead]
    next_cursor: str | None = None
