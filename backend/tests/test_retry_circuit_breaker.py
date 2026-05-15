"""Tests for retry + circuit breaker in westmetall_cash_settlement.

Covers:
  - tenacity retry behaviour (transient failures, exhaustion)
  - circuit breaker open / close / cooldown logic
  - route returns 503 when circuit is open
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest
from tenacity import wait_none

from app.services import westmetall_cash_settlement
from app.services.westmetall_cash_settlement import (
    CB_FAILURE_THRESHOLD,
    CircuitOpenError,
    _cb_check,
    _cb_record_failure,
    _cb_record_success,
    _fetch_with_retry,
    fetch_westmetall_html,
    reset_circuit_breaker,
)


@pytest.fixture(autouse=True)
def _westmetall_service_actor(monkeypatch):
    monkeypatch.setenv("DEV_SERVICE_ACTOR_SUB", "service:westmetall_ingest")


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_cb():
    """Ensure circuit breaker is clean before and after every test."""
    reset_circuit_breaker()
    yield
    reset_circuit_breaker()


@pytest.fixture(autouse=True)
def _no_retry_wait():
    """Remove tenacity wait between retries so tests run instantly."""
    original_wait = _fetch_with_retry.retry.wait
    _fetch_with_retry.retry.wait = wait_none()
    yield
    _fetch_with_retry.retry.wait = original_wait


def _ok_response(html: bytes = b"<html></html>") -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.content = html
    resp.status_code = 200
    resp.raise_for_status = MagicMock()
    return resp


def _error_response(status_code: int = 503) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            message=f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    )
    return resp


# ── retry tests ─────────────────────────────────────────────────────────


class TestRetry:
    """tenacity retry decorator on _fetch_with_retry."""

    def test_succeeds_on_first_try(self):
        with patch.object(
            westmetall_cash_settlement.httpx, "get", return_value=_ok_response(b"<ok/>")
        ):
            html, evidence = _fetch_with_retry("https://example.com")
            assert html == b"<ok/>"
            assert evidence.source_url == "https://example.com"

    def test_retries_transient_then_succeeds(self):
        """Two transient transport errors, then success on 3rd attempt."""
        mock_get = MagicMock(
            side_effect=[
                httpx.TransportError("connection reset"),
                httpx.TransportError("timeout"),
                _ok_response(b"<ok/>"),
            ]
        )
        with patch.object(westmetall_cash_settlement.httpx, "get", mock_get):
            html, evidence = _fetch_with_retry(
                "https://example.com", timeout_seconds=5.0
            )
            assert html == b"<ok/>"
            assert mock_get.call_count == 3

    def test_exhausts_retries_and_raises(self):
        """All 3 attempts fail → exception propagated."""
        mock_get = MagicMock(side_effect=httpx.TransportError("down"))
        with patch.object(westmetall_cash_settlement.httpx, "get", mock_get):
            with pytest.raises(httpx.TransportError, match="down"):
                _fetch_with_retry("https://example.com", timeout_seconds=5.0)
            assert mock_get.call_count == 3

    def test_http_status_error_triggers_retry(self):
        """HTTP 503 triggers retry."""
        responses = [_error_response(503), _error_response(503), _ok_response(b"<ok/>")]
        call_idx = {"i": 0}

        def _get_side_effect(*args, **kwargs):
            resp = responses[call_idx["i"]]
            call_idx["i"] += 1
            return resp

        with patch.object(
            westmetall_cash_settlement.httpx, "get", side_effect=_get_side_effect
        ):
            html, evidence = _fetch_with_retry(
                "https://example.com", timeout_seconds=5.0
            )
            assert html == b"<ok/>"
            assert call_idx["i"] == 3


# ── circuit breaker unit tests ──────────────────────────────────────────


class TestCircuitBreaker:
    """Low-level circuit breaker state machine."""

    def test_starts_closed(self):
        _cb_check()  # should not raise

    def test_stays_closed_while_under_threshold(self):
        for _ in range(CB_FAILURE_THRESHOLD - 1):
            _cb_record_failure()
        _cb_check()  # still closed

    def test_opens_at_threshold(self):
        for _ in range(CB_FAILURE_THRESHOLD):
            _cb_record_failure()
        with pytest.raises(CircuitOpenError):
            _cb_check()

    def test_success_resets_failure_count(self):
        for _ in range(CB_FAILURE_THRESHOLD - 1):
            _cb_record_failure()
        _cb_record_success()
        # Now 4 more failures should NOT open the breaker
        for _ in range(CB_FAILURE_THRESHOLD - 1):
            _cb_record_failure()
        _cb_check()  # still closed

    def test_reset_clears_open_state(self):
        for _ in range(CB_FAILURE_THRESHOLD):
            _cb_record_failure()
        with pytest.raises(CircuitOpenError):
            _cb_check()
        reset_circuit_breaker()
        _cb_check()  # closed again

    def test_closes_after_cooldown(self):
        for _ in range(CB_FAILURE_THRESHOLD):
            _cb_record_failure()
        # Manually move _CB_OPEN_UNTIL into the past
        with westmetall_cash_settlement._CB_LOCK:
            westmetall_cash_settlement._CB_OPEN_UNTIL = time.monotonic() - 1.0
        _cb_check()  # should not raise — cooldown elapsed


# ── integration: fetch_westmetall_html + circuit breaker ────────────────


class TestFetchWithCircuitBreaker:
    def test_records_failure_on_exception(self):
        """fetch_westmetall_html records CB failure when _fetch_with_retry raises."""
        mock_get = MagicMock(side_effect=httpx.TransportError("fail"))
        with patch.object(westmetall_cash_settlement.httpx, "get", mock_get):
            # Disable tenacity retry (call directly through retry wrapper)
            with patch.object(
                westmetall_cash_settlement,
                "_fetch_with_retry",
                side_effect=httpx.TransportError("fail"),
            ):
                with pytest.raises(httpx.TransportError):
                    fetch_westmetall_html("https://example.com")

        # One failure should have been recorded
        assert westmetall_cash_settlement._CB_FAILURE_COUNT == 1

    def test_raises_circuit_open_without_calling_remote(self):
        """When circuit is open, no HTTP call is made."""
        for _ in range(CB_FAILURE_THRESHOLD):
            _cb_record_failure()

        mock_get = MagicMock()
        with patch.object(westmetall_cash_settlement.httpx, "get", mock_get):
            with pytest.raises(CircuitOpenError):
                fetch_westmetall_html("https://example.com")
        mock_get.assert_not_called()


# ── route-level test ────────────────────────────────────────────────────


class TestRouteCircuitBreaker:
    def test_route_returns_503_on_circuit_open(self, client):
        """POST ingest returns 503 when circuit breaker is open."""
        for _ in range(CB_FAILURE_THRESHOLD):
            _cb_record_failure()

        resp = client.post(
            "/market-data/westmetall/aluminum/cash-settlement/ingest",
            json={"settlement_date": "2026-01-30"},
        )
        assert resp.status_code == 503
        assert "Circuit breaker open" in resp.json()["detail"]
