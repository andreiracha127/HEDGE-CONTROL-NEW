from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CashSettlementIngestRequest(BaseModel):
    settlement_date: date = Field(
        ..., description="Settlement date to ingest (YYYY-MM-DD)"
    )


class CashSettlementBulkIngestRequest(BaseModel):
    start_date: date | None = Field(None, description="Start of date range (inclusive)")
    end_date: date | None = Field(None, description="End of date range (inclusive)")


class CashSettlementIngestResponse(BaseModel):
    ingested_count: int
    skipped_count: int
    source: str = Field(..., max_length=64)
    symbol: str = Field(..., max_length=64)
    settlement_date: date
    source_url: str = Field(..., max_length=512)
    html_sha256: str = Field(..., max_length=128)
    fetched_at: datetime
    is_canonical: bool


class CashSettlementBulkIngestResponse(BaseModel):
    ingested_count: int
    skipped_count: int
    source: str = Field(..., max_length=64)
    symbol: str = Field(..., max_length=64)
    source_url: str = Field(..., max_length=512)
    html_sha256: str = Field(..., max_length=128)
    fetched_at: datetime
    is_canonical: bool


class CashSettlementPriceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str = Field(..., max_length=64)
    symbol: str = Field(..., max_length=64)
    settlement_date: date
    price_usd: Decimal
    is_canonical: bool
    source_url: str = Field(..., max_length=512)
    html_sha256: str = Field(..., max_length=128)
    fetched_at: datetime
    created_at: datetime
