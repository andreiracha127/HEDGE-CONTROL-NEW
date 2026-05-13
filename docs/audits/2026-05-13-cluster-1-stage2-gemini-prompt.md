# Cluster 1 Follow-Up Audit — Stage 2 Audit Dispatch — Auditor B

**Cluster:** 1 — A1 follow-up (deal-engine + exposure + scenario boundaries)
**Stage:** 2 of 3
**Target auditor:** Gemini
**Authoring date:** 2026-05-13
**Repository:** `D:/Projetos/Hedge-Control-New`
**Branch:** `main` @ `ba032f476` (post-Cluster-2 merge)
**Expected output:** `docs/audits/2026-05-13-cluster-1-findings-gemini.md`

## 1. Operating Instructions

You are performing an **independent read-only follow-up audit** of four cross-phase deferrals carried over from Phase A1 and Phase A3 jury verdicts. Do not edit code, tests, generated schemas, frontend files, migrations, or governance documents.

Opus 4.7 is performing Stage 1 separately. GPT 5.5 will adjudicate in Stage 3. **Do not rely on either of them.** Your value is independent verification, adversarial state modeling, and catching failures that the first auditor may normalize as expected backend behavior — especially in soft-delete lifecycle interactions, snapshot reuse decisions, and aggregation duplication drift.

Use direct code evidence. Every accepted finding must include file and line references, a concrete failure mode, and the institutional rule it violates. Do not report style preferences, generic refactors, or aesthetic issues without a demonstrated correctness, auditability, determinism, or reconstructability impact.

Treat these surfaces as **post-A1 evolved state**. The original A1 audit ran against `9f67357`; A3 against `659e5ba9d`. Multiple PRs have landed since then. Code shifts may have introduced new gaps or partially closed old ones. Re-derive surface state from current `main @ ba032f476`; do not trust the original A1/A3 line citations.

## 2. Institutional Context

Closed phases and waves:

