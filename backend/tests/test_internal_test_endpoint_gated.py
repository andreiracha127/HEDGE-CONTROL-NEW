"""The /internal/test/cleanup endpoint is dual-gated by env and identity."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.core.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, get_current_user
from app.main import app


BACKEND_DIR = Path(__file__).resolve().parents[1]


def _post_cleanup(trace_id: str = "x"):
    client = TestClient(app)
    client.cookies.set(CSRF_COOKIE_NAME, "test-csrf-token")
    return client.post(
        "/internal/test/cleanup",
        json={"trace_id": trace_id},
        headers={CSRF_HEADER_NAME: "test-csrf-token"},
    )


def _internal_test_routes_for_env(app_env: str) -> list[str]:
    env = os.environ.copy()
    env.update(
        {
            "APP_ENV": app_env,
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "AUDIT_SIGNING_KEY": "test-signing-key-for-audit-hmac",
            "SCHEDULER_DISABLED": "1",
            "CLERK_FAPI_HOST": "clerk.test",
            "CLERK_AUDIENCE": "hedge-control",
            "SERVICE_JWT_SIGNING_KEY": "x" * 64,
            "SERVICE_JWT_PUBLIC_KEY": "x" * 64,
            "BACKEND_SERVICE_ISSUER": "https://svc.test",
            "BACKEND_SERVICE_AUDIENCE": "hedge-control",
        }
    )
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json; "
                "from app.main import app; "
                "print(json.dumps([getattr(r, 'path', '') for r in app.routes "
                "if '/internal/test' in getattr(r, 'path', '')]))"
            ),
        ],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_cleanup_present_when_test_env_and_correct_identity() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "service:e2e_cleanup",
        "roles": [],
    }
    try:
        response = _post_cleanup("nonexistent")
        assert response.status_code == 200, response.text
        assert isinstance(response.json(), dict)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_rejects_unauthenticated() -> None:
    response = _post_cleanup()
    assert response.status_code in (401, 403), response.text


def test_cleanup_rejects_wrong_service_identity() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "service:westmetall_ingest",
        "roles": [],
    }
    try:
        response = _post_cleanup()
        assert response.status_code == 403, response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_rejects_human_role_even_auditor() -> None:
    app.dependency_overrides[get_current_user] = lambda: {
        "sub": "real-auditor",
        "roles": ["auditor"],
    }
    try:
        response = _post_cleanup()
        assert response.status_code == 403, response.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_cleanup_absent_when_production_env() -> None:
    assert _internal_test_routes_for_env("production") == []


def test_cleanup_absent_when_staging_env() -> None:
    assert _internal_test_routes_for_env("staging") == []
