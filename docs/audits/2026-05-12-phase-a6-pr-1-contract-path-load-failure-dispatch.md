# Phase A6 Remediation Dispatch - PR-A6-1 Contract Path and Load-Failure Discipline

**Phase:** A6 - Frontend Svelte institutional control surface
**Wave:** PR-A6-1
**Authoring date:** 2026-05-12
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main`
**Required branch:** `audit-a6/contract-path-load-failure-discipline`
**Source verdict:** `docs/audits/2026-05-12-phase-a6-jury-verdict.md`

## 1. Objective

Close:

- `J-A6-01` - Align frontend API paths with the generated OpenAPI contract.
- `J-A6-05` - Surface non-2xx mutation failures instead of silently clearing
  in-flight state.
- `J-A6-07` - Enforce typed contract paths or static route drift guards.

This wave restores basic route/API connectivity and prevents failed backend
responses from becoming silent frontend fallbacks. It is intentionally limited
to broken endpoint paths, explicit error surfacing, and drift guards for the
repaired call sites.

## 2. Non-Negotiable Constraints

- Do not edit `docs/governance.md`.
- Do not implement PR-A6-2 settlement/RFQ evidence fixes in this wave, except
  that the contract status path itself may be corrected because it is part of
  `J-A6-01`.
- Do not add backend endpoints merely to match stale frontend strings.
- Do not normalize failed loads into empty arrays, zero totals, or "no data"
  states when the backend returned non-2xx.
- Do not broadly migrate the whole frontend to the typed client. Use typed
  calls or static drift guards only for the call sites touched in this wave.
- Do not regenerate schemas blindly. If schema drift is discovered, document it
  and make the smallest required schema/update change in this wave only if it is
  necessary to type or guard the repaired paths.

Hard-fail remains the institutional rule: when the backend rejects or cannot
serve an institutional route, the operator must see an explicit failure.

## 3. Findings and Evidence

### J-A6-01 - Stale API paths

The jury accepted these stale paths:

- `frontend-svelte/src/routes/(protected)/cashflow/+page.svelte:33` calls
  `/cashflow/analytics${qs}`.
- `frontend-svelte/src/routes/(protected)/cashflow/+page.svelte:34` calls
  `/cashflow/projections${qs}`.
- `frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte:15`
  calls `/mtm/snapshots/latest`.
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:16`
  calls `/pl/snapshot/latest`.
- `frontend-svelte/src/routes/(protected)/contracts/+page.svelte:19` calls
  `/contracts?...`.
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:55`
  calls `/contracts/${contractId}`.
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:70`
  calls `/contracts/${contractId}/status`.

Canonical paths from `docs/api/openapi_v1.json` and
`frontend-svelte/src/lib/api/schema.d.ts` include:

- `/cashflow/analytic`
- `/cashflow/projection`
- `/contracts/hedge`
- `/contracts/hedge/{contract_id}`
- `/contracts/hedge/{contract_id}/status`
- `/mtm/snapshots`
- `/pl/snapshots`

### J-A6-05 - Silent non-2xx mutation failures

The jury accepted that these mutation handlers suppress hard-fail detail:

- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:142`
  `rejectRfq()`.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:160`
  `cancelRfq()`.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:175`
  `refreshRfq()`.
- `frontend-svelte/src/routes/(protected)/market-data/+page.svelte:35`
  market-data ingest.

### J-A6-07 - Call-site drift guard gap

The jury accepted that typed generated schema exists but routed pages use
`apiFetch(path: string)`, so stale strings compile:

- `frontend-svelte/src/lib/api/client.ts:1`
- `frontend-svelte/src/lib/api/fetch.ts:9`
- `frontend-svelte/package.json:16`
- `frontend-svelte/package.json:17`
- `.github/workflows/ci.yml:122`

## 4. Required Implementation Boundary

### Endpoint Corrections

Correct the route files identified above to use current contract paths.

Minimum acceptable behavior:

- Cashflow page calls `/cashflow/analytic`, `/cashflow/projection`, and the
  existing ledger path.
- Contracts list/detail/status calls use `/contracts/hedge...`.
- MTM and P&L pages call contract-backed snapshot endpoints. If there is no
  `/latest` route, fetch the documented collection endpoint and select the
  intended snapshot deterministically, with explicit empty/error states.
- Every repaired load path distinguishes:
  - loading;
  - successful empty data;
  - backend non-2xx failure;
  - malformed response.

### Error Surfacing

For the RFQ and market-data mutation handlers in `J-A6-05`:

- parse backend error bodies on non-2xx;
- show `notifications.error(...)` or the established local error surface;
- do not reset UI state in a way that implies success;
- keep successful mutation reloads unchanged unless the current code races or
  double-submits.

### Drift Guard

Add one narrow guard for the paths fixed in this wave:

- preferred: migrate these repaired calls to `client.GET`, `client.POST`, and
  `client.PATCH` from `frontend-svelte/src/lib/api/client.ts`; or
- acceptable: add a focused static test that fails when the repaired stale path
  literals reappear.

The guard must cover at least the seven stale paths listed in `J-A6-01`.

## 5. Acceptance Criteria

- No routed page in this wave calls `/cashflow/analytics`,
  `/cashflow/projections`, `/contracts`, `/contracts/{id}`,
  `/contracts/{id}/status`, `/mtm/snapshots/latest`, or `/pl/snapshot/latest`.
- Each repaired page has an explicit non-2xx error state.
- RFQ reject/cancel/refresh and market-data ingest show backend failure detail
  instead of silently clearing in-flight state.
- Drift guard or typed calls prevent these exact stale paths from compiling or
  passing tests again.
- The implementation does not create backend routes to satisfy stale frontend
  calls.
- `docs/governance.md` has no diff.

## 6. Required Tests

Add or update focused frontend tests.

Minimum coverage:

- contract list/detail/status calls use `/contracts/hedge...`;
- cashflow calls use singular `/cashflow/analytic` and `/cashflow/projection`;
- MTM/P&L snapshot pages do not call nonexistent `/latest` paths;
- one non-2xx RFQ mutation response produces an operator-visible error;
- one non-2xx market-data ingest response produces an operator-visible error;
- static or typed-client guard fails if the stale path literals return.

If Playwright route interception is the existing local pattern, use it. If unit
tests are more stable for the path checks, prefer narrow unit tests and reserve
E2E for critical route smoke.

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
rg -n "/cashflow/analytics|/cashflow/projections|/contracts\\?|/contracts/\\$\\{contractId\\}|/contracts/\\$\\{contractId\\}/status|/mtm/snapshots/latest|/pl/snapshot/latest" frontend-svelte/src
rg -n "apiFetch\\(" frontend-svelte/src/routes
git diff --check
```

If `npm run api:types:check` is run on Windows and fails because
`/tmp/schema-check.d.ts` is not a valid local path, report that separately and
use CI `openapi_diff` plus the drift guard tests for this wave.

## 8. Out of Scope

- Settlement lifecycle redesign. That is PR-A6-2.
- RFQ actor identity and quote/event parsing. That is PR-A6-2.
- P&L/MTM zero-default removal and numeric precision fixes. That is PR-A6-3.
- Orders/audit pages and login gating. That is PR-A6-4.
- Full typed-client migration across the entire frontend.

## 9. PR Requirements

- Use branch `audit-a6/contract-path-load-failure-discipline`.
- Push normally; do not use `--no-verify`.
- Open a PR against `main`.
- Include in the PR body:
  - findings closed;
  - files changed;
  - tests run and results;
  - stale-path grep result;
  - hook artifact path;
  - statement that `docs/governance.md` has no diff.
