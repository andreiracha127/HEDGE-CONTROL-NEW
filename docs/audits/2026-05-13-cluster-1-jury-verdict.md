# Cluster 1 Follow-Up Audit — Jury Verdict

## Executive Summary

- Total accepted findings: 5
- Tier 1: 3
- Tier 2: 1
- Tier 3: 1
- Tier 4: 0
- Rejected auditor findings: 1
- Fresh jury findings: 0
- Original A1/A3 deferrals retired: 4/4 (D-1.1, D-1.2, D-1.3, D-1.4)

Cluster 1 is not clean, but the failure surface is narrower than Auditor A's raw count and materially stronger than Auditor B's minimal list. D-1.2 is closed by the current exposure retirement design. D-1.1 is not reachable through a Deal archive route today, but DealEngine still consumes archived Orders / HedgeContracts as live economics. D-1.3 and D-1.4 require binding institutional decisions and both land as correctness work.

Commands run:
- `pytest -q backend/tests/test_pr5_lifecycle_acceptance.py backend/tests/test_pnl_provenance.py backend/tests/test_scenario_whatif_run.py backend/tests/test_deal_engine.py` — 124 passed, 5 skipped, 2 deprecation warnings.
- `python -m alembic heads` from `backend/` — single head `043_a5_audit_payload_input`.

## Institutional Decisions

### D-1.3 — Deal Engine snapshot reuse on total price unavailability

**Decision:** Reject current reuse. Always propagate `PriceReferenceUnprovable` when zero live quotes are available.

**Rationale:**
Governance forbids fallback pricing regimes and hard-fails when price reference evidence is missing (`docs/governance.md:146`, `docs/governance.md:174-184`). The current branch returns a historical `DealPNLSnapshot` when all quotes are unprovable, and the hash check proves only the deal id, date, link ids, and persisted `price_references`, not the live economic content behind those links. Under §2.6 and §2.7, a compute endpoint cannot silently substitute a sealed historical valuation for an unprovable current valuation. Historical retrieval belongs in history endpoints; current computation must fail closed.

**Implementation shape:**
Remove the `if unprovable_errors:` candidate-probe branch in `DealEngineService.compute_deal_pnl` and raise the first `PriceReferenceUnprovable`. Invert the existing total-unavailability reuse tests so the expected result is a hard-fail and no new snapshot. **HTTP boundary: the route layer must map the propagated `PriceReferenceUnprovable` to HTTP `424 Failed Dependency` per `docs/governance.md:152` ("Hard-fail propagation: price reference unprovable → HTTP 424"). Any inline guidance in the Stage 1 Opus findings that names HTTP 422 for this case is overridden by this verdict — 422 is reserved by governance for missing zero-default economics (`avg_entry_price`, `fixed_price_value`) and missing settlement_date (governance lines 155-157), not for unprovable live prices.** If product later insists on outage repair, it must be a separate explicit request path with caller opt-in, signed `reused_during_outage` audit evidence, and a hash that includes canonical content of every linked Order / HedgeContract. Do not keep the current implicit repair branch.

### D-1.4 — Scenario duplicates A1 exposure aggregation

**Decision:** Extract shared primitive.

**Rationale:**
Exposure aggregation is a canonical economic primitive. The current scenario service duplicates live A1 aggregation and already diverges on lifecycle filters: scenario loads all Orders, all HedgeContracts, and all HedgeOrderLinkage rows, while live A1 filters archived Orders, archived hedges, and inactive hedge statuses. This is not merely future drift potential; it can produce a wrong scenario projection today. Under §2.1, scenario may add explicit virtual deltas, but its baseline must start from the same live primitive as `/exposures/commercial` and `/exposures/global`.

**Implementation shape:**
Add shared pure aggregation functions under `ExposureService`, for example:
- `compute_commercial_exposure_pure(*, orders: list[tuple[Order, Decimal]], linkages: list[HedgeOrderLinkage], calculation_timestamp: datetime) -> list[CommercialExposureRead]`
- `compute_global_exposure_pure(*, orders: list[tuple[Order, Decimal]], contracts: list[HedgeContract], virtual_contracts: list[VirtualHedgeContract], linkages: list[HedgeOrderLinkage], calculation_timestamp: datetime) -> list[GlobalExposureRead]`

