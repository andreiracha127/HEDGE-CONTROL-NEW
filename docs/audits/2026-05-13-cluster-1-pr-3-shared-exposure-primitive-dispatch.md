# Cluster 1 Remediation Dispatch — PR-CL1-3 — Shared Exposure Primitive for Scenario and Live A1

**Cluster:** 1 — A1 follow-up (deal-engine + exposure + scenario boundaries)
**Wave:** PR-CL1-3 (3 of 4)
**Authoring date:** 2026-05-13
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `ea08d9868` post-PR-#73)
**Required branch:** `audit-followup/cluster-1-shared-exposure-primitive`
**Source verdict:** `docs/audits/2026-05-13-cluster-1-jury-verdict.md` §J-CL1-04, §J-CL1-05, §D-1.4 Institutional Decision, §PR-CL1-3 wave entry

## 1. Objective

Close **J-CL1-04** (Tier 1 / Blocking) and **J-CL1-05** (Tier 2 / High) by implementing the verdict's binding **D-1.4** institutional decision: **extract shared exposure primitives**.

Two coupled gaps to close:

1. **J-CL1-04 — wrong projection today**: `scenario_whatif_service` loads all Orders, all HedgeContracts, and all HedgeOrderLinkage rows without applying live A1 lifecycle filters. Live `ExposureService` filters `Order.deleted_at IS NULL`, archived HedgeContracts, and inactive hedge statuses. Running scenario with an empty delta list against the same database produces a different exposure projection than the live exposure endpoints — not future drift, a current correctness gap.

2. **J-CL1-05 — structural drift control**: scenario and `ExposureService` each implement the same aggregation rules independently. Even after the lifecycle filters are aligned, a future evolution to one will silently diverge from the other unless they share a single primitive.

