# Cluster 3 Implementation Dispatch — PR-CL3-2 — Clerk JWT Validation + httpOnly Cookies + Service-Account Issuance

**Cluster:** 3 — Security / Platform (D-3.2 IdP selection + D-3.3 token storage)
**Wave:** PR-CL3-2 (2 of 4)
**Authoring date:** 2026-05-14
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `e3ad0dffb` post-PR #79; assume PR-CL3-1 has merged before this wave starts — see §11)
**Required branch:** `audit-followup/cluster-3-clerk-jwt-cookies`
**Source-of-truth:** `docs/governance.md` AUTHORIZATION MATRIX (post-PR #79); Cluster 3 platform decisions (Clerk + httpOnly + dev FAPI provisional)

## 1. Objective

Swap the generic JWKS validator at `backend/app/core/auth.py` for a Clerk-specific JWT validation pipeline + introduce httpOnly session cookies + add CSRF rotation + add service-account JWT issuance helpers (the minting side that PR-CL3-1 only verified consumption of).

Three coupled deliverables:

1. **Clerk JWKS validator** — point JWKS fetch at Clerk's FAPI host (`clerk.<random>.lcl.dev` provisional per Andrei's authorization, with `# TODO(post-cluster-3)` marker for custom domain swap). Validate Clerk-issued session JWTs server-side. Extract roles from Clerk org metadata claim.
2. **httpOnly session cookie management** — replace Bearer token from header with httpOnly + Secure + SameSite=Lax cookie. Cookie set after Clerk session-token exchange at `/auth/session` endpoint, refreshed on each authenticated request, cleared at `/auth/logout`. CSRF token rotation alongside.
3. **Auditor-exclusive validation duplicated at JWT-validation time** — per governance.md "Role combinability" subsection ("JWT validator MUST reject mixed sets at validation time, BEFORE any route gate is evaluated"). PR-CL3-1 keeps the defensive check inside `get_current_actor_roles`; this wave adds the same check earlier inside `get_current_user` for strict compliance with the constitutional wording.
4. **Service-account JWT issuance** — backend mints short-lived (~5min) JWT for the 3 internal-issued identities (westmetall_ingest, rfq_outbound, cashflow_pipeline). Issuer = backend, audience = backend, sub = `service:<name>`. Same signing key as the JWKS that backend serves to itself.

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`. Matrix landed in PR #79.
- Do **not** change the role list, the per-route gate semantics, the Counterparty per-type authorization, or any anomaly retirement (those landed in PR-CL3-1). This wave is auth-mechanism only — JWT issuer + verification + cookie + service-account minting.
- Do **not** introduce CSP changes, nginx edits, or frontend code changes (PR-CL3-3 + PR-CL3-4 own those; this wave's contract with the frontend is the cookie name/format and CSRF header name).
- Do **not** add the Clerk custom domain. The dispatch uses dev FAPI host `clerk.<random>.lcl.dev` per Andrei's authorization 2026-05-14. Add `# TODO(post-cluster-3): swap to clerk.<custom-domain>` markers at every config site.
- Do **not** add a migration unless required by service-account key storage (and even then, prefer env-var secrets over DB-stored keys; see §4.4).
- Do **not** delete the existing `_FAIL_CLOSED_ENVS` behavior or the `validate_auth_config` startup gate (Phase A5 J-A5-06 invariant stays).
- Do **not** widen scope into PR-CL3-3 (frontend) or PR-CL3-4 (CSP).

## 3. Findings and Evidence

Verified at HEAD `e3ad0dffb` for the pre-wave baseline. PR-CL3-2 MUST be executed after PR-CL3-1 has merged; otherwise `get_current_actor_roles`, `_VALID_HUMAN_ROLES`, and `require_service_identity` are not valid assumptions. If those identifiers are absent on live `main`, stop and report PR-CL3-1 as a blocking dependency rather than improvising a second helper surface.

### Existing JWT validator (to be swapped)

