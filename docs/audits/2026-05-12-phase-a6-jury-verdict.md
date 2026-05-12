# Phase A6 Jury Verdict

## Executive Summary

- Total accepted findings: 12
- Tier 1: 2
- Tier 2: 7
- Tier 3: 3
- Tier 4: 0
- Rejected auditor findings: 1
- Fresh jury findings: 1

## Accepted Findings

### J-A6-01 - Align frontend API paths with the generated OpenAPI contract

**Source:** Opus J-A6-OPUS-01, J-A6-OPUS-02, J-A6-OPUS-03, J-A6-OPUS-04, J-A6-OPUS-05 | Gemini J-A6-GEMINI-02
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted with severity change
**Evidence:**
- `frontend-svelte/src/routes/(protected)/cashflow/+page.svelte:33` - calls `/cashflow/analytics${qs}`.
- `frontend-svelte/src/routes/(protected)/cashflow/+page.svelte:34` - calls `/cashflow/projections${qs}`.
- `frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte:15` - calls `/mtm/snapshots/latest`.
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:16` - calls `/pl/snapshot/latest`.
- `frontend-svelte/src/routes/(protected)/contracts/+page.svelte:19` - calls `/contracts?...`.
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:55` - calls `/contracts/${contractId}`.
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:70` - calls `/contracts/${contractId}/status`.
- `docs/api/openapi_v1.json:7347` - canonical cashflow endpoint is `/cashflow/analytic`.
- `docs/api/openapi_v1.json:7663` - canonical cashflow endpoint is `/cashflow/projection`.
- `docs/api/openapi_v1.json:7706` - canonical contract list endpoint is `/contracts/hedge`.
- `docs/api/openapi_v1.json:7872` - canonical contract detail endpoint is `/contracts/hedge/{contract_id}`.
- `docs/api/openapi_v1.json:8094` - canonical contract status endpoint is `/contracts/hedge/{contract_id}/status`.
- `docs/api/openapi_v1.json:9915` - canonical MTM snapshots endpoint is `/mtm/snapshots`.
- `docs/api/openapi_v1.json:10392` - canonical P&L snapshots endpoint is `/pl/snapshots`.

**Failure mode:**
Operators can open core A6 routes whose API calls do not exist in the current contract. Cashflow analytics/projection, MTM, P&L, contracts list, contracts detail, and contract status transition either 404 or leave state unset. Several pages only update state on `res.ok` and otherwise fall through to empty or "no data" states, so the operator cannot distinguish true absence from a contract failure.

**Governance impact:**
This impairs evidence visibility and reconstructability for A3/A5 state. I downgrade from Tier 1 to Tier 2 because the broken GETs do not themselves submit an incorrect economic mutation, and the contract PATCH currently hits a non-existent path rather than succeeding incorrectly.

**Remediation boundary:**
One endpoint-repair PR limited to the affected route files. Replace stale string paths with generated-schema paths, and add explicit non-2xx error surfaces for these load paths.

### J-A6-02 - Do not expose settlement as a generic contract status patch

**Source:** Gemini J-A6-GEMINI-03
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted with reachability caveat
**Evidence:**
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:17` - allows `active` to transition to `settled`.
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:35` - labels that transition as `Liquidar`.
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:70` - sends a PATCH status body `{ status: targetStatus }`.
- `docs/api/openapi_v1.json:7472` - canonical ledger settlement endpoint is `/cashflow/contracts/{contract_id}/settle`.
- `docs/api/openapi_v1.json:3050` - `HedgeContractSettlementCreate` requires `source_event_id`, `cashflow_date`, and `legs`.
- `backend/app/api/routes/cashflow_ledger.py:28` - ledger settlement is a POST route that creates a settlement response.
- `backend/app/services/cashflow_ledger_service.py:265` - settlement creates a `HedgeContractSettlementEvent`.
- `backend/app/api/routes/contracts.py:135` - status patch exists separately as `/contracts/hedge/{contract_id}/status`.
- `backend/app/services/contract_service.py:277` - status patch mutates only `contract.status`.

**Failure mode:**
The current detail page is masked by J-A6-01 because it loads from the wrong detail endpoint. Once that path is corrected, the visible `Liquidar` action can mark a hedge contract `settled` through a generic status patch without the ledger settlement payload and without creating settlement ledger entries. That would let the UI close a lifecycle state while bypassing the Phase A3 cashflow reconciliation path.

