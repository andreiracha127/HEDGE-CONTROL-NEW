"""CSP report endpoint tests (PR-CL3-4): legacy/modern shapes, logging, 204, CSRF-exempt, rate-limit."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# The CSP report endpoint is CSRF-exempt and unauthenticated by design.
# We use the main app client (which has the full middleware stack).


@pytest.fixture
def csp_report_payload() -> dict:
    """Legacy CSP report shape (what older browsers send)."""
    return {
        "csp-report": {
            "document-uri": "https://example.com/app",
            "violated-directive": "script-src",
            "blocked-uri": "https://evil.com/mal.js",
            "source-file": "https://example.com/app.js",
            "line-number": 42,
            "referrer": "https://example.com/landing",
        }
    }


@pytest.fixture
def modern_report_payload() -> dict:
    """Modern Reporting API shape (Report-To / ReportingObserver)."""
    return {
        "type": "csp-violation",
        "url": "https://example.com/dashboard",
        "body": {
            "documentURL": "https://example.com/dashboard",
            "effectiveDirective": "connect-src",
            "blockedURL": "wss://evil.com/socket",
            "sourceFile": "https://example.com/chunk.js",
            "lineNumber": 123,
            "referrer": "",
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_csp_report_post_valid_logs_violation(client: TestClient, csp_report_payload: dict) -> None:
    """POST a valid legacy CSP report; assert structlog csp_violation event emitted."""
    with patch("app.api.routes.csp_report.logger.warning") as mock_log:
        resp = client.post("/csp/report", json=csp_report_payload)
        assert resp.status_code == 204
        mock_log.assert_called_once()
        args, kwargs = mock_log.call_args
        assert args[0] == "csp_violation"
        assert kwargs["blocked_uri"] == "https://evil.com/mal.js"
        assert kwargs["violated_directive"] == "script-src"
        assert kwargs["document_uri"] == "https://example.com/app"


def test_csp_report_accepts_modern_reporting_api_body(
    client: TestClient, modern_report_payload: dict
) -> None:
    """POST a modern Report-To payload; assert 204 and normalized fields logged."""
    with patch("app.api.routes.csp_report.logger.warning") as mock_log:
        resp = client.post("/csp/report", json=modern_report_payload)
        assert resp.status_code == 204
        mock_log.assert_called_once()
        _, kwargs = mock_log.call_args
        assert kwargs["document_uri"] == "https://example.com/dashboard"
        assert kwargs["violated_directive"] == "connect-src"
        assert kwargs["blocked_uri"] == "wss://evil.com/socket"


def test_csp_report_logs_all_fields(client: TestClient) -> None:
    """The structured csp_violation log MUST include all 7 keys even when optional values absent."""
    payload = {"csp-report": {"document-uri": "https://ex.com", "violated-directive": "img-src"}}
    with patch("app.api.routes.csp_report.logger.warning") as mock_log:
        resp = client.post("/csp/report", json=payload)
        assert resp.status_code == 204
        _, kwargs = mock_log.call_args
        for key in (
            "blocked_uri",
            "violated_directive",
            "document_uri",
            "source_file",
            "line_number",
            "referrer",
        ):
            assert key in kwargs  # present (may be None)
        assert kwargs["violated_directive"] == "img-src"


def test_csp_report_post_returns_204(client: TestClient, csp_report_payload: dict) -> None:
    """Successful report returns 204 No Content (no body)."""
    resp = client.post("/csp/report", json=csp_report_payload)
    assert resp.status_code == 204
    assert resp.content == b""


def test_csp_report_post_invalid_json_returns_400(client: TestClient) -> None:
    """Malformed JSON body returns 400."""
    resp = client.post(
        "/csp/report",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "invalid JSON" in resp.json()["detail"]


def test_csp_report_csrf_exempt(client: TestClient, csp_report_payload: dict) -> None:
    """POST /csp/report without CSRF token succeeds (204, not 403) — exempt in csrf.py:31."""
    resp = client.post("/csp/report", json=csp_report_payload)
    assert resp.status_code == 204  # NOT 403


def test_csp_report_rate_limit_uses_configured_limit(client: TestClient) -> None:
    """51st POST to /csp/report returns 429 (uses default RATE_LIMIT_CSP_REPORT=50/minute)."""
    tiny = {"csp-report": {"document-uri": "u", "violated-directive": "d"}}

    # First 50 should succeed (204)
    for _ in range(50):
        r = client.post("/csp/report", json=tiny)
        assert r.status_code == 204

    # 51st must be rate-limited
    r51 = client.post("/csp/report", json=tiny)
    assert r51.status_code == 429
    body = r51.json()
    assert "Rate limit exceeded" in body.get("detail", "")
