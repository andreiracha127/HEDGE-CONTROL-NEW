"""ReconciliationRun model — durable anchor for exposure-reconcile audit rows.

The audit pattern requires a stable ``entity_id`` for every signed audit
event. The exposure reconcile route mutates many ``Exposure`` rows in a
single invocation, but the audit row itself needs ONE durable identifier to
reference. That identifier is the ``ReconciliationRun.id`` persisted at the
start of every reconcile call.

See PR-7 / J-A1-02 §3.2(a.i).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, JSON, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.models.base import Base


class ReconciliationRunStatus(enum.Enum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ReconciliationRun(Base):
    """One row per ``POST /exposures/reconcile`` invocation.

    Anchor for the signed audit event emitted by the route. Created in
    state ``running`` at the top of the service and updated to
    ``succeeded`` (with a summary payload) on success. On failure the
    surrounding ``unit_of_work`` rolls the row back, which is the
    intended behavior — a failed reconcile leaves no anchor and no
    audit, exactly as a failed mutation should.
    """

    __tablename__ = "reconciliation_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    status: Mapped[ReconciliationRunStatus] = mapped_column(
        Enum(ReconciliationRunStatus, name="reconciliation_run_status"),
        default=ReconciliationRunStatus.running,
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rows_created: Mapped[int] = mapped_column(default=0, nullable=False)
    rows_updated: Mapped[int] = mapped_column(default=0, nullable=False)
    summary: Mapped[object | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(length=512), nullable=True)
