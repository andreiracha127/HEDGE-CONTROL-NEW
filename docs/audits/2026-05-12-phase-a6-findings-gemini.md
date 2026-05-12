# Phase A6 - Stage 2 Audit Findings (Auditor B / Gemini 3.1 Pro)
**Auditor:** Gemini 3.1 Pro
**Date:** 2026-05-12

## Finding J-A6-GEMINI-01 - Handle non-2xx HTTP responses on critical mutations

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:142 - rejectRfq() drops errors because the res.ok check has no else block to notify the user.
- frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte:160 - cancelRfq() similarly ignores res.ok failures and simply toggles operationInFlight = false.
- frontend-svelte/src/routes/(protected)/market-data/+page.svelte:36 - triggerIngest() lacks an else block for res.ok, swallowing HTTP 422 or 400 validation failures.
- frontend-svelte/e2e/rfq-lifecycle.spec.ts:1 - Test suite only asserts happy-path loading and layout, lacking any assertions for API rejection or hard-fails.

**Failure mode:**
If the backend rejects a cancellation, rejection, or data ingestion due to a hard-fail condition (e.g., stale state, validation failure, unprovable reference), the API call correctly fails but the frontend swallows the error. The loading spinner disappears, the modal closes, and the operator believes the mutation succeeded. They may then make subsequent decisions based on a corrupted understanding of the system's state.

**Governance impact:**
Violates "no silent fallback" and "hard-fail on missing evidence/unprovable references". The UI essentially provides a silent fallback by ignoring the backend's hard-fail.

**Recommended remediation boundary:**
Add explicit else branches to the res.ok checks in these functions that parse the error body and display it via notifications.error(), ensuring operators see why a mutation was rejected. Extend Playwright tests to cover 4xx backend responses.

## Finding J-A6-GEMINI-02 - Correct stale API endpoints across analytics and contracts

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- frontend-svelte/src/routes/(protected)/contracts/+page.svelte:19 - Uses /contracts instead of /contracts/hedge.
- frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:55 - Uses /contracts/id instead of /contracts/hedge/id.
- frontend-svelte/src/routes/(protected)/cashflow/+page.svelte:33 - Uses /cashflow/analytics and /cashflow/projections instead of the singular endpoints.
- frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte:15 - Uses /mtm/snapshots/latest which does not exist in the OpenAPI schema.
- frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:16 - Uses /pl/snapshot/latest which does not exist in the OpenAPI schema.

**Failure mode:**
Operators navigating to the Contracts, Cashflow, MTM, or P&L pages will trigger 404 Not Found errors on the API fetch. The pages will fail to load, display errors, or redirect in a loop, rendering critical institutional evidence and operator views completely unreachable.

**Governance impact:**
Violates the mandate that "evidence missing and unprovable references are hard-fail" by making the evidence strictly unreachable due to schema drift. Reconstructability is broken if operators cannot view the active contracts or ledgers.

**Recommended remediation boundary:**
Update the string paths inside apiFetch() calls across the analytics, cashflow, and contracts pages to exactly match the generated schema.d.ts. Ensure backend endpoints for "latest" snapshots exist or switch the frontend to fetch collections and take the first item.

## Finding J-A6-GEMINI-03 - Expose proper ledger-based settlement mutation

**Severity:** Tier 1 / Blocking
**Status:** Open
**Evidence:**
- frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte:70 - Uses PATCH /contracts/id/status to settle a contract (status: 'settled').
- frontend-svelte/src/lib/api/schema.d.ts:79 - The canonical backend mutation for settlement is POST /cashflow/contracts/{contract_id}/settle, requiring specific HedgeContractSettlementCreate payload.

**Failure mode:**
The frontend attempts to settle contracts using a legacy status-patch endpoint instead of the Phase A3 ledger reconciliation endpoint. This bypasses the mandatory cashflow generation, creating a contract that appears "settled" but has no corresponding accounting ledger entries, corrupting the institutional state.

**Governance impact:**
Violates "CashFlow is always derived, never manually input" and "One methodology per endpoint". By bypassing the canonical ledger settlement engine, the economic model is fundamentally broken.

**Recommended remediation boundary:**
Replace the transitionStatus('settled') call with a specific settlement modal or flow that calls POST /cashflow/contracts/{contract_id}/settle with the required leg data, and remove the direct settled option from the generic status transition.

## Finding J-A6-GEMINI-04 - Remove precision loss in market data price formatting

**Severity:** Tier 2 / High
**Status:** Open
**Evidence:**
- frontend-svelte/src/routes/(protected)/market-data/+page.svelte:112 - Uses formatNumber(price.price ?? price.value) to display Westmetall settlement prices.
- frontend-svelte/src/lib/utils/format.ts:69 - formatNumber converts string values using Number(value) and limits display to 2 decimal places.

**Failure mode:**
Westmetall aluminum prices are precision indices defined as NUMERIC(18, 6) by the backend and transmitted as strings to preserve precision. By passing these through formatNumber(), the frontend coerces the 6-decimal string into an IEEE-754 float and subsequently truncates it to 2 decimal places. Operators viewing the market data table will see distorted price inputs, which may lead to incorrect manual verification or validation of cashflow projections.

**Governance impact:**
Violates "Can display or form code distort financial quantities?". This explicitly distorts precision market data indices.

**Recommended remediation boundary:**
Change the interpolation in market-data/+page.svelte to use formatPrice(...) which correctly utilizes formatDecimalString(..., 6) under the hood without Number() coercion.

## Anti-findings considered
- **Quantity Bindings via type="number" (Tier 3):**
rfq/new/+page.svelte:177 binds quantity_mt via a standard HTML number input, which is serialized as a JS number. While format.ts notes that converting backend strings to Number loses precision, for form inputs (which are typed in by humans and generally well within 15 significant digits for MT quantities), the schema permits number | string. This is not a strict violation of the schema, so it was deemed acceptable.
- **WebSocket Polling Fallback:** The WebSocket store ws.svelte.ts implements a polling fallback gracefully when WS disconnects. This is robust and complies with determinism rather than silently failing to update real-time states. No finding reported.
- **Missing /orders pages:** The OpenAPI schema contains multiple endpoints for managing orders. However, there are no Svelte routes mapping to an Orders view. Per instructions ("Missing navigation is a finding only if it blocks a required institutional workflow..."), without a concrete directive stating order management must be done via the web UI (it might be API-driven via integrations), this is deferred.

## Cross-phase deferrals
- Resolving the missing latest endpoints for MTM and PNL snapshots might require backend changes (Phase A3/A6 intersection). If the backend is not intended to provide a /latest endpoint, the frontend should fetch the list /mtm/snapshots and sort client-side. This should be verified against backend intents.

## Recommended remediation waves
- **Wave 1: API Drift & Error Handling.** Address J-A6-GEMINI-01 and J-A6-GEMINI-02 immediately to restore basic connectivity and error visibility across the application.
- **Wave 2: Format & Data Integrity.** Fix J-A6-GEMINI-04 to ensure market data displays correctly without precision loss.
- **Wave 3: Settlement Workflows.** Fix J-A6-GEMINI-03 to implement the correct /cashflow/.../settle interaction, which may require additional UI components to collect settlement legs.