Live exposure endpoints should keep SQL-side lifecycle filtering and delegate the aggregation rules to the pure primitive. Scenario should filter to the same live baseline, apply explicit virtual deltas, and delegate to the same primitive.

## Accepted Findings

### J-CL1-01 — DealEngine consumes archived linked entities as live economics

**Source:** Opus J-CL1-OPUS-04 + Opus J-CL1-OPUS-11; subsumes the reachable part of Opus J-CL1-OPUS-01
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted with severity change
**Deferral source:** D-1.1 + D-1.2 interaction

**Evidence:**
- `backend/app/services/deal_engine.py:559-611` — `compute_deal_pnl` loads linked Orders / HedgeContracts with `session.get(...)` and no `deleted_at` filter.
- `backend/app/services/deal_engine.py:918-957` and `backend/app/services/deal_engine.py:1036` — `compute_pnl_breakdown` repeats the unfiltered traversal.
- `backend/app/services/deal_engine.py:1245-1269` — `_recompute_tons` counts linked Orders / HedgeContracts with no lifecycle filter.
- `backend/app/services/exposure_engine.py:122` and `backend/app/services/exposure_engine.py:218-235` — exposure reconcile reads only live Orders and retires Exposure rows whose source Order is archived.
- `backend/app/api/routes/orders.py:129-144` and `backend/app/api/routes/contracts.py:89-104` — Order and HedgeContract archive routes are live and audited.

**Failure mode:**
Archive an Order linked to a Deal. Exposure retires the Order and net exposure drops it, but Deal P&L, P&L breakdown, and tonnage still value and count the archived Order. A variable-price archived Order can also require a market quote even though it no longer has live exposure. The same shape applies to archived HedgeContracts.

**Governance impact:**
§2.1 is breached because exposure and deal P&L disagree on which primitives are live. §2.7 is breached because an operator cannot reconstruct a single canonical economic state across dashboards.

**Remediation boundary:**
In `DealEngineService.compute_deal_pnl`, `compute_pnl_breakdown`, and `_recompute_tons`, skip Orders with `deleted_at is not None` and HedgeContracts with `deleted_at is not None`. Add a focused test that archives a linked Order and proves Deal tons, P&L, and breakdown exclude it.

### J-CL1-02 — Deal soft-delete contract is half-wired

**Source:** Opus J-CL1-OPUS-02 + Opus J-CL1-OPUS-03 + Gemini J-CL1-GEMINI-01
**Severity:** Tier 3 / Medium
**Status:** Open
**Disposition:** Accepted with severity downgrade
**Deferral source:** D-1.1

**Evidence:**
- `backend/app/models/deal.py:160-163` — `Deal` has `is_deleted` and `deleted_at`.
- `backend/app/models/deal.py:171-194` — `DealLink` has no lifecycle column and has hard uniqueness over `(linked_type, linked_id)`.
- `backend/app/services/deal_engine.py:886`, `backend/app/services/deal_engine.py:893`, `backend/app/services/deal_engine.py:1183`, `backend/app/services/deal_engine.py:1194` — normal Deal readers filter `Deal.is_deleted == False`.
- `backend/app/api/routes/deals.py:71-87` — `find_deal_by_linked_entity` resolves the Deal with `session.get(Deal, link.deal_id)` and does not apply the normal deleted-deal filter.
- `rg ".is_deleted\s*=\s*True" backend/app` found no Deal writer; only Counterparty and Exposure are written.

**Failure mode:**
The exact original "soft-deleted Deal still owns invisible links" path is not reachable through a current route, because no Deal archive writer exists. The current backend is still internally inconsistent: lifecycle fields and read filters exist, one linked-entity resolver bypasses the filter, and no contract states whether links cascade, block archive, or survive. A future archive endpoint would immediately activate the original hazard.

**Governance impact:**
§2.7 requires explicit lifecycle semantics. A half-wired lifecycle state is not a blocking production bug today, but it is an institutional maintenance hazard.

