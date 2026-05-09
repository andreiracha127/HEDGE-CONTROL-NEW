from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from app.utils.price_reference import PriceQuote


class MTMObjectType(str, Enum):
    hedge_contract = "hedge_contract"
    order = "order"


class MTMResultResponse(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    object_type: MTMObjectType
    object_id: str = Field(..., max_length=64)
    as_of_date: date
    mtm_value: Decimal
    price_d1: Decimal
    entry_price: Decimal
    quantity_mt: Decimal
    price_quote: PriceQuote | None = None


class MTMSnapshotCreate(BaseModel):
    object_type: MTMObjectType
    object_id: str = Field(..., max_length=64)
    as_of_date: date
    correlation_id: str = Field(
        ..., description="Caller-provided correlation id for evidence", max_length=64
    )


class MTMSnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str = Field(..., max_length=64)
    object_type: MTMObjectType
    object_id: str = Field(..., max_length=64)
    as_of_date: date
    mtm_value: Decimal
    price_d1: Decimal
    entry_price: Decimal
    quantity_mt: Decimal
    price_source: str | None = Field(None, max_length=64)
    price_symbol: str | None = Field(None, max_length=32)
    price_settlement_date: date | None = None
    inputs_hash: str | None = Field(None, max_length=64)
    correlation_id: str = Field(..., max_length=64)
    created_at: datetime
