from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any

import httpx
from fastapi import Depends, HTTPException, Request, status
from jose import JWTError, jwt

from app.core.config import get_settings


JWKS_CACHE_TTL_SECONDS = 300

# APP_ENV values that require fully-configured JWT auth and reject anonymous
# fallback. Canonical source is ``Settings.app_env`` (PR-A5-3 / J-A5-06).
_FAIL_CLOSED_ENVS = {"production", "prod", "staging", "stage", "preprod", "pre-prod"}

logger = logging.getLogger(__name__)


@dataclass
class AuthSettings:
    issuer: str
    audience: str
    jwks_url: str


def _canonical_env() -> str:
    """Return the lowercased canonical APP_ENV from settings.

    The legacy ``ENVIRONMENT`` os.getenv() lookup is intentionally NOT
    consulted (J-A5-06): the auth fail-closed gate must agree with the
    audit-signing fail-closed gate in ``config.py``, which reads
    ``Settings.app_env`` only.
    """
    return (get_settings().app_env or "").strip().lower()


def _auth_enabled() -> bool:
    return bool(get_settings().jwt_issuer)


def _auth_explicitly_disabled() -> bool:
    return os.getenv("AUTH_DISABLED", "").lower() in ("1", "true", "yes")


def validate_auth_config() -> None:
    """Call at startup. Fails closed in production/staging-like envs.

    Behavior matrix (J-A5-06):

    * ``APP_ENV`` in production/staging-like values:
        * if JWT_ISSUER/JWT_AUDIENCE/JWKS_URL are all present → boot;
        * otherwise → ``RuntimeError`` (fail-closed at startup);
        * ``AUTH_DISABLED`` is **not** honored here — it cannot silently
          downgrade a production deployment to anonymous access.
    * ``APP_ENV`` in development/local/test:
        * full JWT config present → boot;
        * JWT_ISSUER unset → allowed; auth is disabled and an explicit
          warning is emitted (especially if ``AUTH_DISABLED=true``).
    """
    s = get_settings()
    env = _canonical_env()

    if _auth_enabled():
        # Auth claims to be on; require full triplet, otherwise we'd fall
        # back to anonymous on first JWKS dependency call in production.
        if not (s.jwt_audience and s.jwks_url):
            raise RuntimeError(
                "JWT_ISSUER is set but JWT_AUDIENCE/JWKS_URL are missing — "
                "auth would fail open. Configure the full triplet."
            )
        return

    # Auth disabled. Fail closed in production/staging.
    if env in _FAIL_CLOSED_ENVS:
        if _auth_explicitly_disabled():
            raise RuntimeError(
                f"AUTH_DISABLED is not honored when APP_ENV={env!r}. "
                "Configure JWT_ISSUER/JWT_AUDIENCE/JWKS_URL or change APP_ENV."
            )
        raise RuntimeError(
            f"JWT_ISSUER is empty but APP_ENV={env!r}. "
            "Set JWT_ISSUER/JWT_AUDIENCE/JWKS_URL — production/staging "
            "auth is fail-closed."
        )

    if _auth_explicitly_disabled():
        logger.warning(
            "Authentication is explicitly disabled via AUTH_DISABLED (APP_ENV=%s)",
            env or "<unset>",
        )


def get_auth_settings() -> AuthSettings | None:
    if not _auth_enabled():
        return None
    s = get_settings()
    issuer = s.jwt_issuer
    audience = s.jwt_audience
    jwks_url = s.jwks_url
    if not issuer or not audience or not jwks_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="JWT settings missing",
        )
    return AuthSettings(issuer=issuer, audience=audience, jwks_url=jwks_url)


class JWKSCache:
    def __init__(self) -> None:
        self._jwks: dict[str, Any] | None = None
        self._expires_at = 0.0

    def get(self, settings: AuthSettings) -> dict[str, Any]:
        now = time.time()
        if self._jwks is None or now >= self._expires_at:
            self._jwks = self._fetch_jwks(settings.jwks_url)
            self._expires_at = now + JWKS_CACHE_TTL_SECONDS
        return self._jwks

    @staticmethod
    def _fetch_jwks(jwks_url: str) -> dict[str, Any]:
        # NOTE: This is a synchronous HTTP call, but all routes using
        # get_current_user are sync def, so FastAPI runs them in a thread
        # pool — the event loop is NOT blocked. The TTL cache further
        # limits the frequency of actual HTTP requests.
        try:
            response = httpx.get(jwks_url, timeout=5.0)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="JWKS unavailable",
            ) from exc


_jwks_cache = JWKSCache()


def _extract_token(request: Request) -> str:
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )
    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header",
        )
    return parts[1]


def _select_jwk(jwks: dict[str, Any], kid: str | None) -> dict[str, Any]:
    keys = jwks.get("keys", [])
    for key in keys:
        if kid is None or key.get("kid") == kid:
            return key
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token key"
    )


