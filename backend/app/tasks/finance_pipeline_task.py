"""Scheduled task boundary for the HB-3 finance pipeline daily run."""

from __future__ import annotations

from datetime import date

from app.core.database import SessionLocal
from app.core.logging import get_logger
from app.models.finance_pipeline import PipelineTriggerSource
from app.services.finance_pipeline_service import (
    FinancePipelineService,
    HolidaySkipSignal,
    RunAlreadyInProgressSignal,
)

logger = get_logger()


def run_finance_pipeline_daily(today: date | None = None) -> None:
    """Execute one scheduled finance-pipeline run without crashing APScheduler."""
    run_date = today or date.today()
    session = SessionLocal()
    try:
        run = FinancePipelineService.run_daily_pipeline(
            session,
            run_date,
            trigger_source=PipelineTriggerSource.scheduler,
            actor="service:cashflow_pipeline",
        )
        logger.info(
            "finance_pipeline_task_success",
            run_date=run_date.isoformat(),
            run_id=str(run.id),
            status=run.status.value,
        )
    except HolidaySkipSignal as exc:
        logger.info(
            "finance_pipeline_task_skipped_holiday",
            run_date=run_date.isoformat(),
            reason=str(exc),
        )
    except RunAlreadyInProgressSignal as exc:
        logger.info(
            "finance_pipeline_task_already_running",
            run_date=run_date.isoformat(),
            reason=str(exc),
        )
    except Exception as exc:  # pragma: no cover - scheduler safety net
        session.rollback()
        logger.error(
            "finance_pipeline_task_failure",
            run_date=run_date.isoformat(),
            error=str(exc),
            exc_info=True,
        )
    finally:
        session.close()