- `backend/app/core/auth.py:27-31` — `AuthSettings` dataclass: `jwks_url`, `audience`, `issuer`. Generic IdP-agnostic. Will be parameterized with Clerk values.
- `backend/app/core/auth.py:115-145` — `JWKSCache` with TTL refresh. Reusable as-is for Clerk JWKS endpoint.
- `backend/app/core/auth.py:147-161` — `_extract_token` reads `Authorization: Bearer <token>`. Will be REPLACED with cookie reader (PR-CL3-2 owns the swap).
- `backend/app/core/auth.py:185-224` — `get_current_user` JWKS validation. Issuer + audience must point at Clerk values; everything else stays.

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
- Each needs short-lived (~5min) JWT issued by backend, signed with the same key the backend's self-JWKS exposes.
- The minting helpers are CLI-callable (for cron triggering westmetall_ingest, for worker startup of rfq_outbound + cashflow_pipeline).

## 4. Required Implementation Boundary

### 4.1 Clerk JWT validation swap

Refactor `backend/app/core/auth.py`:

```python
@dataclass
class AuthSettings:
    jwks_url: str  # https://<clerk-fapi-host>/.well-known/jwks.json
    audience: str  # Clerk app instance ID (or empty string if Clerk omits aud)
    issuer: str    # https://<clerk-fapi-host>
    # TODO(post-cluster-3): swap fapi_host from clerk.<random>.lcl.dev to clerk.<custom-domain>
    fapi_host: str  # for cookie domain + connect-src CSP origin


def get_auth_settings() -> AuthSettings | None:
    if not _auth_enabled():
        return None
    fapi_host = os.environ["CLERK_FAPI_HOST"]
    return AuthSettings(
        jwks_url=f"https://{fapi_host}/.well-known/jwks.json",
        audience=os.environ.get("CLERK_AUDIENCE", ""),
        issuer=f"https://{fapi_host}",
        fapi_host=fapi_host,
    )
```

Env vars introduced:
- `CLERK_FAPI_HOST` (mandatory) — e.g. `clerk.abcdef.lcl.dev` in dev. Production: swap to custom domain post-Cluster-3.
- `CLERK_AUDIENCE` (optional, depending on Clerk app config).

Update `validate_auth_config` to verify `CLERK_FAPI_HOST` is set in `_FAIL_CLOSED_ENVS`.

### 4.2 Cookie-based session

Replace `_extract_token` with cookie reader:

```python
SESSION_COOKIE_NAME = "__Session"  # Clerk-style; opaque to frontend
CSRF_COOKIE_NAME = "csrf_token"
CSRF_HEADER_NAME = "X-CSRF-Token"

def _extract_token(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session cookie missing",
        )
    return token
```

The `_extract_token` Bearer-header path is removed for human Clerk sessions. Preserve a separate Bearer transport for backend-minted service JWTs because cron/worker callers (Westmetall, RFQ outbound, cashflow pipeline) cannot receive browser httpOnly cookies.

Add `backend/app/api/routes/auth.py`:

```python
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

    response.set_cookie(
        SESSION_COOKIE_NAME,
        session_token,
        httponly=True,
        secure=_canonical_env() in _FAIL_CLOSED_ENVS,  # always True in prod
        samesite="lax",
        max_age=300,  # match Clerk session TTL
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE_NAME,
        csrf,
        httponly=False,  # frontend reads this to echo back in X-CSRF-Token header
        secure=_canonical_env() in _FAIL_CLOSED_ENVS,
        samesite="lax",
        max_age=300,
        path="/",
    )
    return {"actor_sub": payload["sub"], "csrf_token": csrf}


@router.post("/auth/refresh")
async def refresh_session(
    request: Request,
    session_token: str = Body(..., embed=True),  # fresh Clerk session token from frontend SDK
    response: Response,
) -> dict[str, str]:
    """Refresh httpOnly cookie + CSRF token using a fresh Clerk JWT."""
    payload = _validate_clerk_token(session_token)
    # Mint fresh CSRF
    csrf = secrets.token_urlsafe(32)
    # Re-set cookies with fresh max_age
    # ... (same Set-Cookie logic as create_session)
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

### 4.3 CSRF middleware

Add `backend/app/core/csrf.py`:

```python
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

Register in `backend/app/main.py`:

```python
app.add_middleware(BaseHTTPMiddleware, dispatch=csrf_middleware)
```