**D-1.4 decision (binding):** Extract pure aggregation functions under `ExposureService`. Both scenario and live exposure call the same primitives. Scenario applies its lifecycle filters and explicit virtual deltas at the input boundary, then delegates aggregation. Live exposure keeps SQL-side lifecycle filtering and delegates aggregation. Empty-delta scenario exposure must equal live exposure on a fixed fixture (parity assertion).

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`.
- Do **not** add a migration. Single alembic head must remain `043_a5_audit_payload_input`. The shared primitive lives in code only; no schema change is required.
- Do **not** change the public response shapes of `/exposures/commercial`, `/exposures/global`, or `/scenarios/what-if`. The primitives produce the same DTOs that already exist (`CommercialExposureRead`, `GlobalExposureRead`).
- Do **not** widen scope into wave PR-CL1-1 (archived-link traversal in `deal_engine.py`) or PR-CL1-2 (snapshot reuse / 424 mapping). Even though "archived order" is a recurring concept, those waves stay in their own files.
- Do **not** widen scope into wave PR-CL1-4 (Deal soft-delete contract). The `Deal` model and `DealLink` are not touched here.
- Do **not** add a virtual-delta abstraction layer to the primitives themselves. The primitives are pure aggregators over (orders, linkages, contracts). Scenario applies its deltas at the input-construction step **before** calling the primitive, not via primitive callbacks.
- Do **not** introduce Decimal-to-float coercion inside the primitive. The primitive operates on Decimals end-to-end; the float coercion in the current scenario DTO construction is a known structural-drift gap (J-CL1-05). The primitive must use `quantize_mt` / `quantize_price` and return Decimal-typed values that the DTOs accept directly.
- Do **not** change scenario's MTM aggregation rules in this wave. The MTM block at `scenario_whatif_service.py:466-467` already filters non-active contracts; that path is unchanged here.

The institutional rule is canonical-primitive integrity: one aggregation implementation, two callers (live + scenario), with explicit input shaping at each call site.

## 3. Findings and Evidence

Verified at HEAD `ea08d9868`.

### J-CL1-04 — scenario reads non-canonical inputs

- `backend/app/services/scenario_whatif_service.py:213-229` — `_load_orders`, `_load_contracts`, `_load_linkages` issue `session.query(Order).all()`, `session.query(HedgeContract).all()`, `session.query(HedgeOrderLinkage).all()`. No `deleted_at` filter on Orders, no `deleted_at` filter on HedgeContracts, no status filter on hedges, no orphan-linkage filter.
- `backend/app/services/scenario_whatif_service.py:232-302` — `_compute_commercial_exposure` consumes the raw `(order, quantity)` list directly.
- `backend/app/services/scenario_whatif_service.py:305-443` — `_compute_global_exposure` consumes raw lists for orders, contracts, virtual contracts, linkages.
- `backend/app/services/scenario_whatif_service.py:466-467` — scenario MTM filters non-active contracts: this is the precedent that exposure aggregation does **not** follow today.
- `backend/app/services/exposure_service.py:85-193` — `compute_commercial_snapshot` filters `Order.deleted_at IS NULL` and uses `_linked_by_order_subquery` (which itself filters live entities).
- `backend/app/services/exposure_service.py:199-408` — `compute_global_snapshot` filters archived Orders, archived HedgeContracts, and inactive/cancelled hedge statuses; only `active` and `partially_settled` hedges contribute.

Failure mode: archive an Order, run scenario with `deltas=[]`, scenario reports the archived Order in commercial exposure. Same for an archived HedgeContract. Same for a settled hedge in global exposure.

### J-CL1-05 — duplicated aggregation primitives

- `backend/app/services/scenario_whatif_service.py:232-443` — scenario implements its own aggregation rules: per-commodity rollup with `pre_active`/`pre_passive`/`residual_active`/`residual_passive`/`reduction_active`/`reduction_passive`; sign convention (sales→active, purchase→passive); residual non-negative check raising 409.
- `backend/app/services/exposure_service.py:85-408` — live exposure implements the same rules in SQL (commercial) and in Python over SQL-filtered query results (global).
- `backend/app/services/scenario_whatif_service.py:291-300` and `:422-441` — scenario builds DTOs via `float(item["..."])` casts.
- `backend/app/schemas/exposure.py:28-95` + `backend/app/schemas/_types.py:7-19` — `CommercialExposureRead` and `GlobalExposureRead` use Decimal-constrained `MTQuantity` fields; the float cast is a representation-drift hazard.
- `backend/tests/test_scenario_whatif_run.py` — has scenario behavior tests, but no parity assertion against `ExposureService` on a shared fixture.

### Cross-deferral interaction (J-CL1-04 subsumes Opus J-CL1-OPUS-08 + J-CL1-OPUS-09)

The wave consolidates three Opus findings: scenario reads archived Orders (J-CL1-OPUS-07), archived HedgeContracts (J-CL1-OPUS-08), and orphan / inactive-hedge linkages (J-CL1-OPUS-09). All collapse to the same fix shape: align scenario's input boundary to live A1's filters, then delegate to the shared primitive.

## 4. Required Implementation Boundary

### 4.1 New shared primitives in `backend/app/services/exposure_service.py`

Add two pure module-level or staticmethod functions. They take pre-filtered, pre-shaped inputs and return canonical DTOs. They do **not** query the session.

```python
def compute_commercial_exposure_pure(
    *,
    orders: list[tuple[Order, Decimal]],
    linkages: list[HedgeOrderLinkage],
    calculation_timestamp: datetime,
) -> list[CommercialExposureRead]:
    """Pure aggregation of commercial exposure rows.

    Inputs are caller-shaped:
    - `orders`: list of (Order, quantity_mt_after_deltas) tuples. Caller
      is responsible for filtering archived orders, applying virtual
      quantity deltas, and quantizing.
    - `linkages`: hedge-order linkages to consider for residual
      reduction. Caller filters orphan or stale linkages.
    - `calculation_timestamp`: stamp threaded onto every returned row.

    Rules (canonical A1; do not diverge):
    - sales orders → pre_active, purchase orders → pre_passive
    - residual = max(quantity - linked_qty, 0); raises if negative
    - per-commodity rollup; sorted output by commodity
    - skip fixed-price orders (variable-only)
    """
    # implementation mirrors current scenario shape, but Decimal-typed
    ...


