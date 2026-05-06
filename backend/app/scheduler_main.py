"""Standalone scheduler process entrypoint for Railway."""

from __future__ import annotations

import signal
from threading import Event
from types import FrameType

from app.core.logging import configure_logging, get_logger
from app.tasks.scheduler import is_scheduler_disabled, start_scheduler, stop_scheduler

configure_logging()
logger = get_logger()


def run(shutdown_event: Event | None = None) -> int:
    """Run the APScheduler worker until SIGTERM or SIGINT is received."""
    if is_scheduler_disabled():
        logger.info("scheduler_process_disabled")
        return 0

    event = shutdown_event or Event()

    def _handle_shutdown(signum: int, _frame: FrameType | None) -> None:
        logger.info("scheduler_shutdown_signal", signal=signum)
        event.set()

    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    start_scheduler()
    logger.info("scheduler_process_started")

    try:
        event.wait()
        return 0
    finally:
        stop_scheduler()
        logger.info("scheduler_process_stopped")


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