**Remediation boundary:**
Choose one small contract: either remove `Deal.is_deleted` / `Deal.deleted_at` until Deal archive is actually supported, or add a proper `/deals/{id}/archive` contract with signed audit event, RBAC, DealLink cascade/block semantics, and reader filters including `find_deal_by_linked_entity`. Do not add a Deal archive route without resolving DealLink semantics.

### J-CL1-03 — Total-unavailability snapshot reuse silently substitutes stale valuation

**Source:** Opus J-CL1-OPUS-05 + Gemini J-CL1-GEMINI-03; subsumes Opus J-CL1-OPUS-06 and Opus J-CL1-OPUS-12
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted with severity change
**Deferral source:** D-1.3

**Evidence:**
- `backend/app/services/deal_engine.py:51-79` — `_compute_inputs_hash` includes deal id, snapshot date, link ids, and `price_references`; it does not include linked Order price type, quantity, average price, or linked HedgeContract status, quantity, fixed price.
- `backend/app/services/deal_engine.py:657-703` — total quote unavailability probes prior snapshots and returns a matching candidate instead of raising.
- `backend/app/api/routes/deals.py:216-239` — the route records `event_type="created"` whether the returned snapshot is fresh or reused.
- `backend/tests/test_pnl_provenance.py:2202-2245` — existing test pins reuse as successful; no mutation-between-snapshots test protects the stale-content case.

**Failure mode:**
Create a fixed-price Order snapshot, then mutate the Order into variable-price with the same DealLink. During a market-data outage, the candidate hash still matches because the link id and stored `price_references` are unchanged. The compute endpoint returns the old fixed-price snapshot as if it were current variable-price P&L. The same class of bug applies to quantity, average price, and hedge status changes.

**Governance impact:**
§2.6 and the governance hard-fail list forbid silent fallback when price evidence is unprovable. §2.7 is also breached because the audit trail cannot distinguish fresh computation from outage reuse.

**Remediation boundary:**
Remove the total-unavailability reuse branch and update tests to assert `PriceReferenceUnprovable`. This also closes the separate audit-event and mutation-test gaps. If the branch is preserved, the fix must include explicit caller opt-in, distinct signed audit event, and content hashing for linked entities; partial mitigation is not enough.

### J-CL1-04 — Scenario exposure baseline ignores live lifecycle filters

**Source:** Opus J-CL1-OPUS-07 + Opus J-CL1-OPUS-08 + Opus J-CL1-OPUS-09 + Gemini J-CL1-GEMINI-04
**Severity:** Tier 1 / Blocking
**Status:** Open
**Disposition:** Accepted
**Deferral source:** D-1.4

**Evidence:**
- `backend/app/services/scenario_whatif_service.py:213-229` — scenario loads all Orders, all HedgeContracts, and all HedgeOrderLinkage rows.
- `backend/app/services/scenario_whatif_service.py:232-302` and `backend/app/services/scenario_whatif_service.py:305-443` — commercial/global scenario exposure consumes those raw lists.
- `backend/app/services/exposure_service.py:108-194` — live commercial exposure filters `Order.deleted_at IS NULL`.
- `backend/app/services/exposure_service.py:295-313` and `backend/app/services/exposure_service.py:351-378` — live global exposure filters archived Orders, archived HedgeContracts, and only active / partially-settled hedges.
- `backend/app/services/scenario_whatif_service.py:466-467` — only scenario MTM skips non-active contracts; exposure aggregation does not.

**Failure mode:**
Run scenario with an empty delta list after an Order or HedgeContract has been archived. Live exposure excludes the entity; scenario exposure still includes it. For a settled hedge, live global exposure excludes it but scenario global exposure can still include the full hedge quantity. The what-if projection is therefore not a projection over current live state.

**Governance impact:**
§2.1 is breached because scenario produces a wrong exposure projection from non-canonical primitives. The scenario rule "Explicit deltas only" is also breached: archived entities become an implicit delta from live baseline.

**Remediation boundary:**
Filter scenario baseline inputs with the same lifecycle/status rules as live A1 exposure, then route scenario and live calculations through the shared pure primitive required by the D-1.4 decision.

