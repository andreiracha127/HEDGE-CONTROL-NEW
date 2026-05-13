# Cluster 1 Follow-Up Audit — Stage 1 Audit Dispatch — Auditor A

**Cluster:** 1 — A1 follow-up (deal-engine + exposure + scenario boundaries)
**Stage:** 1 of 3
**Target auditor:** Opus 4.7
**Authoring date:** 2026-05-13
**Repository:** `D:/Projetos/Hedge-Control-New`
**Branch:** `main` @ `ba032f476` (post-Cluster-2 merge)
**Expected output:** `docs/audits/2026-05-13-cluster-1-findings-opus.md`

## 1. Operating Instructions

You are performing a **read-only follow-up audit** of four cross-phase deferrals carried over from Phase A1 and Phase A3 jury verdicts. Do not edit code, tests, generated schemas, frontend files, migrations, or governance documents. Your job is to inspect the current backend services and produce an evidence-backed findings report against the four deferred surfaces and any genuinely-new gaps that the original A1/A3 audits did not see.

Use direct code evidence. Every accepted finding must include file and line references, a concrete failure mode, and the institutional rule it violates. Do not report cosmetic code-style preferences, naming preferences, or generic refactors unless they create a correctness, auditability, determinism, or reconstructability failure.

Treat these surfaces as **post-A1 evolved state**. The original A1 audit ran against `9f67357`; A3 against `659e5ba9d`. Several PRs have landed since then (A2 ledger work, A3 wave dispatches, A4 inbound/replay/LLM, A5 audit hardening, A6 frontend, Cluster 2 backend hardening). Code may have shifted; do not trust the original cited line ranges verbatim — re-derive surface state from current `main @ ba032f476`.

## 2. Institutional Context

Closed phases and waves:

- **A1** closed 2026-05-06 — economic primitives and lifecycle foundations.
- **A2** closed 2026-05-09 — RFQ canonical identity, ranking, award, outbound evidence.
- **A3** closed 2026-05-10 — valuation, MTM, cashflow baseline/ledger reconciliation, P&L lifecycle.
- **A4** closed 2026-05-10 — integration trust, inbound durability, replay, LLM decision reconstruction.
- **A5** closed 2026-05-12 — signed audit trail, mutation/evidence atomicity, audit history preservation, auth fail-closed.
- **A6** closed 2026-05-13 — frontend institutional control surface.
- **Cluster 2 backend hardening** closed 2026-05-13 — RFQ actor JWT derivation across 8 routes + status endpoint refuses settled; PR #71 merge `ba032f476`.

Binding governance is `docs/governance.md`. For Cluster 1 the load-bearing clauses are:

- **§2.1 Economic primitives integrity** — exposure aggregation must be canonical, not duplicated with drift potential.
- **§2.6 No silent fallback / no overflow clamp** — economic state cannot be silently repaired or extrapolated.
- **§2.7 Audit reconstructability** — every economic mutation has reconstructible evidence; lifecycle states are explicit; soft-delete must not orphan referential evidence.
- **No silent fallback** — applies especially to D-1.3 (snapshot reuse on total price unavailability).
- **Evidence missing or unprovable references are hard-fail.**
- **Phases remain explicit and must not be broadened.**

No edits to `docs/governance.md` may be proposed.

## 3. Deferred Surfaces — In Scope

