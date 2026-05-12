# Phase A6 - Stage 2 Audit Dispatch - Auditor B

**Phase:** A6 - Frontend Svelte institutional control surface
**Stage:** 2 of 3
**Target auditor:** Gemini 3.1 Pro
**Authoring date:** 2026-05-12
**Repository:** `D:/Projetos/Hedge-Control-New`
**Branch:** `main`
**Expected output:** `docs/audits/2026-05-12-phase-a6-findings-gemini.md`

## 1. Operating Instructions

You are performing an independent read-only institutional frontend audit. Do
not edit code, tests, generated schemas, backend files, migrations, or
governance documents.

Opus 4.7 is performing Stage 1 separately. GPT 5.5 will adjudicate in Stage 3.
Do not rely on either of them. Your value is independent verification,
adversarial state modeling, and catching failures that a first auditor may
normalize as UI behavior.

Use direct code evidence. Every accepted finding must include file and line
references, a concrete failure mode, and the institutional rule it violates.
Do not report style preferences, generic refactors, or aesthetic issues without
a demonstrated correctness, auditability, determinism, authorization, or
reconstruction impact.

## 2. Institutional Context

Closed phases:

- A1 closed economic primitives and lifecycle foundations.
- A2 closed RFQ canonical identity, ranking, award, and outbound evidence.
- A3 closed valuation, MTM, cashflow baseline/ledger reconciliation, and P&L
  lifecycle.
- A4 closed integration trust, inbound durability, replay protection, and LLM
  decision reconstruction.
- A5 closed signed audit trail, mutation/evidence atomicity, audit history
  preservation, and auth fail-closed guardrails.

Phase A6 is the frontend audit. It asks whether the Svelte application can
faithfully operate the institutional backend without corrupting payloads,
misstating state, hiding hard-fail errors, bypassing role expectations, or
losing evidence context at the operator surface.

Binding governance is `docs/governance.md`. The relevant rules are:

- auditability and reconstructability are primary optimization targets;
- institutional messages and decision artifacts are evidence;
- evidence missing and unprovable references are hard-fail;
- no silent fallback;
- no mutation without evidence;
- one phase at a time, with frontend findings kept inside A6 unless a
  cross-phase backend issue is directly implicated.

## 3. Primary Scope

Start with these files and expand only as needed:

- `frontend-svelte/package.json`
- `frontend-svelte/src/app.css`
- `frontend-svelte/src/routes/+layout.svelte`
- `frontend-svelte/src/routes/(protected)/+layout.svelte`
- `frontend-svelte/src/routes/(public)/login/+page.svelte`
- `frontend-svelte/src/lib/api/fetch.ts`
- `frontend-svelte/src/lib/api/client.ts`
- `frontend-svelte/src/lib/api/schema.d.ts`
- `frontend-svelte/src/lib/stores/auth.svelte.ts`
- `frontend-svelte/src/lib/stores/ws.svelte.ts`
- `frontend-svelte/src/lib/stores/notifications.svelte.ts`
- `frontend-svelte/src/lib/utils/format.ts`
- `frontend-svelte/src/lib/utils/sanitize.ts`
- `frontend-svelte/src/lib/components/table/DataTable.svelte`
- `frontend-svelte/src/lib/components/table/create-table.svelte.ts`
- `frontend-svelte/src/lib/components/chart/EChart.svelte`
- `frontend-svelte/src/routes/(protected)/rfq/+page.svelte`
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte`
- `frontend-svelte/src/routes/(protected)/rfq/[id]/+page.svelte`
- `frontend-svelte/src/routes/(protected)/contracts/+page.svelte`
- `frontend-svelte/src/routes/(protected)/contracts/[id]/+page.svelte`
- `frontend-svelte/src/routes/(protected)/counterparties/+page.svelte`
- `frontend-svelte/src/routes/(protected)/counterparties/[id]/+page.svelte`
- `frontend-svelte/src/routes/(protected)/cashflow/+page.svelte`
- `frontend-svelte/src/routes/(protected)/exposures/+page.svelte`
- `frontend-svelte/src/routes/(protected)/market-data/+page.svelte`
- `frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte`
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte`
- `frontend-svelte/src/routes/(protected)/analytics/what-if/+page.svelte`
- `frontend-svelte/e2e/*.spec.ts`
- `frontend-svelte/src/**/*.test.ts`
- `frontend-svelte/scripts/*.mjs`
- `docs/api/openapi_v1.json`

Derive the live surface:

- `rg --files frontend-svelte/src/routes`
- `rg -n "apiFetch\\(" frontend-svelte/src`
- `rg -n "method:" frontend-svelte/src`
- `rg -n "fetch\\(" frontend-svelte/src`
- `rg -n "authStore\\.has|hasRole|hasAnyRole" frontend-svelte/src`
- `rg -n "Number\\(|parseFloat|parseInt|toFixed|type=\"number\"|bind:value" frontend-svelte/src`

Do not assume the route list above is complete.

## 4. Audit Questions

### Q1 - Page and Navigation Reachability

Are protected pages, detail routes, error routes, and navigation entries
consistent with backend workflows?

Look for pages that route to stale paths, lose IDs, expose dead actions, or
make critical evidence unreachable. Missing navigation is a finding only if it
blocks a required institutional workflow or reconstruction path.

### Q2 - Request Construction and Response Interpretation

Do pages construct requests and interpret responses using the actual backend
contract?

Check endpoints, query parameters, request JSON, status handling, response
field names, fallback fields, `any` casts, and generated schema drift. Report
when code can compile while sending or reading the wrong contract.

### Q3 - Critical Action Gating