# Anonymous fallback identity. Used ONLY when auth is disabled in a
# non-production/staging environment — see get_current_user(). The role
# list intentionally includes ``auditor`` to keep local dev workflows
# usable; the production/staging gate below prevents this identity from
# ever being returned in a fail-closed environment.
_AUTH_DISABLED_FALLBACK_MARKER = object()

_ANONYMOUS_USER: dict[str, Any] = {
    "sub": "anonymous",
    "name": "Anonymous (auth disabled)",
    "roles": ["trader", "risk_manager", "auditor"],
    "_auth_disabled_fallback": _AUTH_DISABLED_FALLBACK_MARKER,
}


def get_auth_disabled_fallback_user() -> dict[str, Any]:
    """Return the singleton dev/test fallback identity used when auth is off."""
    return _ANONYMOUS_USER

_VALID_HUMAN_ROLES = frozenset({"trader", "risk_manager", "auditor"})
_INTERNAL_SERVICE_IDENTITIES = frozenset(
    {
        "service:westmetall_ingest",
        "service:rfq_outbound",
        "service:cashflow_pipeline",
    }
)
# ``service:webhook_inbound`` is intentionally excluded here: webhook ingress
# authenticates through provider signatures, not internal service JWTs.


def get_current_user(
    request: Request,
    settings: AuthSettings | None = Depends(get_auth_settings),
) -> dict[str, Any]:
    if not _auth_enabled() or settings is None:
        # Defense-in-depth (J-A5-06): even if validate_auth_config() was
        # bypassed at startup, reject anonymous access at request time in
        # production/staging-like environments.
        if _canonical_env() in _FAIL_CLOSED_ENVS:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        return get_auth_disabled_fallback_user()

    token = _extract_token(request)
    try:
        header = jwt.get_unverified_header(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

    jwks = _jwks_cache.get(settings)
    jwk = _select_jwk(jwks, header.get("kid"))

    try:
        payload = jwt.decode(
            token,
            jwk,
            algorithms=["RS256"],
            audience=settings.audience,
            issuer=settings.issuer,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc

    return payload


def get_current_actor_sub(
    user: dict[str, Any] = Depends(get_current_user),
) -> str:
    """Authoritative actor identifier for mutation evidence."""
    sub = user.get("sub") if isinstance(user, dict) else None
    if not isinstance(sub, str) or not sub.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated subject is required",
        )
    actor_sub = sub.strip()
    if len(actor_sub) > 64:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authenticated subject must be at most 64 characters",
        )
    return actor_sub


def extract_actor_roles_from_payload(user: dict[str, Any]) -> list[str]:
    """Validate and normalize human authorization roles from a JWT payload."""
    raw = user.get("roles") if isinstance(user, dict) else None
    if not isinstance(raw, list):
        return []
    roles = sorted({r for r in raw if isinstance(r, str) and r in _VALID_HUMAN_ROLES})
    sub = user.get("sub")
    if isinstance(sub, str) and sub.startswith("service:") and roles:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Service identities cannot carry human roles",
        )
    if (
        user is _ANONYMOUS_USER
        and sub == "anonymous"
        and user.get("_auth_disabled_fallback") is _AUTH_DISABLED_FALLBACK_MARKER
        and roles == ["auditor", "risk_manager", "trader"]
    ):
        # Auth-disabled local/test fallback is dev-only; fail-closed envs never
        # return this identity from get_current_user().
        return roles
    if "auditor" in roles and len(roles) > 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid role combination: auditor must be exclusive",
        )
    return roles


def get_current_actor_roles(
    user: dict[str, Any] = Depends(get_current_user),
) -> list[str]:
    """Authoritative role set for authorization decisions."""
    return extract_actor_roles_from_payload(user)


def require_role(role: str):
    return require_any_role(role)


def require_any_role(*roles: str):
    def _dependency(user: dict[str, Any] = Depends(get_current_user)) -> None:
        if not isinstance(user, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authenticated user payload is invalid",
            )
        actor_roles = get_current_actor_roles(user)
        if not set(actor_roles).intersection(set(roles)):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
            )

    return _dependency


def require_service_identity(name: str):
    """Route gate for internal-issued service-account JWTs."""
    expected = f"service:{name}" if not name.startswith("service:") else name
    if expected not in _INTERNAL_SERVICE_IDENTITIES:
        raise ValueError(f"Unknown service identity: {expected}")

    def _gate(user: dict[str, Any] = Depends(get_current_user)) -> None:
        get_current_actor_roles(user)
        actor_sub = get_current_actor_sub(user)
        if actor_sub == expected:
            return
        dev_actor_sub = os.getenv("DEV_SERVICE_ACTOR_SUB", "").strip()
        if (
            _canonical_env() not in _FAIL_CLOSED_ENVS
            and dev_actor_sub == expected
            and user is get_auth_disabled_fallback_user()
        ):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Service identity {expected} required",
        )

    return _gate
