"""The /internal/test/cleanup endpoint is dual-gated by env and identity."""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from app.core.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME


def _reload_app(monkeypatch, app_env: str):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("DATABASE_URL", "sqlite+pysqlite:///:memory:")
    monkeypatch.setenv("AUDIT_SIGNING_KEY", "test-signing-key-for-audit-hmac")
    monkeypatch.setenv("SCHEDULER_DISABLED", "1")
    if app_env in {"production", "staging"}:
        monkeypatch.setenv("CLERK_FAPI_HOST", "clerk.test")
        monkeypatch.setenv("CLERK_AUDIENCE", "hedge-control")
        monkeypatch.setenv("SERVICE_JWT_SIGNING_KEY", "x" * 64)
        monkeypatch.setenv("SERVICE_JWT_PUBLIC_KEY", "x" * 64)
        monkeypatch.setenv("BACKEND_SERVICE_ISSUER", "https://svc.test")
        monkeypatch.setenv("BACKEND_SERVICE_AUDIENCE", "hedge-control")

    import app.core.config as config
    import app.core.auth as auth
    import app.api.routes.internal_test as internal_test
    import app.main as main

    importlib.reload(config)
    importlib.reload(auth)
    importlib.reload(internal_test)
    return importlib.reload(main), auth


def _post_cleanup(app, trace_id: str = "x"):
    client = TestClient(app)
    client.cookies.set(CSRF_COOKIE_NAME, "test-csrf-token")
    return client.post(
        "/internal/test/cleanup",
        json={"trace_id": trace_id},
        headers={CSRF_HEADER_NAME: "test-csrf-token"},
    )


def test_cleanup_present_when_test_env_and_correct_identity(monkeypatch) -> None:
    main, auth = _reload_app(monkeypatch, "test")
    main.app.dependency_overrides[auth.get_current_user] = lambda: {
        "sub": "service:e2e_cleanup",
        "roles": [],
    }
    try:
        response = _post_cleanup(main.app, "nonexistent")
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), dict)
    finally:
        main.app.dependency_overrides.pop(auth.get_current_user, None)


def test_cleanup_rejects_unauthenticated(monkeypatch) -> None:
    main, _auth = _reload_app(monkeypatch, "test")
    response = _post_cleanup(main.app)
    assert response.status_code in (401, 403), response.text


def test_cleanup_rejects_wrong_service_identity(monkeypatch) -> None:
    main, auth = _reload_app(monkeypatch, "test")
    main.app.dependency_overrides[auth.get_current_user] = lambda: {
        "sub": "service:westmetall_ingest",
        "roles": [],
    }
    try:
        response = _post_cleanup(main.app)
        assert response.status_code == 403, response.text
    finally:
        main.app.dependency_overrides.pop(auth.get_current_user, None)


def test_cleanup_rejects_human_role_even_auditor(monkeypatch) -> None:
    main, auth = _reload_app(monkeypatch, "test")
    main.app.dependency_overrides[auth.get_current_user] = lambda: {
        "sub": "real-auditor",
        "roles": ["auditor"],
    }
    try:
        response = _post_cleanup(main.app)
        assert response.status_code == 403, response.text
    finally:
        main.app.dependency_overrides.pop(auth.get_current_user, None)


def test_cleanup_absent_when_production_env(monkeypatch) -> None:
    main, auth = _reload_app(monkeypatch, "production")
    main.app.dependency_overrides[auth.get_current_user] = lambda: {
        "sub": "service:e2e_cleanup",
        "roles": [],
    }
    try:
        response = _post_cleanup(main.app)
        assert response.status_code == 404, response.text
    finally:
        main.app.dependency_overrides.pop(auth.get_current_user, None)


def test_cleanup_absent_when_staging_env(monkeypatch) -> None:
    main, _auth = _reload_app(monkeypatch, "staging")
    response = _post_cleanup(main.app)
    assert response.status_code == 404, response.text