### J-CL1-05 — Scenario/live aggregation parity is not structurally protected

**Source:** Opus J-CL1-OPUS-10 + Gemini J-CL1-GEMINI-04
**Severity:** Tier 2 / High
**Status:** Open
**Disposition:** Accepted with severity downgrade
**Deferral source:** D-1.4

**Evidence:**
- `backend/app/services/scenario_whatif_service.py:291-300` and `backend/app/services/scenario_whatif_service.py:422-441` — scenario constructs exposure DTOs through `float(...)` casts.
- `backend/app/schemas/exposure.py:28-95` and `backend/app/schemas/_types.py:7-19` — exposure schemas are Decimal-constrained `MTQuantity` fields.
- `backend/app/services/exposure_service.py:108-194` and `backend/app/services/exposure_service.py:295-405` — live exposure has separate SQL aggregation and quantization rules.
- `backend/tests/test_scenario_whatif_run.py` has scenario behavior tests, but no parity test against live `ExposureService` on a shared fixture.

**Failure mode:**
Even after lifecycle filtering is fixed, scenario and live exposure can drift because they are separate implementations of the same primitive. The current float boundary also makes exact parity tests harder and can surface representation drift in Decimal-constrained DTOs.

**Governance impact:**
§2.1 requires a canonical economic primitive, not two implementations that must stay aligned by convention. This is Tier 2 because the current Tier 1 wrong-projection cases are captured in J-CL1-04; this finding is the structural drift control.

**Remediation boundary:**
Extract the shared pure primitive, keep Decimal/`quantize_mt` at the boundary, and add parity tests proving empty-delta scenario exposure equals live exposure on a fixed fixture.

## Rejected Findings

### J-CL1-GEMINI-02 — Reconcile creates duplicate Exposure rows on Order un-delete

**Disposition:** Rejected
**Reason:** The current implementation explicitly chooses retired-row history plus fresh live row on un-delete. `reconcile_from_orders` filters active lookup by `Exposure.is_deleted == False` (`backend/app/services/exposure_engine.py:167-174`) and documents the reversibility choice (`backend/app/services/exposure_engine.py:206-215`). Readers filter retired rows, including net exposure (`backend/app/services/exposure_engine.py:303-325`), task listing (`backend/app/services/exposure_engine.py:541-550`), and execute-side stale URL defense (`backend/app/services/exposure_engine.py:577-586`). Tests pin retirement, idempotency, fresh-row-on-revival, task cancellation, task listing, and execution rejection (`backend/tests/test_pr5_lifecycle_acceptance.py:356-370`, `:489-540`, `:713-775`). No live double-counting or reconstructability failure remains on D-1.2 itself.

## Subsumed Findings

- Opus J-CL1-OPUS-01 is accepted only to the extent it describes stale DealLink ownership over archived linked entities; the impossible "different Order with same identifier" framing is not carried. The concrete fix is J-CL1-01.
- Opus J-CL1-OPUS-03 is subsumed by J-CL1-02; it activates only if a Deal archive writer is introduced.
- Opus J-CL1-OPUS-06 is subsumed by J-CL1-03; removing reuse closes the audit ambiguity.
- Opus J-CL1-OPUS-08 and J-CL1-OPUS-09 are subsumed by J-CL1-04; they are the hedge-status and linkage forms of the same scenario baseline drift.
- Opus J-CL1-OPUS-11 is subsumed by J-CL1-01; it correctly raises severity to Tier 1.
- Opus J-CL1-OPUS-12 is subsumed by J-CL1-03 as required verification for the reuse removal.
- Gemini J-CL1-GEMINI-01 is subsumed by J-CL1-02 and downgraded because no Deal archive writer is reachable today.
- Gemini J-CL1-GEMINI-04 is split: current wrong projection goes to J-CL1-04; structural parity drift goes to J-CL1-05.

## Cross-Cluster Deferrals

- Cluster 3 / RBAC: if a future Deal archive route is added, the role policy for archiving deals belongs with the RBAC matrix. The current verdict does not authorize a new route.
- Cluster 4 / market-data governance: a future explicit stale-feed policy may define an operator-approved repair workflow. Until then, D-1.3 must hard-fail on total unavailability.
- No Cluster 2 carryover: RFQ actor/status work is not implicated by these findings.