**Governance impact:**
Cashflow is always derived and settlement must be reconstructible from ledger evidence. A status-only settlement is an unsupported lifecycle transition.

**Remediation boundary:**
In the same PR that fixes contract paths, remove `settled` and `partially_settled` from generic status buttons or replace them with a settlement flow that calls `/cashflow/contracts/{contract_id}/settle` with the required settlement event payload. Keep cancellation/status-only work separate from ledger settlement.

### J-A6-03 - Remove zero-default financial fallbacks from analytics displays

**Source:** Opus J-A6-OPUS-06
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted with severity change
**Evidence:**
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:41` - maps labels with `(e: any) => e.commodity ?? e.label ?? ''`.
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:49` - maps realized P&L with `e.realized_pnl ?? e.realized ?? 0`.
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:56` - maps unrealized P&L with `e.unrealized_pnl ?? e.unrealized ?? 0`.
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:83` - totals missing realized/unrealized values as zero.
- `frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte:39` - maps date labels with `e.date ?? e.snapshot_date ?? e.label ?? ''`.
- `frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte:46` - maps MTM values with `e.mtm_value ?? e.value ?? 0`.

**Failure mode:**
If the backend response shape drifts or omits a required economic value, the analytics view renders zero or blank categories instead of hard-failing. This can make a missing P&L or MTM value look like a real zero. The current endpoint drift in J-A6-01 makes this pattern especially dangerous because it normalizes missing data conventions.

**Governance impact:**
This violates the no silent fallback and no zero-default rules for financial state. I downgrade from Tier 1 to Tier 2 because this is display corruption and operator misdirection, not a submitted mutation.

**Remediation boundary:**
Type the P&L and MTM responses from the generated schema or local entity types and render an explicit error state when required fields are absent. Do not keep alternate-field or zero fallback chains for primary financial values.

### J-A6-04 - Stop fabricating RFQ actor identity in frontend mutation bodies

