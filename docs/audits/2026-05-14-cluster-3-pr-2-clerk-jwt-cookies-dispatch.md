# Cluster 3 Implementation Dispatch — PR-CL3-2 — Clerk JWT Validation + httpOnly Cookies + Service-Account Issuance

**Cluster:** 3 — Security / Platform (D-3.2 IdP selection + D-3.3 token storage)
**Wave:** PR-CL3-2 (2 of 4)
**Authoring date:** 2026-05-14
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `e3ad0dffb` post-PR #79; this dispatch is self-contained for JWT/cookie/service-token primitives and does not require route-gate changes from PR-CL3-1)
**Required branch:** `audit-followup/cluster-3-clerk-jwt-cookies`
**Source-of-truth:** `docs/governance.md` AUTHORIZATION MATRIX (post-PR #79); Cluster 3 platform decisions (Clerk + httpOnly + dev FAPI provisional)

## 1. Objective

Swap the generic JWKS validator at `backend/app/core/auth.py` for a Clerk-specific JWT validation pipeline + introduce httpOnly session cookies + add CSRF rotation + add service-account JWT issuance helpers (the minting side that PR-CL3-1 only verified consumption of).

Three coupled deliverables:

1. **Clerk JWKS validator** — point JWKS fetch at Clerk's FAPI host (`clerk.<random>.lcl.dev` provisional per Andrei's authorization, with `# TODO(post-cluster-3)` marker for custom domain swap). Validate Clerk-issued session JWTs server-side. Extract roles from Clerk org metadata claim.
2. **httpOnly session cookie management** — replace Bearer token from header with httpOnly + Secure + SameSite=Lax cookie. Cookie set after Clerk session-token exchange at `/auth/session` endpoint, refreshed on each authenticated request, cleared at `/auth/logout`. CSRF token rotation alongside.
3. **Auditor-exclusive validation at JWT-validation time** — per governance.md "Role combinability" subsection ("JWT validator MUST reject mixed sets at validation time, BEFORE any route gate is evaluated"). This wave adds the check inside `get_current_user` for strict compliance with the constitutional wording.
4. **Service-account JWT issuance** — backend mints short-lived (~5min) JWT for the 3 internal-issued identities (westmetall_ingest, rfq_outbound, cashflow_pipeline). Issuer = backend, audience = backend, sub = `service:<name>`. Signing uses `SERVICE_JWT_SIGNING_KEY`; verification uses `SERVICE_JWT_PUBLIC_KEY`.

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`. Matrix landed in PR #79.
- Do **not** change the role list, the per-route gate semantics, the Counterparty per-type authorization, or any anomaly retirement (those landed in PR-CL3-1). This wave is auth-mechanism only — JWT issuer + verification + cookie + service-account minting.
- Do **not** introduce CSP changes, nginx edits, or frontend code changes (PR-CL3-3 + PR-CL3-4 own those; this wave's contract with the frontend is the cookie name/format and CSRF header name).
- Minimal backend CORS adjustment is in scope for this wave: `allow_credentials=True` and `X-CSRF-Token` are required request-transport plumbing for httpOnly cookie + double-submit CSRF. This is not a per-route authorization gate change; all route dependencies and role predicates remain untouched.
- Do **not** add the Clerk custom domain. The dispatch uses dev FAPI host `clerk.<random>.lcl.dev` per Andrei's authorization 2026-05-14. Add `# TODO(post-cluster-3): swap to clerk.<custom-domain>` markers at every config site.
- Do **not** add a migration unless required by service-account key storage (and even then, prefer env-var secrets over DB-stored keys; see §4.4).
- Do **not** delete the existing `_FAIL_CLOSED_ENVS` behavior or the `validate_auth_config` startup gate (Phase A5 J-A5-06 invariant stays).
- Do **not** widen scope into PR-CL3-3 (frontend) or PR-CL3-4 (CSP).

## 3. Findings and Evidence

Verified at HEAD `e3ad0dffb` for the pre-wave baseline. PR-CL3-2 is self-contained for JWT-validation concerns: define `_VALID_HUMAN_ROLES` in `backend/app/core/auth.py` before `get_current_user`. If a later rebase already contains the same constant, reuse it rather than keeping two definitions.

### Existing JWT validator (to be swapped)

- `backend/app/core/auth.py:27-31` — `AuthSettings` dataclass: `jwks_url`, `audience`, `issuer`. Generic IdP-agnostic. Will be parameterized with Clerk values.
- `backend/app/core/auth.py:115-145` — `JWKSCache` with TTL refresh. Reusable as-is for Clerk JWKS endpoint.
- `backend/app/core/auth.py:147-161` — current `_extract_token(request) -> str` reads `Authorization: Bearer <token>`. PR-CL3-2 REPLACES that current signature with a source-aware cookie/service-token extractor.
- `backend/app/core/auth.py:185-224` — `get_current_user` JWKS validation. Issuer + audience must point at Clerk values; everything else stays.

### Auditor-exclusive role validation deliverable

Define the following NEW module-level constant in `backend/app/core/auth.py` before `get_current_user`:

```python
_VALID_HUMAN_ROLES = frozenset({"trader", "risk_manager", "auditor"})
```

