# Phase A6 - Stage 1 Audit Dispatch - Auditor A

**Phase:** A6 - Frontend Svelte institutional control surface
**Stage:** 1 of 3
**Target auditor:** Opus 4.7
**Authoring date:** 2026-05-12
**Repository:** `D:/Projetos/Hedge-Control-New`
**Branch:** `main`
**Expected output:** `docs/audits/2026-05-12-phase-a6-findings-opus47.md`

## 1. Operating Instructions

You are performing a read-only institutional frontend audit. Do not edit code,
tests, generated schemas, backend files, migrations, or governance documents.
Your job is to inspect the current Svelte frontend and produce an
evidence-backed findings report.

Use direct code evidence. Every accepted finding must include file and line
references, a concrete failure mode, and the institutional rule it violates. Do
not report visual style preferences, naming preferences, generic refactors, or
"nice to have" UI improvements unless they create a correctness,
auditability, determinism, authorization, or operational-control failure.

Treat the frontend as an institutional control surface, not a marketing site.
The frontend may be a finding when it can send an incorrect mutation, suppress
a backend hard-fail, display stale or misleading financial state, break role
boundaries, corrupt numeric semantics, or make an operator unable to
reconstruct what action was taken.

## 2. Institutional Context

Closed phases:

- A1 is closed: economic primitives and lifecycle foundations.
- A2 is closed: RFQ canonical identity, ranking, award, and outbound evidence.
- A3 is closed: valuation, MTM, cashflow baseline, ledger reconciliation, and
  P&L lifecycle.
- A4 is closed: integration trust, inbound durability, replay, and LLM decision
  reconstruction.
- A5 is closed: signed audit trail, mutation/evidence atomicity, audit history
  preservation, and auth fail-closed guardrails.

Phase A6 audits whether the Svelte frontend faithfully preserves and exposes
those closed backend contracts. Do not reopen backend business logic unless
frontend behavior can provoke an incorrect backend call, misrepresent a backend
hard-fail as success, or hide evidence needed by an operator.

Binding governance is `docs/governance.md`. For A6, the relevant institutional
rules are:

- auditability and reconstructability are primary optimization targets;
- messages and decision artifacts are evidence;
- evidence missing, ambiguous dates, unreconstructible contracts, and
  unprovable references are hard-fail conditions;
- no mutation without evidence;
- no silent fallback;
- phases are explicit and must not be broadened into unrelated product work.

## 3. Primary Scope

Start with these files and expand only as needed:

- `frontend-svelte/package.json`
- `frontend-svelte/src/routes/+layout.svelte`
- `frontend-svelte/src/routes/(protected)/+layout.svelte`
- `frontend-svelte/src/routes/(public)/login/+page.svelte`
- `frontend-svelte/src/lib/api/fetch.ts`
- `frontend-svelte/src/lib/api/client.ts`
- `frontend-svelte/src/lib/api/schema.d.ts`
- `frontend-svelte/src/lib/stores/auth.svelte.ts`
- `frontend-svelte/src/lib/stores/ws.svelte.ts`
- `frontend-svelte/src/lib/utils/format.ts`
- `frontend-svelte/src/lib/utils/sanitize.ts`
- `frontend-svelte/src/lib/components/table/DataTable.svelte`
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
- `frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte`
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte`
- `frontend-svelte/src/routes/(protected)/analytics/what-if/+page.svelte`
- `frontend-svelte/e2e/*.spec.ts`
- `frontend-svelte/src/**/*.test.ts`
- `docs/api/openapi_v1.json`

Derive the current frontend surface rather than trusting this list:

- Use `rg --files frontend-svelte/src/routes` to map routed pages.
- Use `rg -n "apiFetch\\(" frontend-svelte/src` to map API use.
- Use `rg -n "method:" frontend-svelte/src` to identify mutating calls.
- Use `rg -n "fetch\\(" frontend-svelte/src` to catch raw fetch bypasses.
- Use `rg -n "authStore\\.has|hasRole|hasAnyRole" frontend-svelte/src` to map
  frontend role gating.
- Use `rg -n "Number\\(|parseFloat|parseInt|toFixed|type=\"number\"|bind:value" frontend-svelte/src`
  to map numeric conversion and form entry points.

Do not accept a generated type file as proof if page code ignores it with
`any`, fallback fields, stale endpoint names, or ad hoc response parsing.

## 4. Audit Questions

Answer these questions explicitly. A negative answer is not automatically a
finding; it becomes a finding only if it creates a concrete correctness,
auditability, determinism, authorization, or reconstruction failure.

### Q1 - API Contract Discipline

Does the frontend call backend endpoints with the current OpenAPI contract?

Check generated schema usage, endpoint names, request bodies, response parsing,
raw `fetch`, duplicated `apiFetch` helpers, and `any` casts in critical flows.
A schema mismatch is a finding when it can send an incorrect mutation, read the
wrong response field, hide a hard-fail, or display incorrect financial state.

### Q2 - Institutional Mutation Workflows

Do all frontend mutation flows preserve backend semantics?

Inspect RFQ create, preview, quote/ranking display, award, reject, cancel,
refresh, archive, order creation/archive/linking, counterparty create/update,
cashflow settlement, MTM/P&L snapshots, and scenario execution. Confirm the UI
does not enable unsupported transitions, submit stale state, double-submit
critical actions, or report success before the backend confirms success.

### Q3 - Hard-Fail and Error Surfacing

Are backend hard-fail responses visible and operationally unambiguous?

Check handling of HTTP 400, 401, 403, 404, 409, 422, 424, and 5xx responses.
Findings include treating non-2xx as success, replacing a hard-fail with empty
data, retrying in a way that hides the failure, or showing an operator a stale
success state after rejection.

### Q4 - Numeric, Unit, and Direction Integrity

Does the frontend preserve institutional numeric semantics?

Audit quantities in MT, prices in USD/MT, P&L/MTM/cashflow values, signs,
directions, date windows, rounding, and display formatting. `Number`,
`parseFloat`, `parseInt`, `toFixed`, and `<input type="number">` are not
findings by themselves; they are findings when they can corrupt submitted
payloads or misstate displayed financial values.

### Q5 - Identity and Evidence Preservation

Does the UI preserve canonical IDs and evidence references?

Check RFQ numbers, UUIDs, order IDs, contract IDs, counterparty IDs, quote IDs,
state-event timelines, inbound evidence references, and audit/verification
links where exposed. Do not allow display names, array indexes, or stale local
state to become mutation identifiers.

### Q6 - Auth, Role, and Session Boundaries

Does frontend auth/role behavior support backend fail-closed policy?

Inspect login, token storage, expiry handling, logout, route protection,
Authorization headers, WebSocket authentication, and role-gated UI actions.
Frontend role gating is not a backend security boundary; report it only when
it can mislead operators, keep stale capabilities visible, omit required auth,
or break auditor/trader/risk-manager workflows.

### Q7 - Real-Time State and Race Discipline

Can WebSocket events, polling fallback, or local state create stale decisions?

Inspect sequence handling, subscription ownership, stale ranking checks,
load/reload races, duplicate event processing, optimistic updates, and terminal
state handling. A finding requires a concrete path to wrong action availability
or misleading institutional state.

### Q8 - Generated Schema and Drift Controls

Can frontend schema drift survive CI or local regeneration?

Inspect `frontend-svelte/scripts/regen-schema.mjs`,
`frontend-svelte/scripts/check-schema-drift.sh`, `docs/api/openapi_v1.json`,
`frontend-svelte/src/lib/api/schema.d.ts`, and workflow usage. Report drift
only if it can let frontend code compile or ship against a stale backend
contract.

### Q9 - Auditability of Operator Actions

Can an operator reconstruct what they did from the UI state and backend
evidence?

Check critical screens for enough identifiers and state context before actions
such as award, reject, cancel, settle, archive, and scenario run. A missing
label is not enough; the finding must show a realistic operator can submit or
confirm the wrong institutional action because canonical context is hidden or
ambiguous.

### Q10 - Test and E2E Coverage for Critical Paths

Do frontend tests protect the critical institutional workflows?

Inspect unit tests, store tests, formatting tests, and Playwright tests. Test
gaps are findings only when they leave a concrete frontend invariant
unprotected and production code does not otherwise make the failure impossible.

## 5. Severity Taxonomy

Use this taxonomy:

- **Tier 1 / Blocking:** The frontend can submit an incorrect institutional
  mutation; enable an unsupported lifecycle transition; misreport a backend
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
## Finding J-A6-OPUS-XX - Short imperative title

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

- Pure visual preference, color, spacing, or copy changes.
- Generic "improve UX" recommendations without a concrete institutional
  failure mode.
- Backend-only defects unless frontend behavior triggers or hides them.
- Missing pages as findings unless a required institutional evidence workflow
  is unreachable or unreconstructible.
- A test gap when production code makes the failure impossible.
- A raw `any` cast unless it masks a concrete contract or state failure.
- Client-side role gating as a security issue by itself when the backend
  enforces authorization correctly.

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
5. Write the report to `docs/audits/2026-05-12-phase-a6-findings-opus47.md`.
6. Do not edit anything else.
