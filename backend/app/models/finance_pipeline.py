"""Finance Pipeline Run / Step models."""

from __future__ import annotations

import enum
import hashlib
import uuid
from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.models.base import Base


class PipelineRunStatus(enum.Enum):
    running = "running"
    completed = "completed"
    failed = "failed"
    partial = "partial"


class PipelineStepStatus(enum.Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"


PIPELINE_STEPS: tuple[str, ...] = (
    "market_snapshot",
    "mtm_computation",
    "pl_snapshot",
    "cashflow_baseline",
    "risk_flags",
    "summary",
)


class PipelineTriggerSource(enum.Enum):
    scheduler = "scheduler"
    manual = "manual"


class PipelineRiskFlagType(enum.Enum):
    missing_mtm_price = "missing_mtm_price"
    unhedged_exposure_over_guardrail = "unhedged_exposure_over_guardrail"
    kyc_regression_with_active_deals = "kyc_regression_with_active_deals"
    workflow_approval_pending_past_expiry = "workflow_approval_pending_past_expiry"


class PipelineRiskFlagSeverity(enum.Enum):
    informational = "informational"
    warning = "warning"
    critical = "critical"


RiskFlagPayloadType = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")
RUN_LEVEL_RISK_FLAG_SUBJECT_KEY = "__run__"


def _risk_flag_subject_key(context) -> str:
    subject_entity_id = context.get_current_parameters().get("subject_entity_id")
    return str(subject_entity_id or RUN_LEVEL_RISK_FLAG_SUBJECT_KEY)


class FinancePipelineRun(Base):
    __tablename__ = "finance_pipeline_runs"
    __table_args__ = (UniqueConstraint("run_date", name="uq_finance_pipeline_runs_run_date"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[PipelineRunStatus] = mapped_column(
        Enum(PipelineRunStatus, name="pipeline_run_status"),
        nullable=False,
        default=PipelineRunStatus.running,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    steps_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    steps_total: Mapped[int] = mapped_column(Integer, default=6, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    triggered_by: Mapped[PipelineTriggerSource] = mapped_column(
        Enum(PipelineTriggerSource, name="pipeline_trigger_source"),
        nullable=False,
        default=PipelineTriggerSource.manual,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    steps: Mapped[list[FinancePipelineStep]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="FinancePipelineStep.step_number",
    )
    risk_flags: Mapped[list[FinancePipelineRiskFlag]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        order_by="FinancePipelineRiskFlag.created_at",
    )

    @property
    def risk_flags_count(self) -> int:
        return len(self.risk_flags)

    @staticmethod
    def compute_hash(run_date: date) -> str:
        return hashlib.sha256(str(run_date).encode()).hexdigest()


class FinancePipelineStep(Base):
    __tablename__ = "finance_pipeline_steps"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("finance_pipeline_runs.id"), nullable=False
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    step_name: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[PipelineStepStatus] = mapped_column(
        Enum(PipelineStepStatus, name="pipeline_step_status"),
        nullable=False,
        default=PipelineStepStatus.pending,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    records_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[FinancePipelineRun] = relationship(back_populates="steps")


class FinancePipelineRiskFlag(Base):
    __tablename__ = "finance_pipeline_risk_flags"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "subject_entity_key",
            "flag_type",
            name="uq_finance_pipeline_risk_flags_run_subject_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("finance_pipeline_runs.id"),
        nullable=False,
        index=True,
    )
    flag_type: Mapped[PipelineRiskFlagType] = mapped_column(
        Enum(PipelineRiskFlagType, name="pipeline_risk_flag_type"),
        nullable=False,
    )
    severity: Mapped[PipelineRiskFlagSeverity] = mapped_column(
        Enum(PipelineRiskFlagSeverity, name="pipeline_risk_flag_severity"),
        nullable=False,
    )
    subject_entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    subject_entity_key: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default=_risk_flag_subject_key,
    )
    payload: Mapped[dict] = mapped_column(
        RiskFlagPayloadType,
        nullable=False,
        default=dict,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[FinancePipelineRun] = relationship(back_populates="risk_flags")