This constant is used by the auditor-exclusive JWT-time validation rule in §4.4. It is part of PR-CL3-2 scope because governance requires mixed auditor roles to be rejected by the JWT validator before any route gate dependency runs.

### Clerk session JWT shape (per Clerk docs)

Clerk session JWTs have the following claims of interest:
- `sub` — Clerk user ID (e.g. `user_2abc...`); becomes our actor_sub.
- `org_role` or `public_metadata.roles` — depends on Clerk dashboard config. The role array MUST be configured in Clerk dashboard to live at a stable claim path. Recommended: set up Clerk to inject `roles: ["trader" | "risk_manager" | "auditor"]` array into the session JWT via Clerk's "session token" customization.
- `iat`, `exp`, `iss`, `aud`, `azp` — standard.
- `nbf` — not-before claim.

Backend MUST validate `iss` matches the FAPI host and `aud` matches the configured Clerk app instance.

### Existing cookie infrastructure

- `backend/app/main.py` — FastAPI app instance. Will need a Set-Cookie middleware OR explicit cookie set on auth responses.
- No existing CSRF middleware. PR-CL3-2 introduces double-submit token pattern.

### Service-account minting requirements

- 3 internal-issued identities per governance.md: westmetall_ingest, rfq_outbound, cashflow_pipeline.
- Each needs short-lived (~5min) JWT issued by backend, signed with `SERVICE_JWT_SIGNING_KEY` and verified by the matching `SERVICE_JWT_PUBLIC_KEY`.
- The minting helpers are CLI-callable (for cron triggering westmetall_ingest, for worker startup of rfq_outbound + cashflow_pipeline).

## 4. Required Implementation Boundary

### 4.1 Clerk JWT validation swap

Refactor `backend/app/core/auth.py`. Keep the existing `AuthSettings` dataclass shape (`jwks_url`, `audience`, `issuer`) and derive the Clerk FAPI host locally from `CLERK_FAPI_HOST` when building those values. Do not add a fourth dataclass field in this wave.

```python
@dataclass
class AuthSettings:
    jwks_url: str  # https://<clerk-fapi-host>/.well-known/jwks.json
    audience: str  # Clerk app instance ID (or empty string if Clerk omits aud)
    issuer: str    # https://<clerk-fapi-host>


def get_auth_settings() -> AuthSettings | None:
    if not _auth_enabled():
        return None
    fapi_host = os.environ["CLERK_FAPI_HOST"]
    return AuthSettings(
        jwks_url=f"https://{fapi_host}/.well-known/jwks.json",
        audience=os.environ.get("CLERK_AUDIENCE", ""),
        issuer=f"https://{fapi_host}",
    )


def _validate_clerk_token(token: str, settings: AuthSettings) -> dict[str, Any]:
    header = jwt.get_unverified_header(token)
    jwk = jwks_cache.get_key(settings.jwks_url, header["kid"])
    decode_kwargs: dict[str, Any] = {
        "key": jwk,
        "algorithms": ["RS256"],
        "issuer": settings.issuer,
    }
    if settings.audience:
        decode_kwargs["audience"] = settings.audience
    else:
        decode_kwargs["options"] = {"verify_aud": False}
    return jwt.decode(token, **decode_kwargs)
```

Env vars introduced:
- `CLERK_FAPI_HOST` (mandatory) — e.g. `clerk.abcdef.lcl.dev` in dev. Production: swap to custom domain post-Cluster-3.
- `CLERK_AUDIENCE` (mandatory in fail-closed environments; may remain empty only when auth is disabled outside `_FAIL_CLOSED_ENVS`).

Update `validate_auth_config` to verify `CLERK_FAPI_HOST` is set in `_FAIL_CLOSED_ENVS`.

### 4.2 Cookie-based session

Add the following NEW module constants to `backend/app/core/auth.py`, then replace the current `_extract_token(request) -> str` helper with the NEW `_extract_token_with_source(request) -> tuple[str, str]` helper. After this change, `get_current_user` must be the only token-extraction call site and must use `_extract_token_with_source`; delete the old `_extract_token` helper.

```python
SESSION_COOKIE_NAME = "__Session"  # Clerk-style; opaque to frontend
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

def _extract_token_with_source(request: Request) -> tuple[str, str]:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        return token, "cookie"
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth.removeprefix("Bearer ").strip(), "bearer"
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Session cookie missing",
    )
```

The Bearer fallback is service-token transport only. `_extract_token_with_source` accepts Bearer syntactically, but `get_current_user` MUST use the returned source to reject Clerk-issued human tokens delivered by Bearer and accept backend-issued service tokens delivered by Bearer. This keeps cron/worker callers (Westmetall, RFQ outbound, cashflow pipeline) on Bearer transport without reopening human Clerk Bearer auth.

Mandatory integration point in `backend/app/core/auth.py`: update `get_current_user` to call `token, source = _extract_token_with_source(request)` exactly as shown in the full §4.6 function body. The old `token = _extract_token(request)` line must not remain.

Create new file `backend/app/api/routes/auth.py` as a new route module with these routes: `POST /auth/session`, `POST /auth/refresh`, `POST /auth/logout`, and `GET /auth/me`.

Complete file template:

