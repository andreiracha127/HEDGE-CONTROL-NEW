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


class TestReconcileResponseSchemaCarriesRetired:
    """PR-5 codex P2 — ReconcileResponse must surface `retired` count in
    HTTP responses; the field is silently filtered by FastAPI's
    response_model unless declared on the schema."""

    def test_route_returns_retired_key_when_sweep_runs(self, client, session):
        """Per §3.8 retirement sweep + ReconcileResponse contract:
          response["retired"] >= 1 after reconcile sees a soft-deleted
          source Order that previously had a live Exposure row.
        """
        from datetime import datetime, timezone

        from app.models.exposure import Exposure
        from app.models.orders import Order, OrderType, PriceType
        from decimal import Decimal

        # Live order → reconcile → live Exposure row.
        order = Order(
            order_type=OrderType.sales,
            price_type=PriceType.variable,
            commodity="ALUMINUM",
            quantity_mt=Decimal("100.000"),
        )
        session.add(order)
        session.commit()

        first = client.post("/exposures/reconcile")
        assert first.status_code == 200
        assert "retired" in first.json()
        assert first.json()["retired"] == 0
        assert first.json()["created"] == 1

        # Soft-delete the order; the next reconcile must retire the row.
        order = session.query(Order).filter(Order.id == order.id).one()
        order.deleted_at = datetime.now(timezone.utc)
        session.commit()

        second = client.post("/exposures/reconcile")
        assert second.status_code == 200
        body = second.json()
        assert "retired" in body, (
            "ReconcileResponse must surface the retirement-sweep count "
            f"per PR-5 §3.8. Got: {body}"
        )
        assert isinstance(body["retired"], int)
        assert body["retired"] >= 1

        # Sanity: the Exposure row is now retired in the DB as well.
        exposure = (
            session.query(Exposure).filter(Exposure.source_id == order.id).one()
        )
        assert exposure.is_deleted is True
        assert exposure.deleted_at is not None