Update `CORSMiddleware` for the split frontend/backend deployment used by `VITE_API_BASE_URL`:

- `allow_credentials=True`
- allowed headers include `X-CSRF-Token`
- allowed origins include the deployed frontend origin(s); do not use `allow_origins=["*"]` with credentials.

This is required because PR-CL3-3 sends `credentials: "include"` and `X-CSRF-Token` cross-origin from the static frontend.

### 4.4 Auditor-exclusive validation duplicated at JWT-validation time

Per governance "Role combinability": validation MUST happen at JWT-validation time, before any route-gate dependency evaluates. PR-CL3-1 keeps a redundant defensive check inside `get_current_actor_roles`. For strict constitutional compliance, add the same check inside `get_current_user`; do not remove the PR-CL3-1 helper check.

Dependency assertion before editing: `rg -nP "def get_current_actor_roles|_VALID_HUMAN_ROLES|def require_service_identity" backend/app/core/auth.py` MUST find the PR-CL3-1 helper surface. If it does not, PR-CL3-2 is running on the wrong base.

```python
def get_current_user(...) -> dict[str, Any]:
    # ... existing JWT validation ...

    payload = jwt.decode(token, jwk, algorithms=["RS256"], audience=..., issuer=...)

    # Auditor-exclusive role combinability check (governance §"Role combinability")
    raw_roles = payload.get("roles") if isinstance(payload, dict) else None
    if isinstance(raw_roles, list):
        roles = {r for r in raw_roles if isinstance(r, str) and r in _VALID_HUMAN_ROLES}
        if "auditor" in roles and len(roles) > 1:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid role combination: auditor must be exclusive",
            )

    return payload
```

`get_current_actor_roles` (from PR-CL3-1) keeps its own redundant check — defense in depth, no harm if the JWT-time check fires first.

### 4.5 Service-account JWT minting

Add to `backend/app/core/auth.py`:

```python
SERVICE_TOKEN_TTL_SECONDS = 300  # 5 min per governance "TTL ~5min"

def mint_service_token(identity: str) -> str:
    """Mint a short-lived JWT for an internal-issued service identity.

    Used by:
    - Westmetall ingest cron entrypoint (mints `service:westmetall_ingest`)
    - RFQ outbound worker startup (mints `service:rfq_outbound`)
    - Cashflow pipeline worker startup (mints `service:cashflow_pipeline`)

    Signing key: SERVICE_JWT_SIGNING_KEY env var (RSA private key PEM).
    Verification: backend's own JWKS at /api/.well-known/service-jwks.json
    (served by the JWKS endpoint added in §4.6).
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

CLI entrypoint at `backend/scripts/mint_service_token.py`:

```python
#!/usr/bin/env python3
"""Mint a service-account JWT for cron/worker startup.

Usage:
    python -m backend.scripts.mint_service_token --identity westmetall_ingest

Output: token to stdout. Caller is responsible for piping into the
target process's environment (e.g. WESTMETALL_INGEST_TOKEN env var).
"""
```

### 4.6 Service-account verification (consume side already in PR-CL3-1)

PR-CL3-1 added `require_service_identity(name)`. PR-CL3-2 adds the JWT verification flow that backs it: when `get_current_user` validates a token whose `iss` matches the backend's own service issuer (not Clerk), it MUST validate against backend's own public key (different JWKS), not Clerk's.

Pattern:

```python
def get_current_user(...) -> dict[str, Any]:
    # Try Clerk JWKS first
    try:
        return _validate_clerk_token(token)
    except HTTPException as clerk_err:
        # Fall through to backend service JWKS
        pass

    try:
        return _validate_service_token(token)
    except HTTPException as service_err:
        # Both validators failed — re-raise the Clerk error (more user-facing)
        raise clerk_err
```

OR (preferred): inspect the `iss` claim from the unverified header to route to the right validator:

```python
def get_current_user(...) -> dict[str, Any]:
    token = _extract_token(request)
    unverified = jwt.decode(token, options={"verify_signature": False})
    issuer = unverified.get("iss", "")

    if issuer == os.environ["BACKEND_SERVICE_ISSUER"]:
        return _validate_service_token(token)
    return _validate_clerk_token(token)
