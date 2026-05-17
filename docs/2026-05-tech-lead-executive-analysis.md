# Tech-Lead Pilot Go/No-Go Brief — Hedge Control Platform

**Date:** 2026-05-17
**Document type:** Pilot launch decision brief (prescriptive)
**Pilot target:** Aluminium LME cash / 8 pre-approved counterparties (2 per type: brokers, banks, suppliers, customers) / 140k tonnes/year volume cap / June 2026
**Author:** Tech-lead (orchestrator)
**Supersedes:** a prior draft pilot-readiness checklist (`docs/2026-05-14-pilot-readiness-checklist.md`) that existed as an untracked working artifact and was never committed to `main`; its operational content is absorbed into §4 / §5 / §7 below.
**Source spec:** `docs/superpowers/specs/2026-05-17-tech-lead-pilot-go-no-go-brief-design.md`

---

## §1 RECOMMENDATION

**Verdict:** `conditional-go`.

Approve the launch of a controlled pilot of the Hedge Control Platform in **June 2026** for **aluminium LME cash settlement only** with **8 pre-approved counterparties (2 brokers, 2 banks, 2 suppliers, 2 customers — fully enumerated in §4)** under a **140k tonnes/year aluminium volume cap**, contingent on the closure of the **4 hard blockers listed below** and the **signed approval of the four institutional signatories** named in §7.

**Why conditional-go (not unconditional-go):** the backend institutional core is fully closed post-A1-A6 backlog retirement (main `94b029dec`, alembic head `045_market_data_governance_columns`, 1440 backend tests passing). However, four compliance and operational fronts do not yet meet the threshold for operation with multiple real counterparties. Each is addressable inside the 4-week runway to a June launch.

### Hard blockers (mandatory before go-decision)

| # | Blocker | Owner | Closure evidence | Risk if accepted without closure |
|---|---|---|---|---|
| HB-1 | KYC gate minimum at RFQ creation (counterparty `KYC=approved` checked; governance amendment documenting the gate) | Backend | Guard tests + governance §amendment + audit-event coverage | Operating with non-approved counterparty → compliance violation |
| HB-2 | Workflow Approvals for mutations above threshold (Deal create/award + HedgeContract settle) | Backend + Frontend | Threshold config + approval state machine + audit trail completeness | Trader/risk_manager bypass of institutional limits |
| HB-3 | Finance Pipeline daily hardening (6 steps complete + idempotency + scheduled via Railway scheduler service) | Backend + Ops | End-to-end pipeline run + idempotency tests + scheduler runbook evidence | Manual reconciliation at 8-counterparty / 140k-tonne-annual scale becomes operationally infeasible |
| HB-4 | Audit Daily Report (canned report for risk + auditor daily consumption; replaces ad-hoc verification) | Backend + Frontend | Report endpoint + frontend view + auditor sign-off of structure | Auditor without operational tooling → audit fatigue within days |

**Pre-requisite baseline (1-day pre-work, not a blocker):** update `docs/GAP_ANALYSIS_LEGACY_VS_NEW.md` to reflect the post-A1-A6 state — Deal Engine and Exposure Engine landed, Cluster 1-4 retired, alembic head 045.

**Nice-to-have / stretch (deferrable post-pilot, accepted with compensating controls per §6):** frontend table unification (Contracts, Orders, Audit pages), full Reports/Dashboard suite, Locust performance baseline, expanded custom Prometheus metrics.

**Effective `go` date:** the latest of (last HB closure, last signatory sign-off). At demonstrated institutional velocity (14 PRs in 5 days during the A1-A6 backlog closure 2026-05-13 to 2026-05-17), the realistic window is **2026-06-15 to 2026-06-25**.

**Sign-off:** see §7 for the four-signatory table and the explicit conditions linked to each HB.

---

## §2 Conditions of go — Detail of the 4 Hard Blockers

Each blocker below carries: why it is hard (vs nice-to-have), scope of implementation expected (reusing Cluster 3/4-style patterns where applicable), closure evidence required, and target placement within the 4-week runway to June launch.

### HB-1 — KYC gate minimum at RFQ creation

