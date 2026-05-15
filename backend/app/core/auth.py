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
SESSION_COOKIE_NAME = "__Session"
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"
SERVICE_TOKEN_TTL_SECONDS = 300

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
    # TODO(post-cluster-3): swap dev CLERK_FAPI_HOST values to clerk.<custom-domain>.
    return bool(os.getenv("CLERK_FAPI_HOST") or get_settings().jwt_issuer)


def is_auth_enabled() -> bool:
    return _auth_enabled()


def _auth_explicitly_disabled() -> bool:
    return os.getenv("AUTH_DISABLED", "").lower() in ("1", "true", "yes")


def validate_auth_config() -> None:
    """Call at startup. Fails closed in production/staging-like envs.

    Behavior matrix (J-A5-06):

    * ``APP_ENV`` in production/staging-like values:
        * Cluster 3 Clerk + service-token env vars are mandatory;
        * legacy JWT_ISSUER/JWT_AUDIENCE/JWKS_URL remain supported only as
          migration fallback outside the Clerk-primary fail-closed contract;
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
    clerk_host = os.getenv("CLERK_FAPI_HOST", "").strip()

    if (
        env in _FAIL_CLOSED_ENVS
        and not clerk_host
        and not s.jwt_issuer
        and _auth_explicitly_disabled()
    ):
        raise RuntimeError(
            f"Cannot boot in fail-closed environment (APP_ENV={env!r}) when "
            "AUTH_DISABLED is explicitly set and authentication is not configured. "
            "Production and staging require authentication. Configure "
            "CLERK_FAPI_HOST or JWT_ISSUER/JWT_AUDIENCE/JWKS_URL, or change APP_ENV."
        )

    cluster3_missing: list[str] = []
    if env in _FAIL_CLOSED_ENVS:
        for name in (
            "CLERK_FAPI_HOST",
            "CLERK_AUDIENCE",
            "SERVICE_JWT_SIGNING_KEY",
            "SERVICE_JWT_PUBLIC_KEY",
            "BACKEND_SERVICE_ISSUER",
            "BACKEND_SERVICE_AUDIENCE",
        ):
            if not os.getenv(name):
                cluster3_missing.append(name)

    if cluster3_missing:
        raise RuntimeError(
            f"Missing required auth configuration in fail-closed environment "
            f"(APP_ENV={env!r}): "
            + ", ".join(sorted(cluster3_missing))
        )

    if clerk_host:
        return

    if s.jwt_issuer:
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
                f"Cannot boot in fail-closed environment (APP_ENV={env!r}) when "
                "AUTH_DISABLED is explicitly set. Production and staging require "
                "authentication. Configure CLERK_FAPI_HOST or "
                "JWT_ISSUER/JWT_AUDIENCE/JWKS_URL, or change APP_ENV."
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
    fapi_host = os.getenv("CLERK_FAPI_HOST", "").strip()
    if fapi_host:
        return AuthSettings(
            issuer=f"https://{fapi_host}",
            audience=os.getenv("CLERK_AUDIENCE", ""),
            jwks_url=f"https://{fapi_host}/.well-known/jwks.json",
        )
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

    def get_key(self, jwks_url: str, kid: str | None) -> dict[str, Any]:
        now = time.time()
        if self._jwks is None or now >= self._expires_at:
            self._jwks = self._fetch_jwks(jwks_url)
            self._expires_at = now + JWKS_CACHE_TTL_SECONDS
        return _select_jwk(self._jwks, kid)

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


def _extract_token_with_source(request: Request) -> tuple[str, str]:
    token = getattr(request, "cookies", {}).get(SESSION_COOKIE_NAME)
    if token:
        return token, "cookie"
    auth = getattr(request, "headers", {}).get("Authorization", "")
    scheme, _, token = auth.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip(), "bearer"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session cookie missing",
    )


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


def _validate_clerk_token(token: str, settings: AuthSettings) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(token)
        jwk = _jwks_cache.get_key(settings.jwks_url, header.get("kid"))
        decode_kwargs: dict[str, Any] = {
            "key": jwk,
            "algorithms": ["RS256"],
            "issuer": settings.issuer,
        }
        if settings.audience:
            decode_kwargs["audience"] = settings.audience
        else:
            decode_kwargs["options"] = {"verify_aud": False}
        payload = jwt.decode(token, **decode_kwargs)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    _validate_human_roles_at_jwt_time(payload)
    return payload


def _validate_human_roles_at_jwt_time(payload: dict[str, Any]) -> None:
    # Enforce governance SoD at token-validation time; route helpers repeat the
    # check as defense-in-depth for all runtime dependency paths.
    raw_roles = payload.get("roles") if isinstance(payload, dict) else None
    if not isinstance(raw_roles, list) or any(not isinstance(r, str) for r in raw_roles):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid roles claim",
        )
    if any(r.startswith("service:") for r in raw_roles):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid roles claim",
        )
    roles = {r for r in raw_roles if r in _VALID_HUMAN_ROLES}
    if "auditor" in roles and len(roles) > 1:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid role combination: auditor must be exclusive",
        )


def _get_unverified_issuer(token: str) -> str | None:
    try:
        claims = jwt.get_unverified_claims(token)
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    issuer = claims.get("iss") if isinstance(claims, dict) else None
    return issuer if isinstance(issuer, str) else None


def _validate_service_token(token: str) -> dict[str, Any]:
    issuer = os.getenv("BACKEND_SERVICE_ISSUER", "")
    audience = os.getenv("BACKEND_SERVICE_AUDIENCE", "")
    public_key = os.getenv("SERVICE_JWT_PUBLIC_KEY", "")
    if not (issuer and audience and public_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Service token configuration missing",
        )
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
        )
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from exc
    sub = payload.get("sub") if isinstance(payload, dict) else None
    if sub not in _INTERNAL_SERVICE_IDENTITIES:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service identity",
        )
    if payload.get("roles"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Service identities cannot carry human roles",
        )
    return payload


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

    assert settings is not None
    token, source = _extract_token_with_source(request)
    token_issuer = _get_unverified_issuer(token)
    service_issuer = os.getenv("BACKEND_SERVICE_ISSUER", "")

    if service_issuer and token_issuer == service_issuer:
        if source != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Service token requires bearer transport",
            )
        return _validate_service_token(token)

    if source != "cookie" and os.getenv("CLERK_FAPI_HOST"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session cookie missing",
        )
    return _validate_clerk_token(token, settings)


def mint_service_token(identity: str) -> str:
    expected = identity if identity.startswith("service:") else f"service:{identity}"
    if expected not in _INTERNAL_SERVICE_IDENTITIES:
        raise ValueError(f"Unknown internal service identity: {expected}")

    issuer = os.getenv("BACKEND_SERVICE_ISSUER", "")
    audience = os.getenv("BACKEND_SERVICE_AUDIENCE", "")
    signing_key = os.getenv("SERVICE_JWT_SIGNING_KEY", "")
    if not (issuer and audience and signing_key):
        raise ValueError(
            "Missing service token configuration: BACKEND_SERVICE_ISSUER, "
            "BACKEND_SERVICE_AUDIENCE, and SERVICE_JWT_SIGNING_KEY are required"
        )

    now = int(time.time())
    payload = {
        "sub": expected,
        "iss": issuer,
        "aud": audience,
        "iat": now,
        "exp": now + SERVICE_TOKEN_TTL_SECONDS,
        "nbf": now,
    }
    return jwt.encode(payload, signing_key, algorithm="RS256")


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
        # Auth-disabled local/test fallback is isolated by object identity and
        # by the fail-closed env gate in get_current_user(); signed JWT payloads
        # and copied dicts still go through the normal SoD checks below.
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
