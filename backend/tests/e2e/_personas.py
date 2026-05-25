"""Identity minters for E2E tests."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from base64 import urlsafe_b64encode
from collections.abc import Iterator
from contextlib import contextmanager

import httpx
from fastapi.testclient import TestClient

from app.core.auth import (
    CSRF_COOKIE_NAME,
    CSRF_HEADER_NAME,
    SESSION_COOKIE_NAME,
    get_current_user,
)
from app.main import app

FULL_STACK = os.environ.get("E2E_FULL_STACK") == "1"
FULL_STACK_BASE_URL = os.environ.get(
    "E2E_FULL_STACK_BASE_URL", "http://localhost:8000"
)
META_APP_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "test-meta-app-secret")


class _E2ETestClient(TestClient):
    """TestClient that mirrors the repo-wide CSRF behavior for mutations."""

    _csrf_exempt_prefixes = ("/auth/session", "/webhooks/", "/healthz")

    def request(self, method, url, *args, **kwargs):  # type: ignore[no-untyped-def]
        if (
            method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
            and isinstance(url, str)
            and not url.startswith(self._csrf_exempt_prefixes)
        ):
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.setdefault(CSRF_HEADER_NAME, "test-csrf-token")
            kwargs["headers"] = headers
            self.cookies.set(CSRF_COOKIE_NAME, "test-csrf-token")
        return super().request(method, url, *args, **kwargs)


def _override_user(sub: str, roles: list[str]) -> None:
    app.dependency_overrides[get_current_user] = lambda: {"sub": sub, "roles": roles}


def _clear_override() -> None:
    app.dependency_overrides.pop(get_current_user, None)


def _b64url(payload: dict[str, object] | bytes) -> str:
    raw = (
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if isinstance(payload, dict)
        else payload
    )
    return urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _dev_session_token(sub: str, roles: list[str]) -> str:
    return ".".join(
        [
            _b64url({"alg": "HS256", "typ": "JWT"}),
            _b64url({"sub": sub, "roles": roles, "exp": int(time.time()) + 300}),
            _b64url(b"e2e-dev-signature"),
        ]
    )


@contextmanager
def _persona(sub: str, roles: list[str]) -> Iterator[TestClient | httpx.Client]:
    if FULL_STACK:
        csrf = "test-csrf-token"
        session_token = _dev_session_token(sub, roles)
        headers = {
            CSRF_HEADER_NAME: csrf,
        }
        cookies = {CSRF_COOKIE_NAME: csrf, SESSION_COOKIE_NAME: session_token}
        with httpx.Client(
            base_url=FULL_STACK_BASE_URL,
            headers=headers,
            cookies=cookies,
            timeout=10.0,
        ) as client:
            yield client
        return

    _override_user(sub, roles)
    client = _E2ETestClient(app)
    client.cookies.set(CSRF_COOKIE_NAME, "test-csrf-token")
    client.headers[CSRF_HEADER_NAME] = "test-csrf-token"
    try:
        yield client
    finally:
        _clear_override()


@contextmanager
def as_trader() -> Iterator[TestClient | httpx.Client]:
    with _persona("e2e-trader", ["trader"]) as client:
        yield client


@contextmanager
def as_risk_manager() -> Iterator[TestClient | httpx.Client]:
    with _persona("e2e-risk-manager", ["risk_manager"]) as client:
        yield client


@contextmanager
def as_auditor() -> Iterator[TestClient | httpx.Client]:
    with _persona("e2e-auditor", ["auditor"]) as client:
        yield client


@contextmanager
def as_service(identity: str) -> Iterator[TestClient | httpx.Client]:
    valid = {
        "service:westmetall_ingest",
        "service:rfq_outbound",
        "service:cashflow_pipeline",
        "service:webhook_inbound",
        "service:e2e_cleanup",
    }
    if identity not in valid:
        raise ValueError(f"unknown service identity: {identity}")
    with _persona(identity, []) as client:
        yield client


def as_meta_webhook(raw_body: bytes) -> dict[str, str]:
    digest = hmac.new(
        META_APP_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return {"X-Hub-Signature-256": f"sha256={digest}"}
