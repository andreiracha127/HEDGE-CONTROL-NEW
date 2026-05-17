# Tech-Lead Pilot Go/No-Go Brief Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `docs/2026-05-tech-lead-executive-analysis.md` as a prescriptive pilot go/no-go sign-off brief and remove the now-redundant `docs/2026-05-14-pilot-readiness-checklist.md` from the working tree in a single commit. (At authoring time the checklist was assumed to be tracked; Task 10 §2 below uses `git rm`, but if the file is untracked at execution time, a plain working-tree delete is the equivalent operation — see the brief's commit message for the deviation note.)

**Architecture:** Doc-authoring task with single-file output (one markdown file rewritten) plus a single-file deletion (the deprecated checklist). The brief follows the Decision-First, Evidence-Backing structure approved during brainstorming (7 sections; ~220-275 lines total). Source-of-truth is the design spec at `docs/superpowers/specs/2026-05-17-tech-lead-pilot-go-no-go-brief-design.md`.

**Tech Stack:** Markdown only (GFM tables, headings, lists). No code, no migrations, no tests.

---

## File Structure

**Files to change:**
- **Rewrite:** `docs/2026-05-tech-lead-executive-analysis.md` (currently 293 lines, becomes 220-275 lines per spec acceptance criterion 8)
- **Delete:** `docs/2026-05-14-pilot-readiness-checklist.md` (currently 125 lines, content absorbed into §4/§5/§7 of the brief)

**Source materials to read before/during authoring:**
- `docs/superpowers/specs/2026-05-17-tech-lead-pilot-go-no-go-brief-design.md` — the design spec; authoritative
- `docs/2026-05-tech-lead-executive-analysis.md` (current) — preserves structural cues + identifies stale facts to correct
- `docs/2026-05-14-pilot-readiness-checklist.md` (current) — operational content to migrate to §4/§5/§7
- `docs/governance.md` — cross-references in §3 (MARKET-DATA GOVERNANCE landed; AUTHORIZATION MATRIX landed)
- `MEMORY.md` (auto-loaded) — index of project memory entries used for cross-references
- 5 specific memory entries cross-referenced in the spec:
  - `project_a1_a6_backlog_closed.md`
  - `project_cluster_4_pr2_landed.md`
  - `reference_review_gates_2026_05_17.md`
  - `feedback_executor_false_completion_pattern.md`
  - `reference_audit_cycle_pattern.md`

**Files for cross-reference validation (acceptance criterion 10):**
- `docs/governance.md` (must exist)
- `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` (legacy citation; verify still present)
- The 5 memory files listed above (already verified during spec authoring)

---

### Task 1: Baseline read — gather source facts

**Files:** none changed; reading only.

- [ ] **Step 1: Read the design spec (authoritative)**

Open and re-read `docs/superpowers/specs/2026-05-17-tech-lead-pilot-go-no-go-brief-design.md` end-to-end. This is the canonical contract for what the brief contains.

- [ ] **Step 2: Capture the four facts that anchor §3 (Why this recommendation)**

Run from repo root:

```bash
git log --oneline -1 main
cd backend && python -m alembic heads && cd ..
git log --oneline main --since="2026-05-13" --until="2026-05-18" | wc -l
git log --oneline main --since="2026-05-13" --until="2026-05-18"
```

Expected:
- main HEAD: `94b029dec` (or later if main has advanced — use the actual current HEAD)
- alembic head: `045_market_data_governance_columns`
- commit count since 2026-05-13: ≥ 14 (the A1-A6 backlog closure rhythm)
- commit list visible for citation reference

Record these four facts on a scratch buffer; they go verbatim into §3.

- [ ] **Step 3: Confirm the deprecation target exists and capture its open-items list**

```bash
test -f docs/2026-05-14-pilot-readiness-checklist.md && echo "EXISTS" || echo "MISSING"
grep -c "^| " docs/2026-05-14-pilot-readiness-checklist.md
```

Expected: `EXISTS` and a count > 5 (the matrix and sign-off tables).

If MISSING: stop and inform Andrei — the migration plan in the spec assumes the file exists.

- [ ] **Step 4: Confirm governance.md sections referenced in §3**

```bash
grep -n "MARKET-DATA GOVERNANCE\|AUTHORIZATION MATRIX" docs/governance.md
```

Expected: two line numbers showing both appendices landed (one near line 188-340 for AUTHORIZATION MATRIX, one near line 442-748 for MARKET-DATA GOVERNANCE).

Record both line ranges; §3 cites them.

---

### Task 2: Author §1 RECOMMENDATION

**Files:**
- Create (overwrite): `docs/2026-05-tech-lead-executive-analysis.md`