The four deferrals you must audit are documented in `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §Cluster 1. Read that file and the prior jury verdicts before forming any finding.

### D-1.1 — Soft-deleted Deal retains invisible DealLink ownership
- Source: A1 jury — `J-A1-OPUS-07` (Tier 3 deferred).
- Original surfaces cited: `backend/app/models/deal.py` (`DealLink` unique constraint), `backend/app/services/deal_engine.py` (cross-deal uniqueness check in `add_link`), deal soft-delete lifecycle.
- A1 jury wrote: "If a deal is marked deleted while its links remain, those links still block reuse but the owning deal is hidden from normal deal reads."
- The fix direction was not specified — A1 jury asked a future audit to define the lifecycle contract for deleted deals and their links.

### D-1.2 — Exposure soft-delete creates duplicate source snapshots
- Source: A1 jury — `J-A1-OPUS-08` (Tier 3 deferred).
- Original surfaces cited: `backend/app/models/exposure.py` (`Exposure.is_deleted` lifecycle), `backend/app/services/exposure_engine.py` (`reconcile_from_orders`).
- A1 jury wrote: "Exposure soft-delete can create duplicate source snapshots."
- Since A1 closed, `reconcile_from_orders` has evolved — soft-delete retirement sweep (§3.8) and HedgeTask cancellation were added. Re-audit must verify whether the original gap remains or whether new gaps were introduced by the evolution.

### D-1.3 — Deal Engine repair path reuses prior snapshot price references
- Source: A3 jury — `X-A3-J-01` (cross-phase deferred to A1 follow-up).
- Original surface cited: `backend/app/services/deal_engine.py` snapshot-reuse repair path in `compute_deal_pnl`.
- A3 jury wrote: "Future audit must verify whether total price unavailability may legitimately reuse a sealed snapshot, or whether `PriceReferenceUnprovable` must always propagate even when a stored hash matches."
- This is an explicit **institutional decision request**. Your audit must produce a recommendation on this decision, supported by code evidence and constitutional rationale.

### D-1.4 — Scenario duplicates A1 exposure aggregation logic
- Source: A3 jury — `X-A3-J-02` (cross-phase deferred).
- Original surface cited: `backend/app/services/scenario_whatif_service.py` exposure aggregation functions.
- A3 jury wrote: "Future audit must verify extraction of shared pure exposure-calculation primitives usable by both live exposure and scenario what-if paths."
- The duplication is not automatically a valuation hard-fail because scenario runs over virtual deltas, but the durable risk is cross-phase drift from A1 exposure semantics.

## 4. Primary Scope

Start with these files and expand only as needed. Re-derive line ranges from current `main`; do not trust the original A1/A3 citations as line-stable.

### Code

- `backend/app/models/deal.py` — `Deal` (lifecycle: `is_deleted`, `deleted_at`), `DealLink` (unique constraints, lifecycle gap), `DealLinkedType`, `DealStatus`.
- `backend/app/models/exposure.py` — `Exposure` (lifecycle: `is_deleted`, `deleted_at`), `ContractExposure`, `HedgeExposure`, `HedgeTask`, `ExposureStatus`, `ExposureSourceType`.
- `backend/app/services/deal_engine.py` — `DealEngineService.add_link`, `remove_link`, `compute_deal_pnl` (especially the snapshot-reuse repair branch around the `unprovable_errors` path), `_recompute_tons`.
- `backend/app/services/exposure_engine.py` — `ExposureEngineService.reconcile_from_orders` (the soft-delete retirement sweep and HedgeTask cancellation), `_get_linked_qty_map`, `cancel_stale_tasks`, `list_pending_tasks`, all functions that read or aggregate `Exposure` rows.
- `backend/app/services/exposure_service.py` — `ExposureService.compute_commercial_snapshot` (the A1 canonical aggregation primitive).
- `backend/app/services/scenario_whatif_service.py` — `_compute_commercial_exposure`, `_compute_global_exposure`, `_apply_deltas`, `_load_orders`, `_load_contracts`, `_load_linkages`, `run_what_if`.
- `backend/app/services/linkage_service.py` — `LinkageService.create` and any consumer that queries `DealLink` without filtering by parent `Deal.is_deleted`.
- `backend/app/api/routes/deals.py` — any deal soft-delete / archive route.
- `backend/app/api/routes/exposures.py` — exposure reconcile route, exposure listing, hedge-task listing.
- `backend/app/api/routes/scenario.py` — scenario what-if route.

### Tests

- `backend/tests/test_deal_engine*.py`
- `backend/tests/test_exposure*.py`
- `backend/tests/test_scenario*.py`
- `backend/tests/test_linkage*.py`
- Any soft-delete coverage under `backend/tests/`.

### Prior jury context

Read in order, before forming findings:

1. `docs/governance.md`
2. `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §Cluster 1
3. `docs/audits/2026-05-06-phase-a1-jury-verdict.md` — search for `J-A1-OPUS-07` and `J-A1-OPUS-08`
4. `docs/audits/2026-05-09-phase-a3-jury-verdict.md` §8 — `X-A3-J-01` and `X-A3-J-02`