```python
import secrets
from typing import Any

from fastapi import APIRouter, Body, Depends, Request, Response

from app.core.auth import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    _FAIL_CLOSED_ENVS,
    get_current_user,
    _canonical_env,
    _validate_clerk_token,
)

router = APIRouter(tags=["auth"])


def _set_auth_cookies(response: Response, session_token: str, csrf: str) -> None:
    secure = _canonical_env() in _FAIL_CLOSED_ENVS
    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        secure=secure,  # always True in prod
        samesite="lax",
        max_age=300,  # match Clerk session TTL
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf,
        httponly=False,  # frontend reads this to echo back in X-CSRF-Token header
        secure=secure,
        samesite="lax",
        max_age=300,
        path="/",
    )


@router.post("/auth/session")
async def create_session(
    request: Request,
    session_token: str = Body(..., embed=True),  # Clerk session token from frontend SDK
    response: Response,
) -> dict[str, str]:
    """Exchange Clerk session token for httpOnly cookie.

    The frontend SDK (PR-CL3-3) calls this after Clerk authentication
    completes. Backend validates the token, sets httpOnly cookie,
    and returns a fresh CSRF token for double-submit.
    """
    # Validate the Clerk session token (same JWKS validation as get_current_user)
    payload = _validate_clerk_token(session_token)

    # Mint a CSRF token (cryptographically random, returned in body + cookie)
    csrf = secrets.token_urlsafe(32)
    _set_auth_cookies(response, session_token, csrf)
    return {"actor_sub": payload["sub"], "csrf_token": csrf}


@router.post("/auth/refresh")
async def refresh_session(
    request: Request,
    session_token: str = Body(..., embed=True),  # fresh Clerk session token from frontend SDK
    response: Response,
) -> dict[str, str]:
    """Refresh httpOnly cookie + CSRF token using a fresh Clerk JWT."""
    payload = _validate_clerk_token(session_token)
    csrf = secrets.token_urlsafe(32)
    _set_auth_cookies(response, session_token, csrf)
    return {"actor_sub": payload["sub"], "csrf_token": csrf}


@router.post("/auth/logout")
async def logout(response: Response) -> dict[str, str]:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    response.delete_cookie(CSRF_COOKIE_NAME, path="/")
    return {"status": "logged_out"}


@router.get("/auth/me")
async def read_current_identity(
    user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    return {"actor_sub": user["sub"], "roles": user.get("roles", [])}
```

Register the new route module in `backend/app/main.py`:

```python
from app.api.routes import auth

app.include_router(auth.router)
```

### 4.3 CSRF middleware

Create new file `backend/app/core/csrf.py` with the following complete module template:

```python
import secrets

from fastapi import Request, status
from fastapi.responses import JSONResponse

from app.core.auth import CSRF_COOKIE_NAME, CSRF_HEADER_NAME


async def csrf_middleware(request: Request, call_next):
    """Double-submit CSRF token check on mutating methods.

    Frontend reads csrf_token cookie (non-httpOnly) and echoes it in
    X-CSRF-Token header on every POST/PATCH/PUT/DELETE. Backend validates
    cookie value == header value.

    Exempt: /auth/session (initial cookie set), /webhooks/* (provider HMAC),
    /healthz (no auth).
    """
    if request.method not in ("POST", "PATCH", "PUT", "DELETE"):
        return await call_next(request)
    if request.url.path.startswith(("/auth/session", "/webhooks/", "/healthz")):
        return await call_next(request)

    cookie = request.cookies.get(CSRF_COOKIE_NAME)
    header = request.headers.get(CSRF_HEADER_NAME)
    if not cookie or not header or not secrets.compare_digest(cookie, header):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "CSRF token missing or mismatch"},
        )
    return await call_next(request)
```

In `backend/app/main.py`, import `BaseHTTPMiddleware` and `csrf_middleware`, then register the CSRF middleware after existing middleware setup and before route handling:

```python
app.add_middleware(BaseHTTPMiddleware, dispatch=csrf_middleware)
```

Update `CORSMiddleware` for the split frontend/backend deployment used by `VITE_API_BASE_URL`. Current `backend/app/main.py` has `allow_credentials=False`; that must change because httpOnly cookie auth cannot work cross-origin unless the browser is allowed to attach cookies to API requests:

- `allow_credentials=True`
- allowed headers include `X-CSRF-Token`
- allowed origins include the deployed frontend origin(s); do not use `allow_origins=["*"]` with credentials.

This is required because PR-CL3-3 sends `credentials: "include"` and `X-CSRF-Token` cross-origin from the static frontend.

### 4.4 Auditor-exclusive validation duplicated at JWT-validation time

Per governance "Role combinability": validation MUST happen at JWT-validation time, before any route-gate dependency evaluates. For strict constitutional compliance, add the check inside the Clerk-human branch of `get_current_user` after `_validate_clerk_token` succeeds. Do not run this check against backend service JWTs.

Always define `_VALID_HUMAN_ROLES` in this PR and add the auditor-exclusive check to the Clerk validation path in `get_current_user`. Do not add route-gate helpers in this wave.

```python
_VALID_HUMAN_ROLES = frozenset({"trader", "risk_manager", "auditor"})


def get_current_user(...) -> dict[str, Any]:
    # ... service-token branch has already returned before this block ...

    payload = jwt.decode(token, jwk, algorithms=["RS256"], audience=..., issuer=...)

    # Auditor-exclusive role combinability check (governance §"Role combinability")
    raw_roles = payload.get("roles") if isinstance(payload, dict) else None
    if not isinstance(raw_roles, list) or any(not isinstance(r, str) for r in raw_roles):
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

    return payload
```

