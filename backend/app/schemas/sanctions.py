from __future__ import annotations

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("reason")
    @classmethod
    def _reason_must_be_meaningful(cls, v: str) -> str:
        # This reason is the immutable audit evidence for a risk_manager override
        # of a flagged sanctions hit; an all-whitespace value (which slips past
        # min_length) is not acceptable rationale.
        if len(v.strip()) < 8:
            raise ValueError("reason must contain at least 8 non-whitespace characters")
        return v


class SanctionsAdjudicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    partner_id: uuid.UUID
    superseded_screening_id: uuid.UUID
    decision: str
    reason: str
    adjudicated_at: datetime
