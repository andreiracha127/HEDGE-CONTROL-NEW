import os
import signal
from unittest.mock import MagicMock, patch


def test_scheduler_main_handles_sigterm_and_stops_scheduler() -> None:
    from app import scheduler_main

    registered_handlers = {}

    def _register_handler(sig: signal.Signals, handler) -> None:
        registered_handlers[sig] = handler

    shutdown_event = MagicMock()

    def _wait_until_signal() -> None:
        registered_handlers[signal.SIGTERM](signal.SIGTERM, None)

    shutdown_event.wait.side_effect = _wait_until_signal

    with (
        patch.dict(os.environ, {"SCHEDULER_DISABLED": ""}),
        patch.object(scheduler_main.signal, "signal", side_effect=_register_handler),
        patch.object(scheduler_main, "start_scheduler") as mock_start_scheduler,
        patch.object(scheduler_main, "stop_scheduler") as mock_stop_scheduler,
    ):
        result = scheduler_main.run(shutdown_event=shutdown_event)

    assert result == 0
    mock_start_scheduler.assert_called_once_with()
    shutdown_event.set.assert_called_once_with()
    mock_stop_scheduler.assert_called_once_with()


def test_scheduler_main_exits_when_scheduler_disabled() -> None:
    from app import scheduler_main

    with (
        patch.dict(os.environ, {"SCHEDULER_DISABLED": "true"}),
        patch.object(scheduler_main, "start_scheduler") as mock_start_scheduler,
        patch.object(scheduler_main, "stop_scheduler") as mock_stop_scheduler,
    ):
        result = scheduler_main.run(shutdown_event=MagicMock())

    assert result == 0
    mock_start_scheduler.assert_not_called()
    mock_stop_scheduler.assert_not_called()