```

The latter is cleaner — single code path per token type.

Add `/api/.well-known/service-jwks.json` endpoint (or include service public key in existing `/healthz` extension) so the validator can fetch its own public key. For PR-CL3-2 simplicity, embed the public key path as env var `SERVICE_JWT_PUBLIC_KEY` and skip the JWKS endpoint until cluster 4 if needed.

### 4.7 Production fail-closed extensions

`validate_auth_config` MUST verify in `_FAIL_CLOSED_ENVS`:
- `CLERK_FAPI_HOST` is set
- `SERVICE_JWT_SIGNING_KEY` is set
- `SERVICE_JWT_PUBLIC_KEY` is set
- `BACKEND_SERVICE_ISSUER` is set
- `BACKEND_SERVICE_AUDIENCE` is set

Missing any → fail-closed at startup (raise `RuntimeError`).

Concrete shape:

```python
def validate_auth_config() -> None:
    env = _canonical_env()
    if env not in _FAIL_CLOSED_ENVS:
        return

    missing: list[str] = []
    for name in (
        "CLERK_FAPI_HOST",
        "SERVICE_JWT_SIGNING_KEY",
        "SERVICE_JWT_PUBLIC_KEY",
        "BACKEND_SERVICE_ISSUER",
        "BACKEND_SERVICE_AUDIENCE",
    ):
        if not os.getenv(name):
            missing.append(name)

    if missing:
        raise RuntimeError(
            "Missing required auth configuration in fail-closed environment: "
            + ", ".join(sorted(missing))
        )
```

## 5. Constitutional Rules

- `docs/governance.md` AUTHORIZATION MATRIX > Service identities subsection — distinguishes internal-issued (JWT signed by backend) from external-ingress (provider auth). PR-CL3-2 implements the JWT issuance for the 3 internal identities; webhook_inbound stays as-is.
- `docs/governance.md` AUTHORIZATION MATRIX > Role combinability — auditor exclusive at JWT validation time.
- `docs/governance.md` §"GOVERNANCE HARD FAILS" — startup fail-closed if config missing.

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes D-3.2 + D-3.3 (token storage portion) iff every item below is true.

### 6.1 Clerk JWT validation

- [ ] `backend/app/core/auth.py` — `AuthSettings` includes `fapi_host`; `get_auth_settings` reads `CLERK_FAPI_HOST`.
- [ ] JWKS URL points at `https://<fapi_host>/.well-known/jwks.json`.
- [ ] `iss` and `aud` match Clerk values.
- [ ] `# TODO(post-cluster-3): swap to clerk.<custom-domain>` marker present at every site that hardcodes the dev FAPI host.

### 6.2 httpOnly cookie

- [ ] `backend/app/api/routes/auth.py` — `/auth/session`, `/auth/refresh`, `/auth/logout` exist with the signatures in §4.2.
- [ ] `backend/app/api/routes/auth.py` — `/auth/me` exists and returns `{actor_sub, roles}` for frontend hydration.
- [ ] Cookie set with `httponly=True`, `secure=True` in fail-closed envs, `samesite="lax"`, `max_age=300`, `path="/"`.
- [ ] CSRF cookie set with `httponly=False` (frontend reads it).
- [ ] Human Clerk sessions read from cookie, NOT from Bearer header.
- [ ] Backend service JWTs retain Bearer transport through a service-only extractor/validator; human Bearer fallback is removed.

### 6.3 CSRF middleware

- [ ] `backend/app/core/csrf.py` exists with the double-submit middleware in §4.3.
- [ ] Middleware registered in `backend/app/main.py`.
- [ ] Exempt paths: `/auth/session`, `/webhooks/`, `/healthz`.
- [ ] CSRF mismatch returns 403 with `detail="CSRF token missing or mismatch"`.
- [ ] `CORSMiddleware` allows credentialed frontend requests (`allow_credentials=True`) and includes `X-CSRF-Token` in allowed headers.

### 6.4 Auditor-exclusive at JWT-validation time

