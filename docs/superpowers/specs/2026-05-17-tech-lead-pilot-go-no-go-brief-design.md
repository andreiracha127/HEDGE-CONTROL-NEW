# Design Spec — Tech-Lead Pilot Go/No-Go Brief

**Date:** 2026-05-17
**Status:** Design approved by Andrei; ready for implementation planning
**Output artifact:** `docs/2026-05-tech-lead-executive-analysis.md` (rewritten in place)
**Sibling action:** `docs/2026-05-14-pilot-readiness-checklist.md` deleted in the same commit (`git rm`)

---

## Goal

Transform the existing tech-lead executive analysis (293 lines, dated Maio 2026, factually stale post-A1-A6 backlog closure) into a **prescriptive pilot go/no-go sign-off brief** for the four institutional signatories (risk_manager, auditor, security/platform owner, tech-lead).

The brief carries an explicit verdict — `conditional-go` for an aluminium pilot with 2-3 counterparties launching in June 2026 — contingent on the closure of 4 hard blockers identified during the brainstorming.

The brief absorbs the operational content of `docs/2026-05-14-pilot-readiness-checklist.md` (Gate A/B/C, sign-off table, daily routine, open items matrix) into a single decision document. The current checklist is deleted in the same commit; its content lives on as §4 (scope), §5 (daily routine), and §7 (sign-off table) of the new brief.

## Design decisions (from brainstorming dialogue 2026-05-17)

| Decision | Choice | Rationale |
|---|---|---|
| Primary audience | Pilot go/no-go sign-off | Four signatories need a decision document, not an analytical reference |
| Relation to existing checklist | Replaces (deletes the checklist; absorbs its operational content) | Avoid divergence between two parallel artifacts; single decision document |
| Pilot launch target | June 2026 (~4 weeks runway from 2026-05-17) | Enough runway to close Workflow Approvals + Finance Pipeline + minimum reports |
| Pilot scope | Aluminium LME cash / 2-3 counterparties (medium volume, supervised) | Representative without material exposure; stress-tests RBAC + KYC gate without multi-commodity complexity |
| Brief tone | Prescriptive with strong recommendation | Mature tech-lead brief pattern; signatories accept/reject the recommendation rather than build the decision from raw evidence |
| Structural approach | Decision-First, Evidence-Backing (Approach A) | Recommendation up front, evidence after; standard board-brief shape |

## Verdict carried by the brief

**`Conditional-go`** — approve the pilot launch in June 2026 contingent on:

1. **4 hard blockers closed** (HB-1 through HB-4, listed below)
2. **4 signatories sign-off** (risk_manager + auditor + security/platform owner + tech-lead)
3. **1-day baseline pre-work completed** (GAP_ANALYSIS_LEGACY_VS_NEW.md update reflecting post-A1-A6 state)

Effective `go` date is the latest of (last HB closure, last signatory sign-off). Estimated 2026-06-15 to 2026-06-25 at demonstrated institutional velocity (~14 PRs in 5 days during A1-A6 backlog closure).

### Hard blockers identified

| # | Blocker | Owner | Closure evidence required | Risk if accepted without closure |
|---|---|---|---|---|
| HB-1 | KYC gate minimum at RFQ creation (counterparty `KYC=approved` checked; governance amendment documenting the gate) | Backend | Guard tests; governance §amendment; audit-event coverage | Operating with non-approved counterparty → compliance violation |
| HB-2 | Workflow Approvals for mutations above threshold (Deal create/award + HedgeContract settle) | Backend + Frontend | Threshold config + approval state machine + audit trail completeness | Trader/risk_manager bypass of institutional limits |
| HB-3 | Finance Pipeline daily hardening (6 steps complete + idempotency + scheduled via Railway scheduler service) | Backend + Ops | End-to-end pipeline run + idempotency tests + scheduler runbook evidence | Manual reconciliation at 2-3 counterparty scale becomes operationally infeasible |
| HB-4 | Audit Daily Report (canned report for risk + auditor daily consumption; replaces ad-hoc verification) | Backend + Frontend | Report endpoint + frontend view + auditor sign-off of the structure | Auditor without operational tooling → audit fatigue within days |

Nice-to-have / stretch (deferrable post-pilot): frontend table unification (Contracts, Orders, Audit pages); Reports/Dashboard suite complete; Locust performance baseline; custom Prometheus metrics expansion.

## Brief structure — 7 sections

### §1 RECOMMENDATION (~30-40 lines)

The decision-carrying section. Reads like an executive cover.