This JWT-time check is the sole required enforcement in PR-CL3-2; route-gate helper changes remain outside this wave.

Malformed human role claims fail closed before any role set construction: missing, scalar, object, null, or list-with-non-string `roles` values MUST raise `HTTPException(401, detail="Invalid roles claim")`. Service tokens are validated on the service branch and do not use Clerk human role claims.

### 4.5 Service-account JWT minting

Add the following NEW service-token constants and minting function to `backend/app/core/auth.py`:

```python
SERVICE_TOKEN_TTL_SECONDS = 300  # 5 min per governance "TTL ~5min"
_INTERNAL_SERVICE_IDENTITIES = frozenset({
    "service:westmetall_ingest",
    "service:rfq_outbound",
    "service:cashflow_pipeline",
})


def mint_service_token(identity: str) -> str:
    """Mint a short-lived JWT for an internal-issued service identity.

    Used by:
    - Westmetall ingest cron entrypoint (mints `service:westmetall_ingest`)
    - RFQ outbound worker startup (mints `service:rfq_outbound`)
    - Cashflow pipeline worker startup (mints `service:cashflow_pipeline`)

    Signing key: SERVICE_JWT_SIGNING_KEY env var (RSA private key PEM).
    Verification: SERVICE_JWT_PUBLIC_KEY env var (public key PEM).
    """
    expected = identity if identity.startswith("service:") else f"service:{identity}"
    if expected not in _INTERNAL_SERVICE_IDENTITIES:
        raise ValueError(f"Unknown internal service identity: {expected}")

    now = int(time.time())
    payload = {
        "sub": expected,
        "iss": os.environ["BACKEND_SERVICE_ISSUER"],  # e.g. "https://api.<domain>"
        "aud": os.environ["BACKEND_SERVICE_AUDIENCE"],  # e.g. "internal-services"
        "iat": now,
        "exp": now + SERVICE_TOKEN_TTL_SECONDS,
        "nbf": now,
    }
    private_key = os.environ["SERVICE_JWT_SIGNING_KEY"]
    return jwt.encode(payload, private_key, algorithm="RS256")
```

Create new file `backend/scripts/mint_service_token.py` as the CLI entrypoint:

```python
#!/usr/bin/env python3
"""Mint a service-account JWT for cron/worker startup.

Usage:
    python -m backend.scripts.mint_service_token --identity westmetall_ingest

Output: token to stdout. Caller is responsible for piping into the
target process's environment (e.g. WESTMETALL_INGEST_TOKEN env var).
"""
```

### 4.6 Service-account verification for service-identity gates

PR-CL3-1 owns the route-gate helper shape for service identities. PR-CL3-2 does not add or modify route-gate helpers; it adds the JWT verification flow those gates consume. When `get_current_user` validates a token whose `iss` matches the backend's own service issuer (not Clerk), it MUST validate against the backend service public key, not Clerk's JWKS, and return a payload with `sub="service:<identity>"`.

Implementation: inspect the `iss` claim from the unverified payload to route to the right validator before signature verification. This routing point is also where the cookie-only transport rule for Clerk human sessions is enforced.

```python
def _validate_service_token(token: str) -> dict[str, Any]:
    public_key = os.environ["SERVICE_JWT_PUBLIC_KEY"]
    # python-jose[cryptography] accepts PEM-formatted RSA public keys here.
    return jwt.decode(
        token,
        public_key,
        algorithms=["RS256"],
        audience=os.environ["BACKEND_SERVICE_AUDIENCE"],
        issuer=os.environ["BACKEND_SERVICE_ISSUER"],
    )


def get_current_user(
    request: Request,
    settings: AuthSettings | None = Depends(get_auth_settings),
) -> dict[str, Any]:
    if settings is None:
        raise HTTPException(status_code=401, detail="Authentication disabled")

    token, source = _extract_token_with_source(request)
    unverified = jwt.decode(token, options={"verify_signature": False})
    issuer = unverified.get("iss", "")

    if issuer == os.environ["BACKEND_SERVICE_ISSUER"]:
        if source != "bearer":
            raise HTTPException(status_code=401, detail="Service token must use Bearer transport")
        return _validate_service_token(token)
    if source == "bearer":
        raise HTTPException(status_code=401, detail="Session cookie missing")
    payload = _validate_clerk_token(token, settings)

    raw_roles = payload.get("roles") if isinstance(payload, dict) else None
    if not isinstance(raw_roles, list) or any(not isinstance(r, str) for r in raw_roles):
        raise HTTPException(status_code=401, detail="Invalid roles claim")
    roles = {r for r in raw_roles if r in _VALID_HUMAN_ROLES}
    if "auditor" in roles and len(roles) > 1:
        raise HTTPException(
            status_code=401,
            detail="Invalid role combination: auditor must be exclusive",
        )
    return payload
```

This is the only accepted validator routing strategy for this wave: single code path per token type, with transport-source enforcement before Clerk validation.