## Recommended Remediation Waves

### PR-CL1-1 — DealEngine live-linked traversal
- Findings: J-CL1-01
- Scope boundary: `backend/app/services/deal_engine.py` and focused tests only.
- Required verification: archive linked Order/HedgeContract and assert tons, P&L snapshot, and P&L breakdown exclude archived entities; run `pytest -q backend/tests/test_deal_engine.py` plus the new focused test.

### PR-CL1-2 — Deal P&L hard-fails on total price unavailability
- Findings: J-CL1-03
- Scope boundary: remove candidate-probe reuse from `compute_deal_pnl`, update snapshot-reuse tests, add mutation/outage regression.
- **HTTP contract (binding per `docs/governance.md:152`):** the propagated `PriceReferenceUnprovable` must reach the caller as HTTP `424 Failed Dependency`. Wave dispatch and implementing PR must assert this code in route-level tests. **Do not** use HTTP 422 — governance reserves 422 for the distinct "missing zero-default economics" / "missing settlement_date" cases (governance lines 155-157), not for unprovable live prices. The Stage 1 Opus findings doc contains a 422 reference for this case that is overridden by this verdict and by governance §152.
- Required verification: `pytest -q backend/tests/test_pnl_provenance.py backend/tests/test_pnl_price_evidence.py`; new route-level test asserting `424 Failed Dependency` on the total-unavailability path.

### PR-CL1-3 — Shared exposure primitive for scenario and live A1
- Findings: J-CL1-04, J-CL1-05
- Scope boundary: `ExposureService` shared pure primitive, scenario input lifecycle filters, scenario/live parity tests. No schema migration.
- Required verification: `pytest -q backend/tests/test_scenario_whatif_run.py backend/tests/test_exposure*.py` and a new empty-delta parity fixture.

### PR-CL1-4 — Deal soft-delete contract cleanup
- Findings: J-CL1-02
- Scope boundary: choose exactly one path: remove dead Deal lifecycle fields, or implement Deal archive with DealLink semantics and audit. Do not combine with PR-CL1-1 through PR-CL1-3.
- Required verification: if removal, migration single-head check and reader tests; if implementation, archive/relink/find-by-linked-entity tests plus audit-event assertion.

## Anti-Findings Confirmed

- D-1.2 exposure retirement is closed as a live aggregation concern. Retired rows are preserved as history; active readers filter them; HedgeTasks are cancelled or filtered defensively.
- Scenario route does not need mutation audit events. `backend/app/api/routes/scenario.py:17-34` delegates in-memory what-if execution and governance explicitly says scenario is in-memory only, no persistence, no timeline, no cache reuse.
- `cancel_stale_tasks` lacking an explicit `Exposure.is_deleted` predicate is not a standalone bug after the retirement sweep, because pending tasks on retired exposures are proactively cancelled and both listing/execution have explicit retired-exposure guards.
- The absence of `DealLink.is_deleted` is not itself a finding. It becomes required only if the chosen Deal archive contract is soft-delete-symmetric; hard-delete cascade or removal of Deal lifecycle fields would not need it.

## Self-Bias Confession

I gave Opus more weight on lifecycle interactions because its report was broader and its Deal-vs-Exposure divergence was directly supported by code. I still rejected or narrowed Opus where it overreached: D-1.2 is closed, and the "different Order with same identifier" uniqueness framing is not a real UUID failure mode. I downgraded Gemini's Deal soft-delete finding because no current route writes `Deal.is_deleted`, and I rejected Gemini's D-1.2 finding because the code and tests document fresh-row-on-revival as deliberate audit history rather than live double-counting.

The thinnest evidence is around whether product wants Deal archive at all. Current code says "not yet"; if production data already contains `deals.is_deleted = true` rows created outside the app, J-CL1-02 should be promoted from Tier 3 to Tier 2 and handled before new lifecycle work. The additional verification that would change this verdict is a live DB sample showing deleted Deal rows or an existing external writer for Deal lifecycle.