Derive the current surface rather than trusting these citations:

- `rg --files backend/app/services` to map all services.
- `rg -n "is_deleted|deleted_at" backend/app/models backend/app/services` to map soft-delete lifecycle touchpoints.
- `rg -n "DealLink" backend/app` to map every reader/writer.
- `rg -n "Exposure\\.is_deleted|Exposure\\(.*is_deleted" backend/app` to map exposure lifecycle filters.
- `rg -n "_compute_commercial_exposure|_compute_global_exposure|compute_commercial_snapshot|compute_global_exposure" backend/app` to map the duplication surface explicitly.
- `rg -n "DealPNLSnapshot|inputs_hash" backend/app/services/deal_engine.py` to map the snapshot reuse path.
- `rg -n "PriceReferenceUnprovable|unprovable" backend/app` to map the no-fallback discipline.

## 5. Audit Questions

Answer these questions explicitly. A negative answer is not automatically a finding; it becomes a finding only if it creates a concrete correctness, auditability, determinism, or reconstructability failure.

### Q1 — DealLink lifecycle vs Deal soft-delete (D-1.1 surface)

Does `DealLink` correctly reflect the lifecycle of its parent `Deal`?

Check: does soft-deleting a `Deal` cascade to its `DealLink` rows (cascade-delete, soft-delete-mirror, or block-on-active-links)? Does `add_link`'s cross-deal uniqueness query filter out links whose parent `Deal` is soft-deleted? Can a soft-deleted deal's link block a brand-new deal from claiming the same entity? Can an operator reconstruct **why** a link is blocked when the owner deal is invisible?

Findings include: blocked link reuse with invisible owner; orphan `DealLink` after `Deal` soft-delete; reuse-check that ignores `Deal.is_deleted`; DB unique constraint that disagrees with the service-layer check.

### Q2 — Exposure soft-delete and duplicate-source semantics (D-1.2 surface)

Does `Exposure` soft-delete preserve a clean single-live-row-per-source invariant?

Check: when `reconcile_from_orders` retires an `Exposure` whose source `Order` was soft-deleted, does any reader still iterate retired rows (e.g. for aggregation, P&L, scenario, audit)? When an `Order` is un-deleted, is the new `Exposure` row distinguishable from the retired one? Are `HedgeTask` rows linked to retired `Exposure` rows correctly cancelled (verify the §3.8 sweep + Codex P2 handling)? Are there consumers that filter `is_deleted == False` correctly, and any that don't?

Findings include: aggregation that double-counts retired+live exposures; HedgeTask still pending against a retired exposure; a reader path that doesn't filter `Exposure.is_deleted`; an un-retire path that creates a third row without retiring the second.

### Q3 — Deal Engine snapshot reuse on total price unavailability (D-1.3 surface)

Is the snapshot-reuse repair path institutionally legitimate?

