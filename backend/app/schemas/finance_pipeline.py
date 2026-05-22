"""Schemas for Finance Pipeline."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models.finance_pipeline import (
    PipelineRiskFlagSeverity,
    PipelineRiskFlagType,
    PipelineTriggerSource,
)


class PipelineStepRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    step_number: int
    step_name: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    records_processed: int = 0
    error_message: str | None = None


class PipelineRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_date: date
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    steps_completed: int
    steps_total: int
    error_message: str | None = None
    inputs_hash: str
    triggered_by: PipelineTriggerSource
    risk_flags_count: int
    created_at: datetime


class PipelineRiskFlagRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    flag_type: PipelineRiskFlagType
    severity: PipelineRiskFlagSeverity
    subject_entity_type: str
    subject_entity_id: uuid.UUID | None = None
    payload: dict
    created_at: datetime


class PipelineRunDetailRead(PipelineRunRead):
    steps: list[PipelineStepRead] = []
    risk_flags: list[PipelineRiskFlagRead] = []


class PipelineRunListResponse(BaseModel):
    items: list[PipelineRunRead]


class TriggerPipelineRequest(BaseModel):
    run_date: date
