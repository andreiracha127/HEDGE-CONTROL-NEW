from __future__ import annotations

from fastapi import status

import httpx

from app.core.auth import get_current_user
import app.main as main_module
from app.main import app


def test_trace_id_header_is_propagated(client) -> None:
    response = client.get("/health", headers={"X-Trace-Id": "trace-123"})
    assert response.status_code == status.HTTP_200_OK
    assert response.headers.get("X-Trace-Id") == "trace-123"


def test_ready_requires_jwt_settings(client) -> None:
    app.dependency_overrides[get_current_user] = lambda: {"roles": ["auditor"]}
    response = client.get("/ready")
    assert response.status_code in {status.HTTP_200_OK, status.HTTP_503_SERVICE_UNAVAILABLE}


def test_metrics_endpoint_available(client) -> None:
    response = client.get("/metrics")
    assert response.status_code == status.HTTP_200_OK


def test_ready_hard_fails_on_jwks_unavailable(client, monkeypatch) -> None:
    app.dependency_overrides[get_current_user] = lambda: {"roles": ["auditor"]}

    def _raise(*_, **__):
        raise httpx.RequestError("fail")

    monkeypatch.setattr(httpx, "get", _raise)
    response = client.get("/ready")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_ready_hard_fails_on_clerk_only_jwks_unavailable(client, monkeypatch) -> None:
    app.dependency_overrides[get_current_user] = lambda: {"roles": ["auditor"]}
    monkeypatch.setattr(main_module._cfg, "jwt_issuer", "")
    monkeypatch.setenv("CLERK_FAPI_HOST", "fitting-pug-55.clerk.accounts.dev")
    monkeypatch.setenv("CLERK_AUDIENCE", "")

    def _raise(*_, **__):
        raise httpx.RequestError("fail")

    monkeypatch.setattr(httpx, "get", _raise)
    response = client.get("/ready")
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
