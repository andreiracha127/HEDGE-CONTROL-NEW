from __future__ import annotations

from datetime import datetime, timezone

import pytest
from structlog.testing import capture_logs

from app.models.market_data import MarketDataSequenceTracker
from app.services.market_data_governance import (
    SequenceMonotonicityViolation,
    check_sequence_monotonicity,
)


INSTRUMENT = "LME_ALU_CASH_SETTLEMENT_DAILY"


def _check(session, sequence_number: int) -> None:
    check_sequence_monotonicity(
        session,
        provider="westmetall",
        instrument=INSTRUMENT,
        sequence_number=sequence_number,
        provider_timestamp=datetime(2026, 5, 16, tzinfo=timezone.utc),
        actor_sub="service:westmetall_ingest",
    )


def test_check_sequence_monotonicity_first_call_creates_tracker_row(session) -> None:
    _check(session, 10)

    tracker = session.get(MarketDataSequenceTracker, ("westmetall", INSTRUMENT))
    assert tracker is not None
    assert tracker.last_sequence == 10


def test_check_sequence_monotonicity_advances_on_higher_sequence(session) -> None:
    session.add(
        MarketDataSequenceTracker(
            provider="westmetall",
            instrument=INSTRUMENT,
            last_sequence=10,
        )
    )
    session.flush()

    _check(session, 20)

    tracker = session.get(MarketDataSequenceTracker, ("westmetall", INSTRUMENT))
    assert tracker is not None
    assert tracker.last_sequence == 20


def test_check_sequence_monotonicity_duplicate_raises(session) -> None:
    session.add(
        MarketDataSequenceTracker(
            provider="westmetall",
            instrument=INSTRUMENT,
            last_sequence=10,
        )
    )
    session.flush()

    with capture_logs() as logs:
        with pytest.raises(SequenceMonotonicityViolation):
            _check(session, 10)

    assert logs[-1]["event"] == "market_data_replay_rejected"
    assert logs[-1]["reason"] == "sequence_duplicate"


def test_check_sequence_monotonicity_out_of_order_raises(session) -> None:
    session.add(
        MarketDataSequenceTracker(
            provider="westmetall",
            instrument=INSTRUMENT,
            last_sequence=10,
        )
    )
    session.flush()

    with capture_logs() as logs:
        with pytest.raises(SequenceMonotonicityViolation):
            _check(session, 5)

    assert logs[-1]["event"] == "market_data_replay_rejected"
    assert logs[-1]["reason"] == "sequence_not_monotonic"