Start the new file from scratch. Discard the old content entirely.

- [ ] **Step 1: Write the document header**

Open `docs/2026-05-tech-lead-executive-analysis.md` for full overwrite. Write exactly this header:

```markdown
# Tech-Lead Pilot Go/No-Go Brief — Hedge Control Platform

**Date:** 2026-05-17
**Document type:** Pilot launch decision brief (prescriptive)
**Pilot target:** Aluminium LME cash / 2-3 pre-approved counterparties / June 2026
**Author:** Tech-lead (orchestrator)
**Supersedes:** `docs/2026-05-14-pilot-readiness-checklist.md` (deleted in the same commit)
**Source spec:** `docs/superpowers/specs/2026-05-17-tech-lead-pilot-go-no-go-brief-design.md`

---
```

- [ ] **Step 2: Write the §1 RECOMMENDATION section**

Write exactly this section (~35-45 lines including the table). Substitute the actual `main` HEAD if it has advanced past `94b029dec`:

```markdown
## §1 RECOMMENDATION

**Verdict:** `conditional-go`.

Approve the launch of a controlled pilot of the Hedge Control Platform in **June 2026** for **aluminium LME cash settlement only** with **2-3 pre-approved counterparties**, contingent on the closure of the **4 hard blockers listed below** and the **signed approval of the four institutional signatories** named in §7.

**Why conditional-go (not unconditional-go):** the backend institutional core is fully closed post-A1-A6 backlog retirement (main `94b029dec`, alembic head `045_market_data_governance_columns`, 1440 backend tests passing). However, four compliance and operational frontes do not yet meet the threshold for operation with multiple real counterparties. Each is addressable inside the 4-week runway to a June launch.

### Hard blockers (mandatory before go-decision)

| # | Blocker | Owner | Closure evidence | Risk if accepted without closure |
|---|---|---|---|---|
| HB-1 | KYC gate minimum at RFQ creation (counterparty `KYC=approved` checked; governance amendment documenting the gate) | Backend | Guard tests + governance §amendment + audit-event coverage | Operating with non-approved counterparty → compliance violation |
| HB-2 | Workflow Approvals for mutations above threshold (Deal create/award + HedgeContract settle) | Backend + Frontend | Threshold config + approval state machine + audit trail completeness | Trader/risk_manager bypass of institutional limits |
| HB-3 | Finance Pipeline daily hardening (6 steps complete + idempotency + scheduled via Railway scheduler service) | Backend + Ops | End-to-end pipeline run + idempotency tests + scheduler runbook evidence | Manual reconciliation at 2-3 counterparty scale becomes operationally infeasible |
| HB-4 | Audit Daily Report (canned report for risk + auditor daily consumption; replaces ad-hoc verification) | Backend + Frontend | Report endpoint + frontend view + auditor sign-off of structure | Auditor without operational tooling → audit fatigue within days |

**Pre-requisite baseline (1-day pre-work, not a blocker):** update `docs/GAP_ANALYSIS_LEGACY_VS_NEW.md` to reflect the post-A1-A6 state — Deal Engine and Exposure Engine landed, Cluster 1-4 retired, alembic head 045.

**Nice-to-have / stretch (deferrable post-pilot, accepted with compensating controls per §6):** frontend table unification (Contracts, Orders, Audit pages), full Reports/Dashboard suite, Locust performance baseline, expanded custom Prometheus metrics.

**Effective `go` date:** the latest of (last HB closure, last signatory sign-off). At demonstrated institutional velocity (14 PRs in 5 days during the A1-A6 backlog closure 2026-05-13 to 2026-05-17), the realistic window is **2026-06-15 to 2026-06-25**.

**Sign-off:** see §7 for the four-signatory table and the explicit conditions linked to each HB.

---
```

- [ ] **Step 3: Validate §1 against acceptance criterion 1**

Acceptance criterion 1 from spec: "§1 reads as standalone (a signatory who reads only §1 understands the verdict, the 4 HBs, the scope, and what they're signing)."

Mental check: read only §1 (just-written). Confirm a signatory sees:
- Verdict word: `conditional-go` ✓
- Pilot scope: aluminium / 2-3 counterparties / June 2026 ✓
- 4 HBs with owners ✓
- Pre-work and stretch items distinguished ✓
- Pointer to §7 for sign-off ✓

If any is unclear, fix inline before moving on.

---

### Task 3: Author §2 Conditions of go — 4 hard blocker details

**Files:**
- Modify (append): `docs/2026-05-tech-lead-executive-analysis.md`

- [ ] **Step 1: Write §2 header + opening paragraph**

