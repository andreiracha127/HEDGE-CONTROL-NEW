"""Tests for the ReconciliationRun anchor model — PR-7 / J-A1-02 §3.2(a.i)."""

from __future__ import annotations

from app.models.reconciliation_run import (
    ReconciliationRun,
    ReconciliationRunStatus,
)
from app.services.exposure_engine import ExposureEngineService


class TestReconciliationRunModel:
    def test_default_status_is_running(self, session) -> None:
        run = ReconciliationRun()
        session.add(run)
        session.flush()
        session.refresh(run)
        assert run.status == ReconciliationRunStatus.running
        assert run.rows_created == 0
        assert run.rows_updated == 0


class TestReconcileServicePersistsRun:
    def test_reconcile_returns_run_and_summary(self, session) -> None:
        # Service returns a tuple (run, summary).
        result = ExposureEngineService.reconcile_from_orders(session)
        assert isinstance(result, tuple)
        assert len(result) == 2
        run, summary = result
        assert isinstance(run, ReconciliationRun)
        assert run.status == ReconciliationRunStatus.succeeded
        assert run.completed_at is not None
        assert isinstance(summary, dict)
        assert summary["created"] == 0
        assert summary["updated"] == 0

    def test_reconcile_writes_run_row_to_db(self, session) -> None:
        run, _summary = ExposureEngineService.reconcile_from_orders(session)
        session.commit()

        persisted = session.get(ReconciliationRun, run.id)
        assert persisted is not None
        assert persisted.status == ReconciliationRunStatus.succeeded
        # PR-5 §3.8: reconcile_from_orders now also retires Exposure rows
        # whose source Order has been soft-deleted, surfaced as "retired"
        # in the summary. With no orders / no stale exposures the count is 0.
        assert persisted.summary == {
            "created": 0,
            "updated": 0,
            "retired": 0,
            "message": "Reconciliation completed",
        }