- **A1** closed 2026-05-06 — economic primitives.
- **A2** closed 2026-05-09 — RFQ canonical identity / ranking / outbound evidence.
- **A3** closed 2026-05-10 — valuation / MTM / cashflow / P&L lifecycle.
- **A4** closed 2026-05-10 — integration trust / inbound durability / replay / LLM decision reconstruction.
- **A5** closed 2026-05-12 — signed audit trail / mutation atomicity / auth fail-closed.
- **A6** closed 2026-05-13 — frontend control surface.
- **Cluster 2 backend hardening** closed 2026-05-13 (PR #71 at `ba032f476`) — JWT actor derivation across 8 RFQ-mutation routes + status endpoint refuses settled.

Binding governance is `docs/governance.md`. For Cluster 1, the load-bearing clauses are:

- **§2.1 Economic primitives integrity** — exposure aggregation is canonical and must not be duplicated with drift potential.
- **§2.6 No silent fallback / no overflow clamp** — economic state must not be silently repaired or extrapolated.
- **§2.7 Audit reconstructability** — every economic mutation has reconstructible evidence; lifecycle states are explicit; soft-delete must not orphan referential evidence.
- **No silent fallback** — applies especially to D-1.3 snapshot reuse on total price unavailability.
- **Evidence missing or unprovable references are hard-fail.**
- **Phases remain explicit; do not broaden into Cluster 2/3/4 territory.**

No edits to `docs/governance.md` may be proposed.

## 3. Deferred Surfaces — In Scope

The four deferrals you must audit are documented in `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §Cluster 1. Read that file and the prior jury verdicts before forming findings.

### D-1.1 — Soft-deleted Deal retains invisible DealLink ownership
- Source: A1 jury — `J-A1-OPUS-07` (Tier 3 deferred).
- Original concern: deal soft-delete leaves `DealLink` rows live; the unique constraint on `(linked_type, linked_id)` still blocks reuse but the owning deal is hidden from normal reads. Operator confusion when relinking a freed entity to a new deal.
- A1 jury did not specify the fix direction — your audit must propose it.

### D-1.2 — Exposure soft-delete creates duplicate source snapshots
- Source: A1 jury — `J-A1-OPUS-08` (Tier 3 deferred).
- Original concern: `Exposure` rows can pile up under the same `source_id` when soft-delete + reconcile produces retired+live pairs. Aggregators or audit consumers that iterate without filtering `is_deleted` may double-count.
- Post-A1, `reconcile_from_orders` was extended with a §3.8 retirement sweep and `HedgeTask` cancellation. Verify whether the original concern persists or whether new patterns introduce different gaps.

### D-1.3 — Deal Engine snapshot reuse on total price unavailability
- Source: A3 jury — `X-A3-J-01` (cross-phase deferred to A1 follow-up).
- Original concern: when ALL live price quotes are unavailable (`unprovable_errors` populated), `compute_deal_pnl` returns a matching `DealPNLSnapshot` whose recomputed hash matches the persisted `price_references`. A3 jury asked whether this is legitimate idempotency or silent extrapolation of stale evidence.
- This deferral requires an institutional decision. Your audit must propose one.

### D-1.4 — Scenario duplicates A1 exposure aggregation
- Source: A3 jury — `X-A3-J-02` (cross-phase deferred).
- Original concern: `scenario_whatif_service` re-implements commercial / global exposure aggregation that lives canonically in `ExposureService`. The duplication may not be a current valuation hard-fail (scenario runs over virtual deltas) but creates durable drift potential.
- A3 jury asked for extraction of a shared pure primitive. Your audit must verify whether that extraction is the right answer or whether a different fix shape applies.

## 4. Primary Scope

Re-derive line ranges from current `main @ ba032f476`. Do not trust the original A1/A3 citations.

### Code

- `backend/app/models/deal.py` — `Deal`, `DealLink`, `DealLinkedType`, `DealStatus`. Note: `DealLink` has no `is_deleted` / `deleted_at` columns; verify.
- `backend/app/models/exposure.py` — `Exposure` (lifecycle), `ContractExposure`, `HedgeExposure`, `HedgeTask`, `ExposureStatus`, `ExposureSourceType`.
- `backend/app/services/deal_engine.py` — `DealEngineService.add_link`, `remove_link`, `compute_deal_pnl` (the snapshot-reuse repair branch in the `unprovable_errors` path), `compute_pnl_breakdown`, `_recompute_tons`, `update_deal_status` (whether soft-delete touches link inventory).
- `backend/app/services/exposure_engine.py` — `ExposureEngineService.reconcile_from_orders`, `_get_linked_qty_map`, `cancel_stale_tasks`, `list_pending_tasks`, and any aggregator. Verify §3.7 (live-orders filter) and §3.8 (retirement sweep) coverage.
- `backend/app/services/exposure_service.py` — `ExposureService.compute_commercial_snapshot` and `compute_global_exposure` (the A1 canonical primitives).
- `backend/app/services/scenario_whatif_service.py` — `_compute_commercial_exposure`, `_compute_global_exposure`, `_apply_deltas`, `_load_orders`, `_load_contracts`, `_load_linkages`, `run_what_if`.
- `backend/app/services/linkage_service.py` — `LinkageService.create` and any reader that queries `DealLink`.
- `backend/app/api/routes/deals.py`, `backend/app/api/routes/exposures.py`, `backend/app/api/routes/scenario.py` — route layer for these surfaces.

### Tests

- `backend/tests/test_deal_engine*.py`
- `backend/tests/test_exposure*.py`
- `backend/tests/test_scenario*.py`
- `backend/tests/test_linkage*.py`
- `backend/tests/test_soft_delete*.py`

### Prior context

Read in order:

1. `docs/governance.md`
2. `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §Cluster 1
3. `docs/audits/2026-05-06-phase-a1-jury-verdict.md` — `J-A1-OPUS-07` and `J-A1-OPUS-08`
4. `docs/audits/2026-05-09-phase-a3-jury-verdict.md` §8 — `X-A3-J-01` and `X-A3-J-02`

Derive surface state via repo searches:

- `rg -n "is_deleted|deleted_at" backend/app/models backend/app/services` for soft-delete touchpoints.
- `rg -n "DealLink" backend/app` for every reader/writer.
- `rg -n "DealPNLSnapshot|inputs_hash" backend/app/services/deal_engine.py` for snapshot reuse.
- `rg -n "compute_commercial_exposure|compute_global_exposure|compute_commercial_snapshot" backend/app` for the duplication surface.
- `rg -n "PriceReferenceUnprovable" backend/app` for fail-closed discipline.

## 5. Audit Questions

Answer these questions explicitly. A negative answer is not automatically a finding; it becomes a finding only if it creates a concrete correctness, auditability, determinism, or reconstructability failure.

### Q1 — Soft-delete lifecycle symmetry across model layer

Is the soft-delete lifecycle symmetric and complete across `Deal`, `DealLink`, `Exposure`, `Order`, `HedgeTask`?

Check: which models have `is_deleted` / `deleted_at`? Which models that participate in lifecycle composition (parent → child references) do NOT have those columns? Is the absence intentional, or a coverage gap that lets parent-soft-delete orphan child rows? For `DealLink` specifically: is its absence of lifecycle columns a deliberate design ("links cascade with deal") or an unguarded gap ("links survive deal soft-delete")?

### Q2 — Cross-deal uniqueness check fairness under soft-delete

If Deal X is soft-deleted but its `DealLink` rows remain live, can a brand-new Deal Y reuse the same `linked_id`?

Check `add_link`'s cross-deal uniqueness query in `deal_engine.py`. Does it filter `Deal.is_deleted == False` on the joined parent? If not, what error message does Operator see when the blocking deal is invisible from `list_deals`? Is the DB unique constraint (`uq_deal_link_entity`) the binding gate, or the service-layer check? If both, do they agree?

Findings include: blocking-but-invisible-owner error; service vs DB constraint disagreement; a soft-delete that does not retire the link inventory.

### Q3 — Exposure retirement sweep completeness

Does `reconcile_from_orders`'s §3.8 retirement sweep + HedgeTask cancellation correctly close the J-A1-OPUS-08 gap?

Check: every reader of `Exposure` rows. Does each filter `is_deleted == False`? Are there callers that read all rows for audit / debugging / scenario? When the §3.8 sweep retires a row, is the corresponding `HedgeTask` cancellation guaranteed (Codex P2 fix at the time)? Can `un-delete` an `Order` create a third `Exposure` row without retiring the second?

Check also: does any aggregator that filters `is_deleted` rely on a `JOIN` that brings retired rows back in (e.g., through a `ContractExposure` or `HedgeExposure` table where retired exposures still appear)?

### Q4 — Snapshot reuse on total price unavailability — institutional decision

State your decision on D-1.3 with constitutional reasoning.

Read `compute_deal_pnl`'s `unprovable_errors` branch. The decision frame:

- **§"no silent fallback"** says the system must not silently extrapolate. Is reusing a sealed `DealPNLSnapshot` (whose hash matches the candidate's persisted `price_references`) a silent extrapolation, or a legitimate idempotency shortcut for repeated POSTs?
- **§"evidence missing is hard-fail"** says missing live evidence is a hard-fail condition. The reused snapshot has persisted evidence (`price_references`) but no fresh evidence. Is persisted evidence sufficient under §2.7 (reconstructability), or does §"no silent fallback" supersede?
- The legacy (pre-PR-8) snapshots without `price_references` are explicitly excluded from reuse. Does that exclusion alone justify the live-reuse path?

Propose a decision: (a) accept current reuse; (b) always propagate `PriceReferenceUnprovable`; (c) gate reuse behind an explicit `force_repair_from_snapshot` flag with signed audit evidence; (d) other. Give constitutional rationale.

### Q5 — Scenario aggregation duplication — drift surface

Where does `scenario_whatif_service` re-implement `ExposureService` aggregation, and where is the drift potential?

For each of `_compute_commercial_exposure` and `_compute_global_exposure` in `scenario_whatif_service.py`:

- Line-by-line compare against the corresponding `ExposureService` function.
- Identify exact divergences in: sign convention, residual clamping, commodity canonicalization, hedge-side mapping, over-allocation handling, rounding/precision, NULL handling on optional fields.
- For each divergence, classify it as (a) intentional virtual-delta semantics specific to scenario; (b) unintentional drift; (c) ambiguous.

Propose the smallest fix boundary. Candidates: extract `compute_commercial_exposure_pure(orders, linkages, deltas) -> CommercialExposureRow[]` into `exposure_service.py`; refactor scenario to call it; or maintain duplication with an explicit invariance test that asserts parity.

### Q6 — Cross-deferral interactions

Are there interactions between the four deferrals that produce failures neither A1 nor A3 saw individually?

Examples to test (not exhaustive):

- D-1.1 + D-1.2: a deal soft-delete that doesn't retire its linked `Exposure` rows.
- D-1.2 + D-1.4: scenario reading retired exposures and reporting wrong what-if state.
- D-1.3 + D-1.4: scenario also reusing stale snapshots during its own aggregation.
- D-1.1 + D-1.3: snapshot reuse against a soft-deleted deal's link set still hash-matches and produces phantom P&L.

For each interaction, state what you searched and what you concluded.

### Q7 — Audit reconstructability for the four surfaces

Can an operator reconstruct the institutional decisions touched by these surfaces from the signed audit trail (closed in A5)?

Check whether each of the following emits a signed audit event with enough state context:

- Deal soft-delete (with link inventory snapshot).
- Exposure retirement sweep (per retired exposure).
- Snapshot reuse decision (the reuse path itself, including which candidate was matched).
- Scenario `run_what_if` (input deltas + aggregation result).

A reconstructability gap is a finding under §2.7. It also constrains the recommended fix for D-1.3 — if you accept current snapshot reuse, the audit trail must record the reuse, not just the resulting computation.

### Q8 — Test protection for institutional invariants

Do existing backend tests protect the invariants for D-1.1 through D-1.4 and their interactions?

Identify any production-code invariant that a future regression could violate without a test catching it. A test gap is a finding only when production code does not otherwise enforce the invariant.

## 6. Severity Taxonomy

Use this taxonomy:

- **Tier 1 / Blocking:** Current backend can produce an incorrect economic state (wrong P&L, wrong exposure aggregate, wrong scenario projection, wrong deal lifecycle state) or make a closed A1/A3 invariant unreconstructible. Includes silent fallback that propagates stale price evidence without hard-fail.
- **Tier 2 / High:** Real edge case can mislead operators or stale critical state; live data remains correct under typical flow. Includes drift potential between scenario and live aggregation.
- **Tier 3 / Medium:** Localized robustness, evidence, or coverage gap with plausible operational impact; no economic-correctness breach.
- **Tier 4 / Low:** Documentation, cosmetic, test-only, or observability improvement. Do not include Tier 4 unless it protects a concrete Cluster 1 boundary.

When uncertain between two severities, choose the lower severity and explain the missing evidence that would make it higher. If you suspect a finding is in scope for Cluster 2 / 3 / 4 instead, defer it explicitly.

## 7. Finding Format

```markdown
## Finding J-CL1-GEMINI-XX - Short imperative title

**Severity:** Tier N / Blocking|High|Medium|Low
**Status:** Open
**Deferral source:** D-1.1 | D-1.2 | D-1.3 | D-1.4 | Fresh (no prior deferral)
**Evidence:**
- `path/to/file.py:123` - what the code does
- `path/to/test.py:456` - relevant test gap or assertion, if any

**Failure mode:**
Concrete sequence breaking correctness, auditability, determinism, or reconstruction.

**Governance impact:**
Exact governance clause or institutional invariant.

**Recommended remediation boundary:**
Smallest acceptable fix boundary.

**Decision (only for D-1.3 and D-1.4 surfaces):**
For snapshot-reuse or scenario-duplication findings, state explicitly your recommendation with a one-paragraph constitutional rationale.
```

After findings, include:

- `Anti-findings considered` — issues inspected and rejected, with evidence.
- `Cross-cluster deferrals` — items belonging to Cluster 3 / 4 or a separate cycle.
- `Recommended remediation waves` — group accepted findings into coherent PR waves, preserving small blast radius.

## 8. Anti-Finding Rules

Do not report:

- Code-style or naming preferences.
- Generic "refactor" recommendations without a concrete failure mode.
- A1/A3 findings already adjudicated and closed — re-read the verdicts and verify before reopening.
- Frontend issues (A6 closed; out of scope here).
- RFQ actor or contract status endpoint issues (Cluster 2 PR #71 just closed those — D-2.1 and D-2.2 are off-limits).
- A test gap when production code's invariants make the failure impossible.
- Performance issues unless they cross a determinism or operator-visibility threshold.

## 9. Allowed Read-Only Verification

You may run read-only or build/test commands if useful:

- `pytest -q backend/tests`
- `pytest -q backend/tests/test_deal_engine*.py`
- `pytest -q backend/tests/test_exposure*.py`
- `pytest -q backend/tests/test_scenario*.py`
- `pytest -q backend/tests/test_linkage*.py`
- `python -m alembic heads` (must show single head; you are not proposing migrations).
- Serena symbolic queries (`find_symbol`, `find_referencing_symbols`, `get_symbols_overview`).

Report any command run and its result. If a command is unavailable, state that explicitly and continue with direct code evidence.

## 10. Required Workflow

1. Read `docs/governance.md`.
2. Read `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §Cluster 1.
3. Read prior jury verdicts (A1 J-A1-OPUS-07/08; A3 X-A3-J-01/02). Verify cited code against current `main`; do not trust line ranges.
4. Derive current backend service surface using repo searches.
5. Inspect every consumer of `DealLink`, `Exposure.is_deleted`, `DealPNLSnapshot`, scenario aggregation.
6. Validate findings against current code at `main @ ba032f476`. Do not rely on memory or prior PR summaries.
7. For D-1.3 and D-1.4, produce an explicit institutional **decision** with constitutional rationale. Punting to "future audit" is not allowed.
8. Write the report to `docs/audits/2026-05-13-cluster-1-findings-gemini.md`.
9. Do not edit anything else.

## 11. Adversarial Posture

You are the second auditor. Your unique value is to:

- Reject Stage-1-style findings that normalize "the test passes" as proof of institutional safety when the test itself does not encode the institutional invariant.
- Catch interactions that a focused single-deferral pass misses (especially D-1.1 + D-1.2 soft-delete cascades and D-1.3 + D-1.4 stale-aggregation paths).
- Distinguish "current behavior is intentional" from "current behavior is accidentally correct under current flow". Only the former is anti-finding-eligible.
- Push back on silent-fallback rationalizations. §"no silent fallback" is a hard rule; any audit acceptance of current behavior must show why the current behavior is not a silent fallback by §2.6 / §2.7 standards.

Do not duplicate Stage 1's findings by accident. State your findings independently; the jury will deduplicate.