Append:

```markdown
## §2 Conditions of go — Detail of the 4 Hard Blockers

Each blocker below carries: why it is hard (vs nice-to-have), scope of implementation expected (reusing Cluster 3/4-style patterns where applicable), closure evidence required, and target placement within the 4-week runway to June launch.

```

- [ ] **Step 2: Write HB-1 sub-section (~18 lines)**

```markdown
### HB-1 — KYC gate minimum at RFQ creation

**Why hard:** governance.md AUTHORIZATION MATRIX (PR #79) declares counterparty per-type access, but no constitutional rule yet requires `kyc_status == approved` before a counterparty appears in any RFQ. With 2-3 real counterparties in the pilot, allowing a non-approved counterparty into the system — even by operator mistake — is a compliance event. A code gate plus a governance amendment is the institutionally consistent fix.

**Scope of implementation:**
1. Governance amendment in `docs/governance.md` — extend the AUTHORIZATION MATRIX section with an explicit KYC-gate invariant ("Counterparty MUST have `kyc_status == approved` before participating in any RFQ invitation, quote, or award").
2. Implementation dispatch in `docs/audits/2026-05-<date>-pilot-pr-kyc-gate-dispatch.md` citing the amendment.
3. Executor session (Codex CLI preferred per `feedback_executor_false_completion_pattern`) implements the guard in `backend/app/services/rfq_service.py` invitation path, the schema validation on `RFQInvitation`, and the audit event metadata expansion.

**Closure evidence required:**
- Guard tests in `backend/tests/test_rfq_kyc_gate.py` (creation rejection + audit event captured)
- Governance amendment merged to main with cross-reference from this brief
- Audit event `rfq_invitation_rejected_kyc_not_approved` emitted on the rejection path

**Target window:** Week 1 of the 4-week runway (governance amendment + dispatch authoring); Week 2 (executor implementation + review absorption).

```

- [ ] **Step 3: Write HB-2 sub-section (~18 lines)**

```markdown
### HB-2 — Workflow Approvals for mutations above threshold

**Why hard:** today every `risk_manager` can create, award, and settle without an approval state machine. With multiple counterparties, threshold-based approvals (e.g. notional above USD N requires a second signatory; settlement above USD M requires auditor co-sign) are the institutional minimum to prevent single-role bypass. Without this, the pilot's daily routine in §5 becomes unauditable at scale.

**Scope of implementation:**
1. Governance amendment in `docs/governance.md` extending AUTHORIZATION MATRIX with workflow-approval invariants and threshold parameters (configurable; default values negotiated with risk_manager).
2. New model `WorkflowApprovalRequest` (status, requested_by, approved_by, threshold_at_request, audit linkage).
3. Approval gate decorator inside Deal/HedgeContract mutation routes, plus frontend approval-pending panel for risk_manager.
4. Same dispatch/executor pattern as HB-1.

**Closure evidence required:**
- New alembic revision (046) for the model
- Backend tests covering threshold breach → approval required, single-role rejection, two-signatory approval acceptance, audit trail completeness
- Frontend e2e covering the approval flow on at least one mutation (Deal award)
- Governance amendment merged with cross-reference

**Target window:** Week 1-2 (amendment + model + dispatch); Week 2-3 (executor implementation + frontend); Week 3 (review absorption).

```

- [ ] **Step 4: Write HB-3 sub-section (~18 lines)**

```markdown
### HB-3 — Finance Pipeline daily hardening

**Why hard:** the Finance Pipeline currently exists as a model + service skeleton but is not running daily under the Railway scheduler service. At 2-3 counterparties the reconciliation evidence must be reconstructable from a deterministic, idempotent daily run, not from manual operator invocation. The pipeline has 6 known steps; gaps in any one break the reconstructability invariant.

**Scope of implementation:**
1. Confirm the 6 pipeline steps and their idempotency semantics; document any gap as a sub-deliverable inside the dispatch.
2. Wire the daily run into `app/scheduler_main.py` with `SCHEDULER_DISABLED` discipline (per `docs/runbook-railway.md`).
3. Add per-step idempotency tests (re-running the same step with the same inputs must be a no-op).
4. Runbook expansion in `docs/runbook-railway.md` documenting the daily run, expected outputs, and failure-recovery procedure.

**Closure evidence required:**
- End-to-end pipeline run test (`backend/tests/test_finance_pipeline_daily_run.py`) exercising all 6 steps
- Per-step idempotency tests
- Scheduler registration verified via `rg -nP "finance_pipeline" backend/app/scheduler_main.py backend/app/tasks/scheduler.py`
- Runbook section signed off by security/platform owner before HB-3 close

**Target window:** Week 2-3 (audit of current pipeline state + gap dispatch); Week 3-4 (executor implementation + runbook + sign-off).

```

