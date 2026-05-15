# Amendment to Cluster 3 PR-CL3-3 Dispatch — Scope Reconciliation after PR-CL3-2 Transport Partner Delivery

**Amendment date:** 2026-05-15
**Original dispatch:** `docs/audits/2026-05-14-cluster-3-pr-3-frontend-clerk-sdk-dispatch.md` (landed via PR #80)
**Trigger:** PR #82 (Cluster 3 PR-CL3-2, merged to main `f5320c006` 2026-05-15) delivered the frontend cookie/CSRF/WS transport partner patch within PR-CL3-2's scope expansion accepted by orchestrator code review.
**Status:** binding — supersedes the cited sections of the original dispatch.

## 0. Amendment context

Per institutional feedback class [[feedback_dispatch_transport_partner_clause]] (saved 2026-05-15): when a backend dispatch ships a new transport contract (cookie set/clear, CSRF header expectations, JWT validation pipeline, protocol-header semantics) AND a sibling wave is tasked with client-side consumption, the backend dispatch MUST pre-authorize the minimum-viable client patch needed. PR-CL3-2 retroactively absorbed this client patch after its executor surfaced the implicit dependency mid-flight; orchestrator code-review verdict 2026-05-15 classified the patch as institutionally SOUND.

The artifact this amendment captures: the partition of original PR-CL3-3 scope into (a) "delivered in PR-CL3-2, do not re-implement", and (b) "remaining in PR-CL3-3". Without this amendment, the PR-CL3-3 executor would either duplicate symbols already shipped (Codex catches as redundancy / drift) or treat the dispatch as obsolete and improvise (silent scope violation).

This amendment is constitutional. It does not edit the original dispatch text; it supersedes specific sections by reference. Future executor handoffs MUST cite both the original dispatch AND this amendment.

## 1. Delivered in PR-CL3-2 — DO NOT re-implement

All citations are to merged state at `main @ f5320c006`. The executor must verify each citation exists at the rebase HEAD before consuming; if any has drifted, halt and report.

### Auth store (original dispatch §4.3)

Original dispatch §4.3 prescribed an interface-based auth store. PR-CL3-2 shipped a class-based runes implementation in [`frontend-svelte/src/lib/stores/auth.svelte.ts`](../../frontend-svelte/src/lib/stores/auth.svelte.ts):

- Singleton `authStore = new AuthStore()` (line 325)
- `authStore.isAuthenticated` — `$derived` from claims presence (line 36)
- `authStore.isRestoring` — `$derived` cold-load hydration flag (line 37)
- `authStore.establishSession(sessionToken)` — POSTs `/auth/session` with `{session_token}` (line 67); replaces the static `set()` setter from the original dispatch
- `authStore.hasRole(role: UserRole)` — checks `roles` array (line 127); `UserRole` type union `'trader' | 'risk_manager' | 'auditor'` defined at line 3
- `authStore.getCsrfToken()` — cookie-first fallback per orchestrator-absorbed Codex catch "Prefer the current CSRF cookie over cached state" (line 123)
- `authStore.logout()` — clears claims + invokes `#clearBackendSession(csrf)` background POST to `/auth/logout` with `keepalive: true` (lines 100-101)
- `#setupSessionRefresh` — schedules `#refreshBackendSession` at `MAX_AGE_MS - REFRESH_LEAD_MS = 300s - 60s = 240s` (method signature line 164; `refreshDelay` computation line 166)
- `#refreshBackendSession` — POSTs `/auth/refresh`; body shape `{session_token: token}` when a token is cached, else `{}` (lines 268-285) ⚠️ see §3.1 below — this contract IS amended for PR-CL3-3
- `#restoreSession` — cold-load hydration via `/auth/me` then immediate `#refreshBackendSession` to reset 5-min lease (lines 183-263)
- `SESSION_COOKIE_MAX_AGE_MS` (line 16), `SESSION_COOKIE_REFRESH_LEAD_MS` (line 17), `CSRF_COOKIE_NAME` (line 14), `API_BASE` (line 15) — constants
- **Refresh 401 → redirect to login** — `#refreshBackendSession` invokes `this.logout()` on any non-OK response (line 289); `logout()` calls `goto('/login')` (line 111). PR-CL3-3 must NOT re-implement this behavior; verify it remains intact post-Clerk-SDK integration.

**PR-CL3-3 obligation:** consume `authStore` as-is. Do not redefine the class. Do not replace runes with stores. Adjust ONLY the call sites that need Clerk SDK integration (see §2 below).

### API client CSRF + credentials (original dispatch §4.4)

In [`frontend-svelte/src/lib/api/fetch.ts`](../../frontend-svelte/src/lib/api/fetch.ts):
- `MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])` (line 4)
- `X-CSRF-Token` injection for mutating methods (line 14)
- `credentials: 'include'` on every authenticated fetch (line 19)

In [`frontend-svelte/src/lib/api/client.ts`](../../frontend-svelte/src/lib/api/client.ts):
- Raw `fetch` wrapper with `credentials: 'include'` (line 9)
- `client.use({ onRequest })` middleware reading `authStore.getCsrfToken()` and setting `X-CSRF-Token` on mutating methods (lines 13-16)

**PR-CL3-3 obligation:** the §4.4 dispatch contract is fully delivered. Do not re-author. Do not split the wrapper. Do not bypass `apiFetch` or the openapi-fetch client for any new mutating call introduced by Clerk SDK integration — route through the existing helpers.

### Route guard hydration (original dispatch §4.8)

In [`frontend-svelte/src/routes/(protected)/+layout.svelte`](../../frontend-svelte/src/routes/(protected)/+layout.svelte): `!isAuthenticated && !isRestoring` guard at line 9 prevents premature redirect during cold-load `/auth/me` hydration. Codex catch "Gate redirects while cookie restore is pending" absorbed in PR-CL3-2 cycle 1.

**PR-CL3-3 obligation:** the cold-load hydration gate is delivered. Do not move the redirect logic outside the layout. Keep the gate intact when adding Clerk-side `initClerk()` boot — Clerk loading is orthogonal to backend cookie restoration, both must complete before the auth decision.

### WebSocket auth (original dispatch §4.8 WebSocket clause)

In [`frontend-svelte/src/lib/stores/ws.svelte.ts`](../../frontend-svelte/src/lib/stores/ws.svelte.ts): cookie+CSRF fallback when `authStore.getToken()` returns null. Cookie-based WS auth requires permitted `Origin` + `csrf_token == __Session.csrf_token` per PR-CL3-2 cycle 3 P2 absorption (`fix(auth): bind cookie websocket auth to csrf`).

**PR-CL3-3 amendment:** the original dispatch §4.8 WebSocket clause proposed "obtain a fresh Clerk token at connect time with `await clerk.session?.getToken({ skipCache: true })`". This path is **superseded**. Cookie-based WS auth is the canonical transport going forward; the Clerk-SDK-token-at-connect-time alternative is obsolete. Do not add `clerk.session.getToken` to the WS path. The cookie+CSRF+Origin binding shipped in PR-CL3-2 is sufficient and the backend WS handshake validates it via the same `_validate_human_roles_at_jwt_time` invariant added in PR-CL3-2 cycle 2 (`backend/app/api/routes/ws.py:32, :80`).

**Cached Clerk JWT must not pre-empt the cookie path.** `establishSession` stores JWT in `AuthStore.#token` (`auth.svelte.ts:96`); `ws.svelte.ts:61-66` Bearer-prefers `authStore.getToken()` when non-null. Post-Clerk-sign-in WS would bypass the cookie path, defeating canonical status. PR-CL3-3 MUST stop caching the JWT in `#token` at `establishSession` AND ensure refresh success calls `#applySession(null, claims, nextCsrf)` (not Clerk JWT, `auth.svelte.ts:303`) — cookie SSoT; #token dead weight post-§3.1. Add `ws.svelte.test.ts` regression: after `establishSession(jwt)` + post-refresh (cookie session), WS first-message uses cookie+CSRF (not Bearer).

## 2. Remaining in PR-CL3-3 scope (verbatim from original dispatch unless noted)

### Unchanged from original dispatch

- **§4.1 Clerk SDK install + config** — `npm install @clerk/clerk-js` in `frontend-svelte/`, create `lib/clerk.ts` with `initClerk()`, `VITE_CLERK_PUBLISHABLE_KEY` env var. **Add `.env.example` entry per §10 (PR body must cite).** No change from original.
- **§4.2 SignIn/SignUp pages** — replace `frontend-svelte/src/routes/(public)/login/+page.svelte` body with `clerk.mountSignIn` (NEW); add `(public)/sign-up/+page.svelte` with `clerk.mountSignUp`. **AMENDED:** the `clerk.addListener` handler MUST call `authStore.establishSession(token)` (PR-CL3-2 delivered) instead of inlining the `/auth/session` + `/auth/me` fetch chain. Do not write a new exchange flow; reuse the store method.
- **§4.5 Logout** — UNCHANGED. Wire a logout button that calls `clerk.signOut()` THEN `authStore.logout()` (PR-CL3-2 delivered). The original dispatch's manual `fetch(/auth/logout)` + `authStore.clear()` chain is superseded by `authStore.logout()` which already handles the background `/auth/logout` POST with `keepalive: true`. Order: `clerk.signOut()` first (Clerk-side session terminated), then `authStore.logout()` (backend cookie cleared + store reset).
- **§4.7 Kill `manualTokenLoginEnabled`** — UNCHANGED. Sweep `rg -nP "manualTokenLoginEnabled" frontend-svelte/src/ backend/app/` MUST return zero. Current survivors verified by orchestrator 2026-05-15:
  - `frontend-svelte/src/lib/config/runtime.ts` (flag definition)
  - `frontend-svelte/src/lib/config/runtime.test.ts` (8 references — all to be deleted along with the flag's test coverage)
  - `frontend-svelte/src/lib/api/reconstructability-surfaces.test.ts` — **delete both J-A6-10 `describe` blocks entirely**: (a) lines ~140-168 `describe('login page — J-A6-10 dev-login gating', ...)` with 4 `it` assertions covering `manualTokenLoginEnabled` import, `data-testid="login-config-error"`, `!manualLoginEnabled` submission refusal, `manualTokenLoginReason` dev banner — every cited symbol is removed when the gate dies; (b) lines ~170-180 `describe('runtime config — J-A6-10 build-flag location', ...)` with the `VITE_ALLOW_MANUAL_TOKEN_LOGIN` env-var assertion — the env var disappears alongside the flag. Verify exact line ranges at rebase via `rg -nP "J-A6-10" frontend-svelte/src/lib/api/reconstructability-surfaces.test.ts` and delete the matched `describe` blocks in full.
  - `.env.example` entries (if any)
  - Phase A6 PR #67 three reason-code constants — to be removed entirely
- **§4.8 Route guard updates** — partially delivered (cold-load hydration gate, see §1 above). Remaining: ensure `initClerk()` boot runs alongside (or before) `authStore.#restoreSession()` so the SignIn page can mount Clerk's modal once Clerk is loaded. The hydration order should be: route enters → `initClerk()` AND `authStore.#restoreSession()` both fire → `isAuthenticated` resolves → redirect decision.

### Amended (replaces original prescription)

#### §3.1 Refresh contract amendment — fresh Clerk token integration

Original dispatch §4.6 prescribed:
```typescript
const token = await clerk.session?.getToken({ skipCache: true });
// ... POST /auth/refresh with { session_token: token }
```

PR-CL3-2 shipped `#refreshBackendSession()` at [`auth.svelte.ts:268`](../../frontend-svelte/src/lib/stores/auth.svelte.ts) which posts `{session_token: token}` if a cached token exists (line 285) else `{}`. The CACHED token is whatever `establishSession` last received — initially fresh, but stale by the 240s refresh tick if Clerk has rotated.

**PR-CL3-3 must extend `#refreshBackendSession` (or wrap it via a public helper) to call `await clerk.session?.getToken({ skipCache: true })` and pass the FRESH token to `/auth/refresh`.** Options:
- (A) Add a `setClerkSessionProvider(fn: () => Promise<string | null>)` method to `authStore` that PR-CL3-3 wires once at boot via `clerk.session`. `#refreshBackendSession` checks the provider first, falls back to cached token if provider is unset (preserves PR-CL3-2 backward compatibility for non-Clerk transport modes).
- (B) Move `#refreshBackendSession` to a public method, override at boot time from the Clerk init module.

Option (A) is preferred (minimal coupling, keeps the store agnostic to Clerk SDK). Acceptance criterion in §4 below.

**Stale-token guard must be reworked alongside option (A):** the existing `#refreshBackendSession` body has `if (this.#token !== token) return;` at `auth.svelte.ts:287` — an early-return guard that compares the captured `const token = this.#token` (line 270) against the current `this.#token` after the await. For cookie-restored sessions (Clerk session arrived via `/auth/me` hydration, not via `establishSession`), `this.#token === null` while the provider returns a fresh non-null Clerk JWT, making `this.#token !== token` always true and silently skipping cookie/CSRF rotation. PR-CL3-3 MUST replace this guard with one that does not depend on `this.#token` equality — for example a session generation counter (`#generation++` on every `establishSession`/`restoreSession`/`logout`, captured before the await, compared after), or a `this.#claims` identity check, or an explicit cancellation token. Document the chosen strategy in the PR body.

#### §3.2 `isTraderOnly()` helper — NOT delivered by PR-CL3-2

Original dispatch §4.3 prescribed `authStore.isTraderOnly()`. PR-CL3-2 shipped `hasRole(role)` but NOT `isTraderOnly()`. Add the helper as an additional method on the existing `AuthStore` class:

```typescript
isTraderOnly(): boolean {
  return this.userRoles.length === 1 && this.userRoles[0] === 'trader';
}
```

(Confirmed: `userRoles` is defined at `auth.svelte.ts:38` as `readonly userRoles = $derived<UserRole[]>(this.#claims?.roles ?? [])` — verified at baseline `f5320c006`; verify still present at rebase HEAD.)

#### §3.3 Refresh fallback to login on 401 — DELIVERED, not remaining work

**Correction (per Codex inline catch on PR #83 review of SHA `ec3fc1e`):** the original draft of this section erroneously claimed PR-CL3-2's `#refreshBackendSession` does not redirect on 401. Verification of merged baseline `f5320c006`:

- `auth.svelte.ts:288-290` — any non-OK response from `/auth/refresh` triggers `this.logout()`
- `auth.svelte.ts:99-112` — `logout()` clears claims, tokens, timers, and calls `goto('/login')` at line 111 (guarded by `#redirecting` flag to prevent double-redirect)

The 401 → redirect chain is fully delivered. PR-CL3-3 has NO obligation to add or re-author this behavior. The only PR-CL3-3 responsibility is to verify the chain remains intact after Clerk SDK boot is wired (i.e. Clerk SDK side effects must not interfere with `logout()` or the `#redirecting` guard).

### Dropped (no longer applicable)

- **WebSocket "fresh Clerk token at connect time" alternative** (original §4.8 WS clause) — see §1 WebSocket subsection above. Cookie-based WS auth is canonical; do not introduce a competing path.

## 4. Amended Acceptance Criteria

Replaces original dispatch §6 with this consolidated list. Inherits unchanged items by reference (cite original §6.X if needed).

### 4.1 Clerk SDK integration (unchanged §6.1)

- [ ] `@clerk/clerk-js` in `frontend-svelte/package.json` dependencies
- [ ] `frontend-svelte/src/lib/clerk.ts` with `initClerk()` per original §4.1
- [ ] `VITE_CLERK_PUBLISHABLE_KEY` in `.env.example` with `# TODO(post-cluster-3)` swap marker

### 4.2 Login / SignUp / Logout (amended §6.2)

- [ ] `/login` mounts `clerk.mountSignIn` with Core 2 routing options
- [ ] `/sign-up` mounts `clerk.mountSignUp` with Core 2 routing options
- [ ] **`addListener` handler calls `authStore.establishSession(token)`** — does NOT re-implement the `/auth/session` + `/auth/me` exchange chain (delivered in PR-CL3-2)
- [ ] Logout button calls `clerk.signOut()` THEN `authStore.logout()` (in this order; both required)
- [ ] No relative `/auth/...` fetch calls outside the `authStore` helpers (PR-CL3-2 `API_BASE` discipline preserved)

### 4.3 Auth store consumption (amended §6.3)

- [ ] `authStore` class and singleton at `auth.svelte.ts:325` reused as-is; not redefined
- [ ] **NEW** `isTraderOnly()` method added per §3.2
- [ ] **NEW** Clerk session-token provider wired per §3.1 option (A) or (B); chosen path documented in PR body
- [ ] **NEW** `#refreshBackendSession` stale-token guard at `auth.svelte.ts:287` reworked per §3.1 stale-token-guard amendment (generation counter / claims-identity check / cancellation token); chosen strategy documented in PR body. Test: cookie-restored session (no `establishSession` call, only `/auth/me` hydration) refresh tick MUST trigger `/auth/refresh` and rotate cookies+CSRF, NOT early-return
- [ ] Refresh 401 → `logout()` → `goto('/login')` chain (DELIVERED in PR-CL3-2; verify intact post-Clerk-SDK boot)

### 4.4 API client CSRF / credentials (DELIVERED §6.4 — no PR-CL3-3 change required)

- [ ] `git diff main -- frontend-svelte/src/lib/api/fetch.ts frontend-svelte/src/lib/api/client.ts` returns empty for `credentials` and `X-CSRF-Token` logic (the lines exist verbatim from PR-CL3-2; PR-CL3-3 only adds NEW call sites if needed for Clerk-related operations)
- [ ] Any NEW mutating fetch introduced by PR-CL3-3 routes through `apiFetch` or the openapi-fetch `client` — not a bare `fetch(...)`

### 4.5 Refresh on TTL (amended §6.5)

- [ ] Layout effect at 240s interval (PR-CL3-2 delivered via `#setupSessionRefresh`); PR-CL3-3 does not duplicate
- [ ] Refresh invokes `await clerk.session?.getToken({ skipCache: true })` and passes to `/auth/refresh` per §3.1 amendment
- [ ] Refresh 401 → `logout()` chain DELIVERED in PR-CL3-2 (`auth.svelte.ts:288-290` → `:99-112`); PR-CL3-3 only verifies it remains intact (no Clerk SDK side effect breaks the `#redirecting` guard or `goto('/login')`)

### 4.6 `manualTokenLoginEnabled` killed (unchanged §6.6, expanded survivor list)

- [ ] `rg -nP "manualTokenLoginEnabled" frontend-svelte/src/` returns zero
- [ ] `rg -nP "manualTokenLoginEnabled" backend/app/` returns zero
- [ ] `rg -nP "manualTokenLoginEnabled" .env.example` returns zero
- [ ] `frontend-svelte/src/lib/config/runtime.ts` flag definition removed
- [ ] `frontend-svelte/src/lib/config/runtime.test.ts` flag-related tests deleted (8 references current)
- [ ] `frontend-svelte/src/lib/api/reconstructability-surfaces.test.ts` — **both J-A6-10 `describe` blocks deleted** in full (dev-login gating ~140-168 + runtime-config build-flag location ~170-180); `rg -nP "J-A6-10|manualTokenLoginEnabled|VITE_ALLOW_MANUAL_TOKEN_LOGIN" frontend-svelte/src/lib/api/reconstructability-surfaces.test.ts` MUST return zero post-deletion
- [ ] Phase A6 PR #67 three reason-code constants removed
- [ ] Login page no longer contains paste-token form
- [ ] Protected layout hydrates `/auth/me` before redirecting on cold load (DELIVERED §1 above)

### 4.7 WebSocket (amended §6.X — WebSocket clause)

- [ ] No `clerk.session.getToken` call introduced in `ws.svelte.ts` or related — cookie-based WS auth is canonical (DELIVERED §1 above)
- [ ] `_validate_human_roles_at_jwt_time` enforcement on WS continues to work post-Clerk-SDK boot (no regression via Clerk SDK side effects on cookie state)
- [ ] **NEW** `establishSession` + refresh success stop caching Clerk JWT in `#token` (#applySession(null, claims, csrf) for refresh per §3.1; cookie SSoT)
- [ ] **NEW** Regression test in `ws.svelte.test.ts` asserts post-`establishSession(jwt)` + `/auth/me` hydration, WS first-message uses cookie+CSRF — not Bearer

### 4.8 Cross-cutting (unchanged §6.7)

- [ ] `docs/governance.md` diff empty
- [ ] `nginx.conf` diff empty
- [ ] No backend code change
- [ ] Single alembic head remains `044_drop_deal_lifecycle_fields`
- [ ] **NEW** `git diff main -- frontend-svelte/src/lib/stores/auth.svelte.ts frontend-svelte/src/lib/api/fetch.ts frontend-svelte/src/lib/api/client.ts` shows only the additions amended above (no rewrites of PR-CL3-2 surface)

## 5. Amended Verification Sweeps

Add to original §8 verification block:

```powershell
# Verify PR-CL3-2 surface preserved
rg -nP "class AuthStore" frontend-svelte/src/lib/stores/auth.svelte.ts            # must match line 26
rg -nP "establishSession|getCsrfToken|hasRole|#refreshBackendSession" frontend-svelte/src/lib/stores/auth.svelte.ts   # all 4 must appear
rg -nP "MUTATING_METHODS" frontend-svelte/src/lib/api/fetch.ts frontend-svelte/src/lib/api/client.ts   # must match PR-CL3-2 lines

# Verify isTraderOnly added
rg -nP "isTraderOnly" frontend-svelte/src/lib/stores/auth.svelte.ts               # MUST match the new method

# Verify Clerk session-token provider wired
rg -nP "clerk\.session\?\.getToken\(.*skipCache: true" frontend-svelte/src/      # MUST match exactly one call site (refresh path)

# Verify NO new manual /auth/* fetches outside the store (delivered surface in auth.svelte.ts is allowed; new call sites elsewhere are forbidden)
rg -nP 'fetch\(`?\$\{?API_BASE\}?/auth/(session|refresh|logout|me)' frontend-svelte/src/ --glob '!**/stores/auth.svelte.ts' --glob '!**/lib/clerk.ts'    # MUST be zero — only auth.svelte.ts (delivered) and the new lib/clerk.ts (this wave's init module if it makes any auth lifecycle call) are allowed to host these fetches

# Verify no scope creep into PR-CL3-2 territory
git diff main -- frontend-svelte/src/lib/api/fetch.ts | rg -nP '^[+-].*credentials|^[+-].*X-CSRF-Token'    # MUST be zero
git diff main -- frontend-svelte/src/lib/api/client.ts | rg -nP '^[+-].*credentials|^[+-].*X-CSRF-Token'  # MUST be zero
```

## 6. Amended Workflow

Replaces original §11 step 1-15 with:

1. **Pre-step:** verify PR-CL3-2 merged. Rebase HEAD on `main @ f5320c006` or later. Verify every PR-CL3-2 citation in §1 still exists at the rebase HEAD; if any drifted, halt and report.
2. Create branch `audit-followup/cluster-3-frontend-clerk-sdk` from rebased main.
3. `cd frontend-svelte && npm install @clerk/clerk-js`.
4. Add `VITE_CLERK_PUBLISHABLE_KEY=pk_test_...` to `.env` (dev value from Clerk dashboard) and `.env.example` with TODO marker.
5. Apply original §4.1 (`lib/clerk.ts` + `initClerk`).
6. Apply original §4.2 with §3 amendment (SignIn/SignUp pages call `authStore.establishSession`).
7. Apply §3.2 (`isTraderOnly()` helper).
8. Apply §3.1 (Clerk session-token provider for refresh) — preferred option (A).
9. Apply original §4.5 with amendment (logout calls `clerk.signOut()` then `authStore.logout()`).
10. Apply §3.3 (refresh-401 redirect to login).
11. Apply original §4.7 (kill `manualTokenLoginEnabled` — expanded survivor list per §4.6 above).
12. Verify §4.8 route-guard cold-load hydration AND refresh-401-redirect chain still work post-Clerk-init coexistence.
13. Run §5 amended verification + original §8 sweep + Vitest + e2e.
14. Push branch, open PR per original §10. Title format unchanged; PR body must include this amendment URL.
15. Codex Connector review is the final gate. **Do not merge.**

## 7. Hook + Codex calibration (additive to original §12)

Existing original §12 predictions stand. Add:

- **Duplication catches** — Codex will flag any re-implementation of PR-CL3-2 surface (auth store class, CSRF middleware logic, etc.). Adjudicate as "delivered in PR-CL3-2 SHA `f5320c006` — see amendment §1".
- **Refresh provider catch** — Codex may flag that `#refreshBackendSession` posts a stale cached token. The §3.1 amendment requires PR-CL3-3 to wire a fresh-token provider. Acceptance criterion at §4.5.
- **`isTraderOnly` absence catch** — Codex will check that the helper exists per the original §4.3 contract. Verified missing as of `f5320c006`.
- **WS Clerk-token regression catch** — if PR-CL3-3 accidentally introduces `clerk.session.getToken` to the WS path, Codex will flag it as a regression of the cookie-based WS auth shipped in PR-CL3-2. Adjudicate "out of scope per amendment §1 WebSocket subsection".
- **manualTokenLoginEnabled survivors in test files** — the runtime.test.ts (8 references) and reconstructability-surfaces.test.ts:146-148 are likely Codex blind spots if PR-CL3-3 only deletes the flag definition. Sweep `rg -nP manualTokenLoginEnabled` across the full `frontend-svelte/` tree, not just `src/lib/config/`.

## 8. Cross-references

- Original dispatch: `docs/audits/2026-05-14-cluster-3-pr-3-frontend-clerk-sdk-dispatch.md`
- Source-of-truth for delivered surface: PR #82 merge commit `f5320c006`
- Cluster 3 platform decisions (Clerk + httpOnly bindado 2026-05-14): governed by `docs/governance.md` AUTHORIZATION MATRIX + memory `project_cluster_3_platform_decisions`
- Institutional precedent: PR #79 (governance.md amendment via PR) — same pattern applied here for dispatch amendment
- Companion feedback class: `feedback_dispatch_transport_partner_clause` (created 2026-05-15)