For PR-CL3-2 simplicity, load the backend service public key from `SERVICE_JWT_PUBLIC_KEY` (public key PEM) and skip a service JWKS endpoint until a later distributed-deploy hardening wave if needed.

### 4.7 Production fail-closed extensions

`validate_auth_config` MUST verify in `_FAIL_CLOSED_ENVS`:
- `CLERK_FAPI_HOST` is set
- `CLERK_AUDIENCE` is set
- `SERVICE_JWT_SIGNING_KEY` is set
- `SERVICE_JWT_PUBLIC_KEY` is set
- `BACKEND_SERVICE_ISSUER` is set
- `BACKEND_SERVICE_AUDIENCE` is set

Missing any → fail-closed at startup (raise `RuntimeError`).

Do not replace the existing `validate_auth_config()` wholesale. Preserve the current J-A5-06 docstring, behavior matrix, `_auth_explicitly_disabled()` / `AUTH_DISABLED` guard, and existing `JWT_ISSUER`/`JWT_AUDIENCE`/`JWKS_URL` startup checks. Add the Cluster 3 checks as an incremental block inside the existing function after the current fail-closed/auth-disabled checks:

```python
# inside existing validate_auth_config(), after the current J-A5-06 checks
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
            "Missing required auth configuration in fail-closed environment: "
            + ", ".join(sorted(cluster3_missing))
    )
```

Cookie domain policy: do not set a broad `Domain=` attribute by default. The backend API origin sets these cookies and browsers will send host-only cookies back to that API origin when frontend requests use `credentials: "include"`. If deployment later requires sharing across sibling subdomains, add an explicit audited `COOKIE_DOMAIN` setting in a separate hardening PR.

## 5. Constitutional Rules

- `docs/governance.md` AUTHORIZATION MATRIX > Service identities subsection — distinguishes internal-issued (JWT signed by backend) from external-ingress (provider auth). PR-CL3-2 implements the JWT issuance for the 3 internal identities; webhook_inbound stays as-is.
- `docs/governance.md` AUTHORIZATION MATRIX > Role combinability — auditor exclusive at JWT validation time.
- `docs/governance.md` §"GOVERNANCE HARD FAILS" — startup fail-closed if config missing.

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes D-3.2 + D-3.3 (token storage portion) iff every item below is true.

### 6.1 Clerk JWT validation

- [ ] `backend/app/core/auth.py` — `AuthSettings` remains the existing 3-field dataclass; `get_auth_settings` reads `CLERK_FAPI_HOST` and derives `jwks_url` + `issuer` from it.
- [ ] JWKS URL points at `https://<fapi_host>/.well-known/jwks.json`.
- [ ] `iss` and `aud` match Clerk values.
- [ ] `# TODO(post-cluster-3): swap to clerk.<custom-domain>` marker present at every site that hardcodes the dev FAPI host.

### 6.2 httpOnly cookie

- [ ] `backend/app/api/routes/auth.py` — `/auth/session`, `/auth/refresh`, `/auth/logout` exist with the signatures in §4.2.
- [ ] `backend/app/api/routes/auth.py` — `/auth/me` exists and returns `{actor_sub, roles}` for frontend hydration.
- [ ] Cookie set with `httponly=True`, `secure=True` in fail-closed envs, `samesite="lax"`, `max_age=300`, `path="/"`.
- [ ] CSRF cookie set with `httponly=False` (frontend reads it).
- [ ] Human Clerk sessions read from cookie, NOT from Bearer header; Clerk JWTs delivered by Bearer are rejected in `get_current_user` before `_validate_clerk_token`.
- [ ] Backend service JWTs retain Bearer transport through the source-aware extractor and service issuer branch; service JWTs delivered by cookie are rejected.
- [ ] Old `_extract_token(request) -> str` helper is deleted or has zero call sites; human paths use `_extract_token_with_source` only.

### 6.3 CSRF middleware

- [ ] `backend/app/core/csrf.py` exists with the double-submit middleware in §4.3.
- [ ] Middleware registered in `backend/app/main.py`.
- [ ] Exempt paths: `/auth/session`, `/webhooks/`, `/healthz`.
- [ ] CSRF mismatch returns 403 with `detail="CSRF token missing or mismatch"`.
- [ ] `CORSMiddleware` allows credentialed frontend requests (`allow_credentials=True`) and includes `X-CSRF-Token` in allowed headers.

### 6.4 Auditor-exclusive at JWT-validation time

- [ ] `get_current_user` raises HTTP 401 with `detail="Invalid role combination: auditor must be exclusive"` when JWT payload has both auditor and another role.
- [ ] `_VALID_HUMAN_ROLES` exists for JWT-time validation in `backend/app/core/auth.py`.

### 6.5 Service-account minting

- [ ] `mint_service_token(identity)` exists in `backend/app/core/auth.py` with the signature in §4.5.
- [ ] Returns RS256 JWT with `sub=service:<identity>`, `iss=BACKEND_SERVICE_ISSUER`, `aud=BACKEND_SERVICE_AUDIENCE`, `exp=now+300`.
- [ ] `backend/scripts/mint_service_token.py` CLI entrypoint exists.
- [ ] `get_current_user` routes to service-token validator when `iss` matches `BACKEND_SERVICE_ISSUER`.

### 6.6 Production fail-closed