- [ ] **Step 5: Write HB-4 sub-section (~18 lines)**

```markdown
### HB-4 — Audit Daily Report

**Why hard:** auditor currently verifies signatures ad-hoc via `/audit/events/{event_id}/verify`. At 2-3 counterparties producing many events per day, ad-hoc verification is operationally infeasible by week two of the pilot. A canned daily report — generated server-side, consumed in a single auditor page — is the minimum tooling required for the auditor to stay current without skipping events.

**Scope of implementation:**
1. New endpoint `/audit/reports/daily/{date}` aggregating: signed-event count, verification status of a deterministic sample, top-N entities mutated, any audit-signature failure, any RBAC rejection event.
2. Frontend page at `frontend-svelte/src/routes/(protected)/audit/daily/+page.svelte` rendering the report with one-click sample re-verification.
3. Auditor sign-off of the report structure before HB-4 closes (the structure itself must satisfy the auditor's daily review needs).

**Closure evidence required:**
- Backend tests covering the endpoint shape, deterministic sample selection, and failure-event surfacing
- Frontend e2e covering the auditor opening the report and triggering re-verification on a sample event
- Auditor signature on the report structure (captured in §7 sign-off table notes)

**Target window:** Week 3 (endpoint dispatch + implementation); Week 3-4 (frontend + auditor structure sign-off).

---
```

- [ ] **Step 6: Validate §2 against acceptance criterion 2**

Acceptance criterion 2 from spec: "§2 details each HB with enough specificity that a future executor session (Codex CLI per `feedback_executor_false_completion_pattern` recommendation) can author dispatches against them without further clarification."

Mental check: for each HB sub-section, confirm:
- The implementation scope is concrete enough to author a dispatch (files named, models named, governance section identified)
- Closure evidence is specific (test file paths + audit events + amendments)
- Target window is set within the 4-week runway

If any HB is too vague, expand the scope sub-bullets before moving on.

---

### Task 4: Author §3 Why this recommendation — evidence post-A1-A6

**Files:**
- Modify (append): `docs/2026-05-tech-lead-executive-analysis.md`

- [ ] **Step 1: Write §3 with concrete facts from Task 1 Step 2**

Append (substitute live values from Task 1 Step 2 if main has advanced):

```markdown
## §3 Why this recommendation — Evidence post-A1-A6

The conditional-go verdict rests on a state-of-the-system baseline that is materially stronger than at any prior point in the project's life. Five factual anchors:

**1. The entire A1-A6 jury cross-phase deferral backlog is institutionally CLOSED.** Main HEAD at `94b029dec` after 14 PRs merged between 2026-05-13 and 2026-05-17 closing Cluster 1 + Cluster 2 + Cluster 3 + Cluster 4 in sequence. Alembic head at `045_market_data_governance_columns`. The platform sits behind the constitutional governance lattice without remaining unresolved deferrals. (See `project_a1_a6_backlog_closed`.)

**2. Test density at production-grade.** Backend pytest at 1440 passed / 9 skipped after PR #88. Frontend Vitest at 292 tests across 22 files. svelte-check 0 errors / 0 warnings. CI 7/7 SUCCESS including Greptile Review as a gating check. Existing tests are not the gap.

**3. Multi-LLM review gates institutionalized.** Codex Connector was decommissioned 2026-05-17; replaced by AugmentCode (catches reviewer) + Greptile (catches + `+1` reaction acceptance signal). PR #88 — the first PR fully under the new gates — received 4 substantive catches (2 AugmentCode + 2 Greptile), all absorbed cleanly. The reviewer-side institutional protocol carried over with no quality regression. (See `reference_review_gates_2026_05_17`.)

**4. Audit cycle pattern validated.** The 3-stage adversarial review → jury verdict → wave dispatches → executor + reviewer → merge protocol (per `reference_audit_cycle_pattern`) executed across four clusters in five days with zero rollback events and zero post-merge governance violations. The pattern is reusable for any post-pilot expansion (hypothetical Phase A7 observability, hypothetical Phase B1 institutional-trader workflow, etc.).

**5. Constitution + governance.md remain canonical with two major appendices landed.** MARKET-DATA GOVERNANCE (PR #86, governance.md ~lines 442-748): three-tier provider trust, replay-window invariants, canonical reconciliation, precision contract, audit-trail attribution. AUTHORIZATION MATRIX (PR #79, governance.md ~lines 188-340): three human roles + four service identities + per-method counterparty authorization. Both are enforced in code with regression coverage.

**The key framing:** the residual risk to a June 2026 pilot is **not technical**. The core platform is mature, well-tested, and constitutionally protected. The residual risk is **compliance and operational** — captured precisely by the 4 hard blockers in §2 and the compensating-control residuals in §6.

---
```

