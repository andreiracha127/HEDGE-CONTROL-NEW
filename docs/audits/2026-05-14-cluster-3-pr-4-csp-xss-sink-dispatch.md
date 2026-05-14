# Cluster 3 Implementation Dispatch — PR-CL3-4 — nginx CSP Report-Only + Violation Reporter + XSS-Sink Inventory

**Cluster:** 3 — Security / Platform (D-3.3 token storage, CSP + XSS-sink portion)
**Wave:** PR-CL3-4 (4 of 4) — final wave of Cluster 3
**Authoring date:** 2026-05-14
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `e3ad0dffb` post-PR #79; assumes PR-CL3-3 has merged before this wave starts — see §11)
**Required branch:** `audit-followup/cluster-3-csp-xss-sink`
**Source-of-truth:** `docs/governance.md` AUTHORIZATION MATRIX; Cluster 3 platform decisions (Clerk + httpOnly + **strict baseline + report-only ramp** CSP shape per Andrei's authorization 2026-05-14)

## 1. Objective

Replace the current baseline CSP at `frontend-svelte/nginx.conf` with the strict Clerk-aware CSP per Andrei's bindado decision (`project_cluster_3_platform_decisions`) — deployed as **`Content-Security-Policy-Report-Only`** first (1-2 sprints of violation collection + tuning), then flipped to `Content-Security-Policy` enforce mode in a subsequent flag-flip PR.

Hard dependency: PR-CL3-4 MUST NOT start until PR-CL3-2 and PR-CL3-3 have merged into live `main`. If `/auth/*`, credentialed CSRF middleware, the CSRF exempt-list mechanism, or the frontend Clerk integration are absent, stop and report the dependency blocker rather than creating fallback infrastructure in this PR.

Three coupled deliverables:

1. **nginx CSP swap** — replace current generic CSP with the strict Clerk-aware baseline per `project_cluster_3_platform_decisions` exact text plus the configured backend HTTP/WebSocket origins required by this split-origin deployment. Header name `Content-Security-Policy-Report-Only` (not enforce). Includes `frame-ancestors 'none'`, `worker-src 'self' blob:`, backend API/WS origins, Clerk origins (`<fapi-host>` + `https://challenges.cloudflare.com`), Clerk telemetry connect-src, Clerk img.clerk.com, `report-to csp-endpoint`, `upgrade-insecure-requests`. NO `'unsafe-eval'`. NO permissive `https:` wildcards.
2. **Backend `/csp/report` endpoint** — receive violation reports from browser-side CSP enforcement. Persist (or log) for analysis. Must be CSRF-exempt (browser-initiated, no human session) and rate-limited to prevent abuse.
3. **XSS-sink inventory doc** — per D-3.3 explicit requirement: document every `innerHTML`, `eval`, `setAttribute('href'|'src')`, dynamic-import call in the SPA. Separate doc at `docs/security/xss-sink-inventory.md`.

This wave closes the last Cluster 3 finding (D-3.3 token storage hardening — CSP portion). After PR-CL3-4 merges, all 3 Cluster 3 jury findings (D-3.1 + D-3.2 + D-3.3) are retired.

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`.
- Do **not** edit backend route gates, auth.py, or any Cluster 3 PR-CL3-1/2/3 territory. Allowed backend changes in this PR are limited to the `/csp/report` router, `main.py` router registration, and the CSRF middleware exempt-list entry required for that unauthenticated browser-report endpoint.
- Do **not** edit frontend code beyond what's strictly needed for CSP compatibility (e.g. removing inline scripts that violate the new CSP). PR-CL3-3 owns the SDK integration.
- Do **not** flip CSP to enforce mode in this PR. Report-only ramp is a sustained period (1-2 sprints) before enforce flip; the flip is a separate follow-up wave.
- Do **not** add `'unsafe-eval'` to `script-src`. Production explicitly excludes it per Clerk docs.
- Do **not** widen scope into Cluster 4 or future XSS-fix waves. The XSS-sink inventory is documentation only; remediation of any sink found is post-Cluster-3 work.

## 3. Findings and Evidence

Verified at HEAD `e3ad0dffb`.

Dependency gate: PR-CL3-4 is intentionally sequenced after PR-CL3-2 and PR-CL3-3. At the baseline cited here, the `/auth/*` routes and CSRF middleware introduced by PR-CL3-2 may not exist yet. Before executing PR-CL3-4, rebase on live `main` after PR-CL3-2 and PR-CL3-3 merge, then verify the auth endpoints and CSRF middleware are present. If either prerequisite is missing, stop; do not implement this dispatch against the older baseline.

### Current CSP at `frontend-svelte/nginx.conf`

Per `nginx.conf` head, current CSP is enforce mode (Content-Security-Policy header) with baseline:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
connect-src 'self' wss: https:; img-src 'self' data: blob:; font-src 'self';
object-src 'none'; frame-ancestors 'self';
```

Gaps relative to bindado strict baseline:
- `script-src` lacks Clerk FAPI host + `https://challenges.cloudflare.com`
- `connect-src` is too permissive (`https:`) — should be explicit backend HTTP origin, backend WebSocket origin, Clerk FAPI, and telemetry only
- `frame-src` not present — needs `https://challenges.cloudflare.com` for Turnstile
- `worker-src` not present — needs `'self' blob:` for Clerk web workers
- `frame-ancestors` is `'self'` — bindado is `'none'`
- `img-src` lacks `https://img.clerk.com`
- No `base-uri 'self'`
- No `upgrade-insecure-requests`
- No `report-to`
- No `'unsafe-inline'` in script-src — Clerk docs allow it for non-strict SvelteKit hydration; bindado choice is "strict baseline" which keeps `'unsafe-inline'` for now (nonce-based is option B in `project_cluster_3_platform_decisions`, deferred to future tuning)

### Bindado strict baseline (per `project_cluster_3_platform_decisions`)

```
Content-Security-Policy-Report-Only:
  default-src 'self';
  script-src 'self' 'unsafe-inline'
    https://<fapi-host>
    https://challenges.cloudflare.com;
  connect-src 'self'
    https://<backend-api-origin>
    wss://<backend-api-origin>
    https://<fapi-host>
    https://clerk-telemetry.com;
  img-src 'self' data: https://img.clerk.com;
  frame-src https://challenges.cloudflare.com;
  worker-src 'self' blob:;
  style-src 'self' 'unsafe-inline';
  form-action 'self';
  frame-ancestors 'none';
  base-uri 'self';
  object-src 'none';
  upgrade-insecure-requests;
  report-to csp-endpoint;
```

### XSS-sink categories (per D-3.3 backlog text)

Required inventory: `innerHTML`, `eval`, `setAttribute('href'|'src')`, dynamic-import. Sweep across:
- `frontend-svelte/src/`
- Any HTML in `frontend-svelte/static/`

## 4. Required Implementation Boundary

### 4.1 nginx CSP swap

Refactor `frontend-svelte/nginx.conf`:

Replace the current `add_header Content-Security-Policy ... always;` line (~line 8) with the strict baseline IN REPORT-ONLY MODE:

```nginx
# CSP — report-only ramp (1-2 sprints to collect violations + tune)
# After clean reports, flip header name to Content-Security-Policy in a
# follow-up PR. See docs/governance.md AUTHORIZATION MATRIX context +
# memory project_cluster_3_platform_decisions for the bindado shape.
#
# TODO(post-cluster-3): swap ${CLERK_FAPI_HOST} from clerk.<random>.lcl.dev
# (dev) to clerk.<custom-domain> (prod custom domain).

add_header Content-Security-Policy-Report-Only "
  default-src 'self';
  script-src 'self' 'unsafe-inline' https://${CLERK_FAPI_HOST} https://challenges.cloudflare.com;
  connect-src 'self' ${VITE_API_BASE_URL} ${VITE_WS_BASE_URL} https://${CLERK_FAPI_HOST} https://clerk-telemetry.com;
  img-src 'self' data: https://img.clerk.com;
  frame-src https://challenges.cloudflare.com;
  worker-src 'self' blob:;
  style-src 'self' 'unsafe-inline';
  form-action 'self';
  frame-ancestors 'none';
  base-uri 'self';
  object-src 'none';
  upgrade-insecure-requests;
  report-to csp-endpoint;
" always;

# Report-To header for the CSP report endpoint (separate from CSP header).
# It must target the backend origin directly; nginx has no /api or /csp proxy.
add_header Report-To '{"group":"csp-endpoint","max_age":10886400,"endpoints":[{"url":"${VITE_API_BASE_URL}/csp/report"}]}' always;

# X-Frame-Options is now redundant with frame-ancestors 'none' but kept
# for legacy browser support.
add_header X-Frame-Options "DENY" always;  # was SAMEORIGIN; tighten to DENY
```

Update `docker-entrypoint.sh` (or equivalent) to substitute `${CLERK_FAPI_HOST}`, `${VITE_API_BASE_URL}`, and `${VITE_WS_BASE_URL}` in `nginx.conf` from env vars at container start. `VITE_WS_BASE_URL` must be the backend WebSocket origin derived from `VITE_API_BASE_URL` (`https://api.example.com` -> `wss://api.example.com`, `http://localhost:8000` -> `ws://localhost:8000`).

Concrete substitution shape:

```sh
#!/bin/sh
set -eu

export VITE_WS_BASE_URL="${VITE_WS_BASE_URL:-$(printf '%s' "$VITE_API_BASE_URL" | sed -e 's#^https://#wss://#' -e 's#^http://#ws://#')}"

envsubst '${CLERK_FAPI_HOST} ${VITE_API_BASE_URL} ${VITE_WS_BASE_URL}' \
  < /etc/nginx/templates/default.conf.template \
  > /etc/nginx/conf.d/default.conf

exec nginx -g 'daemon off;'
```

If the existing Dockerfile uses a different template path, keep that local path but preserve the `envsubst` variable list and verify the entrypoint is the container command.

Verify by deploying the container and inspecting response headers in the browser.

### 4.2 Backend `/csp/report` endpoint

Add `backend/app/api/routes/csp_report.py`:

```python
from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse, Response
import structlog

from app.core.rate_limit import RATE_LIMIT_CSP_REPORT, limiter

router = APIRouter(tags=["csp"])
logger = structlog.get_logger(__name__)


@router.post("/report")
@limiter.limit(RATE_LIMIT_CSP_REPORT)
async def csp_report(request: Request) -> Response:
    """Receive CSP violation reports from browser.

    Per W3C CSP Reporting spec, browser POSTs JSON-formatted reports
    here when a directive is violated. We log them for analysis;
    after 1-2 sprints of clean reports, we'll flip CSP header from
    -Report-Only to enforce.

    Auth: NONE — browsers post these without credentials. CSRF-exempt
    (handled in CSRF middleware exempt list, PR-CL3-2).
    Rate-limited via configured `RATE_LIMIT_CSP_REPORT` to prevent abuse.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "invalid JSON"})

    # The browser sends one report object or an array of report objects.
    reports = body if isinstance(body, list) else [body]
    for report in reports:
        # Reports have a "csp-report" subkey under the legacy spec or
        # a "body" subkey under the modern Reporting API spec.
        violation = report.get("csp-report") or report.get("body") or report
        if not isinstance(violation, dict):
            return JSONResponse(status_code=400, content={"detail": "invalid CSP report"})
        document_uri = (
            violation.get("document-uri")
            or violation.get("documentURL")
            or report.get("url")
        )
        directive = (
            violation.get("violated-directive")
            or violation.get("effective-directive")
            or violation.get("effectiveDirective")
        )
        if not document_uri or not directive:
            return JSONResponse(status_code=400, content={"detail": "missing required CSP report fields"})
        logger.warning(
            "csp_violation",
            blocked_uri=violation.get("blocked-uri") or violation.get("blockedURL"),
            violated_directive=directive,
            document_uri=document_uri,
            source_file=violation.get("source-file") or violation.get("sourceFile"),
            line_number=violation.get("line-number") or violation.get("lineNumber"),
            referrer=violation.get("referrer"),
        )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
```

Field handling: legacy `csp-report` bodies and modern Reporting API `body` wrappers are both accepted. `document-uri`/`documentURL`/outer `url` and `violated-directive`/`effective-directive`/`effectiveDirective` are required for a useful report and missing/non-object reports return 400. `blocked-uri`/`blockedURL`, `source-file`/`sourceFile`, `line-number`/`lineNumber`, and `referrer` are optional per browser/reporting variation and may log as null. The structured log MUST include all seven keys above even when optional values are absent.

Register router in `backend/app/main.py`:

```python
from app.api.routes import csp_report
app.include_router(csp_report.router, prefix="/csp", tags=["CSP"])
```

CSRF middleware (PR-CL3-2) MUST exempt `/csp/report` — browsers send these without CSRF tokens. PR-CL3-2's exempt list already covers `/webhooks/*`; this PR adds `/csp/report` to the exempt list as a required backend infrastructure change for the new unauthenticated reporting endpoint. Document that change in the PR body. Do not mount the FastAPI router at `/api/csp`: the app's `_StripApiPrefixMiddleware` strips `/api/*` before routing, and routers are registered without the `/api` prefix.

Dependency gate: before implementing this PR, verify PR-CL3-2 has merged and introduced request-level CSRF middleware. Run `rg -nP "csrf|CSRF|exempt|/webhooks" backend/app/` and confirm the actual middleware/exempt-list file exists (expected shape from the dispatch is `backend/app/core/csrf.py`). If no request-level CSRF middleware exists, stop and report the PR-CL3-2 dependency blocker.

Exempt-list pattern: after rebasing on PR-CL3-2, locate the CSRF middleware with the command above. If PR-CL3-2 introduced a centralized file such as `backend/app/core/csrf.py`, add `/csp/report` to the same exempt route collection as `/webhooks/*`. If PR-CL3-2 uses a decorator-based exemption, apply the equivalent `@csrf_exempt` (or local helper name) directly to `csp_report`. The implementation must cite the actual file/pattern in the PR body; do not invent a second CSRF exemption mechanism.

Rate limit: add `RATE_LIMIT_CSP_REPORT` / `rate_limit_csp_report` to the existing settings surface with default `"50/minute"`, then use the existing `app.core.rate_limit.limiter` decorator shown above. If local naming differs after rebasing, follow the same backend configurable `@limiter.limit(...)` pattern already used by mutation routes; do not leave this endpoint unbounded.

Add to `backend/app/core/rate_limit.py` beside the existing rate-limit constants:

```python
RATE_LIMIT_CSP_REPORT = os.getenv("RATE_LIMIT_CSP_REPORT", "50/minute")
```

### 4.3 XSS-sink inventory doc

Create `docs/security/xss-sink-inventory.md`:

```markdown
# XSS Sink Inventory — Hedge Control Frontend

**Generated:** 2026-05-14 (PR-CL3-4)
**Source:** `frontend-svelte/src/`
**Methodology:** rg sweep across 4 sink categories per D-3.3 backlog requirement

## Sink categories surveyed

1. `innerHTML` (assignment to .innerHTML or use of {@html} in Svelte)
2. `eval` (any eval call)
3. `setAttribute('href' | 'src')` (potential JavaScript URL injection)
4. Dynamic import (`import(...)` with non-literal arg)

## Sweeps performed

```bash
rg -nP "innerHTML|\\{@html|eval\\(|setAttribute\\(['\"](?:href|src)['\"]" frontend-svelte/src/
rg -nP "import\\([^'\"`]" frontend-svelte/src/
```

## Findings

[Each finding documented as: file:line, snippet, risk classification (input-tainted vs static-string vs framework-internal), remediation status (open / fixed / accepted-risk).]

| Site | Category | Snippet | Risk | Status |
|---|---|---|---|---|
| (none found) | - | - | - | - |

## Conclusion

[Summary: total sinks found, categorization, remediation roadmap.]

## Reconciliation cadence

This inventory MUST be re-generated:
- Before every major frontend release
- After any new dependency that ships templates/HTML
- During each Phase audit cycle going forward

## Cross-references

- D-3.3 backlog item: `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §85-88
- Cluster 3 platform decisions: orchestrator memory `project_cluster_3_platform_decisions`
- CSP enforcement: `frontend-svelte/nginx.conf` (Content-Security-Policy-Report-Only)
```

The executor MUST run the sweeps, populate the table with actual findings, and classify each. Empty result is acceptable (means no sinks found); document as such.

### 4.4 Frontend remediation if CSP-incompatible code found

CSP report-only mode WILL surface violations from the existing frontend. Some may be:
- Inline `<script>` in `app.html` SvelteKit shell — usually fine with `'unsafe-inline'`
- Third-party dependencies that load resources from unknown origins — would need allowlisting OR removal
- Dynamic imports that fail with `script-src 'self'` — would need `'unsafe-eval'` (rejected) OR refactor

For PR-CL3-4: the report-only mode COLLECTS these without breaking. Remediation comes in the follow-up enforce-flip PR (after 1-2 sprints of clean reports). This wave does NOT remediate any CSP violation found — it sets up the collection infrastructure.

If a CSP report DURING THIS PR's local testing reveals a critical violation that even `'unsafe-inline'` doesn't allow, document it in the PR body and propose remediation in the enforce-flip follow-up wave.

## 5. Constitutional Rules

- `docs/governance.md` AUTHORIZATION MATRIX — frontend security headers part of platform hardening (D-3.3).
- `docs/governance.md` §"GOVERNANCE HARD FAILS" — no silent fallback. CSP report-only mode is NOT a fallback; it's an explicit collection phase before enforce.
- CSP report-only mode is a data-collection phase (1-2 sprints) before enforce mode; it does not suppress CSP violations, it records them. This aligns with the governance hard-fail stance on missing evidence: collect evidence first, enforce second.

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes D-3.3 (CSP + XSS-sink portion) iff every item below is true.

### 6.1 nginx CSP

- [ ] `frontend-svelte/nginx.conf` — `Content-Security-Policy-Report-Only` header (NOT enforce) with the bindado strict baseline.
- [ ] All 13 directives present per §3 bindado list (default-src, script-src, connect-src, img-src, frame-src, worker-src, style-src, form-action, frame-ancestors, base-uri, object-src, upgrade-insecure-requests, report-to).
- [ ] `frame-ancestors 'none'` (NOT 'self').
- [ ] No `'unsafe-eval'` anywhere.
- [ ] No permissive `https:` wildcard in `connect-src` (only `'self'` + backend HTTP origin + backend WebSocket origin + Clerk FAPI host + clerk-telemetry.com).
- [ ] `${CLERK_FAPI_HOST}`, `${VITE_API_BASE_URL}`, and `${VITE_WS_BASE_URL}` template substitution works at container start (verify via `docker-compose up` + browser inspection).
- [ ] `# TODO(post-cluster-3): swap ${CLERK_FAPI_HOST} ...` marker present.
- [ ] `Report-To` header points at `${VITE_API_BASE_URL}/csp/report`.
- [ ] `X-Frame-Options: DENY` (tightened from SAMEORIGIN).

### 6.2 Backend `/csp/report`

- [ ] `backend/app/api/routes/csp_report.py` exists with the POST `/csp/report` endpoint per §4.2.
- [ ] Router registered in `backend/app/main.py`.
- [ ] CSRF middleware (PR-CL3-2) exempt list includes `/csp/report`.
- [ ] PR body cites the actual CSRF middleware file/pattern updated for `/csp/report` (central exempt route collection or decorator-based exemption), discovered via `rg -nP "csrf|CSRF|exempt|/webhooks" backend/app/`.
- [ ] Endpoint logs structured `csp_violation` events with all 7 fields per §4.2.
- [ ] Rate-limit applied via configured `RATE_LIMIT_CSP_REPORT` defaulting to `"50/minute"`; no hardcoded magic threshold in tests.
- [ ] Returns 204 (no body) on success.

### 6.3 XSS-sink inventory

- [ ] `docs/security/xss-sink-inventory.md` exists with the structure in §4.3.
- [ ] All 4 sink-category sweeps run; results documented in the table.
- [ ] Findings classified by risk (input-tainted vs static vs framework-internal).
- [ ] Reconciliation cadence section present.
- [ ] Cross-references to D-3.3 + governance + CSP file present.

### 6.4 Cross-cutting

- [ ] `docs/governance.md` diff is empty.
- [ ] No backend route-gate change (PR-CL3-1 + PR-CL3-2 + PR-CL3-3 territory untouched).
- [ ] No alembic migration. Single head remains `044_drop_deal_lifecycle_fields`.
- [ ] No frontend code changes beyond what CSP-compat strictly requires (this PR is infrastructure, not feature work).

## 7. Required Tests

### 7.1 Backend integration test

1. **`backend/tests/test_csp_report_endpoint.py`**:
   - `test_csp_report_post_valid_logs_violation` — POST a valid CSP report shape; assert structlog log emitted with `csp_violation` key.
   - `test_csp_report_accepts_modern_reporting_api_body` — POST a modern Report-To payload with outer `url` and inner `body.documentURL`/`body.effectiveDirective`/`body.blockedURL`; assert 204 and normalized structured log fields.
   - `test_csp_report_logs_all_fields` — assert the structured `csp_violation` log includes `blocked_uri`, `violated_directive`, `document_uri`, `source_file`, `line_number`, `referrer`, and the event name.
   - `test_csp_report_post_returns_204` — assert response status_code == 204.
   - `test_csp_report_post_invalid_json_returns_400` — POST malformed body; assert 400.
   - `test_csp_report_csrf_exempt` — POST without CSRF token; assert 204 (NOT 403).
   - `test_csp_report_rate_limit_uses_configured_limit` — set `RATE_LIMIT_CSP_REPORT=50/minute`, POST 51 reports rapidly, assert 51st returns 429.

### 7.2 Frontend e2e (Playwright)

2. **`frontend-svelte/e2e/csp.spec.ts`** (NEW; repo Playwright `testDir` is `./e2e`):
   - `test_csp_report_only_header_present` — load any page, assert response includes `Content-Security-Policy-Report-Only` header with the bindado directives.
   - `test_csp_enforce_header_NOT_present` — assert no `Content-Security-Policy` (enforce) header (only the -Report-Only variant).
   - `test_report_to_header_present` — assert `Report-To` header points at the backend-origin `${VITE_API_BASE_URL}/csp/report`.
   - `test_no_console_csp_blocks_on_login_page` — load `/login` (Clerk SDK page), assert no CSP violations in browser console.

### 7.3 nginx config validation

3. `nginx -t -c frontend-svelte/nginx.conf` MUST pass syntax check (with mock env substitution).

### 7.4 XSS-sink doc executable

4. The sweeps in `docs/security/xss-sink-inventory.md` MUST be runnable as-is. Run them; assert table contents match current sweep output. Adds CI guard against drift.

## 8. Required Verification

```powershell
# nginx CSP shape
rg -nP "Content-Security-Policy-Report-Only" frontend-svelte/nginx.conf
rg -nP "frame-ancestors 'none'|frame-src.*challenges.cloudflare.com|worker-src 'self' blob:|report-to csp-endpoint" frontend-svelte/nginx.conf
rg -nP "connect-src.*VITE_API_BASE_URL.*VITE_WS_BASE_URL" frontend-svelte/nginx.conf
rg -nP "envsubst.*CLERK_FAPI_HOST.*VITE_API_BASE_URL.*VITE_WS_BASE_URL|VITE_WS_BASE_URL=.*sed" frontend-svelte/docker-entrypoint.sh
rg -nP "form-action 'self'" frontend-svelte/nginx.conf
rg -nP "'unsafe-eval'" frontend-svelte/nginx.conf    # MUST be zero
rg -nP "connect-src[^;]*(^|\\s)https:(\\s|;)" frontend-svelte/nginx.conf    # MUST be zero (no bare permissive https: source)

# TODO marker
rg -nP "TODO\\(post-cluster-3\\)" frontend-svelte/nginx.conf

# Backend endpoint
rg -nP "/csp/report" backend/app/api/routes/csp_report.py backend/app/main.py
rg -nP "csp_violation" backend/app/api/routes/csp_report.py

# CSRF exempt list updated
rg -nP "/csp/report" backend/app/core/csrf.py

# XSS-sink inventory exists + sweeps documented
ls docs/security/xss-sink-inventory.md
rg -nP "innerHTML|eval\\(|setAttribute" docs/security/xss-sink-inventory.md

# Sweep frontend for current sink count (cross-check inventory)
rg -nP "innerHTML|\\{@html|eval\\(|setAttribute\\(['\"](href|src)['\"]" frontend-svelte/src/

# Cross-wave isolation
git diff main -- backend/app/api/routes/                # only csp_report.py + main.py registration + csrf.py exempt list addition
git diff main -- backend/app/core/                     # only csrf.py exempt list addition
git diff main -- frontend-svelte/src/                  # ideally zero or minimal CSP-compat fixes
git diff main -- docs/governance.md                    # zero

# Alembic invariant
cd backend ; python -m alembic heads ; cd ..

# Tests
pytest -q backend/tests/test_csp_report_endpoint.py
cd frontend-svelte ; npm run test:e2e -- csp.spec.ts ; cd ..
```

## 9. Out of Scope

- Flipping CSP from `-Report-Only` to enforce mode. That is a separate post-Cluster-3 follow-up wave after 1-2 sprints of clean reports.
- Nonce-based `script-src` (option B in `project_cluster_3_platform_decisions`). Current bindado choice is `'unsafe-inline'`; nonce migration is future tuning.
- XSS-sink REMEDIATION. PR-CL3-4 inventories sinks; remediation is post-Cluster-3 follow-up.
- Custom domain Clerk swap (TODO post-cluster-3).
- Frontend security tooling beyond CSP (e.g. Trusted Types, Subresource Integrity hashes for CDN-loaded scripts) — defer to future hardening.
- Backend security headers beyond CSP (e.g. Cache-Control: no-store on sensitive endpoints) — defer; out of scope of this wave.
- Rate-limit infrastructure for `/csp/report` if no existing infra. Document as TODO and proceed.

## 10. PR Requirements

Title:
```
fix(audit-followup): close Cluster 3 PR-CL3-4 (nginx CSP report-only ramp + violation reporter + XSS-sink inventory)
```

PR body:
- **Findings closed:** D-3.3 (CSP + XSS-sink portion). Marks Cluster 3 fully closed when this merges.
- **Files changed:** inventory grouped by nginx config / backend endpoint / docs.
- **CSP shape:** explicit statement of the 13 directives + report-only mode + flip-to-enforce roadmap (1-2 sprints).
- **XSS-sink count:** total sinks found across 4 categories, classification breakdown, remediation roadmap.
- **TODO markers:** every `TODO(post-cluster-3)` site cited.
- **CSP-violations-during-local-testing (if any):** documented + remediation proposed.
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-3-csp-xss-sink-{sha}.json` per push.
- **Governance + alembic statements:** diffs empty.

## 11. Workflow

1. **Pre-step:** verify PR-CL3-2 and PR-CL3-3 have both merged. Frontend Clerk integration must be live so CSP can validate against actual Clerk requests, and PR-CL3-2 must provide `/auth/*` + CSRF middleware before this PR can add the `/csp/report` exemption. If either prerequisite is absent on live `main`, stop and report the dependency blocker.
2. `git checkout -b audit-followup/cluster-3-csp-xss-sink`.
3. Apply §4.1 (nginx CSP swap) + verify env-var substitution at container start.
4. Apply §4.2 (backend `/csp/report` endpoint + CSRF exempt list update).
5. Apply §4.3 (XSS-sink inventory): run sweeps, populate table, classify findings.
6. Apply §4.4 ONLY IF local CSP testing reveals a blocker (rare; report-only mode shouldn't block).
7. Run §8 verification + nginx syntax check + tests.
8. Push branch, open PR per §10.
9. Codex Connector review is the final gate. **Do not merge.**

## 12. Hook v2 + Codex calibration notes

- **Expected hook v2 surface area:** small-medium (nginx config swap + small backend endpoint + new doc). Hook may flag prescription-vs-evidence on the `/csp/report` endpoint before it exists.
- **Expected Codex catches:**
  - **CSP directive completeness** — missing any of the 13 directives. Codex will compare against governance text.
  - **`'unsafe-eval'` survival** — Codex will sweep nginx.conf for it; any match = catch.
  - **`connect-src https:` permissive wildcard survival** — should be only `'self'` + Clerk FAPI + telemetry.
  - **Header name** — `Content-Security-Policy-Report-Only` (NOT `Content-Security-Policy`). If executor accidentally enforces, catch.
  - **`Report-To` header missing** — without it, browser doesn't know where to send reports.
  - **CSRF middleware exempt list missing `/csp/report`** — endpoint will 403 silently from browser violations.
  - **XSS-sink inventory empty/incomplete** — Codex may verify by running the same sweeps and comparing.
  - **`${CLERK_FAPI_HOST}` substitution at container start** — if `docker-entrypoint.sh` doesn't templating, header lands with literal `${CLERK_FAPI_HOST}` string.
  - **Rate-limit on report endpoint** — without it, abuse vector.
  - **`Content-Security-Policy` (enforce) header NOT present alongside report-only** — having both confuses browsers.
- **Padrão PR #79:** governance docs receive intense scrutiny. Cluster 3 closure means D-3.1 + D-3.2 + D-3.3 all retire. The matrix prescribed CSP contents; this PR's nginx.conf MUST match exactly.
- **8-section sweep:** §4 boundary, §6 acceptance, §7 tests, §8 verification, §11 workflow MUST consistently enumerate the same 3 deliverables (nginx swap, report endpoint, XSS-sink doc).
- **The largest implementation risk** is `${CLERK_FAPI_HOST}` substitution — if the entrypoint script doesn't templating it, the header lands as broken string and nothing in CI catches it (CI doesn't verify HTTP responses against running container). Mitigation: e2e Playwright test loads a page and asserts the response header text, with `${...}` substituted to actual value. Regression guard.