- [ ] `validate_auth_config` raises if any of `CLERK_FAPI_HOST`, `SERVICE_JWT_SIGNING_KEY`, `SERVICE_JWT_PUBLIC_KEY`, `BACKEND_SERVICE_ISSUER`, `BACKEND_SERVICE_AUDIENCE` missing in `_FAIL_CLOSED_ENVS`.
- [ ] Phase A5 J-A5-06 invariant preserved: anonymous access rejected in production at request-time too.

### 6.7 Cross-cutting

- [ ] `docs/governance.md` diff is empty.
- [ ] No frontend file changed (`git diff main -- frontend-svelte/` empty).
- [ ] No nginx config changed.
- [ ] No new alembic migration. Single head remains `044_drop_deal_lifecycle_fields`.
- [ ] Per-route gates (PR-CL3-1 territory) UNCHANGED (`git diff main -- backend/app/api/routes/counterparties.py backend/app/api/routes/rfqs.py backend/app/api/routes/contracts.py backend/app/api/routes/deals.py backend/app/api/routes/linkages.py backend/app/api/routes/westmetall.py` — diffs only on signature changes if cookie passed differently, NOT on role gates).

## 7. Required Tests

### 7.1 New file `backend/tests/test_clerk_jwt_validation.py`

- **`test_clerk_jwt_valid_returns_user`** — fixture: signed JWT with valid Clerk-shape claims (sub, iss, aud, roles). Returns user dict.
- **`test_clerk_jwt_invalid_signature_401`** — fixture: JWT signed with wrong key. Returns 401.
- **`test_clerk_jwt_expired_401`** — fixture: JWT with `exp` in past.
- **`test_clerk_jwt_wrong_audience_401`** — fixture: JWT with `aud` mismatch.
- **`test_clerk_jwt_wrong_issuer_401`** — fixture: JWT with `iss` mismatch.
- **`test_clerk_jwt_auditor_exclusive_401`** — fixture: JWT with `roles=["auditor", "trader"]`. Returns 401 at JWT validation (NOT at route gate).
- **`test_clerk_jwt_auditor_alone_passes`** — fixture: JWT with `roles=["auditor"]`. Returns user dict (no 401).
- **`test_clerk_jwt_trader_plus_risk_manager_passes`** — fixture: JWT with `roles=["trader", "risk_manager"]`. Returns user dict.
- **`test_clerk_jwt_malformed_roles_claim_401`** — fixtures with missing, scalar, object, null, and list-with-non-string `roles`; each returns 401 with `detail="Invalid roles claim"`.

### 7.2 New file `backend/tests/test_cookie_session.py`

- **`test_session_endpoint_sets_httponly_cookie`** — POST `/auth/session` with valid Clerk session token. Assert `Set-Cookie` header includes `__Session=...` with `HttpOnly`, `Secure` (in prod env), `SameSite=Lax`, `Path=/`, `Max-Age=300`.
- **`test_session_endpoint_returns_csrf_token_in_body_and_cookie`** — same. Assert response body has `csrf_token`, and Set-Cookie has `csrf_token=...` with `HttpOnly` NOT set.
- **`test_authenticated_request_uses_cookie_not_bearer`** — call any auth-required endpoint with cookie, no Authorization header. Returns 200.
- **`test_authenticated_human_bearer_only_401`** — call any human auth-required endpoint with Clerk Bearer header but no cookie. Returns 401 with `detail="Session cookie missing"`.
- **`test_get_current_user_uses_source_aware_extractor`** — assert the old `_extract_token` helper is not called by human auth paths and `get_current_user` destructures `(token, source)` from `_extract_token_with_source`.
- **`test_logout_clears_cookies`** — POST `/auth/logout`. Assert Set-Cookie header sets both cookies to expired (Max-Age=0 or similar).
- **`test_refresh_reexchanges_fresh_clerk_token_and_rotates_csrf`** — POST `/auth/refresh` with a fresh Clerk session token. Assert session cookie is reset and new `csrf_token` differs from prior.
- **`test_auth_me_returns_actor_and_roles`** — GET `/auth/me` with valid session cookie. Assert response has `actor_sub` and `roles`.

### 7.3 New file `backend/tests/test_csrf_middleware.py`

- **`test_csrf_middleware_get_passes_without_token`** — GET endpoint, no CSRF token. Returns 200.
- **`test_csrf_middleware_post_missing_token_403`** — POST endpoint, no CSRF cookie. Returns 403 with `detail="CSRF token missing or mismatch"`.
- **`test_csrf_middleware_post_mismatch_403`** — POST endpoint, cookie value != header value. Returns 403.
- **`test_csrf_middleware_post_match_passes`** — POST endpoint, cookie value == header value. Returns 200.
- **`test_csrf_middleware_session_endpoint_exempt`** — POST `/auth/session` without CSRF token. Returns 200 (exempt).
- **`test_csrf_middleware_webhook_exempt`** — POST `/webhooks/whatsapp` with HMAC but no CSRF. Returns 200 (exempt).
- **`test_cors_allows_credentials_and_csrf_header`** — OPTIONS preflight from allowed frontend origin with `X-CSRF-Token`; assert credentialed CORS response permits it.

### 7.4 New file `backend/tests/test_service_token_minting.py`