- [ ] **Step 2: Validate §3 against acceptance criterion 3**

Acceptance criterion 3: "§3 is factually correct against main at `94b029dec` (cite SHA explicitly; cite alembic head; cite test counts)."

Mental check:
- SHA `94b029dec` cited (or the live SHA from Task 1 Step 2)
- Alembic head `045_market_data_governance_columns` cited
- Test counts (1440 backend / 292 frontend) cited
- Cluster closures cross-referenced
- Two governance appendices cited with line ranges

If main has advanced past `94b029dec` since the spec was written, substitute the live SHA. The narrative claim about the A1-A6 closure is anchored at `94b029dec` and that should stay as the anchor unless the entire backlog status has changed.

---

### Task 5: Author §4 Pilot scope — boundaries

**Files:**
- Modify (append): `docs/2026-05-tech-lead-executive-analysis.md`

- [ ] **Step 1: Write §4 with in/out lists**

Append:

```markdown
## §4 Pilot scope — Boundaries

### In scope

- **Commodity:** LME aluminium cash settlement only. Other LME-tracked metals (copper, etc.) remain post-pilot expansion.
- **Counterparties:** 2-3 pre-approved counterparties named explicitly in the signed sign-off (§7). Counterparty list change before pilot end requires re-signature by risk_manager + tech-lead.
- **Users:** named operators only (no broad organization rollout); credentials provisioned per user per Cluster 3 RBAC matrix.
- **Volume cap:** USD `<to be negotiated with risk_manager before sign-off>` per counterparty per trading day. Risk_manager fills the actual figure in the §7 sign-off notes. Any single trade above the cap → halt + tech-lead escalation.
- **Supervision:** risk_manager daily (full review per §5); auditor sample-basis (verifies sampled AuditEvent rows daily); tech-lead on-call for engineering escalations during trading hours.
- **Settlement evidence:** only canonical paths (`/cashflow/contracts/{contract_id}/settle`); generic status-patch settlement remains forbidden per dispatch §4 acceptance criteria of PR #76 (Cluster 1) and re-asserted here.

### Out of scope

- **Other commodities.** Multi-commodity pilot expansion is a separate decision after first-cycle pilot review (estimated 2026-Q3).
- **Counterparties not on the approved list.** Any new counterparty triggers re-signature, not silent addition.
- **Set-and-forget unsupervised operation.** An operator must be on-shift during trading hours; out-of-hours operation is deferred until full Cluster 3 production posture (Clerk `pk_live_*` + RSA keypair via production secrets manager + CSP enforce-flip).
- **Internet-facing public access.** Pilot operates inside the organization's restricted-network posture until the carryover Cluster 3 production items close.
- **Multiple market-data providers.** Westmetall remains the sole `trusted` provider per `docs/governance.md` §"Current providers". Drift-alert scaffold is ready (`market_data_governance.py`) but no audit-only provider exists today; introduction triggers governance amendment, not silent config.
- **Manual hedge workflows outside the canonical RFQ → HedgeContract → Settlement path.** Any out-of-path operation halts pilot until triaged.

---
```

- [ ] **Step 2: Validate §4 against acceptance criterion 4**

Acceptance criterion 4: "§4 enumerates concrete in/out items without ambiguity."

Mental check: each in-scope and out-of-scope item is unambiguous (named commodity, named counterparty rule, named volume-cap mechanism, named supervision roles). The "USD `<to be negotiated...>`" placeholder is intentional — the signed sign-off fills it. No other placeholders.

---

### Task 6: Author §5 Daily operating routine — cadence

**Files:**
- Modify (append): `docs/2026-05-tech-lead-executive-analysis.md`

- [ ] **Step 1: Write §5 with three time-blocks + stop conditions**

Append:

```markdown
## §5 Daily operating routine — Cadence

Cadence assumes a single trading day during pilot hours. Each block is owned by the named role; the operator/tech-lead is the fallback on-call.

### Morning (start of trading window)

- **Risk_manager** reviews open RFQs from the prior day, the current global net exposure value, and the price-drift delta since the last close (via `/exposures/global` and the Westmetall cash settlement listing).
- **Operator** confirms the scheduler service last-run timestamp via the Railway dashboard or `gh actions` log; confirms `AUDIT_SIGNING_KEY` health probe (a successful `/audit/events/{id}/verify` on the latest event).
- **Risk_manager** signs off morning review in the daily pilot log.

### Mid-day (after first round of awards)

- **Operator or scheduler** runs the Finance Pipeline daily run (manual until HB-3 closes; scheduled via Railway after).
- **Risk_manager** reconciles commercial exposure vs hedge book via `/exposures/reconcile` and checks Global Net Exposure delta.
- **Auditor** opens the Audit Daily Report (per HB-4) and reviews aggregated event counts, failure indicators, and the deterministic verification sample.

### End of day (post-close)

- **Auditor** samples 3-5 audit events manually via `/audit/events/{event_id}/verify` (in addition to the canned report sample); records each sample in the daily pilot log.
- **Auditor** confirms any settlement that occurred today went through `/cashflow/contracts/{contract_id}/settle`, not through a generic status patch.
- **Operator** records any KYC override / compliance exception in the pilot log with timestamp and the signatory who authorized the override.
- **Tech-lead** reviews the incident log for any halt-condition triggered; closes incidents or escalates as needed.

### Stop conditions (halt pilot activity until triaged)

- Any `market_data_replay_rejected` event with reason `bulk_content_mismatch` or `stale_feed`
- Any AuditEvent signature verification failure
- Any commercial exposure over-allocation (commercial > capacity)
- Any Workflow Approval bypass detected (post-HB-2 closure)
- Any KYC gate bypass detected (post-HB-1 closure)
- Any scheduler failure on the Finance Pipeline daily run (post-HB-3 closure)

When any stop condition triggers, tech-lead opens an incident, halts new RFQs until triaged, and reports to all signatories within 24 hours.

---
```

- [ ] **Step 2: Validate §5 against acceptance criterion 5**

Acceptance criterion 5: "§5 specifies cadence at a level a risk_manager could execute on day 1 without further training."

Mental check: each step names the role, the endpoint or UI surface, and the artifact produced. A risk_manager reading §5 alone has a daily routine they can perform without further onboarding.

---

### Task 7: Author §6 Risk acceptance summary

**Files:**
- Modify (append): `docs/2026-05-tech-lead-executive-analysis.md`

- [ ] **Step 1: Write §6 with two-column accepted-vs-mitigated split**

Append:

```markdown
## §6 Risk acceptance summary — Residuals

The pilot signatories accept the following residual risks for the pilot window. Each residual is either (a) compensated by an operational control during the pilot and re-evaluated at the first quarterly review, or (b) mitigated by one of the four hard blockers and therefore not a residual post-go.

### Accepted with compensating controls (residuals during the pilot window)

| Residual | Compensating control during pilot | Re-evaluation trigger |
|---|---|---|
| **KYC enforcement is manual for the pre-pilot counterparty list** | All 2-3 counterparties are pre-approved by risk_manager and named in the signed sign-off; the system does not yet block on `kyc_status` (HB-1 hardens this for unsupervised operation post-pilot) | First quarterly pilot review |
| **IdP is Clerk dev FAPI** | Custom domain Clerk (`pk_live_*`) and RSA keypair via production secrets manager are carryover Cluster 3 items; pilot operates inside restricted-network posture | First quarterly pilot review |
| **CSP is report-only** | Violation reporter is wired (per PR #85); enforce-flip is deferred 1-2 sprints after pilot start to collect telemetry first | After 1-2 sprints of report-only telemetry |
| **Single market-data provider (Westmetall)** | Drift-alert scaffold ready in `market_data_governance.py`; no audit-only provider exists today; introduction requires constitutional amendment | When a second `trusted` provider is proposed |
| **Frontend table duplication (Exposures-only adopted the shared DataTable)** | Contracts / Orders / Audit pages still use bespoke tables; functional and tested, just not unified | Post-pilot (stretch item) |
| **No expanded custom Prometheus metrics; no Locust baseline run** | Existing observability covers request latency, audit signature counts, and standard FastAPI surface; pilot scale is small enough that baseline performance is observable in real time | When pilot expands to more counterparties or commodities |

### Mitigated by the hard blockers (NOT residuals post-go)

Each hard blocker in §2 removes a specific risk from operation. Confirmation that HB closure removes the corresponding risk is part of the closure evidence in §2 and is verified by the signatories before final sign-off.

| Hard blocker | Risk removed by closure |
|---|---|
| HB-1 | KYC bypass risk (governance gate enforcement) |
| HB-2 | Limits bypass risk (approval state machine on threshold-crossing mutations) |
| HB-3 | Manual-reconciliation-drift risk (deterministic daily pipeline) |
| HB-4 | Audit-fatigue / verification-gap risk (canned auditor tooling) |

---
```

