# Cluster 3 Implementation Dispatch — PR-CL3-3 — Frontend Clerk SDK Integration

**Cluster:** 3 — Security / Platform (D-3.2 IdP integration, frontend half)
**Wave:** PR-CL3-3 (3 of 4)
**Authoring date:** 2026-05-14
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `e3ad0dffb` post-PR #79; assumes PR-CL3-2 has merged before this wave starts — see §11)
**Required branch:** `audit-followup/cluster-3-frontend-clerk-sdk`
**Source-of-truth:** `docs/governance.md` AUTHORIZATION MATRIX; Cluster 3 platform decisions (Clerk + httpOnly + dev FAPI provisional)

## 1. Objective

Integrate `@clerk/clerk-js` into the SvelteKit frontend; replace the dev paste-token login with Clerk's hosted sign-in/sign-up flow; route session-token exchange through PR-CL3-2's `/auth/session` endpoint; manage CSRF token from cookie + header echo; wire frontend auth store to Clerk session lifecycle. Kill the legacy `runtimeFlags.manualTokenLoginEnabled` gated paste-token flow (Phase A6 PR #67 protection no longer needed once Clerk handles login).

Three coupled deliverables:

1. **`@clerk/clerk-js` integration** — install SDK, configure with `CLERK_PUBLISHABLE_KEY` env var (dev provisional, with TODO post-cluster-3 swap to production key if different). SignIn/SignUp via Clerk's hosted modal or redirect.
2. **Session lifecycle wiring** — after Clerk authentication, exchange Clerk session token for httpOnly cookie via PR-CL3-2's `/auth/session`. Refresh on TTL approach. Clear on logout via `/auth/logout`.
3. **CSRF token echo** — read `csrf_token` cookie (non-httpOnly), echo in `X-CSRF-Token` header on every mutating request via the API client.
4. **Kill `manualTokenLoginEnabled`** — Phase A6 PR #67 (memory `project_phase_a6_pr4_landed`) gated dev paste-token login behind `runtimeFlags.manualTokenLoginEnabled` with three reason codes; production builds hard-failed config error. With Clerk handling login, the flag + paste-token UI become dead code. Remove both.

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`.
- Do **not** edit backend code (PR-CL3-1 + PR-CL3-2 own backend; this wave consumes their interfaces only).
- Do **not** edit `nginx.conf` (PR-CL3-4 owns CSP).
- Do **not** add custom-domain Clerk publishable key. Use dev provisional `pk_test_...` per Andrei's authorization 2026-05-14. Add `// TODO(post-cluster-3): swap to pk_live_<custom-domain>` markers at every config site.
- Do **not** widen scope into PR-CL3-4 (CSP nginx + violation reporter + XSS-sink inventory).
- Do **not** persist Clerk session token in localStorage or sessionStorage. The httpOnly cookie set by `/auth/session` is the ONLY token storage (governance §"D-3.3 token storage hardening" intent).
- Do **not** keep any `runtimeFlags.manualTokenLoginEnabled` reference. Code AND config (env-var, runtime-loader, JSON schema if any) all gone.

## 3. Findings and Evidence

Verified at HEAD `e3ad0dffb`.

### Existing frontend auth surface

- `frontend-svelte/src/routes/(public)/login/+page.svelte` — current login page. Implements the dev paste-token flow gated by `runtimeFlags.manualTokenLoginEnabled`.
- `frontend-svelte/src/lib/stores/auth.svelte.ts` — auth store (Svelte 5 runes-based). Holds session state, actor sub, roles. Read by route guards.
- `frontend-svelte/src/lib/config/runtime.ts` — runtime configuration loader. Defines `runtimeFlags.manualTokenLoginEnabled` per Phase A6 PR #67.
- `frontend-svelte/src/routes/(protected)/` — protected route group. Layout enforces auth.
- `frontend-svelte/src/lib/api/` — generated OpenAPI client. Currently sends Authorization header; PR-CL3-3 swaps to cookie + CSRF header.

### Phase A6 manualTokenLoginEnabled context

Per memory `project_phase_a6_pr4_landed`: PR #67 closed J-A6-10 by gating the dev paste-token flow behind `runtimeFlags.manualTokenLoginEnabled` with three reason codes; production builds hard-fail config error and refuse submission. The flag was a stop-gap until the production login flow exists. **PR-CL3-3 makes the production login flow exist (Clerk SDK), so the gate becomes obsolete.**

### Frontend dependency on backend interfaces

PR-CL3-3 consumes (does NOT modify):
- `POST /auth/session` (PR-CL3-2) — exchange Clerk session token for httpOnly cookie + CSRF token.
- `POST /auth/refresh` (PR-CL3-2) — rotate cookies + CSRF.
- `POST /auth/logout` (PR-CL3-2) — clear cookies.
- `GET /me` or equivalent — returns actor identity (sub, roles) for the auth store. If endpoint doesn't exist, PR-CL3-3 may need to add it (small backend addendum) OR rely on the response of `/auth/session` to seed the store.

Every frontend call to those backend auth endpoints MUST go through the configured backend origin (`VITE_API_BASE_URL`, currently exposed as `API_BASE` in `frontend-svelte/src/lib/api/fetch.ts`) or a shared API wrapper that prefixes it. Do not use relative `fetch("/auth/...")` from the static frontend; `frontend-svelte/nginx.conf` intentionally has no `/auth` or `/api` proxy in this wave.

Sweep for `GET /me` or `/auth/me` or `/users/me`:

```powershell
rg -nP '"/me"|"/auth/me"|"/users/me"' backend/app/api/routes/
```

If no current endpoint, the executor MUST decide: (a) add `GET /auth/me` as part of this PR (minimal backend addition acceptable since it's session-introspection, not RBAC); (b) seed store entirely from `/auth/session` response (returns actor_sub + csrf_token already; would need to add roles to the response).

## 4. Required Implementation Boundary

### 4.1 Install + configure `@clerk/clerk-js`

```bash
cd frontend-svelte
npm install @clerk/clerk-js
```

Config in `frontend-svelte/src/lib/clerk.ts` (NEW):

```typescript
import Clerk from "@clerk/clerk-js";

// TODO(post-cluster-3): swap from pk_test_... (dev) to pk_live_... (custom-domain)
const PUBLISHABLE_KEY = import.meta.env.PUBLIC_CLERK_PUBLISHABLE_KEY;

if (!PUBLISHABLE_KEY) {
  throw new Error("PUBLIC_CLERK_PUBLISHABLE_KEY missing — auth disabled");
}

export const clerk = new Clerk(PUBLISHABLE_KEY);

export async function initClerk(): Promise<void> {
  await clerk.load({
    // SvelteKit-friendly options — disable Clerk's own routing,
    // hand session-token exchange to our backend.
  });
}
```

Env var: `PUBLIC_CLERK_PUBLISHABLE_KEY` (Vite-prefixed `PUBLIC_` for client-side exposure). Set in `.env.example` with placeholder + TODO marker.

### 4.2 SignIn/SignUp pages

Replace `frontend-svelte/src/routes/(public)/login/+page.svelte` body:

```svelte
<script lang="ts">
  import { onMount } from "svelte";
  import { clerk, initClerk } from "$lib/clerk";
  import { goto } from "$app/navigation";
  import { API_BASE } from "$lib/api/fetch";
  import { authStore } from "$lib/stores/auth.svelte";

  let mountEl: HTMLDivElement;

  onMount(async () => {
    await initClerk();
    clerk.mountSignIn(mountEl, {
      // Clerk's hosted sign-in modal renders here
      afterSignInUrl: "/",
      afterSignUpUrl: "/",
    });

    // Listen for Clerk session change → exchange token + redirect
    clerk.addListener(async ({ session }) => {
      if (session) {
        const token = await session.getToken();
        if (!token) return;
        const response = await fetch(`${API_BASE}/auth/session`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "include",
          body: JSON.stringify({ session_token: token }),
        });
        if (!response.ok) {
          console.error("Session exchange failed", response.status);
          return;
        }
        const { actor_sub, csrf_token, roles } = await response.json();
        authStore.set({ actor_sub, csrf_token, roles, authenticated: true });
        goto("/");
      }
    });
  });
</script>

<div bind:this={mountEl}></div>
```

Add `frontend-svelte/src/routes/(public)/sign-up/+page.svelte` mirroring the structure with `clerk.mountSignUp(...)`.

### 4.3 Auth store wiring

Refactor `frontend-svelte/src/lib/stores/auth.svelte.ts`:

```typescript
import type { Writable } from "svelte/store";

interface AuthState {
  actor_sub: string | null;
  roles: string[];
  csrf_token: string | null;
  authenticated: boolean;
}

const initialState: AuthState = {
  actor_sub: null,
  roles: [],
  csrf_token: null,
  authenticated: false,
};

// Svelte 5 runes-based store
let _state = $state<AuthState>(initialState);

export const authStore = {
  get state() { return _state; },
  set(state: AuthState) { _state = state; },
  clear() { _state = initialState; },
  hasRole(role: string): boolean { return _state.roles.includes(role); },
  isTraderOnly(): boolean {
    return _state.roles.length === 1 && _state.roles[0] === "trader";
  },
};
```

The `isTraderOnly()` helper supports frontend conditional UI per matrix (e.g. hide broker/bank options in counterparty type select).

### 4.4 API client CSRF echo

In `frontend-svelte/src/lib/api/` (generated client wrapper):

- Read `csrf_token` cookie via `document.cookie` parsing OR keep store value from `/auth/session` response.
- On every fetch with method in `{"POST", "PATCH", "PUT", "DELETE"}`, add header `X-CSRF-Token: <token>`.
- All fetches MUST set `credentials: "include"` so the httpOnly cookie is sent.

Pattern:

```typescript
import { API_BASE } from "$lib/api/fetch";

function authedFetch(url: string, options: RequestInit = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("Content-Type", "application/json");
  if (["POST", "PATCH", "PUT", "DELETE"].includes((options.method || "GET").toUpperCase())) {
    const csrf = authStore.state.csrf_token;
    if (csrf) headers.set("X-CSRF-Token", csrf);
  }
  const absoluteUrl = url.startsWith("http") ? url : `${API_BASE}${url}`;
  return fetch(absoluteUrl, {
    ...options,
    headers,
    credentials: "include",
  });
}
```

The generated OpenAPI client may have a `fetch` injection point; use that. If not, wrap the generated client.

### 4.5 Logout

```svelte
<script lang="ts">
  import { clerk } from "$lib/clerk";
  import { authStore } from "$lib/stores/auth.svelte";
  import { goto } from "$app/navigation";
  import { API_BASE } from "$lib/api/fetch";

  async function logout() {
    await clerk.signOut();  // Clerk-side cleanup
    await fetch(`${API_BASE}/auth/logout`, { method: "POST", credentials: "include" });
    authStore.clear();
    goto("/login");
  }
</script>

<button onclick={logout}>Logout</button>
```

### 4.6 Refresh on TTL approach

```typescript
// In a layout-level effect or root +layout.svelte
import { API_BASE } from "$lib/api/fetch";

$effect(() => {
  if (!authStore.state.authenticated) return;
  const refreshInterval = setInterval(async () => {
    const response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: { "X-CSRF-Token": authStore.state.csrf_token ?? "" },
    });
    if (response.ok) {
      const { csrf_token } = await response.json();
      authStore.set({ ...authStore.state, csrf_token });
    } else if (response.status === 401) {
      authStore.clear();
      goto("/login");
    }
  }, 240_000);  // 4min — refresh before 5min TTL expires
  return () => clearInterval(refreshInterval);
});
```

### 4.7 Kill `manualTokenLoginEnabled`

- `frontend-svelte/src/lib/config/runtime.ts` — remove the `manualTokenLoginEnabled` flag definition + any associated reason-code constants.
- Sweep `rg -nP "manualTokenLoginEnabled" frontend-svelte/src/` — every site MUST be removed.
- The login page (§4.2) replaces the gated paste-token form entirely.
- Backend may have any reference (e.g. config endpoint exposing the flag) — sweep `rg -nP "manualTokenLoginEnabled" backend/app/` and remove.
- `.env.example` entries that set the flag — remove.

### 4.8 Route guard updates

Layout in `frontend-svelte/src/routes/(protected)/+layout.svelte` should redirect to `/login` if `!authStore.state.authenticated`. Ensure it calls `initClerk()` to attempt session restoration on cold load (Clerk SDK reads its own cookies + restores session state if user is still signed in).

## 5. Constitutional Rules

- `docs/governance.md` AUTHORIZATION MATRIX — frontend MUST conform to the role-driven UI semantics. Frontend SHOULD hide CRUD UI for type combinations the user can't write (defense in depth; backend enforces).
- `docs/governance.md` AUTHORIZATION MATRIX > Service identities — frontend never authenticates as a service identity; only human roles.

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes D-3.2 (frontend half) iff every item below is true.

### 6.1 Clerk SDK integration

- [ ] `@clerk/clerk-js` listed in `frontend-svelte/package.json` dependencies.
- [ ] `frontend-svelte/src/lib/clerk.ts` exists with the Clerk init pattern from §4.1.
- [ ] `PUBLIC_CLERK_PUBLISHABLE_KEY` documented in `.env.example` with `# TODO(post-cluster-3): swap to pk_live_...` marker.

### 6.2 Login + sign-up + logout

- [ ] `/login` page mounts Clerk sign-in via `clerk.mountSignIn`.
- [ ] `/sign-up` page mounts Clerk sign-up via `clerk.mountSignUp`.
- [ ] After Clerk sign-in, frontend calls `POST /auth/session` and seeds auth store.
- [ ] Logout button calls `clerk.signOut()` + `POST /auth/logout` + clears auth store.
- [ ] Auth session, refresh, and logout calls are routed through `API_BASE` / shared API wrapper, not relative `fetch("/auth/...")`.

### 6.3 Auth store

- [ ] `authStore` state shape includes `actor_sub`, `roles`, `csrf_token`, `authenticated`.
- [ ] `authStore.isTraderOnly()` helper exists.
- [ ] Store is cleared on logout.

### 6.4 API client CSRF

- [ ] All mutating fetches include `X-CSRF-Token` header sourced from auth store.
- [ ] All authenticated fetches set `credentials: "include"`.
- [ ] Sweep `rg -nP "Authorization.*Bearer|sessionStorage|localStorage" frontend-svelte/src/lib/api/` returns zero token-storage leaks.

### 6.5 Refresh

- [ ] Layout effect schedules refresh every 240s (4min) per §4.6.
- [ ] On 401 from refresh, store cleared + redirect to login.

### 6.6 manualTokenLoginEnabled killed

- [ ] `rg -nP "manualTokenLoginEnabled" frontend-svelte/src/` returns zero matches.
- [ ] `rg -nP "manualTokenLoginEnabled" backend/app/` returns zero matches.
- [ ] `rg -nP "manualTokenLoginEnabled" .env.example` returns zero matches.
- [ ] Login page no longer contains paste-token form.
- [ ] Reason-code constants from Phase A6 PR #67 (associated with the flag) removed.

### 6.7 Cross-cutting

- [ ] `docs/governance.md` diff is empty.
- [ ] `nginx.conf` diff is empty.
- [ ] No backend code change beyond optional `GET /auth/me` (if needed per §3 evaluation; otherwise zero backend diff).
- [ ] Frontend tests pass (`npm test` in `frontend-svelte/`).
- [ ] No new alembic migration.

## 7. Required Tests

### 7.1 Vitest unit tests

1. **`auth.svelte.test.ts`** — augment with: `isTraderOnly` returns true only when roles is exactly `["trader"]`, false for `["risk_manager", "trader"]` or `["auditor"]`.
2. **`runtime.test.ts`** — verify `manualTokenLoginEnabled` flag no longer exists in runtime config schema.

### 7.2 Playwright e2e

3. **`e2e/auth.spec.ts`** (NEW or augment existing):
   - Test: visit `/`, redirected to `/login`.
   - Test: complete Clerk sign-in (use Clerk's testing mode or mock), assert redirect to `/`, assert auth store populated.
   - Test: logout, assert redirect to `/login`, assert auth store cleared.
   - Test: protected route accessible after auth, blocked before.

Note: Clerk's e2e testing requires either Clerk's test mode (`pk_test_...` plus test instance config) or mocking the Clerk SDK. Pick the path Andrei prefers; document in PR body.

### 7.3 Visual regression on login page

4. The new login page is visually different from the paste-token UI. Capture a screenshot baseline + assert against it in Playwright.

## 8. Required Verification

```powershell
# Clerk SDK present
cd frontend-svelte ; npm list @clerk/clerk-js ; cd ..
rg -nP "@clerk/clerk-js" frontend-svelte/package.json

# Clerk init site
rg -nP "new Clerk\\(|clerk\\.load\\(|mountSignIn|mountSignUp" frontend-svelte/src/

# manualTokenLoginEnabled killed (every command MUST return zero)
rg -nP "manualTokenLoginEnabled" frontend-svelte/src/
rg -nP "manualTokenLoginEnabled" backend/app/
rg -nP "manualTokenLoginEnabled" .env.example

# CSRF echo
rg -nP "X-CSRF-Token" frontend-svelte/src/lib/api/
rg -nP "credentials.*include" frontend-svelte/src/lib/api/

# No token storage leaks
rg -nP "sessionStorage\\.setItem.*token|localStorage\\.setItem.*token" frontend-svelte/src/

# TODO markers for production swap
rg -nP "TODO\\(post-cluster-3\\)" frontend-svelte/src/

# Cross-wave isolation
git diff main -- backend/app/api/routes/        # zero (PR-CL3-1 + PR-CL3-2 territory)
git diff main -- backend/app/core/              # zero
git diff main -- frontend-svelte/nginx.conf     # zero (PR-CL3-4 territory)
git diff main -- docs/governance.md             # zero

# Alembic invariant
cd backend ; python -m alembic heads ; cd ..

# Test suites
cd frontend-svelte ; npm test ; cd ..
cd frontend-svelte ; npm run test:e2e ; cd ..
```

## 9. Out of Scope

- PR-CL3-1 territory: backend RBAC enforcement.
- PR-CL3-2 territory: backend Clerk JWT validation, cookie endpoints, CSRF middleware, service-account minting.
- PR-CL3-4 territory: nginx CSP, violation reporter, XSS-sink inventory.
- Custom domain Clerk publishable key (TODO post-cluster-3).
- Multi-tenant Clerk org switching UI.
- Sign-up email verification customization beyond Clerk defaults.
- Frontend role-based component visibility BEYOND `isTraderOnly()` helper. The matrix is server-enforced; UI hardening is incremental.
- Migrating away from SvelteKit's static adapter or changing build output.

## 10. PR Requirements

Title:
```
fix(audit-followup): close Cluster 3 PR-CL3-3 (Frontend Clerk SDK + httpOnly session + kill manualTokenLoginEnabled)
```

PR body:
- **Findings closed:** D-3.2 (frontend portion).
- **Files changed:** inventory grouped by Clerk integration / login pages / auth store / API client / killed legacy.
- **Env vars added:** `PUBLIC_CLERK_PUBLISHABLE_KEY`.
- **TODO markers:** every `TODO(post-cluster-3)` site cited.
- **Killed legacy:** explicit statement that `manualTokenLoginEnabled` (and Phase A6 PR #67's three reason codes) removed.
- **`/auth/me` decision:** if endpoint added in this PR, document why; else document the seed-from-session-response approach.
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-3-frontend-clerk-sdk-{sha}.json` per push.
- **Governance + alembic + nginx statements:** diffs empty.

## 11. Workflow

1. **Pre-step:** verify PR-CL3-2 has merged. Frontend depends on `/auth/session`, `/auth/refresh`, `/auth/logout`. If PR-CL3-2 not merged, PR-CL3-3 cannot be tested end-to-end.
2. `git checkout -b audit-followup/cluster-3-frontend-clerk-sdk`.
3. `cd frontend-svelte && npm install @clerk/clerk-js`.
4. Create `.env` entry `PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...` (dev value from Clerk dashboard).
5. Apply §4.1 (Clerk init module).
6. Apply §4.2 (SignIn/SignUp pages).
7. Apply §4.3 (auth store refactor).
8. Apply §4.4 (API client CSRF echo) — wrap or modify generated client.
9. Apply §4.5 (logout button).
10. Apply §4.6 (refresh effect).
11. Apply §4.7 (kill manualTokenLoginEnabled) — sweep frontend, backend, env.example.
12. Apply §4.8 (route guard updates).
13. Run §8 verification + Vitest + e2e locally.
14. Push branch, open PR per §10.
15. Codex Connector review is the final gate. **Do not merge.**

## 12. Hook v2 + Codex calibration notes

- **Expected hook v2 surface area:** medium-large (new Clerk init + 2 new login pages + auth store refactor + API client wrapper + refresh effect + legacy removal). Hook may flag prescription-vs-evidence on `@clerk/clerk-js` types before npm install completes.
- **Expected Codex catches:**
  - **Token leak in localStorage/sessionStorage** — Codex inspects every `localStorage.setItem` / `sessionStorage.setItem` call. Any token-shaped value caught.
  - **Missing `credentials: "include"`** on any authed fetch — cookie won't be sent, request 401s silently.
  - **CSRF header echo missed on a mutating route** — sweep all generated client methods.
  - **`manualTokenLoginEnabled` survivor** — Codex inspects all 3 layers (frontend, backend, env). Missing one → flag.
  - **Reason codes from PR #67 not cleaned up** — the three reason codes were tied to the gate; if gate gone, codes are dead. Codex may inspect.
  - **Refresh interval (240s) vs TTL (300s)** — must refresh BEFORE expiry; 240s is correct margin. Codex may flag if interval > TTL or no margin.
  - **Logout incomplete** — backend logout MUST clear cookies; frontend MUST clear store; Clerk-side MUST sign out. All three required.
  - **Clerk `addListener` cleanup** — not removing the listener on component unmount may leak callbacks across navigations. Codex may flag.
  - **`PUBLIC_CLERK_PUBLISHABLE_KEY` missing from `.env.example`** — without it, fresh clones fail at boot.
- **Padrão PR #79:** governance + dispatch precision matters. The matrix doesn't mention a viewer role; frontend MUST not introduce one accidentally via UI affordances.
- **8-section sweep:** §4 boundary, §6 acceptance, §7 tests, §8 verification, §11 workflow MUST consistently enumerate the same deliverables (Clerk init, login pages, auth store, API client CSRF, refresh, logout, killed legacy). Drift is the canonical authoring failure mode.
- **The largest implementation risk** is the API client CSRF wrapping. The generated client may have inconsistent fetch injection across modules; missing one method = silent CSRF bypass test passes locally but mutating routes 403 in prod. Mitigation: sweep `rg -nP "fetch\\(" frontend-svelte/src/lib/api/` and confirm every match goes through the wrapper.