- **`test_mint_service_token_westmetall`** — `mint_service_token("westmetall_ingest")` returns RS256 JWT. Decode and assert `sub == "service:westmetall_ingest"`, `exp == now+300`.
- **`test_mint_service_token_rfq_outbound`** — `mint_service_token("rfq_outbound")` returns RS256 JWT with `sub == "service:rfq_outbound"`.
- **`test_mint_service_token_cashflow_pipeline`** — `mint_service_token("cashflow_pipeline")` returns RS256 JWT with `sub == "service:cashflow_pipeline"`.
- **`test_mint_service_token_unknown_raises`** — `mint_service_token("not_a_real_identity")` raises ValueError.
- **`test_get_current_user_routes_service_token_to_service_validator`** — fixture: service-minted Bearer JWT. `get_current_user` returns payload with `sub="service:westmetall_ingest"`.
- **`test_service_token_with_clerk_issuer_401`** — fixture: JWT signed with service key but `iss=clerk-fapi`. Returns 401.

### 7.5 Existing test fixture migration

- Human-user test fixtures that mock `Authorization: Bearer ...` headers MUST be updated to set the `__Session` cookie instead. Service-token fixtures remain Bearer JWTs and must use the service-token helper, not cookies.
- Add a targeted grep assertion in the PR notes: `rg -nP "def _extract_token\\(" backend/app/core/auth.py` returns no matches after migration.

### 7.6 Production fail-closed

- **`test_validate_auth_config_missing_clerk_host_fails_closed`** — set env to production, unset CLERK_FAPI_HOST. `validate_auth_config()` raises RuntimeError.
- **`test_validate_auth_config_missing_service_keys_fails_closed`** — same, with each of the 4 service env vars unset individually.

## 8. Required Verification

```powershell
# Helper surface
rg -nP "def mint_service_token|def _validate_clerk_token|def _validate_service_token" backend/app/core/auth.py
rg -nP "SESSION_COOKIE_NAME|CSRF_COOKIE_NAME|CSRF_HEADER_NAME" backend/app/core/auth.py backend/app/core/csrf.py

# Bearer transport split
rg -nP "SESSION_COOKIE_NAME|request\\.cookies" backend/app/core/auth.py
rg -nP "Authorization.*Bearer|request\\.headers\\.get\\(['\"]authorization" backend/app/core/auth.py
rg -nP "def _extract_token\\(" backend/app/core/auth.py  # expect no matches; source-aware helper replaced it
# verify matches are service-token-only; no human Clerk Bearer fallback remains

# Clerk env vars
rg -nP "CLERK_FAPI_HOST|CLERK_AUDIENCE|SERVICE_JWT_SIGNING_KEY|BACKEND_SERVICE_ISSUER" backend/app/core/auth.py

# TODO markers for custom-domain swap
rg -nP "TODO\\(post-cluster-3\\)" backend/app/core/auth.py

# CSRF middleware registered
rg -nP "csrf_middleware|BaseHTTPMiddleware" backend/app/main.py

# Credentialed CORS for static frontend origin
rg -nP "allow_credentials=True|X-CSRF-Token" backend/app/main.py

# Per-route gates UNCHANGED (PR-CL3-1 territory)
git diff main -- backend/app/api/routes/counterparties.py backend/app/api/routes/rfqs.py backend/app/api/routes/contracts.py backend/app/api/routes/deals.py backend/app/api/routes/linkages.py
# (acceptable: only changes are if function signatures absorb cookie-dependency, not role gates)

# Cross-wave isolation
git diff main -- frontend-svelte/
git diff main -- frontend-svelte/nginx.conf
git diff main -- docs/governance.md

# Alembic invariant
cd backend ; python -m alembic heads ; cd ..

# Test suites
pytest -q backend/tests/test_clerk_jwt_validation.py
pytest -q backend/tests/test_cookie_session.py
pytest -q backend/tests/test_csrf_middleware.py
pytest -q backend/tests/test_service_token_minting.py
pytest -q backend/tests
```

`docs/governance.md` diff MUST be empty. Frontend + nginx diffs MUST be empty. Alembic head MUST be `044_drop_deal_lifecycle_fields`.

## 9. Out of Scope

- PR-CL3-1 territory: per-route role gates, Counterparty per-type authorization, anomaly retirement (already landed).
- PR-CL3-3 territory: frontend Clerk SDK integration, kill manualTokenLoginEnabled, frontend cookie reading.
- PR-CL3-4 territory: nginx CSP, violation reporter, XSS-sink doc.
- Custom domain Clerk setup (swap from dev FAPI to clerk.<custom-domain>) — TODO post-Cluster-3.
- Service-account JWKS endpoint (`/api/.well-known/service-jwks.json`). PR-CL3-2 uses env var `SERVICE_JWT_PUBLIC_KEY` instead. Endpoint can land in a follow-up if needed for distributed deploys.
- Multi-region Clerk failover, multi-tenant Clerk app config.
- Frontend session-refresh polling (PR-CL3-3).

## 10. PR Requirements

Title:
```
fix(audit-followup): close Cluster 3 PR-CL3-2 (Clerk JWT + httpOnly cookies + CSRF + service-account minting)
```