- [ ] **Step 2: Validate §6 against acceptance criterion 6**

Acceptance criterion 6: "§6 names the residuals as compensating-control-accepted vs HB-mitigated (no third category like 'deferred without compensating control')."

Mental check: every residual is in one of the two tables. No item appears as "deferred" or "TBD" outside the two categorical buckets.

---

### Task 8: Author §7 Sign-off table

**Files:**
- Modify (append): `docs/2026-05-tech-lead-executive-analysis.md`

- [ ] **Step 1: Write §7 with the four-signatory table + closure paragraph**

Append:

```markdown
## §7 Sign-off

The pilot launch is authorized when all four signatories below mark their decision as `Approved` AND all four hard blockers in §2 have their closure evidence committed to the repository with cross-reference from this brief.

| Role | Name | Decision | Date | Conditions (linked to HBs) | Notes |
|---|---|---|---|---|---|
| Risk manager | _to be filled_ | Pending | _to be filled_ | HB-1, HB-2, HB-3, HB-4 closed; counterparty list approved; volume cap negotiated and recorded in §4 |  |
| Auditor | _to be filled_ | Pending | _to be filled_ | HB-1, HB-4 closed; AuditEvent signing verified end-to-end against the daily report sample |  |
| Security / platform owner | _to be filled_ | Pending | _to be filled_ | HB-3 scheduler runbook signed off; CSP report-only telemetry acceptable; pilot network posture confirmed |  |
| Tech-lead | _to be filled_ | Pending | _to be filled_ | All HBs closed; GAP_ANALYSIS baseline pre-work landed; this brief is current against main HEAD |  |

The verdict in §1 transitions from `conditional-go` to **unconditional-go** the moment all four "Decision" cells read `Approved` AND all four HBs have linked closure evidence committed. Until then, no pilot trade occurs.

The signed brief is the authoritative pilot-launch record. Any amendment (counterparty list change, volume cap revision, scope expansion) requires re-signature by all four signatories.

---

*This brief replaces and deletes `docs/2026-05-14-pilot-readiness-checklist.md` in the same commit. The checklist's operational content lives in §4 (scope), §5 (daily routine), and §7 (sign-off table) of this document.*
```

- [ ] **Step 2: Validate §7 against acceptance criterion 7**

Acceptance criterion 7: "§7 sign-off table is fill-in-ready for the four signatories."

Mental check: table has four rows, each with role / placeholder name / Pending decision / placeholder date / linked HB conditions / empty notes column. Closure paragraph names the transition (conditional-go → unconditional-go) and the amendment rule.

---

### Task 9: Self-review against all 10 acceptance criteria

**Files:** none changed; reviewing only.

- [ ] **Step 1: Read the just-written brief end-to-end**

Open `docs/2026-05-tech-lead-executive-analysis.md` and read every line. Check tone (§1 prescriptive, §3 factual, §4-§5 operational, §6-§7 executive).

- [ ] **Step 2: Run each acceptance criterion**

For each criterion from the spec §"Acceptance criteria for the implementation":

1. §1 standalone? Re-read just §1. Verdict + HBs + scope + sign-off pointer all present. ✓ or fix.
2. §2 dispatch-ready specificity? Each HB names files/models/governance sections. ✓ or expand.
3. §3 factually correct? SHA + alembic head + test counts + cluster closures cited. ✓ or refresh.
4. §4 concrete in/out? Each item unambiguous. ✓ or refine.
5. §5 risk_manager-executable? Endpoints + roles + artifacts named. ✓ or specify.
6. §6 two-bucket residuals? No third category exists. ✓ or recategorize.
7. §7 fill-in-ready? Table has all four signatories with conditions. ✓ or complete.
8. Length 220-275 lines? Run `wc -l docs/2026-05-tech-lead-executive-analysis.md`. ✓ or trim/expand.
9. Tone correct per section? Mental re-read. ✓ or rephrase.
10. Cross-references valid? Run:

```bash
grep -nP "MEMORY|project_|reference_|feedback_|docs/governance|docs/audits|docs/runbook|backend/app|frontend-svelte" docs/2026-05-tech-lead-executive-analysis.md
```

For each non-memory path cited, verify it exists:

```bash
ls docs/governance.md docs/audits/2026-05-13-cross-phase-deferral-backlog.md docs/runbook-railway.md docs/superpowers/specs/2026-05-17-tech-lead-pilot-go-no-go-brief-design.md
```

If any path is missing, remove the citation or replace it with a valid path.

