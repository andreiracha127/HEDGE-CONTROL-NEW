# Phase A6 Remediation Dispatch - PR-A6-4 Reconstructability Surfaces

**Phase:** A6 - Frontend Svelte institutional control surface
**Wave:** PR-A6-4
**Authoring date:** 2026-05-12
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main`
**Required branch:** `audit-a6/reconstructability-surfaces`
**Source verdict:** `docs/audits/2026-05-12-phase-a6-jury-verdict.md`

## 1. Objective

Close:

- `J-A6-08` - Expose orders as reconstructible exposure source records.
- `J-A6-09` - Surface signed audit events and verification for auditor
  workflows.
- `J-A6-10` - Gate dev-only manual JWT login before production use.

This wave adds read-only reconstructability surfaces and prevents the
development token-paste login from being normalized as a production workflow.

## 2. Non-Negotiable Constraints

- Do not edit `docs/governance.md`.
- Do not implement order create/archive/link mutations in this wave.
- Do not make audit pages mutating or administrative beyond read/verify.
- Do not expose signed audit payloads to roles that the backend would reject.
- Do not design a full identity-provider integration in this wave.
- Do not weaken the existing local/development manual-token workflow; gate it
  explicitly by environment/configuration.

This wave is about reconstructability and operator/auditor visibility, not
about adding new economic mutations.

## 3. Findings and Evidence

### J-A6-08 - Orders not visible as source records

Accepted evidence:

- `frontend-svelte/src/routes/+layout.svelte:29` has no orders route.
- `frontend-svelte/src/routes/(protected)/+page.svelte:9` dashboard links do
  not include orders.
- `rg --files frontend-svelte/src/routes` shows no routed orders page.
- `docs/api/openapi_v1.json:10015` exposes `/orders`.
- `docs/api/openapi_v1.json:10224` exposes `/orders/purchase`.
- `docs/api/openapi_v1.json:10265` exposes `/orders/sales`.
- `docs/api/openapi_v1.json:10306` exposes `/orders/{order_id}`.
- `frontend-svelte/src/routes/(protected)/exposures/+page.svelte:24` surfaces
  exposure aggregates without source order detail.

### J-A6-09 - Audit events and verification not visible

Accepted evidence:

- `frontend-svelte/src/routes/+layout.svelte:29` has no audit route.
- `rg --files frontend-svelte/src/routes` shows no routed audit page.
- `frontend-svelte/src/lib/stores/auth.svelte.ts:3` defines the `auditor` role.
- `docs/api/openapi_v1.json:7175` exposes `/audit/events`.
- `docs/api/openapi_v1.json:7303` exposes `/audit/events/{event_id}/verify`.

### J-A6-10 - Dev-only manual JWT login

Accepted evidence:

- `frontend-svelte/src/routes/(public)/login/+page.svelte:19` stores a pasted
  token through `authStore.login`.
- `frontend-svelte/src/routes/(public)/login/+page.svelte:32` asks users to
  paste a JWT.
- `frontend-svelte/src/routes/(public)/login/+page.svelte:57` labels itself as
  development manual-token authentication.
- `frontend-svelte/src/lib/stores/auth.svelte.ts:41` decodes the token
  client-side without a backend login exchange.

## 4. Required Implementation Boundary

### Read-Only Orders Surface

Add a read-only protected orders surface:

- list route for `/orders`;
- detail route for `/orders/{order_id}`;
- display canonical order id, order type, commodity, quantity MT, price type,
  pricing convention, counterparty context where available, lifecycle/status,
  and linked exposure context when available;
- link from exposure/source contexts where stable ids are available;
- do not add create/archive/link forms in this wave.

### Read-Only Audit Surface

Add a read-only protected audit surface:

- list route for `/audit/events` with deterministic ordering and basic filters
  supported by the backend contract;
- detail or inline verification action using `/audit/events/{event_id}/verify`;
- show entity type/id, event type, actor/user, created timestamp, verification
  status, and enough payload context for auditors to inspect evidence;
- hide or disable the route for roles that should not see audit evidence,
  without treating frontend role gating as the security boundary.

### Dev Login Gate

Gate the manual JWT paste login:

- manual token login must be explicitly enabled only in development/test/local
  builds or with a clearly named frontend runtime/build flag;
- production mode must not present the token paste form as the normal login
  flow;
- if no production login is configured, show a hard-fail configuration message
  rather than silently allowing a dev-only flow;
- preserve local developer usability when the flag/env indicates local/dev/test.

## 5. Acceptance Criteria

- `/orders` and `/orders/{id}` frontend routes exist and are read-only.
- Orders route displays enough canonical fields to reconstruct exposure source
  records.
- `/audit/events` frontend route exists and is read-only.
- Audit route can call verify endpoint and display verification result.
- Audit route is visible only to auditor/risk-manager role surfaces, or the PR
  explicitly documents the chosen role policy.
- Manual JWT paste login is gated by dev/local/test config and is not the
  default production flow.
- No order mutation UI is added in this wave.
- `docs/governance.md` has no diff.

## 6. Required Tests

Add or update focused frontend tests.

Minimum coverage:

- orders list route calls `/orders`;
- order detail route calls `/orders/{order_id}`;
- orders route renders canonical id and quantity fields from a mocked response;
- audit events route calls `/audit/events`;
- audit verification action calls `/audit/events/{event_id}/verify` and renders
  valid/invalid/unverifiable status distinctly;
- role visibility for audit navigation is covered;
- production-mode login does not show the token paste form unless the explicit
  dev-login flag is enabled;
- local/dev/test mode keeps manual token login usable.

## 7. Required Verification

Run, at minimum:

```bash
cd frontend-svelte
npm run check
npm test
npm run build
```

Also run and report:

```bash
rg -n "href: '/orders'|href: '/audit'|/orders|/audit/events|manual-token|JWT|VITE_|import\\.meta\\.env" frontend-svelte/src frontend-svelte/package.json
git diff --check
```

Confirm that the backend `/audit/events` and
`/audit/events/{event_id}/verify` endpoints enforce authenticated role
authorization for the intended auditor/risk-manager audience. Do not treat
frontend navigation visibility as the security boundary.

If new Playwright tests are added, run:

```bash
cd frontend-svelte
npm run test:e2e
```

If the backend/test stack is not available for E2E locally, report that and rely
on GitHub E2E.

## 8. Out of Scope

- Order creation, archive, update, or link mutation UI.
- Full audit administration or audit deletion/update actions.
- Production identity-provider selection or backend auth redesign.
- Endpoint repair, settlement/RFQ evidence, and financial precision fixes from
  PR-A6-1 through PR-A6-3.

## 9. PR Requirements

- Use branch `audit-a6/reconstructability-surfaces`.
- Push normally; do not use `--no-verify`.
- Open a PR against `main`.
- Include in the PR body:
  - findings closed;
  - files changed;
  - tests run and results;
  - login gating decision;
  - audit/order route screenshots or route-test evidence if available;
  - hook artifact path;
  - statement that `docs/governance.md` has no diff.
