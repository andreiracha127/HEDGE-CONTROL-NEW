from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Response

from app.core.auth import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    _FAIL_CLOSED_ENVS,
    AuthSettings,
    _canonical_env,
    _validate_clerk_token,
    _validate_human_roles_at_jwt_time,
    get_auth_settings,
    get_current_user,
)

_AUTH_COOKIE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "headers": {
            "Set-Cookie": {
                "description": (
                    "Sets the httpOnly session cookie and the readable CSRF cookie "
                    "used by the double-submit CSRF middleware."
                ),
                "schema": {"type": "string"},
            }
        }
    }
}

_CLEAR_COOKIE_RESPONSES: dict[int | str, dict[str, Any]] = {
    200: {
        "headers": {
            "Set-Cookie": {
                "description": "Clears the session and CSRF cookies.",
                "schema": {"type": "string"},
            }
        }
    }
}

router = APIRouter(tags=["auth"])


def _set_auth_cookies(response: Response, session_token: str, csrf: str) -> None:
    secure = _canonical_env() in _FAIL_CLOSED_ENVS
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=300,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf,
        httponly=False,
        secure=secure,
        samesite="lax",
        max_age=300,
        path="/",
    )


def _validate_session_token(session_token: str, settings: AuthSettings | None) -> dict[str, Any]:
    if settings is None:
        raise HTTPException(status_code=401, detail="Authentication disabled")
    payload = _validate_clerk_token(session_token, settings)
    _validate_human_roles_at_jwt_time(payload)
    return payload


@router.post("/auth/session", responses=_AUTH_COOKIE_RESPONSES)
async def create_session(
    response: Response,
    session_token: str = Body(..., embed=True),
    settings: AuthSettings | None = Depends(get_auth_settings),
) -> dict[str, str]:
    payload = _validate_session_token(session_token, settings)
    csrf = secrets.token_urlsafe(32)
    _set_auth_cookies(response, session_token, csrf)
    return {"actor_sub": payload["sub"], "csrf_token": csrf}


@router.post("/auth/refresh", responses=_AUTH_COOKIE_RESPONSES)
async def refresh_session(
    response: Response,
    session_token: str = Body(..., embed=True),
    settings: AuthSettings | None = Depends(get_auth_settings),
) -> dict[str, str]:
    payload = _validate_session_token(session_token, settings)
    csrf = secrets.token_urlsafe(32)
    _set_auth_cookies(response, session_token, csrf)
    return {"actor_sub": payload["sub"], "csrf_token": csrf}


@router.post("/auth/logout", responses=_CLEAR_COOKIE_RESPONSES)
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"status": "logged_out"}


@router.get("/auth/me")
async def read_current_identity(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return {"actor_sub": user["sub"], "roles": user.get("roles", [])}
