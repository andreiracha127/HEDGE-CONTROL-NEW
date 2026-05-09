from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class PriceReferenceEntry(BaseModel):
    symbol: str
    source: str
    settlement_date: date
    value: Decimal


class PLResultResponse(BaseModel):
    realized_pl: Decimal
    unrealized_mtm: Decimal
    price_references: list[PriceReferenceEntry] = Field(default_factory=list)


class PLSnapshotCreate(BaseModel):
    entity_type: str = Field(..., max_length=32)
    entity_id: uuid.UUID
    period_start: date
    period_end: date


class PLSnapshotResponse(BaseModel):
    id: uuid.UUID
    entity_type: str = Field(..., max_length=32)
    entity_id: uuid.UUID
    period_start: date
    period_end: date
    realized_pl: Decimal
    unrealized_mtm: Decimal
    price_references: list[dict] | None = None
    inputs_hash: str | None = Field(None, max_length=64)
    created_at: datetime
    correlation_id: Optional[uuid.UUID]

    model_config = ConfigDict(from_attributes=True)