**Source:** Opus J-A6-OPUS-07
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `frontend-svelte/src/lib/stores/auth.svelte.ts:31` - `userName` prefers the mutable `name` claim before `sub`.
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:111` - RFQ creation sends `user_id: authStore.userName || 'trader'`.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:118` - award sends `user_id: authStore.userName || 'trader'`.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:144` - reject sends the same fallback.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:162` - cancel sends the same fallback.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:177` - refresh sends the same fallback.
- `frontend-svelte/src/lib/api/schema.d.ts:3246` - `RFQAwardRequest` requires client-provided `user_id`.
- `frontend-svelte/src/lib/api/schema.d.ts:3544` - refresh/reject request schemas require client-provided `user_id`.
- `backend/app/api/routes/rfqs.py:332` - backend passes `payload.user_id` into `RFQService.reject`.
- `backend/app/api/routes/rfqs.py:482` - backend passes `payload.user_id` into `RFQService.award`.

**Failure mode:**
The frontend can write a display name, token subject, or literal `trader` into RFQ action evidence. A token with a `name` claim records a mutable human label rather than immutable subject identity. A token missing both fields records the hard-coded actor `trader`. Current backend schemas require this client field and services consume it, so the actor recorded in RFQ state events can diverge from authenticated identity.

**Governance impact:**
This corrupts mutation evidence and A5 audit reconstructability. Messages and decision artifacts are evidence, not UI artifacts.

**Remediation boundary:**
Frontend: remove the `|| 'trader'` fallback immediately and expose immutable `sub` separately if the current contract still requires a user id. Backend deferral: derive actor identity from the authenticated JWT and remove client-supplied `user_id` from RFQ mutation contracts.

### J-A6-05 - Surface non-2xx mutation failures instead of silently clearing in-flight state

**Source:** Gemini J-A6-GEMINI-01
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted with severity change
**Evidence:**
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:142` - `rejectRfq()` posts reject.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:146` - reject only handles `res.ok`; non-2xx has no error branch.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:160` - `cancelRfq()` posts cancel.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:164` - cancel only handles `res.ok`; non-2xx has no error branch.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:175` - refresh posts refresh.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:179` - refresh only handles `res.ok`; non-2xx has no error branch.
- `frontend-svelte/src/routes/(protected)/market-data/+page.svelte:35` - market-data ingest posts a dated ingestion request.
- `frontend-svelte/src/routes/(protected)/market-data/+page.svelte:40` - ingest only handles `res.ok`; non-2xx has no error branch.

**Failure mode:**
Backend hard-fails such as 409, 422, or 424 leave no operator-visible reason on reject, cancel, refresh, or market-data ingest. The UI clears loading state and, for RFQ actions, resets board mode without proving whether the mutation was rejected or simply ignored.

**Governance impact:**
This hides hard-fail evidence and can stale critical operator state. I downgrade from Tier 1 to Tier 2 because these paths do not show a false success toast on non-2xx, but they still suppress the failure reason.

**Remediation boundary:**
Parse non-2xx error bodies consistently in those four functions and show `notifications.error` with backend detail. Add tests or route assertions for at least one hard-fail response per critical mutation family.

### J-A6-06 - Preserve six-decimal Westmetall price precision in market-data display

**Source:** Gemini J-A6-GEMINI-04
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `frontend-svelte/src/routes/(protected)/market-data/+page.svelte:112` - renders `price.price ?? price.value` through `formatNumber`.
- `frontend-svelte/src/lib/utils/format.ts:61` - comments say decimal economic columns serialize as strings.
- `frontend-svelte/src/lib/utils/format.ts:63` - comments warn `formatNumber` is for plain 2-decimal numbers.
- `frontend-svelte/src/lib/utils/format.ts:67` - `formatNumber` accepts string values.
- `frontend-svelte/src/lib/utils/format.ts:69` - string values are coerced with `Number(value)`.
- `frontend-svelte/src/lib/utils/format.ts:79` - `formatPrice` preserves six decimal places through `formatDecimalString`.

**Failure mode:**
Cash-settlement prices that arrive as decimal strings are coerced to IEEE-754 numbers and displayed with two decimals. Operators doing market-data verification see a rounded value rather than the persisted six-decimal settlement price.

**Governance impact:**
This impairs numeric integrity for price references. Backend state is not mutated by this display path, so Tier 2 is appropriate.

**Remediation boundary:**
Use `formatPrice(price.price ?? price.value, 'USD/MT')` or a dedicated six-decimal settlement formatter. Do not route price fields through `formatNumber`.

### J-A6-07 - Enforce typed contract paths or static route drift guards

**Source:** Opus J-A6-OPUS-08 | Opus J-A6-OPUS-13
**Severity:** Tier 3 / Medium
**Status:** Open
**Disposition:** Accepted with severity change
**Evidence:**
- `frontend-svelte/src/lib/api/client.ts:1` - typed `openapi-fetch` client exists.
- `frontend-svelte/src/lib/api/fetch.ts:9` - production pages use `apiFetch(path: string, init?: RequestInit)`.
- `frontend-svelte/src/routes/(protected)/cashflow/+page.svelte:33` - stale string path compiles.
- `frontend-svelte/src/routes/(protected)/contracts/+page.svelte:19` - stale string path compiles.
- `frontend-svelte/package.json:16` - `api:types` regenerates schema.
- `frontend-svelte/package.json:17` - `api:types:check` regenerates and diffs a temporary schema.
- `.github/workflows/ci.yml:122` - CI runs schema drift check against a live docker-compose backend.
- `frontend-svelte/e2e/rfq-lifecycle.spec.ts:14` - RFQ E2E checks page load only.
- `frontend-svelte/e2e/contracts.spec.ts:34` - contract E2E checks button visibility, not PATCH URL or body.

**Failure mode:**
The generated schema can be up to date and CI can still miss stale frontend strings because routed pages do not use the typed client. Existing E2E tests are smoke tests and do not assert the contract URLs or mutation payloads that failed in J-A6-01 and J-A6-04.

**Governance impact:**
This is a verification and drift-control gap. I downgrade from Tier 2 to Tier 3 because CI does run a schema drift check with a live backend; the remaining failure is untyped call-site discipline and missing critical-path assertions.

**Remediation boundary:**
For the repaired paths, either migrate to `client.GET`/`client.POST`/`client.PATCH` or add a static guard that fails new stale `apiFetch` path literals. Add focused E2E route assertions for cashflow, contracts status, and RFQ mutation bodies.

### J-A6-08 - Expose orders as reconstructible exposure source records

**Source:** Opus J-A6-OPUS-09
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `frontend-svelte/src/routes/+layout.svelte:29` - navigation contains dashboard, RFQ, exposures, cashflow, contracts, counterparties, analytics, and market data; no orders route.
- `frontend-svelte/src/routes/(protected)/+page.svelte:9` - dashboard links only RFQ, exposures, and analytics.
- `rg --files frontend-svelte/src/routes` - no routed orders page exists.
- `docs/api/openapi_v1.json:10015` - backend exposes `/orders`.
- `docs/api/openapi_v1.json:10224` - backend exposes `/orders/purchase`.
- `docs/api/openapi_v1.json:10265` - backend exposes `/orders/sales`.
- `docs/api/openapi_v1.json:10306` - backend exposes `/orders/{order_id}`.
- `frontend-svelte/src/routes/(protected)/exposures/+page.svelte:24` - exposure screen loads exposure aggregates, net exposure, and tasks, but no source order detail.

**Failure mode:**
The UI displays exposures but provides no route to inspect the sales or purchase orders that generated those exposure rows. Operators cannot reconstruct exposure source records from the frontend even though orders are first-class backend and governance objects.

**Governance impact:**
Orders generate commercial active/passive exposure. Hiding them impairs reconstructability of the exposure state surfaced in A6.

**Remediation boundary:**
Add a read-only orders list and detail route first. Defer order create/archive/link mutations to a separate PR unless dispatch explicitly scopes them.

### J-A6-09 - Surface signed audit events and verification for auditor workflows

**Source:** Opus J-A6-OPUS-10
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `frontend-svelte/src/routes/+layout.svelte:29` - navigation has no audit route.
- `rg --files frontend-svelte/src/routes` - no routed audit page exists.
- `frontend-svelte/src/lib/stores/auth.svelte.ts:3` - `auditor` is a frontend role.
- `docs/api/openapi_v1.json:7175` - backend exposes `/audit/events`.
- `docs/api/openapi_v1.json:7303` - backend exposes `/audit/events/{event_id}/verify`.

**Failure mode:**
The A5 signed audit trail is not visible in the frontend, and the auditor role has no route to list or verify audit events. Operators can perform or inspect workflows without a UI path to the signed evidence trail.

**Governance impact:**
Auditability and reconstructability are primary optimization targets. Hiding the signed audit artifacts impairs that target even if backend endpoints exist.

**Remediation boundary:**
Add a read-only audit events route with entity/time filters and per-event verification. Keep it read-only and role-visible to auditor/risk-manager.

### J-A6-10 - Gate dev-only manual JWT login before production use

**Source:** Opus J-A6-OPUS-11
**Severity:** Tier 3 / Medium
**Status:** Open
**Disposition:** Accepted with severity change
**Evidence:**
- `frontend-svelte/src/routes/(public)/login/+page.svelte:19` - login directly stores a pasted token through `authStore.login`.
- `frontend-svelte/src/routes/(public)/login/+page.svelte:32` - login page tells users to paste a JWT.
- `frontend-svelte/src/routes/(public)/login/+page.svelte:57` - page labels itself as development manual-token authentication.
- `frontend-svelte/src/lib/stores/auth.svelte.ts:41` - auth store decodes the token client-side without a backend login exchange.

**Failure mode:**
The only visible login flow is explicitly development-only. In production this either blocks institutional users or normalizes out-of-band token handling. That weakens role/session discipline but is partly a platform deployment decision.

**Governance impact:**
Actor identity and session lifecycle are evidence for mutations. I downgrade from Tier 2 to Tier 3 because a front-door identity provider could exist outside this Svelte app, and that deployment contract is not proven here.

**Remediation boundary:**
Add an explicit build/runtime flag for dev token login and document or implement the production identity entry point. Do not redesign auth storage in the same PR unless separately authorized.

### J-A6-11 - Align RFQ quantity input precision with backend MT precision

**Source:** Opus J-A6-OPUS-14
**Severity:** Tier 3 / Medium
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:10` - `quantityMt` is stored as a JavaScript `number`.
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:105` - submitted `quantity_mt` uses that numeric value.
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:177` - quantity input is `type="number"`.
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:178` - input step is `0.01`.
- `frontend-svelte/src/lib/api/schema.d.ts:3291` - generated RFQ contract allows `quantity_mt: number | string`.
- `backend/app/schemas/_types.py:13` - `MTQuantity` is a `Decimal`.
- `frontend-svelte/src/lib/utils/format.ts:19` - local formatter comments identify MT quantities as three-decimal precision.

**Failure mode:**
The backend accepts decimal MT quantities, while the RFQ creation form constrains entry to two decimals and stores the payload as a JS number. This can reject valid three-decimal institutional quantities or silently round depending on browser behavior.

**Governance impact:**
Quantity in MT is an institutional primitive. This is a localized numeric-integrity gap, so Tier 3 is appropriate.

**Remediation boundary:**
Use `step="0.001"` and preserve quantity as a decimal string at the form boundary, or explicitly document and enforce a two-decimal product rule across backend and frontend.

### J-A6-12 - Parse RFQ quotes and state-event responses exactly once

**Source:** Jury Fresh
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted
**Evidence:**
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:68` - `quotesRes.json()` can be called twice in the fallback expression.
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:69` - `eventsRes.json()` can be called twice in the fallback expression.
- `backend/app/api/routes/rfqs.py:222` - `/rfqs/{rfq_id}/quotes` returns `list[RFQQuoteRead]`, not an `{ items }` envelope.
- `backend/app/api/routes/rfqs.py:243` - `/rfqs/{rfq_id}/state-events` returns `list[RFQStateEventRead]`, not an `{ items }` envelope.

**Failure mode:**
For the current backend contract, `await quotesRes.json()` returns an array. Arrays have no `items` property, so the fallback evaluates `await quotesRes.json()` a second time on an already-consumed body and throws. The same applies to state events. RFQ detail can therefore fail to load quotes and timeline even when the backend returns valid data.

**Governance impact:**
RFQ quote evidence and state-event timelines are required to reconstruct award/reject/cancel decisions. This is a concrete A6 failure missed by both auditors.

**Remediation boundary:**
Parse each response body once, then normalize `Array.isArray(data) ? data : data.items ?? []`. Add a unit or E2E route assertion for array responses on RFQ quotes and state events.

## Rejected Findings

### J-A6-OPUS-12 - JWT held in sessionStorage is reachable by any XSS

**Disposition:** Rejected
**Reason:** The risk is valid security hardening context, but the auditor did not show a concrete XSS sink in the current routed application. `frontend-svelte/src/lib/stores/auth.svelte.ts:138` persists the token in `sessionStorage`, but `frontend-svelte/src/lib/utils/sanitize.ts` exists for chart tooltip escaping and the audit did not identify a current `{@html}` or equivalent sink that exfiltrates the bearer. Track CSP/auth-storage hardening as a cross-phase security item, not an A6 blocking finding.

## Subsumed Findings

- Opus J-A6-OPUS-01, J-A6-OPUS-02, J-A6-OPUS-03, J-A6-OPUS-04, and the stale-path part of J-A6-OPUS-05 are subsumed into J-A6-01.
- Gemini J-A6-GEMINI-02 is subsumed into J-A6-01.
- Gemini J-A6-GEMINI-03 remains separate as J-A6-02 because fixing the stale contract path alone would expose a ledger-bypass settlement flow.
- Opus J-A6-OPUS-13 is subsumed into J-A6-07 because the critical missing tests are the guardrail failure that allowed stale paths and weak mutation evidence to survive.
- Opus J-A6-OPUS-07 is expanded in J-A6-04 to include RFQ creation at `rfq/new/+page.svelte:111`, not only detail actions.

## Cross-Phase Deferrals

- Backend RFQ actor derivation: current backend schemas require client-supplied `user_id` and services consume it. The canonical fix should derive actor identity from authenticated JWT claims server-side, then remove `user_id` from RFQ mutation bodies.
- Production identity provider: A6 can gate the dev paste-token flow, but selecting an IdP or reverse-proxy authentication model is a platform decision outside this read-only jury stage.
- Token storage hardening: HTTP-only cookies, CSRF, CSP, and full XSS-sink inventory should be handled as a security/platform phase unless a concrete current sink is found.
- Backend status endpoint semantics: `/contracts/hedge/{contract_id}/status` exists and can set status without ledger settlement. If settlement must only occur through the ledger endpoint, backend should reject `settled` through the generic status patch.

## Recommended Remediation Waves

### PR-A6-1 - Contract path and load-failure discipline
- Findings: J-A6-01, J-A6-05, J-A6-07
- Scope boundary: cashflow, MTM, P&L, contract list/detail/status paths; explicit non-2xx display for those routes and affected RFQ/market-data mutations; typed-client or static guard for repaired paths.
- Required verification: `npm run check`, `npm test`, `npm run build`, plus targeted E2E route assertions for repaired URLs.

### PR-A6-2 - Settlement and RFQ evidence integrity
- Findings: J-A6-02, J-A6-04, J-A6-12
- Scope boundary: replace status-only settlement UI with ledger settlement or remove settlement buttons; remove/fix frontend actor fallback; parse RFQ quote/event responses once.
- Required verification: frontend tests for settlement action routing, RFQ action body identity, and RFQ detail array responses; backend contract confirmation for actor derivation if included.

### PR-A6-3 - Financial display and numeric precision
- Findings: J-A6-03, J-A6-06, J-A6-11
- Scope boundary: P&L/MTM required-field handling, market-data price formatter, RFQ quantity decimal string handling.
- Required verification: formatter tests for six-decimal prices and three-decimal MT quantities; component/route tests for missing required analytics fields.

### PR-A6-4 - Reconstructability surfaces
- Findings: J-A6-08, J-A6-09, J-A6-10
- Scope boundary: read-only orders route, read-only audit events/verification route, and dev-login gating/documentation.
- Required verification: route-level tests for orders and audit pages, role visibility checks, and explicit production-login configuration behavior.

## Anti-Findings Confirmed

- Raw `fetch` bypass is not present in routed pages; `frontend-svelte/src/lib/api/fetch.ts:17` is the only raw `fetch(` match under `frontend-svelte/src`.
- WebSocket auth handshake is not accepted as a finding: `frontend-svelte/src/lib/stores/ws.svelte.ts:161` handles control messages, and `frontend-svelte/src/lib/stores/ws.svelte.ts:173` dispatches domain events only after authenticated status.
- Client-side role gating alone is not treated as a security boundary issue. The accepted role/session finding is limited to dev-only login and operator-surface behavior.
- Gemini's anti-finding on missing orders is rejected by the jury: orders are not optional generic navigation because they are the source records behind commercial exposure.

## Commands Run

- `rg --files frontend-svelte/src/routes` - completed; confirmed no orders or audit routes.
- `rg -n "apiFetch\\(" frontend-svelte/src` - completed; mapped all API call sites.
- `rg -n "method:" frontend-svelte/src` - completed; mapped mutating call sites.
- `rg -n "fetch\\(" frontend-svelte/src` - completed; found only the centralized wrapper.
- `rg -n "authStore\\.has|hasRole|hasAnyRole" frontend-svelte/src` - completed; mapped frontend role gates.
- `rg -n 'Number\\(|parseFloat|parseInt|toFixed|type="number"|bind:value' frontend-svelte/src` - completed; mapped numeric/form entry points.
- `cd frontend-svelte && npm run check` - passed; `svelte-check found 0 errors and 0 warnings`.
- `cd frontend-svelte && npm test` - passed; 9 test files and 107 tests passed. Svelte emitted the existing `state_referenced_locally` warning in `src/lib/components/table/create-table.svelte.ts`.
- `cd frontend-svelte && npm run build` - passed. Vite emitted the existing `state_referenced_locally` warning and a chunk-size warning for a client chunk above 500 kB.
- `cd frontend-svelte && npm run api:types:check` - first failed before backend startup with `ECONNREFUSED`; after `docker compose up -d db backend`, the package script reached OpenAPI but failed on Windows because `/tmp/schema-check.d.ts` is not a valid absolute file URL for `openapi-typescript`.
- Equivalent Windows-safe schema check - failed with drift. Generated backend types differed from committed `src/lib/api/schema.d.ts`, including added `/rfqs/{rfq_id}/actions/award-quote`, RFQ numeric/string contract differences, and multiple removed/changed response fields.
- `cd frontend-svelte && npm run test:e2e` - not run because the required backend/test stack was not already available.