- [ ] `get_current_user` raises HTTP 401 with `detail="Invalid role combination: auditor must be exclusive"` when JWT payload has both auditor and another role.
- [ ] `get_current_actor_roles` (from PR-CL3-1) retains its own check (defense in depth).

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

1. **`test_clerk_jwt_valid_returns_user`** — fixture: signed JWT with valid Clerk-shape claims (sub, iss, aud, roles). Returns user dict.
2. **`test_clerk_jwt_invalid_signature_401`** — fixture: JWT signed with wrong key. Returns 401.
3. **`test_clerk_jwt_expired_401`** — fixture: JWT with `exp` in past.
4. **`test_clerk_jwt_wrong_audience_401`** — fixture: JWT with `aud` mismatch.
5. **`test_clerk_jwt_wrong_issuer_401`** — fixture: JWT with `iss` mismatch.
6. **`test_clerk_jwt_auditor_exclusive_401`** — fixture: JWT with `roles=["auditor", "trader"]`. Returns 401 at JWT validation (NOT at route gate).
7. **`test_clerk_jwt_auditor_alone_passes`** — fixture: JWT with `roles=["auditor"]`. Returns user dict (no 401).
8. **`test_clerk_jwt_trader_plus_risk_manager_passes`** — fixture: JWT with `roles=["trader", "risk_manager"]`. Returns user dict.

### 7.2 New file `backend/tests/test_cookie_session.py`

9. **`test_session_endpoint_sets_httponly_cookie`** — POST `/auth/session` with valid Clerk session token. Assert `Set-Cookie` header includes `__Session=...` with `HttpOnly`, `Secure` (in prod env), `SameSite=Lax`, `Path=/`, `Max-Age=300`.
10. **`test_session_endpoint_returns_csrf_token_in_body_and_cookie`** — same. Assert response body has `csrf_token`, and Set-Cookie has `csrf_token=...` with `HttpOnly` NOT set.
11. **`test_authenticated_request_uses_cookie_not_bearer`** — call any auth-required endpoint with cookie, no Authorization header. Returns 200.
12. **`test_authenticated_human_bearer_only_401`** — call any human auth-required endpoint with Clerk Bearer header but no cookie. Returns 401 with `detail="Session cookie missing"`.
13. **`test_logout_clears_cookies`** — POST `/auth/logout`. Assert Set-Cookie header sets both cookies to expired (Max-Age=0 or similar).
14. **`test_refresh_reexchanges_fresh_clerk_token_and_rotates_csrf`** — POST `/auth/refresh` with a fresh Clerk session token. Assert session cookie is reset and new `csrf_token` differs from prior.
15. **`test_auth_me_returns_actor_and_roles`** — GET `/auth/me` with valid session cookie. Assert response has `actor_sub` and `roles`.

### 7.3 New file `backend/tests/test_csrf_middleware.py`

16. **`test_csrf_middleware_get_passes_without_token`** — GET endpoint, no CSRF token. Returns 200.
17. **`test_csrf_middleware_post_missing_token_403`** — POST endpoint, no CSRF cookie. Returns 403 with `detail="CSRF token missing or mismatch"`.
18. **`test_csrf_middleware_post_mismatch_403`** — POST endpoint, cookie value ≠ header value. Returns 403.
19. **`test_csrf_middleware_post_match_passes`** — POST endpoint, cookie value == header value. Returns 200.
20. **`test_csrf_middleware_session_endpoint_exempt`** — POST `/auth/session` without CSRF token. Returns 200 (exempt).
21. **`test_csrf_middleware_webhook_exempt`** — POST `/webhooks/whatsapp` with HMAC but no CSRF. Returns 200 (exempt).
22. **`test_cors_allows_credentials_and_csrf_header`** — OPTIONS preflight from allowed frontend origin with `X-CSRF-Token`; assert credentialed CORS response permits it.

### 7.4 New file `backend/tests/test_service_token_minting.py`

