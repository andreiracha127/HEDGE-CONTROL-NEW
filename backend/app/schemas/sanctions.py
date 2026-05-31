from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class AdjudicationDecisionIn(str, enum.Enum):
    clear = "clear"
    blocked = "blocked"


class SanctionsScreeningRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    partner_id: uuid.UUID
    screened_at: datetime
    provider: str
    algorithm: str
    top_score: Decimal | None
    match_count: int
    result: str | None
    status: str


class SanctionsAdjudicationRequest(BaseModel):
    decision: AdjudicationDecisionIn
    reason: str = Field(min_length=8)


class SanctionsAdjudicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    partner_id: uuid.UUID
    superseded_screening_id: uuid.UUID
    decision: str
    reason: str
    adjudicated_at: datetime
