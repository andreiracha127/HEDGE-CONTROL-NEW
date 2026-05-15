from __future__ import annotations

import secrets

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME


def _has_bearer_authorization(request: Request) -> bool:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return scheme.lower() == "bearer" and bool(token)


def _normalized_path(path: str) -> str:
    if path == "/api":
        path = "/"
    elif path.startswith("/api/"):
        path = path[4:]
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


async def csrf_middleware(request: Request, call_next):
    """Double-submit CSRF check for cookie-authenticated mutating requests."""
    if request.method not in ("POST", "PATCH", "PUT", "DELETE"):
        return await call_next(request)
    path = _normalized_path(request.url.path)
    if path.startswith(("/auth/session", "/webhooks/", "/healthz")):
        return await call_next(request)
    if _has_bearer_authorization(request) and SESSION_COOKIE_NAME not in request.cookies:
        return await call_next(request)

    cookie = request.cookies.get(CSRF_COOKIE_NAME)
    header = request.headers.get(CSRF_HEADER_NAME)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "CSRF token missing or mismatch"},
        )
    return await call_next(request)