23. **`test_mint_service_token_westmetall`** — `mint_service_token("westmetall_ingest")` returns RS256 JWT. Decode and assert `sub == "service:westmetall_ingest"`, `exp == now+300`.
24. **`test_mint_service_token_unknown_raises`** — `mint_service_token("not_a_real_identity")` raises ValueError.
25. **`test_get_current_user_routes_service_token_to_service_validator`** — fixture: service-minted Bearer JWT. `get_current_user` returns payload with `sub="service:westmetall_ingest"`.
26. **`test_service_token_with_clerk_issuer_401`** — fixture: JWT signed with service key but `iss=clerk-fapi`. Returns 401.

### 7.5 Existing test fixture migration

- Human-user test fixtures that mock `Authorization: Bearer ...` headers MUST be updated to set the `__Session` cookie instead. Service-token fixtures remain Bearer JWTs and must use the service-token helper, not cookies.

### 7.6 Production fail-closed

25. **`test_validate_auth_config_missing_clerk_host_fails_closed`** — set env to production, unset CLERK_FAPI_HOST. `validate_auth_config()` raises RuntimeError.
26. **`test_validate_auth_config_missing_service_keys_fails_closed`** — same, with each of the 4 service env vars unset individually.

## 8. Required Verification

```powershell
# Helper surface
rg -nP "def mint_service_token|def _validate_clerk_token|def _validate_service_token" backend/app/core/auth.py
rg -nP "SESSION_COOKIE_NAME|CSRF_COOKIE_NAME|CSRF_HEADER_NAME" backend/app/core/auth.py backend/app/core/csrf.py

# Bearer transport split
rg -nP "SESSION_COOKIE_NAME|request\\.cookies" backend/app/core/auth.py
rg -nP "Authorization.*Bearer|request\\.headers\\.get\\(['\"]authorization" backend/app/core/auth.py
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
- **Bearer→Cookie migration:** explicit statement that Authorization header path was removed; test fixture migration done.
- **Service-account JWKS endpoint:** explicit statement that endpoint NOT added (env-var public key used instead); follow-up flag if distributed deploy needs it.
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-3-clerk-jwt-cookies-{sha}.json` per push.
- **Governance + alembic statements:** diffs empty.

## 11. Workflow

1. **Pre-step:** verify PR-CL3-1 has merged (`git log --oneline main | head -5` should show "Cluster 3 PR-CL3-1"). If not merged, base off pre-PR-CL3-1 main and adapt the helper-surface assumptions accordingly.
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
  - **Auditor-exclusive double-check** — PR-CL3-1 puts the check in `get_current_actor_roles`; PR-CL3-2 adds the same check to `get_current_user`. Codex may flag the redundancy as unnecessary; respond that it's defense-in-depth + governance compliance (matrix says "BEFORE any route gate").
  - **`secrets.compare_digest`** — CSRF cookie/header comparison MUST use constant-time comparison. Codex will flag a `==` fallback as a timing oracle.
  - **`# TODO(post-cluster-3)` markers** — every site that hardcodes dev FAPI host MUST have the marker; missing marker → Codex catches as "tech debt without trail".
  - **Production fail-closed env coverage** — every new env var MUST be in `validate_auth_config`'s required list. Codex will trace each.
  - **`SameSite=Lax` justification** — Lax allows top-level cross-site GETs. If frontend is cross-origin with backend, may need `Strict` or `None+Secure`. PR body should document the choice.
  - **CLERK_AUDIENCE optional-vs-required** — Clerk session JWTs may or may not have `aud`; backend validator must handle both. Codex may flag inconsistency.
- **Padrão PR #79:** governance docs receive intense scrutiny; the IMPLEMENTATION PR will be checked against governance text rigorously. The Service identities split (internal-issued vs external-ingress, per-method webhook auth) is now constitutional — Codex will verify the implementation matches.
- **8-section sweep:** §4 boundary, §6 acceptance, §7 tests, §8 verification, §11 workflow MUST consistently enumerate the same 6 deliverables (Clerk JWKS, cookie endpoints, CSRF middleware, auditor-early-validation, service minting, fail-closed). Drift between sections is the canonical authoring failure mode.
- **The largest implementation risk** is the Bearer→cookie fixture migration. ~All existing auth-required tests will need updates simultaneously. Mitigation: write the central conftest helper FIRST, then sweep `rg -nP 'Authorization.*Bearer' backend/tests/` and migrate every site through the helper before running the full suite.
