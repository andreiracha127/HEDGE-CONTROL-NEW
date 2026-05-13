# Cluster 1 Follow-Up Audit — Stage 2 Findings — Auditor B (Gemini)

## Finding J-CL1-GEMINI-01 - DealLink survives Deal soft-delete, breaking cross-deal uniqueness

**Severity:** Tier 2 / High
**Status:** Open
**Deferral source:** D-1.1
**Evidence:**
- `backend/app/models/deal.py:160` - `Deal` has `is_deleted`, but `DealLink` lacks lifecycle columns.
- `backend/app/services/deal_engine.py:312-316` - `add_link` cross-deal uniqueness check queries `DealLink` directly without joining the parent `Deal` to filter `is_deleted == False`.

**Failure mode:**
If a deal is soft-deleted, its links survive. A new deal attempting to link the same entity fails with "already linked to deal", but the operator cannot see the soft-deleted deal in normal views to unlink it. This creates an unresolvable state lock.

**Governance impact:**
§2.7 Audit reconstructability — lifecycle states are explicit; soft-delete must not orphan referential evidence in a blocking state.

**Recommended remediation boundary:**
Add `is_deleted` to `DealLink`. When a deal is soft-deleted, cascade the soft-delete to its links. Update the `uq_deal_link_entity` unique constraint to a partial index `WHERE is_deleted = false`.

---

## Finding J-CL1-GEMINI-02 - Reconcile creates duplicate Exposure rows on Order un-delete

**Severity:** Tier 2 / High
**Status:** Open
**Deferral source:** D-1.2
**Evidence:**
- `backend/app/services/exposure_engine.py:234` - §3.8 sweep sets `exposure.is_deleted = True` when its source `Order` is deleted.
- `backend/app/services/exposure_engine.py:171` - Reconcile's existing-row lookup strictly filters `Exposure.is_deleted == False`.

**Failure mode:**
If an Order is soft-deleted, its Exposure is retired. If the Order is later un-deleted (a valid lifecycle event), Reconcile does not find the active Exposure, so it creates a completely new row. The `source_id` now owns multiple rows (one deleted, one active), breaking the 1:1 exposure-to-order mapping.

**Governance impact:**
§2.1 Economic primitives integrity — exposure aggregation is canonical and must not be duplicated with drift potential.

**Recommended remediation boundary:**
In `reconcile_from_orders`, remove the `is_deleted == False` filter when searching for existing rows. If an existing row is found and `is_deleted` is True, un-delete it and update its values, rather than appending a duplicate row.

---

## Finding J-CL1-GEMINI-03 - Snapshot reuse on total price unavailability violates hard-fail

**Severity:** Tier 1 / Blocking
**Status:** Open
**Deferral source:** D-1.3
**Evidence:**
- `backend/app/services/deal_engine.py:686-703` - Recomputes hash using the candidate snapshot's own persisted `price_references` rather than fresh inputs.

**Failure mode:**
When all price quotes fail, the deal engine silently reuses a prior snapshot by validating the hash against the snapshot's own price history. This masks price service outages, allowing stale D-1 prices to seamlessly masquerade as current state.

**Governance impact:**
§2.6 No silent fallback — economic state must not be silently repaired or extrapolated. Missing market price is unprovable and must hard-fail.

**Recommended remediation boundary:**
Remove the `unprovable_errors` repair branch. Always propagate `PriceReferenceUnprovable` to trigger a 424 Failed Dependency, forcing the operator to resolve the pricing failure.

**Decision:**
(b) Always propagate `PriceReferenceUnprovable`.
§"no silent fallback" is absolute. Reusing a snapshot based on a hash of its own stored references creates a self-fulfilling loop where a stale snapshot justifies its own reuse. This hides the outage and prevents the system from failing closed, violating the strict hard-fail requirement for unprovable prices. The route must return 424 Failed Dependency, alerting the operator, rather than silently succeeding.

---

## Finding J-CL1-GEMINI-04 - Scenario aggregation drifts from canonical ExposureService quantization

**Severity:** Tier 1 / Blocking
**Status:** Open
**Deferral source:** D-1.4
**Evidence:**
- `backend/app/services/scenario_whatif_service.py:270-300` - Scenario applies basic math and returns unquantized `CommercialExposureRead` using float casts.
- `backend/app/services/exposure_service.py:145` - Live exposure uses `quantize_mt` and native `Decimal` inside SQL aggregates.

**Failure mode:**
Scenario what-if uses native Python math without explicit `quantize_mt` application during partial aggregations. `ExposureService` uses SQL aggregates with explicit quantization. This guarantees cross-phase drift for complex boundary thresholds (e.g. exactly fully-hedged boundaries).

**Governance impact:**
§2.1 Economic primitives integrity — exposure aggregation is canonical and must not be duplicated with drift potential.

**Recommended remediation boundary:**
Extract a shared pure Python primitive `compute_commercial_exposure_pure(orders, linkages)` that enforces `quantize_mt` rules. Both Scenario and `ExposureService` should call this primitive, replacing the SQL aggregation in `ExposureService` to guarantee perfect parity.

**Decision:**
Extract shared pure primitive.
Scenario must have exact parity with live exposure. Since Scenario cannot use SQL `GROUP BY` (because it applies virtual deltas in memory), the only way to guarantee parity is for both services to run the same pure-Python aggregation logic. `ExposureService` should load the primitive rows and pass them to the shared function, prioritizing determinism over SQL performance as demanded by the Constitution.

---

## Anti-findings considered

- **Duplicate Exposure rows causing active double counting:** Rejected. While D-1.2 produces multiple rows for the same `source_id`, consumers like `compute_net_exposure` explicitly filter `is_deleted == False`. The bug is a structural duplication and 1:1 invariant breach, not an immediate live-calculation error.
- **Scenario double counting due to duplicate exposures:** Rejected. Scenario aggregation reads directly from primitive `Order` and `HedgeContract` arrays, bypassing the `Exposure` table entirely. Scenario is immune to the D-1.2 duplicate row bug.

## Cross-deferral interactions

- **D-1.1 + D-1.3 (Phantom P&L for deleted deals):** If a deal is soft-deleted, its `DealPNLSnapshot` and `DealLink` rows remain untouched. If a stray `compute_deal_pnl` call occurs, it will see unprovable prices and successfully reuse a snapshot (because `inputs_hash` matches the intact links), generating valid phantom P&L for a deleted deal.

## Cross-cluster deferrals

- None identified. All findings remain strictly within the Cluster 1 Deal/Exposure/Scenario domain.

## Recommended remediation waves

- **Wave 1 (Correctness & Hard Fails):** Fix J-CL1-GEMINI-03 (remove snapshot repair branch) and J-CL1-GEMINI-04 (extract pure exposure aggregation). These block silent fallbacks and deterministic drift.
- **Wave 2 (Lifecycle & Referential Integrity):** Fix J-CL1-GEMINI-01 (DealLink soft-delete cascade) and J-CL1-GEMINI-02 (un-delete reuse in Reconcile). These fix the soft-delete edge cases.