from __future__ import annotations

from unittest.mock import MagicMock

from app.tasks import scheduler as scheduler_mod


def test_scheduler_registers_finance_pipeline_daily_job(monkeypatch) -> None:
    monkeypatch.setenv("SCHEDULER_DISABLED", "false")
    monkeypatch.setattr(scheduler_mod, "logger", MagicMock())
    scheduler_mod._scheduler = None

    scheduler_mod.start_scheduler()
    try:
        jobs = scheduler_mod._scheduler.get_jobs()
        assert any(job.id == "finance_pipeline_daily" for job in jobs)
    finally:
        scheduler_mod.stop_scheduler()


def test_scheduler_skips_when_disabled(monkeypatch) -> None:
    logger = MagicMock()
    monkeypatch.setenv("SCHEDULER_DISABLED", "true")
    monkeypatch.setattr(scheduler_mod, "logger", logger)
    scheduler_mod._scheduler = None

    scheduler_mod.start_scheduler()

    assert scheduler_mod._scheduler is None
    logger.info.assert_any_call("scheduler_disabled")