def compute_global_exposure_pure(
    *,
    orders: list[tuple[Order, Decimal]],
    contracts: list[HedgeContract],
    virtual_contracts: list[VirtualHedgeContract],
    linkages: list[HedgeOrderLinkage],
    calculation_timestamp: datetime,
) -> list[GlobalExposureRead]:
    """Pure aggregation of global exposure rows."""
    ...
```

Constraints on the primitives:

- Decimal-typed throughout. No `float(...)` casts inside the function body. DTO fields are `MTQuantity` (Decimal-constrained).
- `quantize_mt` at the aggregation boundary, not on every intermediate sum.
- Sign convention matches live A1: sales → active, purchase → passive.
- Negative residual raises `HTTPException(status_code=409, ...)` exactly as scenario does today. Live `ExposureService.compute_*_snapshot` raises the same shape (via `_validate_residuals_non_negative`); the message text should match.
- The functions are module-level (or `@staticmethod` on `ExposureService`) — your choice, but they must be importable from `backend/app/services/scenario_whatif_service.py` without circular imports.

### 4.2 Refactor `ExposureService.compute_commercial_snapshot` and `compute_global_snapshot`

Both methods continue to do their SQL-side lifecycle filtering (this is correct — live exposure benefits from query-level filters for performance and atomicity). After the SQL query produces filtered `(Order, Decimal)` tuples / `HedgeContract` rows, **delegate aggregation to the new primitive** rather than doing it inline.

Behavior must be byte-equivalent to today on every existing fixture. The existing tests in `backend/tests/test_exposures_commercial.py` (covers `compute_commercial_snapshot`) and `backend/tests/test_exposures_global.py` (covers `compute_global_snapshot`) should not need changes; if they do, the refactor introduced a regression. `backend/tests/test_exposure_engine.py` and `backend/tests/test_compute_net_exposure.py` cover the engine and net-exposure paths respectively and are not directly exercised by this refactor, but must continue to pass.

### 4.3 Refactor scenario input boundary in `backend/app/services/scenario_whatif_service.py`

#### 4.3.1 Lifecycle filters at `_load_*`

- **`_load_orders`** at `:213-217` (approx; verify line range): change `session.query(Order).all()` to `session.query(Order).filter(Order.deleted_at.is_(None)).all()`. The archived-orders block becomes invisible to scenario.
- **`_load_contracts`** at `:219-223` (approx): **DO NOT** unconditionally filter the existing `_load_contracts` to `{active, partially_settled}` — verified at HEAD `ea08d9868` that the same `contracts` list returned by `_load_contracts` is consumed by the scenario P&L loop at `scenario_whatif_service.py:541-592`, where settled / cancelled / partially_settled contracts contribute **zero unrealized MTM** (line 542-543) but **still emit realized P&L** from `CashFlowLedgerEntry` rows (lines 561-581). Filtering the contracts list to only `{active, partially_settled}` would silently drop settled hedges from `pl_snapshots`, which is **outside this wave's stated "exposure aggregation only" scope** (Codex P2 catch on PR #74 v3 — see §12 calibration).

  Instead, **split into two loaders**:

  - Keep the existing `_load_contracts` unchanged: `session.query(HedgeContract).all()`. The MTM/P&L loop at `:541-592` and any delta-validation path continue to consume this unfiltered list.
  - Add a new helper `_load_exposure_contracts(db: Session) -> list[HedgeContract]` that applies the full exposure-aggregation filter: `session.query(HedgeContract).filter(HedgeContract.deleted_at.is_(None), HedgeContract.status.in_([HedgeContractStatus.active, HedgeContractStatus.partially_settled])).all()`. The status filter mirrors `exposure_service.py:351-378`. The exposure aggregation path (call to `compute_global_exposure_pure`) consumes this filtered helper instead of `_load_contracts`.

  This preserves J-CL1-04's "scenario exposure baseline matches live A1" guarantee for the exposure surface while leaving scenario P&L semantics untouched (settled hedges keep emitting their realized cashflow-ledger contributions through the unchanged P&L loop). The two loaders are independent — both queries run; the runtime cost is one extra `SELECT` per scenario request, which is acceptable given the institutional invariant the split protects.
- **`_load_linkages`** at `:225-229` (approx): the linkage filter must mirror `ExposureService._linked_by_order_subquery` in `backend/app/services/exposure_service.py:31-57` exactly. That subquery joins **both the order side AND the hedge side** and applies the hedge-side lifecycle filter (`HedgeContract.deleted_at IS NULL` plus status in `{active, partially_settled}`). Without the hedge-side filter, scenario will continue to subtract quantities from settled / cancelled / archived hedges' linkages from order residuals, while live exposure (which uses the subquery) will not — empty-delta parity will silently drift on any fixture with a linkage to an inactive or archived hedge. Replace with:

  ```python
  session.query(HedgeOrderLinkage)
      .join(Order, Order.id == HedgeOrderLinkage.order_id)
      .join(HedgeContract, HedgeContract.id == HedgeOrderLinkage.contract_id)
      .filter(
          Order.deleted_at.is_(None),
          HedgeContract.deleted_at.is_(None),
          HedgeContract.status.in_(
              [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
          ),
      )
      .all()
  ```

  If `HedgeOrderLinkage` itself gains a lifecycle column at HEAD verification time, AND it on as well; today the joins-against-live-parents are sufficient because `_linked_by_order_subquery` defines the canonical shape and operates without a linkage-side column.

#### 4.3.2 Apply deltas at input shaping, not inside the primitive

After `_load_orders` returns live Orders, scenario constructs the `(Order, quantity_mt_after_deltas)` tuple list by applying `_apply_deltas`. This is unchanged in shape but now happens **before** the call to `compute_commercial_exposure_pure`. Same for `compute_global_exposure_pure` with virtual contracts.

#### 4.3.3 Delete `_compute_commercial_exposure` and `_compute_global_exposure`

Replace `_compute_commercial_exposure` and `_compute_global_exposure` (`scenario_whatif_service.py:232-302` and `:305-443`) with thin call-sites that delegate to the new primitives. The `float(...)` casts at `:291-300` and `:422-441` are removed; the primitives return Decimal-typed DTOs directly.

`run_what_if` is unchanged in interface; it just calls the new thin helpers.

### 4.4 Parity test (the J-CL1-05 closure)

Add `backend/tests/test_scenario_live_exposure_parity.py`:

1. **`test_empty_delta_commercial_parity`**: fixture with 3 Orders (1 sales variable-price, 1 purchase variable-price, 1 fixed-price), 1 HedgeContract linked to one Order. Call live `ExposureService.compute_commercial_snapshot(session)` and scenario's `run_what_if(deltas=[])`. Assert the returned `CommercialExposureRead` rows are **deeply equal** (commodity-sorted, all Decimal fields exact-equal).
2. **`test_empty_delta_global_parity`**: same fixture; assert `GlobalExposureRead` rows are deeply equal.
3. **`test_archived_order_excluded_from_scenario`**: archive one of the variable-price Orders, call scenario with empty deltas, assert the archived Order does not appear in either commercial or global exposure.
4. **`test_settled_hedge_excluded_from_scenario_exposure`**: mark one HedgeContract as `settled`, call scenario with empty deltas, assert the settled hedge does not contribute to global **exposure** (mirrors live).
4a. **`test_settled_hedge_preserved_in_scenario_pl`**: same fixture as test 4 — a settled HedgeContract with realized P&L from `CashFlowLedgerEntry` rows over the scenario period. Call scenario, assert the settled hedge **DOES** appear in `pl_snapshots` with `unrealized_mtm == 0` and `realized_pl == sum(ledger_entries)`. This is the regression guard for the Codex P2 catch on PR #74 v3 — the dispatch must not let the exposure-side filter silently drop settled hedges from the P&L surface.
5. **`test_orphan_linkage_excluded_via_archived_order`**: archive the Order referenced by a HedgeOrderLinkage, call scenario, assert the orphan linkage is not consumed.
6. **`test_orphan_linkage_excluded_via_settled_hedge`**: leave the Order live, mark the linked HedgeContract `settled` (or `cancelled`, in a parametrized variant), call scenario with empty deltas, assert the linkage's quantity is **not** subtracted from the Order's residual exposure. This is the parity case Codex caught on the v1 dispatch — without the hedge-side filter on `_load_linkages`, scenario would still consume the inactive-hedge linkage while live exposure (via `_linked_by_order_subquery`) would not. Run as a parametrized test across `{settled, cancelled}` HedgeContractStatus values; the archived-hedge case is also a candidate fixture, exercised here or in test 4 above.

The parity tests are the structural protection J-CL1-05 demands. They must call the **public** scenario / live endpoints (not the new primitives directly) so that the primitive is exercised through both callers.

### 4.5 What stays unchanged

- Public response shapes of `/exposures/commercial`, `/exposures/global`, `/scenarios/what-if`.
- `_validate_residuals_non_negative` semantics (negative residual → 409).
- `_apply_deltas` shape — scenario continues to consume deltas the same way.
- Scenario MTM aggregation at `:466+` — this wave is exposure aggregation only.
- `HedgeContractStatus` enum and `Order.price_type` enum.

## 5. Constitutional Rules

- `docs/governance.md` §2.1 — canonical economic primitive. The verdict cites this exact clause as the binding rule for D-1.4.
- "Scenario explicit deltas only" — archived entities becoming an implicit delta from live baseline was the precise scenario-rule breach J-CL1-04 surfaced.

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes J-CL1-04 + J-CL1-05 iff every item below is true.

### 6.1 Shared primitives

- [ ] `backend/app/services/exposure_service.py` — `compute_commercial_exposure_pure` and `compute_global_exposure_pure` exist with the signatures and constraints in §4.1.
- [ ] Both primitives are Decimal-typed end-to-end; `rg -nP "float\\(" backend/app/services/exposure_service.py` shows no new matches inside the primitive bodies.
- [ ] Both primitives are importable from `backend/app/services/scenario_whatif_service.py` (no circular import).

### 6.2 Live exposure refactor

- [ ] `ExposureService.compute_commercial_snapshot` keeps its SQL-side lifecycle filter and delegates aggregation to `compute_commercial_exposure_pure`. Behavior unchanged on every existing test.
- [ ] `ExposureService.compute_global_snapshot` keeps its SQL-side filters and delegates aggregation to `compute_global_exposure_pure`. Behavior unchanged on every existing test.

### 6.3 Scenario input boundary

- [ ] `_load_orders` filters `Order.deleted_at.is_(None)`.
- [ ] **`_load_contracts` is UNCHANGED** — it continues to return all HedgeContract rows. A new helper `_load_exposure_contracts(db: Session) -> list[HedgeContract]` exists and applies the full exposure-aggregation filter (`HedgeContract.deleted_at.is_(None)` AND status in {`active`, `partially_settled`}). The exposure aggregation path consumes `_load_exposure_contracts`; the MTM/P&L loop at `:541-592` continues to consume `_load_contracts`. Settled hedges must still appear in `pl_snapshots` with `realized_pl` populated from `CashFlowLedgerEntry` rows.
- [ ] `_load_linkages` mirrors `ExposureService._linked_by_order_subquery`'s lifecycle filtering: excludes linkages whose parent Order is archived (`Order.deleted_at IS NULL`) **and** linkages whose linked HedgeContract is archived or not in `{active, partially_settled}` status. The query joins both `Order` and `HedgeContract`. Filter symmetry with the live subquery is the structural guarantee against scenario/live drift on the linked-quantity reduction.
- [ ] `_compute_commercial_exposure` and `_compute_global_exposure` no longer exist as separate aggregation implementations (or are reduced to thin delegations).
- [ ] No `float(...)` cast remains inside scenario aggregation paths.

### 6.4 Tests

- [ ] `backend/tests/test_scenario_live_exposure_parity.py` exists with the 6 tests in §4.4 (parametrized variants count as one test).
- [ ] All parity tests pass, including the inactive-hedge linkage variants (test 6) which exercise the hedge-side filter symmetry with `_linked_by_order_subquery`.
- [ ] `backend/tests/test_scenario_whatif_run.py` and `backend/tests/test_exposure*.py` continue to pass.

### 6.5 Sweeps

- [ ] `rg -nP "session\\.query\\(Order\\)\\.all\\(\\)" backend/app/services/scenario_whatif_service.py` returns zero matches.
- [ ] `rg -nP "session\\.query\\(HedgeContract\\)\\.all\\(\\)" backend/app/services/scenario_whatif_service.py` returns **exactly one** match — the unchanged `_load_contracts` body. The new `_load_exposure_contracts` helper has the filter chain (NOT bare `.all()`), and zero other call sites query HedgeContract.
- [ ] `rg -nP "session\\.query\\(HedgeOrderLinkage\\)\\.all\\(\\)" backend/app/services/scenario_whatif_service.py` returns zero matches.
- [ ] `rg -nP "HedgeOrderLinkage" backend/app/services/scenario_whatif_service.py` shows the new `_load_linkages` query joining BOTH `Order` AND `HedgeContract` with the hedge-side lifecycle filter (`HedgeContract.deleted_at` filter present, `HedgeContract.status.in_([...active..., ...partially_settled...])` present). A query that only joins `Order` is incomplete and will fail the parity tests in §4.4.
- [ ] `rg -nP "float\\(" backend/app/services/scenario_whatif_service.py` returns zero new matches in aggregation paths (matches in MTM or unchanged paths are allowed).
- [ ] `rg -nP "compute_commercial_exposure_pure|compute_global_exposure_pure" backend/app/services/` returns matches in both `exposure_service.py` (definition) and `scenario_whatif_service.py` (call site).
- [ ] `python -m alembic heads` prints `043_a5_audit_payload_input`.

### 6.6 Cross-cutting

- [ ] `docs/governance.md` diff is empty.
- [ ] No edit to `backend/app/services/deal_engine.py` (PR-CL1-1 / PR-CL1-2 territory).
- [ ] No edit to `backend/app/services/exposure_engine.py` (reconcile_from_orders is unchanged).
- [ ] No edit to `backend/app/models/`.
- [ ] No frontend file changed (scenario response shape unchanged).

## 7. Required Tests

§4.4 + §6.4 enumerate the tests. Restated as a checklist:

1. `backend/tests/test_scenario_live_exposure_parity.py` (new) — 6 tests, where test 6 (inactive-hedge linkage variants) is parametrized over `{settled, cancelled}` HedgeContractStatus values.
2. `backend/tests/test_scenario_whatif_run.py` (existing) — passes unchanged or with trivial fixture updates if a previous test asserted that scenario reads archived entities.
3. The four existing exposure test files — `backend/tests/test_exposures_commercial.py`, `backend/tests/test_exposures_global.py`, `backend/tests/test_exposure_engine.py`, `backend/tests/test_compute_net_exposure.py` — pass unchanged. Any test failure on `test_exposures_commercial.py` or `test_exposures_global.py` is a regression in the live-side refactor (§4.2) and must be fixed before opening the PR. The engine and net-exposure suites should pass unchanged because this wave does not touch them.

## 8. Required Verification

```powershell
# New primitive sweeps
rg -nP "def compute_commercial_exposure_pure|def compute_global_exposure_pure" backend/app/services/exposure_service.py
rg -nP "compute_commercial_exposure_pure|compute_global_exposure_pure" backend/app/services/scenario_whatif_service.py

# Scenario lifecycle filter sweeps
rg -nP "Order\\.deleted_at" backend/app/services/scenario_whatif_service.py
rg -nP "HedgeContract\\.deleted_at" backend/app/services/scenario_whatif_service.py
rg -nP "HedgeContractStatus\\.active|HedgeContractStatus\\.partially_settled" backend/app/services/scenario_whatif_service.py

# Removed duplication sweeps
rg -nP "session\\.query\\(Order\\)\\.all\\(\\)|session\\.query\\(HedgeContract\\)\\.all\\(\\)|session\\.query\\(HedgeOrderLinkage\\)\\.all\\(\\)" backend/app/services/scenario_whatif_service.py
rg -nP "float\\(" backend/app/services/scenario_whatif_service.py

# Alembic invariant
cd backend ; python -m alembic heads ; cd ..

# Test suite
pytest -q backend/tests/test_scenario_live_exposure_parity.py
pytest -q backend/tests/test_scenario_whatif_run.py
pytest -q backend/tests/test_exposures_commercial.py
pytest -q backend/tests/test_exposures_global.py
pytest -q backend/tests/test_exposure_engine.py
pytest -q backend/tests/test_compute_net_exposure.py
pytest -q backend/tests

# Cross-wave isolation
git diff main -- backend/app/services/deal_engine.py
git diff main -- backend/app/services/exposure_engine.py
git diff main -- backend/app/models/
git diff main -- backend/app/api/routes/
git diff main -- docs/governance.md

# Frontend isolation
git diff -- docs/api/openapi_v1.json frontend-svelte/src/lib/api/schema.d.ts
git diff --check
```

All cross-wave / cross-service diffs against main must be empty except the four files this wave is scoped to:

- `backend/app/services/exposure_service.py` (refactor + new primitives)
- `backend/app/services/scenario_whatif_service.py` (input boundary + delegation)
- `backend/tests/test_scenario_live_exposure_parity.py` (new)
- Possibly `backend/tests/test_scenario_whatif_run.py`, `backend/tests/test_exposures_commercial.py`, and `backend/tests/test_exposures_global.py` (trivial fixture updates only — any non-trivial change indicates a regression that must be reverted, not accommodated).

## 9. Out of Scope

- Wave PR-CL1-1, PR-CL1-2, PR-CL1-4 — none of those surfaces are touched.
- Scenario MTM aggregation logic (the `:466-467` block and below). MTM already filters non-active contracts; that path stays.
- Introducing a virtual-delta abstraction inside the primitives. The primitives are pure aggregators; scenario applies deltas at input shaping.
- Adding a Decimal-vs-float migration to existing `MTQuantity` fields. They are already Decimal in the schema; the wave only removes float coercion in the scenario aggregation path.
- Changing the negative-residual error from 409 to something else. Stays as today.
- Performance optimization of the live exposure SQL paths.
- New endpoint for "scenario diff vs live" or similar product surface.
- Frontend changes. Scenario and exposure response shapes are byte-equivalent for the live path; for the scenario path, only archived entities are excluded — that is a correctness fix and does not change the DTO shape.

## 10. PR Requirements

The implementing PR title must be:

```
fix(audit-followup): close Cluster 1 PR-CL1-3 (shared exposure primitive; scenario lifecycle filters)
```

The PR body must include:

- **Findings closed:** explicit `J-CL1-04` and `J-CL1-05` references + D-1.4 institutional decision citation.
- **Files changed:** inventory grouped by service code / tests.
- **Verification matrix:** §8 sweep results.
- **Parity statement:** explicit mention that `test_empty_delta_commercial_parity` and `test_empty_delta_global_parity` pass on the fixed fixture.
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-1-shared-exposure-primitive-{sha}.json` per push.
- **Governance statement:** `docs/governance.md` diff is empty.
- **Alembic statement:** single head `043_a5_audit_payload_input`.

## 11. Workflow

1. `git checkout -b audit-followup/cluster-1-shared-exposure-primitive` from `main` (or post-PR-CL1-1 / PR-CL1-2 if either lands first — this wave's diff does not overlap theirs at file level, but always base off latest main).
2. Apply §4.1 — add the two new primitives to `exposure_service.py`. Run focused tests on `backend/tests/test_exposures_commercial.py` and `backend/tests/test_exposures_global.py` to confirm the **definition** itself doesn't change behavior (the primitive is dead code at this point).
3. Apply §4.2 — refactor `compute_commercial_snapshot` and `compute_global_snapshot` to delegate. Re-run both `test_exposures_commercial.py` and `test_exposures_global.py`; behavior must be byte-equivalent.
4. Apply §4.3 — scenario input boundary lifecycle filters + delete duplicate aggregation. Re-run `test_scenario_whatif_run.py`; some existing tests may need fixture updates if they relied on scenario reading archived entities (a pre-fix bug).
5. Add `test_scenario_live_exposure_parity.py` per §4.4. Run it.
6. Run §8 verification sweeps locally; fix every hook v2 P1/P2 in place.
7. Push branch and open PR per §10.
8. Codex Connector review is the final gate. Address every Codex inline catch. **Do not merge** — Andrei merges with explicit authorization only.

## 12. Hook v2 + Codex calibration notes

- **Expected hook v2 surface area**: medium diff (one new primitive function in `exposure_service.py`, one refactor of `ExposureService.compute_*_snapshot`, one refactor of `scenario_whatif_service.py`, one new test file). Hook may flag prescription-vs-evidence on the new primitive function names (`compute_commercial_exposure_pure` doesn't exist yet) — known FP class.
- **Expected Codex catches**:
  - **Live-side aggregation regression**: if the refactor of `compute_commercial_snapshot` or `compute_global_snapshot` accidentally changes the residual-clamping order, the commodity canonicalization, or the quantize boundary, existing tests in `backend/tests/test_exposures_commercial.py` and `backend/tests/test_exposures_global.py` catch it — but Codex may also spot the regression by reading the diff. Verify byte-equivalence before pushing.
  - **Scenario-input lifecycle filter mismatch**: the verdict's J-CL1-04 evidence cites three live-A1 filters (Order archived, HedgeContract archived, hedge status in {active, partially_settled}). The implementation must apply **all three** at the scenario input boundary, not just the Order filter. Codex will spot a missing status filter.
  - **`float(...)` cast survival**: if any of the old `float(item["..."])` lines in `_compute_commercial_exposure` / `_compute_global_exposure` survives the refactor (e.g. in a leftover helper), Codex will flag it.
  - **Parity test depth**: the parity tests must assert **deep equality** on Decimal fields, not float-tolerant equality. A `pytest.approx` in the parity tests would silently allow a representation-drift bug to land.
  - **Orphan linkage handling — both sides**: J-CL1-04 §evidence calls out HedgeOrderLinkage rows whose parent Order is archived. Verify the `_load_linkages` filter actually excludes those. **Equally important — and the exact gap Codex caught on the v1 dispatch (this PR review)**: the linkage filter must also exclude rows whose linked HedgeContract is archived or not in `{active, partially_settled}` status, mirroring `ExposureService._linked_by_order_subquery`'s join+filter shape verbatim. A scenario `_load_linkages` that filters Orders but lets settled / cancelled / archived hedges' linkages through will silently subtract their quantities from order residuals while live exposure does not, breaking empty-delta parity. Sweep `rg -nP "HedgeContract" backend/app/services/scenario_whatif_service.py` and confirm `_load_linkages` joins HedgeContract with the lifecycle filter present.
  - **Filter-on-shared-loader cross-surface leak (v3 catch)**: when the same loader function feeds multiple downstream consumers, an exposure-only lifecycle filter applied to the loader **silently drops** entities from the other consumers. Specifically, `_load_contracts` at HEAD feeds both the exposure aggregation path AND the scenario P&L loop at `:541-592`. Filtering `_load_contracts` to `{active, partially_settled}` would drop settled hedges from `pl_snapshots` even though scenario P&L semantics intentionally include settled hedges (zero unrealized MTM but realized P&L from `CashFlowLedgerEntry`). The fix is the **two-loader split** prescribed in §4.3.1: keep `_load_contracts` unchanged, add `_load_exposure_contracts` for the filter-needing consumer. Sweep: `rg -nP "session\\.query\\(HedgeContract\\)" backend/app/services/scenario_whatif_service.py` should show two query sites (the raw `_load_contracts` and the new filtered `_load_exposure_contracts`), not one filtered site. Test 4a in §4.4 is the regression guard.
- The 8-section sweep checklist from `feedback_dispatch_self_consistency` applies. The two surfaces — `exposure_service.py` (primitive + live-side delegation) and `scenario_whatif_service.py` (input boundary + delegation) — must be enumerated consistently across §3 evidence, §4 boundary, §6 acceptance, §7 tests, §8 verification, §11 workflow. Drift between sections is the canonical authoring failure mode.
- **The largest authoring risk** is accidentally changing live-side behavior during the refactor. Mitigation: write tests first (or run them between every refactor step). The parity tests are the structural guarantee; they should still pass even if the live-side refactor is incomplete, because the primitive is shared.