For memory entries, check `MEMORY.md` index (auto-loaded) for the cited slugs. If a slug is invalid, remove or correct it.

- [ ] **Step 3: Fix any failed acceptance inline**

If any criterion failed in Step 2, edit the relevant section. No need to re-run all criteria — just verify the fix.

---

### Task 10: Delete the deprecated checklist + commit single change

**Files:**
- Delete: `docs/2026-05-14-pilot-readiness-checklist.md`
- Already-modified: `docs/2026-05-tech-lead-executive-analysis.md`

- [ ] **Step 1: Verify the brief is complete and saved**

```bash
wc -l docs/2026-05-tech-lead-executive-analysis.md
grep -c "^## §" docs/2026-05-tech-lead-executive-analysis.md
```

Expected:
- Line count: 220-275 (per acceptance criterion 8)
- Section count: 7 (one heading per §)

If counts are wrong, return to Task 9 Step 3.

- [ ] **Step 2: Stage the two changes**

```bash
git rm docs/2026-05-14-pilot-readiness-checklist.md
git add docs/2026-05-tech-lead-executive-analysis.md
git status --short
```

Expected:
- `D  docs/2026-05-14-pilot-readiness-checklist.md`
- `M  docs/2026-05-tech-lead-executive-analysis.md`
- Plus the pre-existing untracked files (`Python/`, `iter*.json`, etc.) — those are NOT staged and remain untracked. Andrei manages them.

- [ ] **Step 3: Verify no unrelated files are staged**

```bash
git diff --cached --stat
```

Expected: exactly two files in the staged diff (the deletion + the rewrite). If any other file appears, unstage it (`git restore --staged <file>`).

- [ ] **Step 4: Commit the single change**

Use a HEREDOC for the commit message:

```bash
git commit -m "$(cat <<'EOF'
docs(pilot): rewrite tech-lead executive analysis as pilot go/no-go brief; deprecate stale checklist

Replaces docs/2026-05-tech-lead-executive-analysis.md (293 stale lines) with a
prescriptive 7-section sign-off brief carrying a conditional-go verdict for an
aluminium / 2-3 counterparty pilot launch in June 2026. Absorbs the operational
content of docs/2026-05-14-pilot-readiness-checklist.md (deleted in the same
commit) into §4 (scope), §5 (daily routine), and §7 (sign-off table).

4 hard blockers gate the verdict (HB-1 KYC gate; HB-2 Workflow Approvals;
HB-3 Finance Pipeline daily hardening; HB-4 Audit Daily Report). Conditional-go
transitions to unconditional-go when all 4 HBs close + all 4 signatories sign.

Brief anchored on main 94b029dec post-A1-A6 backlog closure (alembic head 045,
1440 backend tests, 7/7 CI green, multi-LLM gates institutionalized
post-Codex-decommission per reference_review_gates_2026_05_17).

Design spec: docs/superpowers/specs/2026-05-17-tech-lead-pilot-go-no-go-brief-design.md
Implementation plan: docs/superpowers/plans/2026-05-17-tech-lead-pilot-go-no-go-brief.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 5: Verify the commit landed**

```bash
git log --oneline -2
git show --stat HEAD
```

Expected:
- Latest commit is the one just authored
- `--stat` shows exactly two files changed (1 deletion, 1 modification)

- [ ] **Step 6: Final confirmation to Andrei**

Report back:
- Commit SHA (paste raw `git rev-parse HEAD`)
- Final line count (paste raw `wc -l docs/2026-05-tech-lead-executive-analysis.md`)
- Confirmation that the checklist is gone (paste raw `test -f docs/2026-05-14-pilot-readiness-checklist.md && echo EXISTS || echo DELETED`)
- Brief is ready for circulation to the four signatories (risk_manager, auditor, security/platform owner, tech-lead)

---

## Self-Review Notes (for the planner)

Spec coverage check: each of the 10 acceptance criteria from the spec is mapped to a validation step inside one of Tasks 2-9. The migration plan (single commit with delete + rewrite) is covered by Task 10. The 7 sections of the brief are covered one-per-task (Tasks 2-8). The 5 source-material reads are covered by Task 1.

Placeholder scan: the only intentional placeholders in the final brief are `_to be filled_` in the §7 sign-off table (signatories fill on signing) and `USD <to be negotiated with risk_manager before sign-off>` in §4 (risk_manager fills before signing). Both are flagged inline in the brief text as intentional fill-on-signing slots, not authoring failures.

Type consistency check: HB-1 through HB-4 are referenced consistently across §1 (table), §2 (sub-sections), §6 (mitigated-by table), §7 (per-signatory conditions). Each HB has the same owner string in every appearance.
