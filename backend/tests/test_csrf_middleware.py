from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME
from app.core.csrf import csrf_middleware
from app.main import app as main_app


def _csrf_client() -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def _middleware(request, call_next):
        return await csrf_middleware(request, call_next)

    @app.get("/probe")
    async def read_probe():
        return {"ok": True}

    @app.post("/probe")
    async def write_probe():
        return {"ok": True}

    @app.post("/auth/session")
    async def auth_session():
        return {"ok": True}

    @app.post("/webhooks/whatsapp")
    async def webhook():
        return {"ok": True}

    @app.post("/healthz")
    async def healthz():
        return {"ok": True}

    return TestClient(app)


def test_csrf_middleware_get_passes_without_token() -> None:
    response = _csrf_client().get("/probe")

    assert response.status_code == 200


def test_csrf_middleware_post_missing_token_403() -> None:
    response = _csrf_client().post("/probe")

    assert response.status_code == 403
    assert response.json() == {"detail": "CSRF token missing or mismatch"}


def test_csrf_middleware_post_mismatch_403() -> None:
    client = _csrf_client()
    client.cookies.set(CSRF_COOKIE_NAME, "cookie-token")
    response = client.post(
        "/probe",
        headers={CSRF_HEADER_NAME: "header-token"},
    )

    assert response.status_code == 403


def test_csrf_middleware_post_match_passes() -> None:
    client = _csrf_client()
    client.cookies.set(CSRF_COOKIE_NAME, "same-token")
    response = client.post(
        "/probe",
        headers={CSRF_HEADER_NAME: "same-token"},
    )

    assert response.status_code == 200


def test_csrf_middleware_bearer_without_session_cookie_passes() -> None:
    response = _csrf_client().post(
        "/probe",
        headers={"Authorization": "bearer service-token"},
    )

    assert response.status_code == 200


def test_csrf_middleware_bearer_with_session_cookie_still_requires_csrf() -> None:
    client = _csrf_client()
    client.cookies.set(SESSION_COOKIE_NAME, "session-token")
    response = client.post(
        "/probe",
        headers={"Authorization": "Bearer service-token"},
    )

    assert response.status_code == 403


def test_csrf_middleware_session_endpoint_exempt() -> None:
    response = _csrf_client().post("/auth/session")

    assert response.status_code == 200


def test_csrf_middleware_webhook_exempt() -> None:
    response = _csrf_client().post("/webhooks/whatsapp")

    assert response.status_code == 200


def test_csrf_middleware_healthz_exempt() -> None:
    response = _csrf_client().post("/healthz")

    assert response.status_code == 200


def test_cors_allows_credentials_and_csrf_header() -> None:
    response = TestClient(main_app).options(
        "/auth/session",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-CSRF-Token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "x-csrf-token" in response.headers["access-control-allow-headers"].lower()