PR body must include:
- **Findings closed:** D-3.2 + D-3.3 (token storage portion) references.
- **Files changed:** inventory grouped by core auth / cookie endpoints / CSRF middleware / service minting / tests.
- **Env vars added:** CLERK_FAPI_HOST, CLERK_AUDIENCE, SERVICE_JWT_SIGNING_KEY, SERVICE_JWT_PUBLIC_KEY, BACKEND_SERVICE_ISSUER, BACKEND_SERVICE_AUDIENCE. Document each + production-required marker.
- **TODO markers landed:** every `TODO(post-cluster-3): swap to clerk.<custom-domain>` site cited.
- **Bearer→Cookie migration:** explicit statement that human Clerk Authorization Bearer fallback was removed, while service-token Bearer transport remains; test fixture migration done.
- **Service-account JWKS endpoint:** explicit statement that endpoint NOT added (env-var public key used instead); follow-up flag if distributed deploy needs it.
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-3-clerk-jwt-cookies-{sha}.json` per push.
- **Governance + alembic statements:** diffs empty.

## 11. Workflow

1. **Pre-step:** confirm the base branch and ensure `_VALID_HUMAN_ROLES` exists in `backend/app/core/auth.py`; add the JWT-time auditor-exclusive check to `get_current_user` in this PR regardless of route-gate state.
2. `git checkout -b audit-followup/cluster-3-clerk-jwt-cookies`.
3. Provision dev Clerk project: get `CLERK_FAPI_HOST` value (e.g. `clerk.abcdef12.lcl.dev`), set in `.env.example` and local dev.
4. Apply §4.1 (Clerk JWKS swap). Run `pytest -q backend/tests/test_clerk_jwt_validation.py` (write tests first).
5. Apply §4.2 (cookie endpoints + `_extract_token` swap). Run §7.2 tests + migrate any test fixture broken by Bearer→cookie.
6. Apply §4.3 (CSRF middleware). Run §7.3 tests.
7. Apply §4.4 (auditor-exclusive earlier).
8. Apply §4.5 + §4.6 (service-account minting + verification routing). Run §7.4 tests.
9. Apply §4.7 (fail-closed extensions). Run §7.6 tests.
10. Migrate test fixtures (§7.5) — central conftest update.
11. Run §8 verification locally; fix every hook v2 P1/P2.
12. Push branch, open PR per §10.
13. Codex Connector review is the final gate. **Do not merge** — Andrei merges with explicit authorization.

## 12. Hook v2 + Codex calibration notes

- **Expected hook v2 surface area:** large (auth.py rewrite + new auth routes + CSRF middleware + service minting + ~26 new tests + fixture migration). Hook may flag high churn in `auth.py` — treat as expected, not as a P1.
- **Expected Codex catches:**
  - **Cookie security flag completeness** — every `set_cookie` call MUST include all 5 flags (httponly, secure, samesite, max_age, path). Missing any → Codex catch.
  - **CSRF middleware exempt list completeness** — `/auth/session`, `/webhooks/`, `/healthz` MUST all be exempt. Missing `/healthz` → frontend can't probe liveness without CSRF.
  - **Bearer→cookie test fixture migration** — every test that hardcoded `headers={"Authorization": "Bearer ..."}` MUST be migrated. Codex will inspect test files and flag any survivor.
  - **Service-token issuer routing** — if `get_current_user` doesn't inspect `iss` to route to right validator, both Clerk and service tokens may collide / mis-validate. Codex will trace the validator routing.
  - **Auditor-exclusive JWT-time check** — PR-CL3-2 adds the check to `get_current_user` because governance says the validator must reject mixed auditor roles "BEFORE any route gate".
  - **`secrets.compare_digest`** — CSRF cookie/header comparison MUST use constant-time comparison. Codex will flag a `==` fallback as a timing oracle.
  - **`# TODO(post-cluster-3)` markers** — every site that hardcodes dev FAPI host MUST have the marker; missing marker → Codex catches as "tech debt without trail".
  - **Production fail-closed env coverage** — every new env var MUST be in `validate_auth_config`'s required list. Codex will trace each.
  - **`SameSite=Lax` justification** — Lax allows top-level cross-site GETs. If frontend is cross-origin with backend, may need `Strict` or `None+Secure`. PR body should document the choice.
  - **CLERK_AUDIENCE fail-closed requirement** — in fail-closed environments `CLERK_AUDIENCE` MUST be set and validated; outside fail-closed environments it may remain empty only when auth is disabled.
- **Padrão PR #79:** governance docs receive intense scrutiny; the IMPLEMENTATION PR will be checked against governance text rigorously. The Service identities split (internal-issued vs external-ingress, per-method webhook auth) is now constitutional — Codex will verify the implementation matches.
- **8-section sweep:** §4 boundary, §6 acceptance, §7 tests, §8 verification, §11 workflow MUST consistently enumerate the same 6 deliverables (Clerk JWKS, cookie endpoints, CSRF middleware, auditor-early-validation, service minting, fail-closed). Drift between sections is the canonical authoring failure mode.
- **The largest implementation risk** is the Bearer→cookie fixture migration. ~All existing auth-required tests will need updates simultaneously. Mitigation: write the central conftest helper FIRST, then sweep `rg -nP 'Authorization.*Bearer' backend/tests/` and migrate every site through the helper before running the full suite.