Read the `compute_deal_pnl` body around the `unprovable_errors` branch. The current code returns a matching existing `DealPNLSnapshot` whose recomputed `inputs_hash` (using the candidate's persisted `price_references`) matches. **The A3 jury punted this decision; you must produce a recommendation.**

Frame the decision: under §"no silent fallback" and §"evidence missing is hard-fail", is reusing a sealed snapshot when zero fresh quotes are available a legitimate idempotency shortcut, or is it a silent extrapolation of stale price evidence? Consider: how is "stale" defined when no fresh evidence exists to compare? Is the snapshot's persisted `price_references` itself the evidence chain, or is the live quote always required? What happens if the legacy (pre-PR-8) snapshots without `price_references` are involved?

If you accept the current behavior, justify it. If you reject it, propose the constitutional shape of the fix (e.g. always propagate `PriceReferenceUnprovable`, gate reuse by a configurable `price_staleness_window`, or require an explicit `force_repair_from_snapshot` flag).

### Q4 — Scenario duplicates A1 exposure aggregation (D-1.4 surface)

Does `scenario_whatif_service` duplicate aggregation logic that lives canonically in `ExposureService.compute_commercial_snapshot` (or `_compute_global_exposure` equivalent)?

Read `_compute_commercial_exposure` and `_compute_global_exposure` in `scenario_whatif_service.py` and compare to `ExposureService.compute_commercial_snapshot` in `exposure_service.py`. Identify:

- Are the aggregation rules byte-equivalent today?
- Are there subtle drift points (sign conventions, residual clamping, commodity canonicalization, hedge-side mapping)?
- If A1 evolves (e.g. adds an over-allocation clamp, changes the canonical commodity table), does scenario diverge silently?
- What is the institutional cost of extracting a shared primitive (e.g. `compute_commercial_exposure_pure(orders, linkages, deltas) -> CommercialExposureRow[]`)?

Propose the smallest fix boundary that eliminates the drift potential. Do not propose a wide refactor.

### Q5 — Cross-deferral interactions (any combination of D-1.1 / D-1.2 / D-1.3 / D-1.4)

Are there interactions between the four deferrals that create gaps neither A1 nor A3 saw individually?

Examples to consider (not exhaustive):

- D-1.1 + D-1.2: if a deal is soft-deleted, are its linked `Exposure` rows retired? Or do they become orphan-but-live?
- D-1.2 + D-1.4: does scenario read soft-deleted exposures, producing different what-if state from live state?
- D-1.3 + D-1.4: does scenario's exposure recomputation also reuse stale snapshots?
- D-1.1 + D-1.3: does a snapshot reuse against a soft-deleted deal's link set still hash-match, leading to phantom P&L?

For each interaction you check, state what you searched and what you found. A finding here must show a concrete failure mode, not a speculative "could happen".

### Q6 — Audit/reconstruction coverage for these surfaces

Are existing `audit_event` integrations + signed audit trail (closed in A5) sufficient to reconstruct the institutional decisions touched by D-1.1 through D-1.4?

Check: does deal soft-delete emit a signed audit event with the link inventory? Does `reconcile_from_orders`'s retirement sweep emit an event per retired exposure? Does `compute_deal_pnl`'s snapshot-reuse branch leave reconstructible evidence (e.g. the reuse decision is loggable / queryable)? Does scenario `run_what_if` emit an event with the input deltas and the (potentially duplicated) aggregation result?

If reconstructability is incomplete on any of these surfaces, that is a finding under §2.7 — and it may constrain the recommended fix shape for D-1.3 (e.g. snapshot reuse becomes acceptable iff every reuse leaves a signed audit row).

### Q7 — Test coverage for the surfaces and their interactions

Do existing tests in `backend/tests/` protect the institutional invariants for these four surfaces?

Check: tests that cover deal soft-delete + link lifecycle; tests that cover exposure retirement and un-retire; tests that cover deal_engine snapshot reuse on total unprovable; tests that compare scenario aggregation to live aggregation. A test gap is a finding only when production code does not otherwise make the failure impossible.

## 6. Severity Taxonomy

Use this taxonomy:

- **Tier 1 / Blocking:** The current surface can produce an incorrect economic state (wrong P&L, wrong exposure aggregate, wrong scenario projection, wrong deal lifecycle decision) or make a closed A1/A3 invariant unreconstructible. Includes silent fallback that propagates stale price evidence without a hard-fail.
- **Tier 2 / High:** A real edge case can mislead operators or stale critical state, but live-data semantics remain correct under typical flow. Includes drift potential between scenario and live aggregation under a future A1 evolution.
- **Tier 3 / Medium:** A localized robustness, evidence, or coverage gap with plausible operational impact but no immediate economic-correctness breach.
- **Tier 4 / Low:** Documentation, cosmetic, test-only, or observability improvement. Do not include Tier 4 unless it protects a concrete Cluster 1 boundary.

When uncertain between two severities, choose the lower severity and explain the missing evidence that would make it higher.

## 7. Finding Format

Write findings in this format:

```markdown
## Finding J-CL1-OPUS-XX - Short imperative title

**Severity:** Tier N / Blocking|High|Medium|Low
**Status:** Open
**Deferral source:** D-1.1 | D-1.2 | D-1.3 | D-1.4 | Fresh (no prior deferral)
**Evidence:**
- `path/to/file.py:123` - what the code does
- `path/to/test.py:456` - relevant test gap or assertion, if any

**Failure mode:**
Describe the concrete sequence that breaks correctness, auditability, determinism, or reconstruction.

**Governance impact:**
Name the exact governance clause or institutional invariant.

**Recommended remediation boundary:**
State the smallest acceptable fix boundary. Do not prescribe broad refactors.

**Decision (only for D-1.3 and D-1.4 surfaces):**
For finings on the snapshot-reuse or scenario-duplication surfaces, state explicitly your recommendation for the institutional decision (e.g. "accept current reuse", "always propagate PriceReferenceUnprovable", "extract shared primitive into ExposureService.compute_commercial_exposure_pure", etc.) with a one-paragraph constitutional rationale.
```

After findings, include:

- `Anti-findings considered` — issues you inspected and rejected, with evidence.
- `Cross-cluster deferrals` — items that belong to Cluster 3 (security/platform), Cluster 4 (market-data governance), or a separate cycle.
- `Recommended remediation waves` — group accepted findings into coherent PR waves, preserving small blast radius.

## 8. Anti-Finding Rules

Do not report:

- Pure code-style preferences, naming, or comment density.
- Generic "improve readability" or "extract helper" recommendations without a concrete institutional failure mode.
- A1/A3 findings that have already been adjudicated and closed in those phases (re-read the verdicts and verify before reopening).
- Frontend issues (Cluster 1 is backend-only; A6 closed the frontend audit).
- RFQ actor-derivation or contract status-endpoint issues (Cluster 2 just closed those in PR #71 — do not re-litigate D-2.1 or D-2.2).
- A test gap when production code makes the failure impossible (an explicit constraint or invariant in the service code).
- Performance optimizations unless they cross a determinism or operator-visibility threshold.

## 9. Allowed Read-Only Verification

You may run read-only or build/test commands if useful:

- `pytest -q backend/tests` (full suite — slow, run once if needed)
- `pytest -q backend/tests/test_deal_engine*.py`
- `pytest -q backend/tests/test_exposure*.py`
- `pytest -q backend/tests/test_scenario*.py`
- `pytest -q backend/tests/test_linkage*.py`
- `python -m alembic heads` (confirm single head — must remain `043_a5_audit_payload_input` per §6.3 invariant of Cluster 2; you are not proposing migrations).
- Serena symbolic queries (`find_symbol`, `get_symbols_overview`, `find_referencing_symbols`).

Report any command you run and its result. If a command is unavailable because the environment is not running, state that explicitly and continue with direct code evidence.

## 10. Required Workflow

1. Read `docs/governance.md`.
2. Read `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §Cluster 1.
3. Read the prior jury verdicts (A1 J-A1-OPUS-07/08; A3 X-A3-J-01/02) — do not trust their cited line ranges; verify against current code.
4. Derive the current backend service surface using repo searches.
5. Inspect the primary scope files, tests, and any consumer of `DealLink`, `Exposure.is_deleted`, `DealPNLSnapshot`, scenario aggregation.
6. Validate each finding against current code at `main @ ba032f476`, not memory, not the prior A1/A3 line citations.
7. For D-1.3 and D-1.4, produce an explicit institutional **decision** with constitutional rationale — this is mandatory; punting to "future audit" is not allowed.
8. Write the report to `docs/audits/2026-05-13-cluster-1-findings-opus.md`.
9. Do not edit anything else.
