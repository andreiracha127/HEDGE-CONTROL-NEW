from __future__ import annotations

import secrets

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME, SESSION_COOKIE_NAME


def _has_bearer_authorization(request: Request) -> bool:
    return request.headers.get("Authorization", "").startswith("Bearer ")


async def csrf_middleware(request: Request, call_next):
    """Double-submit CSRF check for cookie-authenticated mutating requests."""
    if request.method not in ("POST", "PATCH", "PUT", "DELETE"):
        return await call_next(request)
    if request.url.path.startswith(("/auth/session", "/webhooks/", "/healthz")):
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
