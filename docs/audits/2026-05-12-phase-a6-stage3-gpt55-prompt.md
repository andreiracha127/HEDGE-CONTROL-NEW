# Phase A6 - Stage 3 Jury Dispatch

**Phase:** A6 - Frontend Svelte institutional control surface
**Stage:** 3 of 3
**Target jury:** GPT 5.5
**Authoring date:** 2026-05-12
**Repository:** `D:/Projetos/Hedge-Control-New`
**Branch:** `main`
**Expected output:** `docs/audits/2026-05-12-phase-a6-jury-verdict.md`

## 1. Operating Instructions

You are the institutional jury for Phase A6. This is a read-only adjudication.
Do not edit implementation code, tests, generated schemas, backend files,
migrations, or governance documents.

Your job is to adjudicate two independent frontend auditor reports:

- Auditor A: `docs/audits/2026-05-12-phase-a6-findings-opus47.md`
- Auditor B: `docs/audits/2026-05-12-phase-a6-findings-gemini.md`

You must validate every accepted finding by reading the current code directly.
Do not rubber-stamp either auditor. Do not reject a finding only because the
other auditor missed it. Do not accept a finding unless it has a concrete
failure mode supported by current frontend code and, where relevant, the
backend contract it calls.

## 2. Inputs

Read these files first:

- `docs/governance.md`
- `docs/audits/2026-05-12-phase-a6-stage1-opus47-prompt.md`
- `docs/audits/2026-05-12-phase-a6-stage2-gemini-prompt.md`
- `docs/audits/2026-05-12-phase-a6-findings-opus47.md`
- `docs/audits/2026-05-12-phase-a6-findings-gemini.md`

Then inspect implementation evidence in the Phase A6 scope:

- `frontend-svelte/package.json`
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
- all routed pages under `frontend-svelte/src/routes/(protected)/`
- frontend tests under `frontend-svelte/src/**/*.test.ts`
- Playwright tests under `frontend-svelte/e2e/`
- `frontend-svelte/scripts/regen-schema.mjs`
- `frontend-svelte/scripts/check-schema-drift.sh`
- `docs/api/openapi_v1.json`

Derive the current surface rather than trusting the list:

- `rg --files frontend-svelte/src/routes`
- `rg -n "apiFetch\\(" frontend-svelte/src`
- `rg -n "method:" frontend-svelte/src`
- `rg -n "fetch\\(" frontend-svelte/src`
- `rg -n "authStore\\.has|hasRole|hasAnyRole" frontend-svelte/src`
- `rg -n "Number\\(|parseFloat|parseInt|toFixed|type=\"number\"|bind:value" frontend-svelte/src`

## 3. Binding Governance

Binding governance is `docs/governance.md`. For Phase A6, these clauses are
central:

- auditability and reconstructability are primary optimization targets;
- institutional messages and decision artifacts are evidence;
- evidence missing and unprovable references are hard-fail;
- contracts and state transitions must be reconstructible;
- no silent fallback;
- no mutation without evidence;
- phases remain explicit and must not be broadened into unrelated backend or
  product work.

Hard-fail, determinism, auditability, role discipline, numeric integrity, and
reconstruction remain mandatory.

## 4. Jury Questions

For each auditor finding, answer:

1. Is the cited frontend path reachable in the current routed application?
2. Does the failure involve a real backend endpoint, generated schema contract,
   store, or component state, or is it speculative?
3. Can it submit an incorrect mutation, expose an unsupported lifecycle action,
   misreport hard-fail as success, corrupt numeric/identity semantics, stale a
   critical state, or block reconstruction?
4. Does backend enforcement make the frontend issue non-blocking, and if so,
   what severity remains?
5. Does the finding belong in A6, or should it be deferred to backend,
   observability, design-system, or later cross-phase cleanup?
6. Is the remediation boundary small enough for a controlled PR wave?

You may add fresh findings only if both auditors missed a concrete,
evidence-backed issue discovered during adjudication. Fresh findings must meet
the same standard as accepted auditor findings.

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
  improvement. Do not carry Tier 4 unless it protects a concrete A6 boundary.

If an auditor overstates severity, downgrade it. If an auditor understates a
governance breach, upgrade it. Explain every severity change.

## 6. Verdict Format

Write the verdict to:

`docs/audits/2026-05-12-phase-a6-jury-verdict.md`

Use this structure:

```markdown
# Phase A6 Jury Verdict

## Executive Summary

- Total accepted findings: N
- Tier 1: N
- Tier 2: N
- Tier 3: N
- Tier 4: N
- Rejected auditor findings: N
- Fresh jury findings: N

## Accepted Findings

### J-A6-XX - Canonical title

**Source:** Opus J-A6-OPUS-XX | Gemini J-A6-GEMINI-XX | Jury Fresh
**Severity:** Tier N / Blocking|High|Medium|Low
**Status:** Open
**Disposition:** Accepted | Accepted with severity change | Accepted as subsumed
**Evidence:**
- `path/to/file.svelte:123` - frontend evidence
- `path/to/schema.d.ts:456` - contract evidence, if relevant

**Failure mode:**
Concrete sequence.

**Governance impact:**
Exact invariant.

**Remediation boundary:**
Smallest acceptable PR boundary.
```

Then include:

```markdown
## Rejected Findings

### Auditor finding ID - short title

**Disposition:** Rejected
**Reason:** Evidence-based reason, with file/line references where relevant.

## Subsumed Findings

Map duplicate auditor findings to the canonical accepted finding.

## Cross-Phase Deferrals

Items that are real but belong to backend, design-system, observability, or a
later cross-phase cleanup.

## Recommended Remediation Waves

### PR-A6-1 - Short wave title
- Findings: J-A6-...
- Scope boundary:
- Required verification:

### PR-A6-2 - Short wave title
- Findings: J-A6-...
- Scope boundary:
- Required verification:

## Anti-Findings Confirmed

Important suspected issues that were checked and found safe.
```

## 7. Adjudication Rules

- Convergent findings are not automatically correct. Verify them.
- Single-auditor findings are not automatically weak. Verify them.
- Reject findings that are merely style, preference, generic "better UX", or
  visual polish without a concrete institutional failure mode.
- Preserve narrow PR boundaries. Do not turn A6 into a broad frontend rewrite.
- Do not alter `docs/governance.md`.
- Do not recommend merge. This stage only produces the jury artifact and
  remediation sequencing.
- If Stage 1 or Stage 2 reports are missing, stop and report that the stage is
  incomplete rather than fabricating a verdict.

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
