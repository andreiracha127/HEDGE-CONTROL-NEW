from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from app.models.finance_pipeline import PipelineTriggerSource
from app.services.finance_pipeline_service import HolidaySkipSignal
from app.tasks.finance_pipeline_task import run_finance_pipeline_daily


def test_task_holiday_logs_skipped_no_exception(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr("app.tasks.finance_pipeline_task.logger", logger)
    monkeypatch.setattr(
        "app.tasks.finance_pipeline_task.FinancePipelineService.run_daily_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(HolidaySkipSignal("holiday")),
    )

    run_finance_pipeline_daily(today=date(2026, 5, 23))

    logger.info.assert_any_call(
        "finance_pipeline_task_skipped_holiday",
        run_date="2026-05-23",
        reason="holiday",
    )


def test_task_business_day_logs_success(monkeypatch) -> None:
    logger = MagicMock()
    run = MagicMock()
    run.id = "run-id"
    run.status.value = "completed"
    run.triggered_by = PipelineTriggerSource.scheduler
    monkeypatch.setattr("app.tasks.finance_pipeline_task.logger", logger)
    monkeypatch.setattr(
        "app.tasks.finance_pipeline_task.FinancePipelineService.run_daily_pipeline",
        lambda *args, **kwargs: run,
    )

    run_finance_pipeline_daily(today=date(2026, 5, 22))

    logger.info.assert_any_call(
        "finance_pipeline_task_success",
        run_date="2026-05-22",
        run_id="run-id",
        status="completed",
    )


def test_task_internal_failure_logs_exception_no_crash(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setattr("app.tasks.finance_pipeline_task.logger", logger)
    monkeypatch.setattr(
        "app.tasks.finance_pipeline_task.FinancePipelineService.run_daily_pipeline",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("simulated DB outage")),
    )

    run_finance_pipeline_daily(today=date(2026, 5, 22))

    logger.error.assert_called_once()
    assert logger.error.call_args.args == ("finance_pipeline_task_failure",)