Are award, reject, cancel, refresh, archive, settle, snapshot, and scenario
actions enabled only under valid frontend state?

Frontend gating is UX, not backend authorization. Still, stale or wrong gating
is a finding when it can lead an operator to submit an impossible or wrong
institutional action, repeatedly fire a mutation, or act on stale ranking or
terminal state.

### Q4 - Error and Confirmation Semantics

Can the UI distinguish pending, success, failure, partial failure, and stale
state?

Inspect loading flags, disabled buttons, notifications, redirects, and error
messages. Report paths where a non-2xx backend response, aborted request, or
hard-fail status can leave the operator believing a mutation succeeded.

### Q5 - Numeric Precision and Formatting

Can display or form code distort financial quantities?

Audit Decimal strings, USD/MT prices, MT quantities, cashflow/P&L signs,
rounding, date windows, and percentage ratios. Focus on submitted payloads and
operator decisions. Do not report harmless display rounding unless it can
change a decision or hide material state.

### Q6 - Identity and Correlation Discipline

Does UI state keep canonical identities distinct from labels?

Check RFQ IDs versus RFQ numbers, quote IDs, counterparty IDs, order IDs,
contract IDs, deal link IDs, WebSocket topic IDs, and table row keys. Findings
include using display text, array index, or stale client state as an identifier
for mutation or evidence lookup.

### Q7 - WebSocket and Polling Consistency

Does real-time state converge deterministically?

Inspect auth handshake, subscription lifecycle, event validation, sequence
numbers, polling fallback, reconnect handling, stale closures, duplicate
events, and cleanup on route changes. Report concrete paths to wrong displayed
state or action availability.

### Q8 - Auth and Role Lifecycle

Does the frontend handle token expiry, logout, route guards, and role changes
without stale authority?

Check session storage, JWT parsing, expiry timers, redirects, role-derived UI,
Authorization headers, and WebSocket token handling. Do not confuse frontend
role gating with backend security; focus on operational correctness and
misleading controls.

### Q9 - Evidence Visibility

Can an institutional user see enough context before and after actions?

Check RFQ state event timelines, quote source information, counterparty
identity, linked order/contract context, cashflow ledger context, MTM/P&L
snapshot context, and audit verification availability if exposed. Report only
when missing context can cause wrong action or unreconstructible operator
intent.

### Q10 - Test Protection

Do unit, store, component, and Playwright tests protect the frontend invariants
above?

Test gaps are findings only when a concrete production path is exposed and the
existing tests would not catch it.

## 5. Severity Taxonomy

Use this taxonomy:

- **Tier 1 / Blocking:** The frontend can submit an incorrect institutional
  mutation; enable an unsupported lifecycle transition; misreport backend
  hard-fail as success; corrupt price, quantity, direction, identity, or date
  semantics in a mutation; or make a closed A1-A5 decision unreconstructible.
- **Tier 2 / High:** A real edge case can mislead operators, stale critical
  state, break role/session behavior, or impair evidence visibility, but the
  backend still prevents incorrect economic state under normal flow.
- **Tier 3 / Medium:** A localized robustness, drift, or coverage gap with
  plausible operational impact but no immediate institutional invariant breach.
- **Tier 4 / Low:** Documentation, cosmetic, test-only, or observability
  improvement. Do not include Tier 4 unless it protects a concrete A6 boundary.

When uncertain between two severities, choose the lower severity and explain
the missing evidence that would make it higher.

## 6. Finding Format

Write findings in this format:

```markdown
## Finding J-A6-GEMINI-XX - Short imperative title

**Severity:** Tier N / Blocking|High|Medium|Low
**Status:** Open
**Evidence:**
- `path/to/file.svelte:123` - what the code does
- `path/to/test.ts:456` - relevant test gap or assertion, if any

**Failure mode:**
Describe the concrete sequence that breaks correctness, auditability,
determinism, authorization, or reconstruction.

**Governance impact:**
Name the exact governance clause or institutional invariant.

**Recommended remediation boundary:**
State the smallest acceptable fix boundary. Do not prescribe broad refactors.
```

After findings, include:

- `Anti-findings considered` - issues you inspected and rejected, with evidence.
- `Cross-phase deferrals` - items that belong to backend or a later
  cross-phase cleanup.
- `Recommended remediation waves` - group accepted findings into coherent PR
  waves, preserving small blast radius.

## 7. Anti-Finding Rules

Do not report:

- Pure aesthetics, layout polish, color, or copy changes.
- Accessibility findings unless they block an institutional workflow or create
  material operational ambiguity.
- Backend-only findings unless frontend behavior triggers or hides them.
- Missing generic audit dashboards unless a concrete evidence workflow is
  unreachable.
- Test gaps without a production failure mode.
- Client-side authorization concerns when backend enforcement is correct and
  the UI only affects convenience.

## 8. Allowed Read-Only Verification

You may run read-only or build/test commands if useful:

- `cd frontend-svelte && npm run check`
- `cd frontend-svelte && npm test`
- `cd frontend-svelte && npm run build`
- `cd frontend-svelte && npm run api:types:check`
- `cd frontend-svelte && npm run test:e2e` only if the required backend/test
  environment is already available.

Report any command you run and its result. If a command is unavailable because
the environment is not running, state that explicitly and continue with direct
code evidence.

## 9. Required Workflow

1. Read `docs/governance.md`.
2. Derive the current frontend route/API/mutation surface using repo searches.
3. Inspect the primary scope files and tests.
4. Validate each finding against current code, not memory or prior PR summaries.
5. Write the report to `docs/audits/2026-05-12-phase-a6-findings-gemini.md`.
6. Do not edit anything else.