**Why hard:** governance.md AUTHORIZATION MATRIX (PR #79) declares counterparty per-type access, but no constitutional rule yet requires `kyc_status == approved` before a counterparty appears in any RFQ. With 8 enumerated counterparties spanning 4 types in the pilot (§4), allowing a non-approved counterparty into the system — even by operator mistake — is a compliance event. A code gate plus a governance amendment is the institutionally consistent fix.

**Scope of implementation:**
1. Governance amendment in `docs/governance.md` — extend the AUTHORIZATION MATRIX section with an explicit KYC-gate invariant ("Counterparty MUST have `kyc_status == approved` before participating in any RFQ invitation, quote, or award").
2. Implementation dispatch in `docs/audits/2026-05-<date>-pilot-pr-kyc-gate-dispatch.md` citing the amendment.
3. Executor session (Codex CLI preferred per `feedback_executor_false_completion_pattern`) implements the guard in `backend/app/services/rfq_service.py` invitation path, the schema validation on `RFQInvitation`, and the audit event metadata expansion.

**Closure evidence required:**
- Guard tests in `backend/tests/test_rfq_kyc_gate.py` (creation rejection + audit event captured)
- Governance amendment merged to main with cross-reference from this brief
- Audit event `rfq_invitation_rejected_kyc_not_approved` emitted on the rejection path

**Target window:** Week 1 of the 4-week runway (governance amendment + dispatch authoring); Week 2 (executor implementation + review absorption).

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

### HB-3 — Finance Pipeline daily hardening

**Why hard:** the Finance Pipeline currently exists as a model + service skeleton but is not running daily under the Railway scheduler service. At 8 counterparties and ~560 tonnes/trading day average aluminium throughput (140k/year ÷ ~250 trading days), the reconciliation evidence must be reconstructable from a deterministic, idempotent daily run, not from manual operator invocation. The pipeline has 6 known steps; gaps in any one break the reconstructability invariant.

**Scope of implementation:**
1. Confirm the 6 pipeline steps and their idempotency semantics; document any gap as a sub-deliverable inside the dispatch.
2. Wire the daily run into `backend/app/scheduler_main.py` with `SCHEDULER_DISABLED` discipline (per `docs/runbook-railway.md`).
3. Add per-step idempotency tests (re-running the same step with the same inputs must be a no-op).
4. Runbook expansion in `docs/runbook-railway.md` documenting the daily run, expected outputs, and failure-recovery procedure.

**Closure evidence required:**
- End-to-end pipeline run test (`backend/tests/test_finance_pipeline_daily_run.py`) exercising all 6 steps
- Per-step idempotency tests
- Scheduler registration verified via `rg -nP "finance_pipeline" backend/app/scheduler_main.py backend/app/tasks/scheduler.py`
- Runbook section signed off by security/platform owner before HB-3 close

**Target window:** Week 2-3 (audit of current pipeline state + gap dispatch); Week 3-4 (executor implementation + runbook + sign-off).

### HB-4 — Audit Daily Report

**Why hard:** auditor currently verifies signatures ad-hoc via `/audit/events/{event_id}/verify`. At 8 counterparties spanning 4 types producing many events per day (RFQ creation, invitation, quote, award, contract settlement, audit-event emission per mutation), ad-hoc verification is operationally infeasible by week two of the pilot. A canned daily report — generated server-side, consumed in a single auditor page — is the minimum tooling required for the auditor to stay current without skipping events.

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

## §3 Why this recommendation — Evidence post-A1-A6

The conditional-go verdict rests on a state-of-the-system baseline that is materially stronger than at any prior point in the project's life. Five factual anchors:

**1. The entire A1-A6 jury cross-phase deferral backlog is institutionally CLOSED.** Main HEAD at `94b029dec` after 14 PRs merged between 2026-05-13 and 2026-05-17 closing Cluster 1 + Cluster 2 + Cluster 3 + Cluster 4 in sequence. Alembic head at `045_market_data_governance_columns`. The platform sits behind the constitutional governance lattice without remaining unresolved deferrals. (See `project_a1_a6_backlog_closed`.)

**2. Test density at production-grade.** Backend pytest at 1440 passed / 9 skipped after PR #88. Frontend Vitest at 292 tests across 22 files. svelte-check 0 errors / 0 warnings. CI 7/7 SUCCESS including Greptile Review as a gating check. Existing tests are not the gap.

**3. Multi-LLM review gates institutionalized.** Codex Connector was decommissioned 2026-05-17; replaced by AugmentCode (catches reviewer) + Greptile (catches + `+1` reaction acceptance signal). PR #88 — the first PR fully under the new gates — received 4 substantive catches (2 AugmentCode + 2 Greptile), all absorbed cleanly. The reviewer-side institutional protocol carried over with no quality regression. (See `reference_review_gates_2026_05_17`.)

**4. Audit cycle pattern validated.** The 3-stage adversarial review → jury verdict → wave dispatches → executor + reviewer → merge protocol (per `reference_audit_cycle_pattern`) executed across four clusters in five days with zero rollback events and zero post-merge governance violations. The pattern is reusable for any post-pilot expansion (hypothetical Phase A7 observability, hypothetical Phase B1 institutional-trader workflow, etc.).

**5. Constitution + governance.md remain canonical with two major appendices landed.** MARKET-DATA GOVERNANCE (PR #86, governance.md ~lines 442-748): three-tier provider trust, replay-window invariants, canonical reconciliation, precision contract, audit-trail attribution. AUTHORIZATION MATRIX (PR #79, governance.md ~lines 188-340): three human roles + four service identities + per-method counterparty authorization. Both are enforced in code with regression coverage.

**The key framing:** the residual risk to a June 2026 pilot is **not technical**. The core platform is mature, well-tested, and constitutionally protected. The residual risk is **compliance and operational** — captured precisely by the 4 hard blockers in §2 and the compensating-control residuals in §6.

---

## §4 Pilot scope — Boundaries

### In scope

- **Commodity:** LME aluminium cash settlement only. Other LME-tracked metals (copper, etc.) remain post-pilot expansion.
- **Counterparties:** 8 pre-approved counterparties spanning all 4 institutional types (per `docs/governance.md` AUTHORIZATION MATRIX, Cluster 3 per-type access). All 8 named explicitly here; any change before pilot end requires re-signature by risk_manager + tech-lead.

  | Type      | Counterparties (pre-approved)                |
  | --------- | -------------------------------------------- |
  | Broker    | Stonex Financial, Marex                      |
  | Bank      | Banco BS2, Itaú                              |
  | Supplier  | Alecar, Rusal                                |
  | Customer  | Casa do Alumínio, Aluminios del Mexico        |

  Per-type access semantics (binding): `trader` sees customers + suppliers only; brokers and banks are invisible to `trader` (GET returns 404 to avoid existence leak). Risk_manager and auditor see all 8. **Post-HB-1 (target state for pilot day 1):** the HB-1 KYC gate (§2 HB-1) operates against this pre-approved list — any RFQ invitation pointing at a counterparty not in this table OR with `kyc_status != approved` is rejected at creation with an audit event. **Pre-HB-1 (current code):** the gate does not exist yet; admission is procedural (the 8 names are pre-approved by risk_manager and operator discipline keeps non-list counterparties out — see §6 residual risk "KYC enforcement is manual for the pre-pilot counterparty list").

- **Users:** named operators only (no broad organization rollout); credentials provisioned per user per Cluster 3 RBAC matrix.
- **Volume cap:** **140,000 tonnes of aluminium per year (institutional annual cap; equivalent to 140k tonnes/year as written elsewhere in this brief).** Derived per-day average ≈ 560 tonnes (140,000 ÷ ~250 trading days). The institutional cap is the annual figure; risk_manager negotiates per-counterparty and per-day sub-caps from this top-line during sign-off (recorded in §7 notes). Any single trade that would breach the annual cap year-to-date → halt + tech-lead escalation. The HB-2 workflow approval threshold (§2 HB-2) is calibrated against this volume framing.
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

## §6 Risk acceptance summary — Residuals

The pilot signatories accept the following residual risks for the pilot window. Each residual is either (a) compensated by an operational control during the pilot and re-evaluated at the first quarterly review, or (b) mitigated by one of the four hard blockers and therefore not a residual post-go.

### Accepted with compensating controls (residuals during the pilot window)

| Residual | Compensating control during pilot | Re-evaluation trigger |
|---|---|---|
| **KYC enforcement is manual for the pre-pilot counterparty list** | All 8 counterparties (§4) are pre-approved by risk_manager and named in the signed sign-off; the system does not yet block on `kyc_status` (HB-1 hardens this for unsupervised operation post-pilot) | First quarterly pilot review |
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

*This brief supersedes a prior draft pilot-readiness checklist (`docs/2026-05-14-pilot-readiness-checklist.md`) that existed as an untracked working artifact and was never committed to `main`. The checklist's operational content lives in §4 (scope), §5 (daily routine), and §7 (sign-off table) of this document.*