Content:
- Verdict: `Conditional-go` with one-paragraph statement.
- Pilot scope summary: aluminium / 2-3 counterparties / June 2026.
- 4 hard blockers listed in table form (#/blocker/owner/closure-evidence/risk-if-accepted).
- Pre-requisite baseline: GAP_ANALYSIS update (1-day pre-work, not a blocker).
- Nice-to-have/stretch deferrals (one line summary).
- Effective `go` date contingent statement.
- Pointer to §7 sign-off table.

The reader sees the verdict and the conditions on page one. Everything after §1 is the evidence backing.

### §2 Conditions of go — detail of the 4 hard blockers (~60-80 lines)

Per blocker, 4 sub-sections of ~15-20 lines each:

- **Why this is hard** (institutional context — what makes it block-worthy vs nice-to-have)
- **Scope of implementation** (referencing Cluster 3/4-style patterns: governance amendment first when applicable, then dispatch, then executor session; cite existing scaffolds where they support the work, e.g. `market_data_governance.py` registry pattern reused for KYC tiers)
- **Closure evidence requirements** (specific tests, governance lines, runbook deliverables)
- **Target window within the 4-week runway** (week 1 / week 2 / week 3 / week 4 placement)

### §3 Why this recommendation — evidence post-A1-A6 (~40-50 lines)

State-of-the-system update reading as factual baseline:

- All four clusters closed; main at `94b029dec`; alembic head at `045_market_data_governance_columns`.
- 1440 backend tests passing / 9 skipped; 292 frontend tests; 7/7 CI checks green.
- 14 PRs merged across 5 days (2026-05-13 to 2026-05-17); ~100+ catches absorbed pre-Codex-decommission; ~30+ hook v2 cycles.
- Multi-LLM review gates institutionalized (Codex Connector decommissioned 2026-05-17; replaced by AugmentCode + Greptile with comparable rigor — see `reference_review_gates_2026_05_17`).
- Constitution + governance.md remain canonical; MARKET-DATA GOVERNANCE appendix landed (PR #86); AUTHORIZATION MATRIX appendix landed (PR #79).
- 100% scope discipline across the backlog (zero post-merge governance violation detected).

Closes with the key framing: **the residual risk is not technical**. The core platform is mature and well-protected. The residual risk is **compliance/operational** (covered by the 4 HBs).

### §4 Pilot scope — boundaries (~30-40 lines)

In scope:
- Commodity: LME aluminium cash settlement only
- Counterparties: 2-3 pre-approved (named in the signed sign-off; subject to risk_manager approval)
- Volume cap: USD X / counterparty / day (specific number to be negotiated with risk_manager before sign-off; placeholder in the spec)
- Supervision: risk_manager daily; auditor sample basis; tech-lead on-call for engineering escalations

Out of scope:
- Other commodities (copper, etc.) — future pilot expansion after first cycle review
- Counterparties not on the approved list — pre-pilot list change requires re-signature
- Set-and-forget operation — operator is on-shift during pilot trading hours
- Internet-facing production without custom-domain Clerk + RSA keypair via production secrets manager (carryover from Cluster 3)
- Multiple market-data providers (Westmetall remains sole trusted provider per `docs/governance.md` §"Current providers")

### §5 Daily operating routine — cadence (~25-35 lines)

Cadence for risk_manager + auditor + operator/tech-lead:

**Morning (start of trading window):**
- Risk_manager reviews open RFQs from prior day + global net exposure delta + price drift since last close
- Operator confirms scheduler last-run timestamp + audit signing key health probe

**Mid-day (after first round of awards):**
- Finance pipeline manual or scheduled run (per HB-3 state)
- Risk_manager reconciles commercial exposure vs hedge book
- Audit daily report (per HB-4) generated and reviewed

**End of day (post-close):**
- Auditor samples 3-5 audit events via `/audit/events/{event_id}/verify`
- Auditor confirms any settlement went through `/cashflow/contracts/{contract_id}/settle` (not generic status patch)
- Operator records any KYC/compliance override decision in the pilot log
- Tech-lead reviews incident log if any halt-condition triggered

**Stop conditions (halt pilot activity until triaged):**
- Price-reference failure (`market_data_replay_rejected` reason `bulk_content_mismatch` or `stale_feed`)
- Audit-signature failure on any economic mutation
- Exposure over-allocation (commercial > capacity)
- Workflow Approval bypass detected (post-HB-2 closure)
- KYC gate bypass detected (post-HB-1 closure)

### §6 Risk acceptance summary — residuals (~20-30 lines)

Two-column table:

**Accepted with compensating controls** (the pilot signatories accept these as residuals during the pilot window):
- KYC: manual approval per counterparty in the pre-pilot list; HB-1 hardens this for unsupervised operation post-pilot
- IdP: Clerk dev FAPI (production custom-domain + RSA keypair via secrets manager remain Cluster 3 carryover)
- CSP: report-only ramp continues (enforce-flip after 1-2 sprints of telemetry per Cluster 3 carryover)
- Single market-data provider: Westmetall sole `trusted` provider; drift-alert scaffold ready but no audit-only provider exists today
- Frontend table duplication: Exposures-only DataTable adoption (Contracts/Orders/Audit still use bespoke tables — stretch)

**Mitigated by hard blockers** (each HB removes one residual from operation):
- HB-1 removes "KYC bypass risk" by enforcing the gate
- HB-2 removes "Limits bypass risk" by enforcing approval thresholds
- HB-3 removes "Manual reconciliation drift risk" by automating pipeline
- HB-4 removes "Audit fatigue / verification gap risk" by canned reporting

Re-evaluation trigger for accepted residuals: **first quarterly pilot review** (estimated 2026-Q3) — at that point each accepted residual is re-classified as still-acceptable / now-mitigated / now-blocker.

### §7 Sign-off table (~15-20 lines)

Four signatories; conditions linked to the 4 HBs.

| Role | Name | Decision | Date | Conditions (linked to HBs) | Notes |
|---|---|---|---|---|---|
| Risk manager | _to be filled_ | Pending | _to be filled_ | HB-1, HB-2, HB-3, HB-4 closed; pilot counterparty list approved; volume cap negotiated |  |
| Auditor | _to be filled_ | Pending | _to be filled_ | HB-1, HB-4 closed; AuditEvent signing verified end-to-end |  |
| Security/platform owner | _to be filled_ | Pending | _to be filled_ | HB-3 scheduler runbook signed off; CSP report-only telemetry acceptable |  |
| Tech-lead | _to be filled_ | Pending | _to be filled_ | All HBs closed; GAP_ANALYSIS baseline pre-work landed |  |

Below the table: a paragraph confirming that conditional-go becomes unconditional-go once all four "Decision" cells read `Approved` AND all four HBs have linked closure evidence committed to the repo.

## Migration plan

**Single commit** rewriting the tech-lead doc and deleting the checklist:

```
git rm docs/2026-05-14-pilot-readiness-checklist.md
# rewrite docs/2026-05-tech-lead-executive-analysis.md per the 7-section structure above
git add docs/2026-05-tech-lead-executive-analysis.md
git commit -m "docs(pilot): rewrite tech-lead executive analysis as pilot go/no-go brief; deprecate stale checklist"
```

No PR needed — the brief is internal-decision artifact and the deletion of the checklist is the orchestrator's call per project ownership (Andrei).

## Acceptance criteria for the implementation

The implementation plan (next step: writing-plans skill) will produce a step-by-step plan to author this brief. Acceptance criteria for the finished brief:

1. §1 reads as standalone (a signatory who reads only §1 understands the verdict, the 4 HBs, the scope, and what they're signing).
2. §2 details each HB with enough specificity that a future executor session (Codex CLI per `feedback_executor_false_completion_pattern` recommendation) can author dispatches against them without further clarification.
3. §3 is factually correct against main at `94b029dec` (cite SHA explicitly; cite alembic head; cite test counts).
4. §4 enumerates concrete in/out items without ambiguity.
5. §5 specifies cadence at a level a risk_manager could execute on day 1 without further training.
6. §6 names the residuals as compensating-control-accepted vs HB-mitigated (no third category like "deferred without compensating control").
7. §7 sign-off table is fill-in-ready for the four signatories.
8. Total length 220-275 lines (vs 293 + 125 = 418 in the current two-document state; ~35% net reduction by elimination of duplication).
9. Tone is prescriptive in §1, factual in §3, operational in §4-§5, executive in §6-§7.
10. Cross-references to `docs/governance.md`, the closed cluster memories, and `MEMORY.md` index entries are valid (no link rot to non-existent files).

## Cross-references to memory

- `project_a1_a6_backlog_closed` — backlog closure milestone the brief is anchored on
- `project_cluster_4_pr2_landed` — final cluster closure (the brief baselines from this commit)
- `reference_review_gates_2026_05_17` — current institutional review gates referenced in §3
- `feedback_executor_false_completion_pattern` — pattern referenced in §2 (executor recommendation for the HB dispatches)
- `reference_audit_cycle_pattern` — pattern referenced in §2 for HB execution discipline
