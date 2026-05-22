"""APScheduler integration — started/stopped via the FastAPI lifespan."""

from __future__ import annotations

import os

from apscheduler.schedulers.background import BackgroundScheduler

from app.core.config import get_settings
from app.core.logging import get_logger
from app.tasks.finance_pipeline_task import run_finance_pipeline_daily
from app.tasks.market_data_staleness_task import run_market_data_staleness_check
from app.tasks.rfq_timeout_task import run_rfq_timeout_check
from app.tasks.westmetall_task import run_westmetall_ingestion
from app.tasks.workflow_approval_sweeper import workflow_approval_sweeper

logger = get_logger()

_scheduler: BackgroundScheduler | None = None


def is_scheduler_disabled() -> bool:
    """Return whether scheduler startup is disabled by environment."""
    return os.getenv("SCHEDULER_DISABLED", "").strip().lower() in ("1", "true", "yes")


def start_scheduler() -> None:
    """Create and start the background scheduler.

    The Westmetall ingestion job is scheduled daily at 18:00 UTC by default.
    Override with ``WESTMETALL_CRON_HOUR`` / ``WESTMETALL_CRON_MINUTE`` env vars.
    The finance pipeline job is scheduled daily at 19:00 UTC by default.
    Override with ``FINANCE_PIPELINE_CRON_HOUR`` /
    ``FINANCE_PIPELINE_CRON_MINUTE`` env vars.
    Set ``SCHEDULER_DISABLED=1`` to skip starting the scheduler entirely
    (useful in tests and single-shot CLI scripts).
    """
    global _scheduler  # noqa: PLW0603

    if is_scheduler_disabled():
        logger.info("scheduler_disabled")
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(
        run_westmetall_ingestion,
        trigger="cron",
        hour=int(os.getenv("WESTMETALL_CRON_HOUR", "18")),
        minute=int(os.getenv("WESTMETALL_CRON_MINUTE", "0")),
        id="westmetall_daily_ingestion",
        replace_existing=True,
        misfire_grace_time=3600,  # allow up to 1 h late execution
    )
    _scheduler.add_job(
        run_rfq_timeout_check,
        trigger="cron",
        minute=int(os.getenv("RFQ_TIMEOUT_CRON_MINUTE", "0")),
        id="rfq_timeout_check",
        replace_existing=True,
        misfire_grace_time=900,  # allow up to 15 min late execution
    )
    _scheduler.add_job(
        run_market_data_staleness_check,
        trigger="interval",
        minutes=int(os.getenv("MARKET_DATA_STALENESS_CHECK_INTERVAL_MINUTES", "15")),
        id="market_data_staleness_check",
        replace_existing=True,
        misfire_grace_time=900,
    )
    _scheduler.add_job(
        workflow_approval_sweeper,
        trigger="interval",
        minutes=get_settings().workflow_approval_sweeper_interval_minutes,
        id="workflow_approval_sweeper",
        replace_existing=True,
        misfire_grace_time=900,
    )
    _scheduler.add_job(
        run_finance_pipeline_daily,
        trigger="cron",
        hour=int(os.getenv("FINANCE_PIPELINE_CRON_HOUR", "19")),
        minute=int(os.getenv("FINANCE_PIPELINE_CRON_MINUTE", "0")),
        id="finance_pipeline_daily",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.start()
    logger.info(
        "scheduler_started",
        jobs=[j.id for j in _scheduler.get_jobs()],
    )


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler if running."""
    global _scheduler  # noqa: PLW0603
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler_stopped")
        _scheduler = None
