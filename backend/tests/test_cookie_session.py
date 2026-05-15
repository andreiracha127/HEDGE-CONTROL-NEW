from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.core import auth as auth_module
from app.api.routes import auth as auth_routes
from app.core.auth import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    get_auth_settings,
    get_current_user,
)
from app.main import app
from tests.auth_token_helpers import (
    clerk_settings,
    generate_rsa_keypair,
    make_clerk_token,
    patched_jwks,
    rsa_jwk,
)

AUTHORIZATION_HEADER = "Authorization"
BEARER_PREFIX = "Bearer "


def _client_with_clerk_auth(monkeypatch):
    private_pem, public_pem = generate_rsa_keypair()
    jwks = {"keys": [rsa_jwk(public_pem)]}
    monkeypatch.setenv("CLERK_FAPI_HOST", "fitting-pug-55.clerk.accounts.dev")
    monkeypatch.setenv("CLERK_AUDIENCE", "hedge-control-tests")
    monkeypatch.setattr(auth_module, "_canonical_env", lambda: "production")
    monkeypatch.setattr(auth_routes, "_canonical_env", lambda: "production")
    original = app.dependency_overrides.copy()
    app.dependency_overrides.clear()
    app.dependency_overrides[get_auth_settings] = lambda: clerk_settings()
    return TestClient(app), private_pem, jwks, original


def _restore_overrides(original) -> None:
    app.dependency_overrides.clear()
    app.dependency_overrides.update(original)


def _set_cookie_header(response, name: str) -> str:
    values = response.headers.get_list("set-cookie")
    return next(value for value in values if value.startswith(f"{name}="))


def test_session_endpoint_sets_httponly_cookie(monkeypatch) -> None:
    client, private_pem, jwks, original = _client_with_clerk_auth(monkeypatch)
    token = make_clerk_token(private_pem, roles=["risk_manager"])
    try:
        with patched_jwks(auth_module, jwks):
            response = client.post("/auth/session", json={"session_token": token})
    finally:
        _restore_overrides(original)

    assert response.status_code == 200, response.text
    cookie = _set_cookie_header(response, SESSION_COOKIE_NAME)
    assert f"{SESSION_COOKIE_NAME}=" in cookie
    assert "HttpOnly" in cookie
    assert "Secure" in cookie
    assert "SameSite=lax" in cookie
    assert "Max-Age=300" in cookie
    assert "Path=/" in cookie


def test_session_endpoint_returns_csrf_token_in_body_and_cookie(monkeypatch) -> None:
    client, private_pem, jwks, original = _client_with_clerk_auth(monkeypatch)
    token = make_clerk_token(private_pem, roles=["risk_manager"])
    try:
        with patched_jwks(auth_module, jwks):
            response = client.post("/auth/session", json={"session_token": token})
    finally:
        _restore_overrides(original)

    assert response.status_code == 200, response.text
    assert response.json()["csrf_token"]
    csrf_cookie = _set_cookie_header(response, CSRF_COOKIE_NAME)
    assert f"{CSRF_COOKIE_NAME}=" in csrf_cookie
    assert "HttpOnly" not in csrf_cookie
    assert "Secure" in csrf_cookie
    assert "SameSite=lax" in csrf_cookie
    assert "Max-Age=300" in csrf_cookie
    assert "Path=/" in csrf_cookie


def test_cookie_endpoints_document_set_cookie_headers_in_openapi() -> None:
    app.openapi_schema = None
    schema = app.openapi()

    for path in ("/auth/session", "/auth/refresh", "/auth/logout"):
        headers = schema["paths"][path]["post"]["responses"]["200"]["headers"]
        assert "Set-Cookie" in headers
        assert headers["Set-Cookie"]["schema"] == {"type": "string"}


def test_authenticated_request_uses_cookie_not_bearer(monkeypatch) -> None:
    client, private_pem, jwks, original = _client_with_clerk_auth(monkeypatch)
    token = make_clerk_token(private_pem, roles=["risk_manager"])
    client.cookies.set(SESSION_COOKIE_NAME, token)
    try:
        with patched_jwks(auth_module, jwks):
            response = client.get("/auth/me")
    finally:
        _restore_overrides(original)

    assert response.status_code == 200, response.text
    assert response.json() == {"actor_sub": "user_test", "roles": ["risk_manager"]}


def test_authenticated_human_bearer_only_401(monkeypatch) -> None:
    client, private_pem, jwks, original = _client_with_clerk_auth(monkeypatch)
    token = make_clerk_token(private_pem, roles=["risk_manager"])
    try:
        with patched_jwks(auth_module, jwks):
            response = client.get(
                "/auth/me",
                headers={AUTHORIZATION_HEADER: BEARER_PREFIX + token},
            )
    finally:
        _restore_overrides(original)

    assert response.status_code == 401
    assert response.json()["detail"] == "Session cookie missing"


def test_get_current_user_uses_source_aware_extractor() -> None:
    source = auth_module.get_current_user.__code__.co_names
    assert "_extract_token_with_source" in source
    assert not hasattr(auth_module, "_extract_token")


def test_logout_clears_cookies(monkeypatch) -> None:
    client, private_pem, jwks, original = _client_with_clerk_auth(monkeypatch)
    token = make_clerk_token(private_pem, roles=["risk_manager"])
    client.cookies.set(SESSION_COOKIE_NAME, token)
    client.cookies.set(CSRF_COOKIE_NAME, "csrf")
    try:
        with patched_jwks(auth_module, jwks):
            response = client.post(
                "/auth/logout",
                headers={CSRF_HEADER_NAME: "csrf"},
            )
    finally:
        _restore_overrides(original)

    assert response.status_code == 200, response.text
    session_cookie = _set_cookie_header(response, SESSION_COOKIE_NAME)
    csrf_cookie = _set_cookie_header(response, CSRF_COOKIE_NAME)
    assert re.search(r"max-age=0|expires=", session_cookie, re.IGNORECASE)
    assert re.search(r"max-age=0|expires=", csrf_cookie, re.IGNORECASE)


def test_refresh_reexchanges_fresh_clerk_token_and_rotates_csrf(monkeypatch) -> None:
    client, private_pem, jwks, original = _client_with_clerk_auth(monkeypatch)
    old_csrf = "old-csrf"
    token = make_clerk_token(private_pem, roles=["risk_manager"])
    client.cookies.set(SESSION_COOKIE_NAME, token)
    client.cookies.set(CSRF_COOKIE_NAME, old_csrf)
    try:
        with patched_jwks(auth_module, jwks):
            response = client.post(
                "/auth/refresh",
                json={"session_token": token},
                headers={CSRF_HEADER_NAME: old_csrf},
            )
    finally:
        _restore_overrides(original)

    assert response.status_code == 200, response.text
    assert response.json()["csrf_token"] != old_csrf
    assert SESSION_COOKIE_NAME in _set_cookie_header(response, SESSION_COOKIE_NAME)


def test_auth_me_returns_actor_and_roles(monkeypatch) -> None:
    client, private_pem, jwks, original = _client_with_clerk_auth(monkeypatch)
    token = make_clerk_token(private_pem, roles=["auditor"])
    client.cookies.set(SESSION_COOKIE_NAME, token)
    try:
        with patched_jwks(auth_module, jwks):
            response = client.get("/auth/me")
    finally:
        _restore_overrides(original)

    assert response.status_code == 200, response.text
    assert response.json() == {"actor_sub": "user_test", "roles": ["auditor"]}
