# Phase A1 — PR #5 Dispatch — Snapshot Lifecycle Filters

**Wave:** 2
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-06
**Findings covered:** J-A1-OPUS-02 (Tier 1)
**Branch name:** `audit-a1/snapshot-lifecycle`
**Base:** `main` (latest, post #15 + #13 + #14 + #16)
**Upstream deps satisfied:** PR #16 (Order commodity model + per-commodity snapshots) MERGED — this PR adds lifecycle filters to the commodity-aware substrate.

---

## 1. Mission

Add lifecycle filters to every query that contributes to commercial / global exposure snapshots so that **soft-deleted, settled, and cancelled entities cannot inflate live risk KPIs**. After PR #16, snapshots are correctly per-commodity; but they still aggregate `Order` and `HedgeContract` rows regardless of `deleted_at` or `status`, so an operator deleting a sales order or settling a hedge sees no immediate change in `/exposures/global` because the dead rows still count.

This is a constitutional Tier 1 violation (§2.1: "Exposure is state, never event" — state must reflect current reality, not stale rows; §2.5: Global formula is over **live** entities, not historical).

**Persona:** Senior engineer for an institutional risk platform. The exposure number on the operator's screen is the truth they trade against. A settled hedge that still counts as risk reduction is a worse error than a missing hedge — it produces silent over-confidence in coverage.

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-06-phase-a1-jury-verdict.md`** — finding J-A1-OPUS-02 (§3 Opus-only, jury-validated). Read in full.
- **`docs/governance.md`** — §2.1 (Exposure is state), §2.5 (Global Exposure formula).
- **`docs/audits/2026-05-06-phase-a1-findings-opus.md`** — F-A1-OPUS-06 for full mechanism.
- **Code currently in main (read these before writing — line numbers shifted post #16, verify by grep):**
  - `backend/app/services/exposure_service.py` — `compute_commercial_snapshot` (~71-169), `compute_global_snapshot` (~175-345), `_linked_by_order_subquery` (~31-43), `_validate_residuals_non_negative` (~45-65). All commodity-aware after PR #16; this PR adds the lifecycle filters on top.
  - `backend/app/models/orders.py:54-118` — `Order.deleted_at: Mapped[DateTime | None]` (no `status` field on Order; only `deleted_at`).
  - `backend/app/models/contracts.py:75-190` — `HedgeContract.status: Mapped[HedgeContractStatus]` (default `active`, NOT NULL) AND `HedgeContract.deleted_at: Mapped[DateTime | None]`.
  - `backend/app/models/contracts.py:46-50` — `HedgeContractStatus` enum: `active`, `partially_settled`, `settled`, `cancelled`. **"Live" statuses (must contribute to live exposure):** `active`, `partially_settled`. **Excluded:** `settled`, `cancelled`.
  - `backend/app/services/exposure_engine.py` — `reconcile_from_orders` (touches `Order` queries; coordinate with PR-4 per §8).

---

## 3. Scope IN

### 3.0 Import prerequisites (Codex P2)

The prescriptions in §3.3, §3.5, §3.9, §3.10 reference `HedgeContractStatus` for the live-hedge predicate. The current service files do **not** import this symbol in the relevant scope, so applying any of those prescriptions verbatim would raise `NameError` at the first affected endpoint or reconcile run. Update the imports BEFORE applying any of those prescriptions.

**`backend/app/services/exposure_service.py`** — current line 18:

```python
# Before
from app.models.contracts import HedgeClassification, HedgeContract

# After
from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus
```

**`backend/app/services/exposure_engine.py`** — current line 155 has a function-scope import inside `compute_net_exposure`:

```python
# Current (function-scope inside compute_net_exposure, ~line 155):
from app.models.contracts import HedgeContract, HedgeClassification
```

The §3.9 `_get_linked_qty_map` helper is a separate `@staticmethod` on `ExposureEngineService` and references `HedgeContractStatus` (per §3.9). Its name-resolution scope is **not** shared with `compute_net_exposure`'s function-local imports — applying the §3.9 prescription with only a function-scope import inside `compute_net_exposure` would raise `NameError` when `reconcile_from_orders` calls `_get_linked_qty_map`. Both §3.9 (helper) and §3.10 (rewrite of `compute_net_exposure`) reference `HedgeContractStatus`; module-scope import is the only location that satisfies both name-resolution scopes.

Prescription:

1. **ADD module-scope import** at the top of `backend/app/services/exposure_engine.py`, alongside the existing model imports (e.g., the `from app.models.exposure import (...)` / `from app.models.linkages import HedgeOrderLinkage` / `from app.models.orders import ...` block):

   ```python
   # New module-scope line:
   from app.models.contracts import HedgeClassification, HedgeContract, HedgeContractStatus
   ```

2. **REMOVE the now-redundant function-scope import** inside `compute_net_exposure` (current ~line 155):

   ```python
   # Delete this line — module-scope import in step 1 subsumes it cleanly:
   from app.models.contracts import HedgeContract, HedgeClassification
   ```

The module-scope import covers `compute_net_exposure` (§3.10), `_get_linked_qty_map` (§3.9), and any other method on `ExposureEngineService` that references these symbols, with no scope-resolution surprises.

**Verify the exact `from app.models.contracts import ...` line in each file before editing** — the import order may have shifted between dispatch authoring and execution. For `exposure_service.py`, match the current order verbatim and just append `HedgeContractStatus`. For `exposure_engine.py`, add the new module-scope line alongside the existing `app.models.*` imports and delete the function-scope line. If `HedgeContractStatus` is already present at module scope in either file (e.g., a refactor between dispatch authoring and execution adds it), the ADD step is a no-op — `grep -n "from app.models.contracts" backend/app/services/exposure_service.py backend/app/services/exposure_engine.py` first to confirm.

### 3.1 Filter `Order.deleted_at IS NULL` in commercial snapshot queries

**File:** `backend/app/services/exposure_service.py` — `compute_commercial_snapshot` (~71-169).

The method currently has three queries iterating `Order` (pre_rows, residual_rows, reduction_rows). All three filter `Order.price_type == PriceType.variable` but none filter `Order.deleted_at`. Add to each:

```python
.filter(
    Order.price_type == PriceType.variable,
    Order.deleted_at.is_(None),
)
```

`is_(None)` is the SQLAlchemy idiom for `IS NULL` (works in both SQLite and Postgres via the dialect). Do NOT use `Order.deleted_at == None` or `Order.deleted_at == False` — both are wrong (`deleted_at` is a `DateTime | None`, not boolean).

### 3.2 Filter `Order.deleted_at IS NULL` in global snapshot order-side queries

**File:** `backend/app/services/exposure_service.py` — `compute_global_snapshot` (~175-345).

Apply the same filter to the two `Order` queries (`pre_order_rows`, `residual_order_rows`). Match the §3.1 idiom verbatim.

### 3.3 Filter `HedgeContract` lifecycle in global snapshot hedge-side queries

**File:** `backend/app/services/exposure_service.py` — `compute_global_snapshot`, the `total_hedge_rows` and `residual_hedge_rows` queries.

> **Import prerequisite:** this snippet uses `HedgeContractStatus`. See §3.0 for the import update required in `exposure_service.py` before applying.

Currently both query `HedgeContract` without lifecycle filter. Add to each:

```python
.filter(
    HedgeContract.deleted_at.is_(None),
    HedgeContract.status.in_(
        [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
    ),
)
```

This is the **single canonical predicate** for "live hedge" — the two clauses together. Do not split them; both must hold. A `partially_settled` hedge still has open quantity and contributes to live exposure; `settled` and `cancelled` do not.

Also apply to the `min_contract_residual` query that computes the residual non-negativity check — same filter, same predicate. If the filter is omitted there, settled hedges' residuals would still be validated, producing false 409 errors for legitimately-zero residuals on dead contracts.

### 3.4 Filter linkages by their hedge's lifecycle in `_linked_by_order_subquery`

**File:** `backend/app/services/exposure_service.py` — `_linked_by_order_subquery` (~31-43).

Currently the subquery aggregates `HedgeOrderLinkage` rows by `order_id` without joining `HedgeContract`. Result: a linkage from a now-settled or now-deleted hedge still counts toward the order's "linked qty", reducing residual / commercial exposure as if the hedge were still hedging. That is the inverse of the snapshot bug — instead of inflating, it under-reports commercial exposure (because dead linkages absorb commercial that the operator should see).

Fix:

```python
@staticmethod
def _linked_by_order_subquery(session: Session):
    """Subquery: total linked qty per order, counting only linkages whose
    hedge contract is still live (active / partially_settled, not deleted)."""
    return (
        session.query(
            HedgeOrderLinkage.order_id.label("order_id"),
            func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0).label(
                "linked_qty"
            ),
        )
        .join(HedgeContract, HedgeContract.id == HedgeOrderLinkage.contract_id)
        .filter(
            HedgeContract.deleted_at.is_(None),
            HedgeContract.status.in_(
                [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
            ),
        )
        .group_by(HedgeOrderLinkage.order_id)
        .subquery()
    )
```

Note: this changes the subquery's residual semantics. An order that was previously "fully hedged" via a linkage to a hedge that has since been settled will now show a positive commercial residual — correct, because the hedge is no longer hedging anything live. This is a **behavior change visible to operators** — flag in PR description as `[BEHAVIOR_SHIFT]`.

**On the symmetric `Order.deleted_at IS NULL` filter inside `_linked_by_order_subquery`:** the subquery aggregates by `order_id`, and its sole consumer (`compute_commercial_snapshot`) joins back to `Order` and already filters `Order.deleted_at IS NULL` upstream per §3.1. The order-side filter is therefore upstream of every consumer of this subquery's `linked_qty` aggregate, so adding `Order.deleted_at IS NULL` here would be belt-and-suspenders, not load-bearing. **Decision: do NOT add the symmetric `Order` filter to `_linked_by_order_subquery` in this PR** — keep the subquery focused on the hedge-side lifecycle (which has no upstream filter). The §3.5 sibling subquery (`linked_by_contract`) is in the opposite situation (see §3.5) and DOES require the dual filter.

### 3.5 Apply same lifecycle predicate to `linked_by_contract` subquery — with dual hedge AND order filter

**File:** `backend/app/services/exposure_service.py` — the inline `linked_by_contract` subquery inside `compute_global_snapshot` (~257-265 in current main).

> **Import prerequisite:** this snippet uses `HedgeContractStatus`. See §3.0 for the import update required in `exposure_service.py` before applying.

The bug this subquery hides is more acute than §3.4's. Consider: a live Hedge Short Aluminum 100 linked to a Sales Order Aluminum 100 that is then **soft-deleted**. If the subquery only filters `HedgeContract`, the linkage from the dead order still subtracts from the hedge's residual, zeroing `residual_contract_qty`. Then `compute_global_snapshot` filters out the dead order on the commercial side AND the residual-zero hedge on the global hedge-short-unlinked side, so `/exposures/global` omits **both** the deleted commercial order and the still-live hedge — the operator loses sight of the hedge entirely. This is a worse failure mode than §3.4: the hedge isn't dead, but it disappears from the snapshot.

**Required fix:** the `linked_by_contract` subquery MUST join `Order` AND filter `Order.deleted_at IS NULL` in addition to the `HedgeContract` lifecycle filter. Symmetric to §3.4's hedge-side filter, but applied in the opposite direction — and load-bearing here, not belt-and-suspenders, because no upstream consumer of `linked_by_contract` filters `Order` on this path:

```python
linked_by_contract = (
    session.query(
        HedgeOrderLinkage.contract_id.label("contract_id"),
        func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0).label(
            "linked_qty"
        ),
    )
    .join(HedgeContract, HedgeContract.id == HedgeOrderLinkage.contract_id)
    .join(Order, Order.id == HedgeOrderLinkage.order_id)
    .filter(
        HedgeContract.deleted_at.is_(None),
        HedgeContract.status.in_(
            [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
        ),
        Order.deleted_at.is_(None),
    )
    .group_by(HedgeOrderLinkage.contract_id)
    .subquery()
)
```

**Dual-filter rationale (institutional invariant):** a linkage that reduces hedge residual must couple a live hedge AND a live order. If either side is dead, the linkage does not count toward residual; both the hedge's `linked_qty` and the order's `linked_qty` revert to zero, so both sides reappear in the snapshot with their full pre-linkage exposure. This is the same invariant as §3.4 in mirror image: §3.4 filters out linkages from dead hedges (so commercial doesn't keep getting reduced by a dead hedge); §3.5 filters out linkages from dead orders (so a live hedge doesn't keep getting reduced by a dead order's linkage).

### 3.6 Filter `Order.deleted_at IS NULL` in `_validate_residuals_non_negative`

**File:** `backend/app/services/exposure_service.py` — `_validate_residuals_non_negative` (~45-65).

This helper validates that no order has negative residual after linkages. If it queries Order without filtering deleted_at, it could fail with a misleading 409 on a soft-deleted order whose linkages weren't cleaned up. Inspect the function body and add the filter consistent with §3.1. Do NOT skip — defense-in-depth, prevents misleading error messages.

### 3.7 Coordinate with `reconcile_from_orders` (PR-4 territory — soft scope)

**File:** `backend/app/services/exposure_engine.py` — `reconcile_from_orders` queries `Order` to derive `Exposure` rows.

PR-4 (linkage hardening, J-A1-OPUS-01) modifies this function to hard-fail on negative residuals. **Do NOT re-implement that fix here.** But the same `Order.deleted_at IS NULL` filter prevents NEW `Exposure` rows from being created for soft-deleted orders. **Additionally, per §3.8, `reconcile_from_orders` MUST retire existing `Exposure` rows whose source order has been soft-deleted, matching the lifecycle semantics required by J-A1-OPUS-02.** Filtering alone is insufficient: pre-existing `Exposure` rows derived from now-deleted orders persist in the table and are still counted by `compute_net_exposure`, so the lifecycle invariant is broken on the reconcile side until §3.8 retirement runs.

**Coordination plan:**
- If PR-4 lands first: rebase this PR on top of PR-4's reconcile changes; add the `Order.deleted_at IS NULL` filter to the order query in `reconcile_from_orders`. Verify PR-4's residual hard-fail still works on the filtered query (it should — the filter narrows the input set, doesn't change the assertion).
- If this PR lands first: PR-4 rebases on top; PR-4's residual assertion runs on the lifecycle-filtered orders.
- Either order works; the filter and the assertion are orthogonal.

Document the coordination in PR description; the orchestrator will sequence the merges to minimize rebase work.

§3.8 retires existing rows. Cross-consumer parity for live-linkage semantics extends further: §3.9 fixes the reconcile linkage aggregation AND preserves its `dict[str, Decimal]` caller-contract (Codex P1); §3.10 changes `compute_net_exposure`'s hedge aggregation from whole-contract `NOT IN` exclusion to residual subtraction (`quantity_mt - SUM(live linkages)`) AND skips zero-residual grouped rows in the downstream loop to preserve the response-shape invariant (Codex P2), ensuring it produces the SAME per-contract residual as `compute_global_snapshot` AND the same response shape as the pre-fix code. All five concerns together (§3.4 hedge-side filter on `_linked_by_order_subquery`; §3.5 dual filter on `linked_by_contract`; §3.9 dual filter on `_get_linked_qty_map` with string-key contract; §3.10 residual subtraction with zero-residual skip in `compute_net_exposure`) establish the institutional invariant as follows: sites listed as load-bearing for the dual-filter predicate (§3.5, §3.9, §3.10) MUST apply both `HedgeContract` and `Order` lifecycle filters together, because no upstream consumer narrows the missing side. Sites listed as belt-and-suspenders (§3.4) MAY rely on the consumer's upstream filter (`compute_commercial_snapshot` already filters `Order.deleted_at IS NULL` per §3.1) and intentionally omit the redundant `Order` predicate. The institutional invariant is consistency between snapshot, reconcile, and net-exposure consumers — not blanket dual-filter application at every linkage query site. Every consumer must additionally (b) compute residuals by subtraction, not whole-contract exclusion, AND (c) preserve the caller's expected key/shape contract (`dict[str, Decimal]` from `_get_linked_qty_map`; per-commodity entries only when residual > 0 from `compute_net_exposure`).

### 3.8 Retire derived `Exposure` rows for deleted source orders (Option A — preferred)

**File:** `backend/app/services/exposure_engine.py` — `reconcile_from_orders`.

**Why this is required, not optional.** §3.7's filter only stops NEW `Exposure` rows from being created for soft-deleted orders. But pre-existing `Exposure` rows whose source order was reconciled BEFORE soft-delete are never re-visited by a filter-only fix; they remain `is_deleted = False` with positive `open_tons`, and `compute_net_exposure` (a separate consumer of the `Exposure` table) keeps counting them. The J-A1-OPUS-02 invariant — "dead source rows cannot inflate live KPIs" — is violated on the reconcile/net-exposure path until those derived rows are retired.

**Exposure model inspection (verified by reading `backend/app/models/exposure.py`):**

- FK to source order: **`Exposure.source_id: UUID`** (polymorphic — discriminated by `source_type: ExposureSourceType` enum: `sales_order` / `purchase_order`). There is no FK constraint to `orders.id`; the join must be `Order.id == Exposure.source_id` AND `Exposure.source_type IN (sales_order, purchase_order)`.
- Lifecycle fields available on `Exposure`: **BOTH** `is_deleted: Boolean` (default False) **AND** `deleted_at: DateTime | None`. There is no `retired` status on `ExposureStatus` (which has only `open` / `partially_hedged` / `fully_hedged` / `cancelled`).
- `Exposure.open_tons` (Numeric) — the quantity field that `compute_net_exposure` aggregates.

**Retirement strategy — Option A preferred order, with fallbacks.** Pick (a); fall back to (b) only if (a) breaks an existing consumer; (c) is last resort.

- **(a) PREFERRED — Soft-delete symmetric to upstream:** set `Exposure.is_deleted = True` AND `Exposure.deleted_at = func.now()`, leaving `open_tons` and `status` untouched for audit. `compute_net_exposure` (and any other consumer of the `Exposure` table) MUST be inspected and updated to filter `Exposure.is_deleted.is_(False)` (or equivalently `Exposure.deleted_at.is_(None)`); without that downstream filter, retirement is invisible. Verify both filter idioms during implementation — the codebase already mixes `is_deleted` and `deleted_at`; pick whichever is consistent with surrounding code on a per-consumer basis but always set both fields here.
- **(b) Fallback if (a) breaks an unfilterable consumer:** set `Exposure.open_tons = 0` AND `Exposure.status = ExposureStatus.cancelled` (the closest semantic match to "retired" in the existing enum — `cancelled` is the lifecycle terminal state). This zeroes the quantity that `compute_net_exposure` aggregates without requiring a downstream filter change. Lossier for audit (the original `open_tons` is lost) — only use if (a) is impractical.
- **(c) Last resort — hard `DELETE`:** only if (a) and (b) are both blocked. Loses audit trail entirely; document the reason in PR description.

**Where the retirement runs.** Inside `reconcile_from_orders`, AFTER the new-creation pass, in the same UoW (per PR-13 boundary — no `session.commit()` from the service). The function's contract becomes "make `Exposure` rows reflect current `Order` lifecycle state — both create live, AND retire dead". Sketch:

```python
# After the existing creation/update pass, sweep stale rows:
stale_exposures = (
    session.query(Exposure)
    .join(
        Order,
        Order.id == Exposure.source_id,
    )
    .filter(
        Exposure.source_type.in_(
            [ExposureSourceType.sales_order, ExposureSourceType.purchase_order]
        ),
        Exposure.is_deleted.is_(False),
        Order.deleted_at.is_(None) == False,  # i.e., Order is soft-deleted
    )
    .all()
)
for exposure in stale_exposures:
    exposure.is_deleted = True
    exposure.deleted_at = func.now()
```

(Use `Order.deleted_at.isnot(None)` in the actual SQLAlchemy idiom — `isnot(None)` is the proper inverse of `is_(None)`. Do NOT use `Order.deleted_at != None` or `not Order.deleted_at.is_(None)`.)

**Reversibility — soft-delete-on-source reversed.** If an operator clears `Order.deleted_at` (un-deletes the order), the next `reconcile_from_orders` MUST either un-retire the `Exposure` row (clear `is_deleted` / `deleted_at`) OR create a fresh `Exposure` row. Pick whichever is easier to reason about; document the choice in the PR description. Acceptance §6.6 covers this case.

**Option B (documented fallback only — DO NOT default here).** If the retirement path proves infeasible (e.g., `compute_net_exposure` has consumers that cannot tolerate the `is_deleted` filter without a coordinated change exceeding PR-5's scope), defer to a follow-up PR. Add to §4 Scope OUT and open a GitHub issue at PR-5 merge time covering the retirement sweep + `compute_net_exposure` lifecycle alignment. Update §6.6 to document the deferred case with a reproducing fixture (Exposure row count remains positive after Order soft-delete) so the follow-up has a starting point. **Option A is the default — choose B only on a documented scope blocker, surfaced in the PR body per §9.**

### 3.9 Filter linkages by live hedge AND live order in reconcile linkage map

**File:** `backend/app/services/exposure_engine.py` — `_get_linked_qty_map(session)` (`exposure_engine.py:60`).

> **Import prerequisite:** this snippet uses `HedgeContractStatus`. See §3.0 for the import update required in `exposure_engine.py` (module-scope import — `_get_linked_qty_map` is a separate `@staticmethod` on `ExposureEngineService` whose scope is not shared with `compute_net_exposure`'s function-locals, so module scope is required) before applying.

The current helper sums `HedgeOrderLinkage.quantity_mt` grouped by `order_id` without joining `HedgeContract` or filtering `Order`. Result: a linkage to a settled or soft-deleted hedge still reduces `Exposure.open_tons` derived in `reconcile_from_orders`, even though `ExposureService` (the snapshot consumer) now shows the order as unhedged after §3.4. Cross-consumer parity is broken — the same data is summarized inconsistently by reconcile vs by snapshot.

Apply the SAME dual-filter predicate from §3.5 — joining `HedgeContract` AND `Order`, requiring both live:

```python
@staticmethod
def _get_linked_qty_map(session: Session) -> dict[str, Decimal]:
    """Sum linkage qty per order_id, counting only linkages whose
    hedge contract AND source order are both live (active/partially_settled
    and not soft-deleted). Mirrors ExposureService.§3.5 dual-filter
    for cross-consumer parity required by J-A1-OPUS-02.

    Keys are `str(order_id)` — `reconcile_from_orders` calls
    `linked_map.get(str(order.id), ...)` (exposure_engine.py:77);
    UUID keys would silently miss every lookup."""
    rows = (
        session.query(
            HedgeOrderLinkage.order_id,
            func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0).label("linked_qty"),
        )
        .join(HedgeContract, HedgeContract.id == HedgeOrderLinkage.contract_id)
        .join(Order, Order.id == HedgeOrderLinkage.order_id)
        .filter(
            HedgeContract.deleted_at.is_(None),
            HedgeContract.status.in_(
                [HedgeContractStatus.active, HedgeContractStatus.partially_settled]
            ),
            Order.deleted_at.is_(None),
        )
        .group_by(HedgeOrderLinkage.order_id)
        .all()
    )
    return {str(row.order_id): row.linked_qty for row in rows}
```

**Caller-contract invariant (P1, Codex catch):** Keys MUST be stringified — `reconcile_from_orders` looks up `linked_map.get(str(order.id), ...)` per existing convention (verified at `backend/app/services/exposure_engine.py:77`). Returning UUID keys breaks every lookup silently and inflates `Exposure.open_tons` for all linked orders (the `.get()` falls through to the `Decimal("0")` default, so `hedged_qty = 0`, `open_qty = order_qty`, and every linked order is treated as fully unhedged). Preserve the existing `dict[str, Decimal]` shape; only add the lifecycle filter — do NOT change the key type.

Note: the `Order` filter is technically redundant with the `Order` query in `reconcile_from_orders` (which §3.7 already filters), BUT it is load-bearing for `compute_net_exposure` (§3.10 below) which consumes Exposure rows produced by reconcile. Without the filter here, an Exposure produced from a stale linkage cycle could survive after both consumers diverge.

Coordination with §3.8: §3.8 retirement uses this updated `_get_linked_qty_map` automatically — no additional changes to retirement logic.

### 3.10 Hedge residual aggregation in `compute_net_exposure` (corrects whole-contract `NOT IN` semantics)

**File:** `backend/app/services/exposure_engine.py` — `compute_net_exposure` (`exposure_engine.py:141`); the offending hedge-side block is at `exposure_engine.py:199-215` (linkage subquery + global hedge query). Note: confirmed by `git grep -n "compute_net_exposure" backend/app/`, this lives in `exposure_engine.py` (NOT `exposure_service.py` as one might expect from the §3 prefix pattern).

> **Import prerequisite:** the "Before" snippet below already uses `HedgeContract.status.in_(["active", "partially_settled"])` (string literals — current code form). The "After" snippet preserves that string-literal form, so no `HedgeContractStatus` import is strictly required for §3.10 alone. However, if the executor opts to align with the §3.3 / §3.5 / §3.9 enum form (`HedgeContractStatus.active`, `HedgeContractStatus.partially_settled`) for consistency across the engine, see §3.0 for the import update.

The current implementation excludes any hedge whose id appears in `linked_contract_ids` via `~HedgeContract.id.in_(linked_contract_ids)` — a whole-contract boolean exclusion. This produces incorrect output for hedges with PARTIAL linkages: a 100 MT hedge with a 40 MT linkage to a live order should show 60 MT residual unlinked exposure, but the boolean exclusion zeroes the entire contract.

The global snapshot path (`compute_global_snapshot` in `exposure_service.py:259-307`) computes `residual_contract_qty = HedgeContract.quantity_mt - func.coalesce(linked_by_contract.c.linked_qty, 0.0)` and groups `func.sum(residual_contract_qty)` by `(commodity, classification)`. `compute_net_exposure` MUST mirror that semantic so the two endpoints agree on the same input data — particularly after §3.5 reincludes a live hedge whose linkage points to a soft-deleted order. The §6.3.5 / §6.3.7 scenarios reproduce this exact divergence, and the partly-linked Codex case (100 MT hedge + 40 MT linkage to a live order: net should show 60 MT, not 0 and not 100) is covered identically by the same residual-subtraction formula.

Replace the linkage-id subquery + `NOT IN` filter (currently `exposure_engine.py:199-211`) with a residual subquery that aggregates LIVE-ORDER linkage qty per contract, then computes `quantity_mt - coalesce(linked_qty, 0)` per row and sums by `(commodity, classification)`:

```python
# Before (incorrect — whole-contract exclusion):
linked_contract_ids = (
    session.query(HedgeOrderLinkage.contract_id).distinct().scalar_subquery()
)
gq = session.query(
    HedgeContract.commodity,
    HedgeContract.classification,
    func.coalesce(func.sum(HedgeContract.quantity_mt), 0).label("total_qty"),
).filter(
    HedgeContract.deleted_at.is_(None),
    HedgeContract.status.in_(["active", "partially_settled"]),
    ~HedgeContract.id.in_(linked_contract_ids),
)

# After (correct — residual subtraction matching §3.5 / global snapshot):
live_linked_qty_per_contract = (
    session.query(
        HedgeOrderLinkage.contract_id.label("contract_id"),
        func.coalesce(
            func.sum(HedgeOrderLinkage.quantity_mt), 0.0
        ).label("linked_qty"),
    )
    .join(Order, Order.id == HedgeOrderLinkage.order_id)
    .filter(Order.deleted_at.is_(None))  # only live-order linkages count
    .group_by(HedgeOrderLinkage.contract_id)
    .subquery()
)

residual_contract_qty = HedgeContract.quantity_mt - func.coalesce(
    live_linked_qty_per_contract.c.linked_qty, 0.0
)

gq = (
    session.query(
        HedgeContract.commodity,
        HedgeContract.classification,
        func.coalesce(func.sum(residual_contract_qty), 0).label("total_qty"),
    )
    .outerjoin(
        live_linked_qty_per_contract,
        HedgeContract.id == live_linked_qty_per_contract.c.contract_id,
    )
    .filter(
        HedgeContract.deleted_at.is_(None),
        HedgeContract.status.in_(["active", "partially_settled"]),
    )
)
if commodity:
    gq = gq.filter(HedgeContract.commodity.in_(commodity_aliases(commodity)))
gq = gq.group_by(HedgeContract.commodity, HedgeContract.classification)
```

The `outerjoin` is essential: hedges with NO linkage at all join to NULL `linked_qty`, then `coalesce(NULL, 0)` makes the residual = full quantity. Hedges with partial linkages get partial residuals. Hedges fully linked to live orders get residual = 0.

**Zero-residual skip (P2, Codex catch — required to preserve response shape):** when ALL of a commodity's live hedges are fully linked to live orders, the grouped `SUM(residual)` is `0`, but the GROUP BY still emits one row per `(commodity, classification)`. The downstream loop at `exposure_engine.py:217-238` creates a fresh `agg[c]` entry on first sight of a commodity (via `agg.setdefault(...)`), so a zero-residual grouped row would inflate the response shape with a commodity entry that should NOT exist (commercial side already filtered the commodity out as `fully_hedged`, and the §4 / §10 invariant says response shape is preserved). Skip those rows in the loop:

```python
# After the residual SUM query, in the downstream aggregation loop:
for row in gq.all():
    if row.total_qty == 0:
        continue  # Skip zero-residual groups: a commodity whose hedges
                  # are all fully linked has no unhedged exposure to
                  # report. Preserves response shape per §4/§10 — without
                  # this skip, a fully-hedged commodity gains a zero-valued
                  # row in the response, vs. the pre-fix "no row" semantic.
    agg.setdefault(row.commodity, ...)
    if row.classification == HedgeClassification.short:
        agg[row.commodity].short_tons += row.total_qty
    else:
        agg[row.commodity].long_tons += row.total_qty
```

**Why the Python-side skip (Option b) over a SQL `HAVING` clause (Option a).**

1. **Fewer SQL surprises.** `HAVING SUM(quantity_mt - COALESCE(linked_qty, 0)) > 0` requires repeating the computed expression literally, which is brittle across SQLAlchemy versions and SQL dialects (SQLite vs Postgres handling of `coalesce` inside aggregate predicates differs subtly).
2. **Symmetric with the existing pattern.** The prior implementation used `if c not in agg`-style guards in Python; keeping the skip in Python aligns with the surrounding code style.
3. **Easier to test in unit form.** A Python `continue` is exercised by any unit test on the loop; a SQL `HAVING` requires DB-introspection assertions to verify it fired.

**Decision: implement Option b (Python-side `continue` in the loop).** Do NOT add a SQL `HAVING` clause; the SQL stays as-is and the loop carries the guard.

**Key invariant (CONSTITUTIONAL):** `compute_net_exposure` and `compute_global_snapshot` MUST produce the same per-contract residual for the same input data. After this fix, the two formulas align byte-for-byte:

```
residual_contract_qty = HedgeContract.quantity_mt
                      - SUM(linkage.quantity_mt WHERE linkage.order is LIVE
                                             AND linkage.contract is LIVE)
```

The hedge-side lifecycle filter (live hedge: `deleted_at IS NULL` AND `status IN (active, partially_settled)`) is enforced on the OUTER query; the linkage-side lifecycle filter (live order: `Order.deleted_at IS NULL`) is enforced on the INNER subquery. This composes the dual-filter invariant from §3.5 / §3.9 to BOTH the hedge contract and its linkages — the same composition the global snapshot performs.

---

## 4. Scope OUT — explicitly NOT in PR-5

- **Audit emission for the routes that consume snapshots** — PR-7 territory.
- **Reconcile residual hard-fail** — PR-4 territory; this PR only adds the lifecycle filter to reconcile's order query (§3.7) and the dual-filter to its linkage map helper (§3.9). The hard-fail assertion itself remains PR-4's surface.
- **`compute_net_exposure` shape / convention changes** — out of scope. §3.10 changes the hedge-side AGGREGATION FORMULA from whole-contract `NOT IN` exclusion to residual subtraction (matching `compute_global_snapshot`); the function's return dict shape, net-tons sign convention, and commodity grouping are unchanged.
- **Decimal primitives** — PR-1 in main; preserve.
- **UoW boundary** — PR-3 in main; preserve.
- **Classification invariant** — PR-6/#14 in main; preserve.
- **Per-commodity grouping** — PR-2/#16 in main; preserve.
- **`Exposure.is_deleted` reconcile semantics (J-A1-OPUS-08)** — Tier 3 deferred; tracked as GitHub issue #12. This PR does NOT touch the `Exposure` model schema or duplicate-source-snapshot semantics from J-A1-OPUS-08. **However, per §3.8, this PR DOES set `Exposure.is_deleted` / `Exposure.deleted_at` on derived `Exposure` rows whose source `Order` has been soft-deleted** — that retirement is required to close J-A1-OPUS-02's lifecycle invariant on the reconcile/net-exposure path. The §3.8 retirement is a write to existing `Exposure` lifecycle fields; it does NOT change the model schema and does NOT pre-empt issue #12's separate concerns.
- **`DealLink` lifecycle on soft-deleted Deal (J-A1-OPUS-07)** — Tier 3 deferred; tracked as GitHub issue #11.
- **Commodity alias normalization** — already in main (per #16 Codex catches); do not re-implement.
- **P&L price evidence** — PR-8 territory.
- **Snapshot persistence schema changes** — none. This PR only changes query filters in service code; no model/migration changes.

---

## 5. Constitutional rules (binding)

- **§2.1** — "Exposure is state, never event." A snapshot of exposure state must reflect **current** state. A row whose entity has been deleted, settled, or cancelled is not part of current state and must not contribute to the snapshot.
- **§2.5** — Global Exposure formula: `Global Active = Commercial Active + Hedge Short (unlinked)`; `Global Passive = Commercial Passive + Hedge Long (unlinked)`. The formula operates on **live** entities. A settled Hedge Short that still counts as `Hedge Short (unlinked)` violates the formula's domain — settled hedges have no Hedge Short component anymore.
- **§2.7** — Output contract: precise, verifiable, audit-friendly. A snapshot that includes dead rows is not precise; a query plan that doesn't filter is not verifiable.

---

## 6. Acceptance criteria (from jury §3 J-A1-OPUS-02 + my additions)

For every test fixture below, **the constitutional formula derivation MUST be in a comment next to the expected output** (anti-Tipo-II per memory `feedback_dispatch_self_consistency`). The fixture only proves the right thing if you can read the formula → numbers chain at review time.

### 6.1 Order lifecycle exclusion

- [ ] **Test:** insert variable-price SO Aluminum 100, then soft-delete (`Order.deleted_at = now()`). `compute_commercial_snapshot()` returns NO row for Aluminum (or returns Aluminum row with active=0). `compute_global_snapshot()` does the same.
  - *Formula (§2.5):* `Commercial Active Aluminum = sum of variable-price SO where deleted_at IS NULL = 0`
- [ ] **Test:** SO Aluminum 100 (live) + SO Aluminum 50 (deleted) → snapshot shows Aluminum.active = 100 (only the live one).
  - *Formula:* `100 + 0 = 100`
- [ ] **Test:** PO Aluminum 80 (deleted) → snapshot shows no Aluminum.passive (or zero); deleted PO doesn't inflate passive.

### 6.2 HedgeContract lifecycle exclusion

- [ ] **Test:** Hedge Short Aluminum 100 with `status=active` → contributes 100 to Aluminum.global_active.
  - *Formula:* `Global Active Aluminum = Commercial Active + Hedge Short live = 0 + 100 = 100`
- [ ] **Test:** Same hedge with `status=partially_settled` → still contributes 100 (partial settlement leaves open exposure).
- [ ] **Test:** Same hedge with `status=settled` → contributes 0 (no live exposure).
  - *Formula:* `Hedge Short live = 0 (settled is not live)`
- [ ] **Test:** Same hedge with `status=cancelled` → contributes 0.
- [ ] **Test:** `status=active` but `deleted_at` is set → contributes 0 (deleted_at is the override; deleted means dead).

### 6.3 Linkage from dead hedge does not reduce commercial

- [ ] **Test (BEHAVIOR_SHIFT, document in PR):** SO Aluminum 100 + Hedge Short Aluminum 100 (status=active) + linkage 100 between them → commercial Aluminum.active = 0 (linkage reduces).
  - Then settle the hedge (`status=settled`).
  - Re-query commercial → Aluminum.active = 100 (linkage no longer reduces because hedge is dead).
  - This is the explicit behavior change vs pre-PR. Operators will see commercial exposure increase when a hedge settles. This is correct: the order is no longer hedged.
- [ ] **Test:** Same with deleted_at instead of status=settled → same outcome.

### 6.3.5 Linkage from soft-deleted order does not reduce live hedge's residual

This is the symmetric mirror of §6.3 — the §3.5 `linked_by_contract` dual-filter case. A live hedge linked to a soft-deleted order must reappear in the snapshot with FULL residual; the linkage from the dead order does not count.

- [ ] **Test (P1, Codex catch):** SO Aluminum 100 (live) + Hedge Short Aluminum 100 (status=active) + linkage 100 between them.
  - Initial snapshot: commercial Aluminum.active = 0 (linkage absorbs commercial residual); global Aluminum.hedge_short_unlinked = 0 (linkage absorbs hedge residual).
  - Soft-delete the order (`Order.deleted_at = now()`).
  - Re-snapshot:
    - commercial Aluminum.active = 0 (the SO is dead and filtered out per §3.1 — does not appear at all).
    - global Aluminum.hedge_short_unlinked = 100 (the live hedge is back to FULL residual because the linkage no longer counts — its order is dead).
  ```python
  # Per §2.5: Hedge Short live unlinked = total_live_hedge_short - linked_to_live_orders.
  # After SO soft-delete: total_live_hedge_short = 100, linked_to_live_orders = 0
  # (linkage's order is dead per §3.5 dual filter), so:
  #   global Aluminum.hedge_short_unlinked = 100 - 0 = 100
  expected_aluminum_hedge_short_unlinked = Decimal("100")
  ```
  - **Failure mode prevented:** without the §3.5 dual filter, the linkage from the dead order still reduces the hedge's `residual_contract_qty` to zero, then `compute_global_snapshot`'s outer filter excludes the residual-zero hedge as well — so `/exposures/global` would omit BOTH the dead order AND the live hedge, silently hiding 100 MT of live risk.

### 6.3.6 `_get_linked_qty_map` parity (P1, Codex catch)

This is the reconcile-side mirror of §6.3 / §6.3.5 — the §3.9 dual-filter case. A linkage to a dead hedge must NOT keep reducing the order's derived `Exposure.open_tons`.

- [ ] **Test:** Variable-price SO Aluminum 100 (live) + Hedge Short Aluminum 100 (active) + linkage 100. Reconcile creates `Exposure.open_tons = 0`. Now settle the hedge (`HedgeContract.status = settled`). Re-run `reconcile_from_orders`. Assert: `Exposure.open_tons` is now 100 (linkage no longer reduces because hedge is dead).
  ```python
  # Per §2.1 (Exposure is state, never event) + §3.9 dual filter:
  #   open_tons = order_qty - linked_qty_from_LIVE_hedges
  # After settle: linked_qty_from_LIVE_hedges = 0, so:
  #   open_tons = 100 - 0 = 100
  expected_open_tons = Decimal("100")
  ```
- [ ] **Test:** Same scenario but with hedge soft-deleted (`HedgeContract.deleted_at` set instead of status=settled) — same outcome, `open_tons = 100`.
  ```python
  # Per §3.9 dual filter (deleted_at IS NULL clause):
  #   linked_qty_from_LIVE_hedges = 0  (hedge has deleted_at set)
  #   open_tons = 100 - 0 = 100
  expected_open_tons = Decimal("100")
  ```
- [ ] **Test:** Same scenario but with order soft-deleted — handled by §3.8 retirement; the linkage map filter is orthogonal but verified to NOT reintroduce the dead order. Assert: the previously-derived `Exposure` row is retired (`is_deleted = True`) and is NOT regenerated by reconcile while the order remains soft-deleted.
  ```python
  # Per §3.8 retirement + §3.9 filter composition:
  #   stale_exposure.is_deleted == True
  #   no new Exposure row created for the dead order
  ```
- [ ] **Test (caller contract — P1, Codex catch):** Set up a live SO + live linkage. Call `_get_linked_qty_map`. Assert: keys are `str` instances (`all(isinstance(k, str) for k in linked_map.keys())`). Cross-check via integration: run `reconcile_from_orders` and assert `Exposure.open_tons` correctly reflects the linkage (NOT inflated by silent `.get()` misses).
  ```python
  # Per §3.9 caller-contract invariant:
  #   reconcile_from_orders does linked_map.get(str(order.id), Decimal("0"))
  #   at exposure_engine.py:77. If keys were UUID, every .get() would miss
  #   and hedged_qty would default to 0, inflating open_tons.
  # Constitutional formula:
  #   open_tons = order_qty - linked_map.get(str(order.id), 0)
  #             = 100 - 40 = 60   (NOT 100, which would mean lookup missed)
  linked_map = ExposureEngineService._get_linked_qty_map(session)
  assert all(isinstance(k, str) for k in linked_map.keys())
  ExposureEngineService.reconcile_from_orders(session)
  exposure = session.query(Exposure).filter(Exposure.source_id == so.id).one()
  assert exposure.open_tons == Decimal("60")  # not Decimal("100")
  ```

### 6.3.7 `/exposures/net` parity with global snapshot (P1, Codex catch)

This is the net-exposure mirror of §6.3.5 — the §3.10 hedge-side linkage filter case. After §3.5 reincludes a live hedge whose linkage points to a soft-deleted order in the global snapshot, `compute_net_exposure` must agree.

- [ ] **Test:** Recreate §6.3.5 fixture (live SO Aluminum 100 + live Hedge Short Aluminum 100 + linkage 100; then soft-delete the SO). Call `compute_net_exposure(session, commodity="aluminum")`. Assert: hedge appears in net exposure with FULL residual (consistent with global snapshot per §3.5).
  ```python
  # Per §2.5 + §3.10 inner-set narrowing:
  #   Hedge in net = total_live_hedge - linked_to_LIVE_orders
  #                = 100 - 0 = 100  (linkage's order is soft-deleted, dropped by §3.10 filter)
  # Net (convention: positive = Vendido/short):
  #   net_tons = (SO_open - PO_open) + global_short - global_long
  #            = (0 - 0) + 100 - 0 = 100
  expected_aluminum_short_tons = Decimal("100")
  expected_aluminum_net_tons = Decimal("100")
  ```
- [ ] **Test:** Same fixture but with order LIVE (no soft-delete). Call `compute_net_exposure`. Assert: hedge does NOT appear in `short_tons` / `long_tons` (it is linked to a live order — already accounted in commercial). Verifies the §3.10 filter narrows correctly without breaking the live path.
  ```python
  # Per §2.5 + §3.10 residual subtraction:
  #   linked_to_LIVE_orders = 100  (live SO linkage counted)
  #   residual_contract_qty = 100 - 100 = 0
  #   Hedge contribution to short_tons = sum(residual) = 0
  expected_aluminum_short_tons = Decimal("0")
  # But commercial side reflects the (still-zero-residual) SO via Exposure rows.
  ```
- [ ] **Test (P1, partly-linked — Codex catch):** Hedge Short Aluminum 100 (active, deleted_at NULL) + linkage 40 to a live SO Aluminum 100. Call `compute_net_exposure`. Assert: hedge residual contribution to `short_tons` = 60 MT (NOT 0, NOT 100). The previous whole-contract `NOT IN` semantic would zero the entire hedge; the §3.10 residual-subtraction fix correctly carries the 60 MT unlinked portion.
  ```python
  # Per §3.10 residual subtraction (constitutional formula):
  #   residual_contract_qty = quantity_mt - SUM(live linkages)
  #                         = 100 - 40 = 60
  # Hedge contribution to short_tons = sum(residual) = 60
  expected_aluminum_short_tons_from_hedge = Decimal("60")
  # Cross-check: compute_global_snapshot for the same fixture must produce
  # identical hedge_short_mt = 60 for the hedge — same constitutional formula.
  ```
- [ ] **Test (response-shape invariant — P2, Codex catch):** Aluminum has only live hedges and they are ALL fully linked to live orders; no live SO/PO Aluminum (commercial = `fully_hedged`, filtered out per §3.1). Call `compute_net_exposure(session)`. Assert: response does NOT contain an Aluminum entry (NOT a zero-valued one). Without the §3.10 zero-residual `continue` guard, the SUM grouped row of `total_qty == 0` would still create an `agg["aluminum"]` entry via `setdefault`, breaking the §4 / §10 response-shape preservation invariant.
  ```python
  # Per §3.10 response-shape invariant (constitutional):
  #   if SUM(residual) == 0 across all live Aluminum hedges
  #     → no Aluminum row in response (shape preserved per §4 / §10)
  #   NOT a zero-valued Aluminum row.
  # Fixture: Hedge Short Aluminum 100 (active, deleted_at NULL)
  #          + live SO Aluminum 100 + linkage 100  (so residual = 0)
  #          + no other live Aluminum SO/PO
  # Expected: response (list[dict]) does NOT contain a row whose
  # "commodity" field is "aluminum". Asserting `"aluminum" not in result`
  # is a TRAP: result is list[dict], the string is never == a dict, so
  # the assertion is trivially true regardless of content and would NOT
  # catch the regression. Build a keyed set of commodities present and
  # assert against THAT.
  result = ExposureEngineService.compute_net_exposure(session)
  commodities_in_response = {row["commodity"] for row in result}
  assert "aluminum" not in commodities_in_response, (
      f"Aluminum should NOT appear in net-exposure response when its only "
      f"live hedges are fully linked to live orders (zero-residual group "
      f"must be skipped per §3.10). Got: {result}"
  )
  ```
- [ ] **Test (cross-endpoint parity — institutional invariant):** For ANY hedge in ANY fixture (live, partially_settled, with/without linkages, with linkages to live OR dead orders), assert that the hedge's contribution to `compute_net_exposure`'s `long_tons` / `short_tons` equals the same hedge's contribution to `compute_global_snapshot`'s `hedge_long_mt` / `hedge_short_mt`. This is the institutional invariant that §3.10 closes; can be implemented as a parametrized test over the §6.1–§6.3.6 fixtures or as a property-based test if a hypothesis fixture exists.
  ```python
  # Per §3.10 invariant: net and global must agree per-contract.
  # For each (commodity, classification):
  #   net_contribution    = sum over hedges of residual_contract_qty
  #   global_contribution = sum over hedges of residual_contract_qty
  #   assert net_contribution == global_contribution
  ```

### 6.4 Multi-commodity isolation preserved (post-#16)

- [ ] **Test:** SO Aluminum 100 + SO Copper 50 + Hedge Short Aluminum 80 (live, unlinked) + Hedge Short Copper 30 (settled) → global.Aluminum.active = 180, global.Copper.active = 50 (NOT 80; the settled Cu hedge is excluded).
  - *Formula:* `Aluminum: 100 + 80 = 180. Copper: 50 + 0 (settled) = 50.`

### 6.5 No false 409 from `_validate_residuals_non_negative` on dead orders

- [ ] **Test:** Soft-delete an order whose residual would be negative (e.g., over-linked from before lifecycle filtering). `compute_commercial_snapshot()` does NOT raise 409 — the dead order is filtered out before validation.

### 6.6 Reconcile (coordinate with PR-4) — filter AND retirement (§3.7 + §3.8)

**Filter path (prevents new dead-source `Exposure` rows — §3.7):**

- [ ] **Test:** Soft-deleted variable-price order does NOT cause `reconcile_from_orders` to create or update an `Exposure` row.
- [ ] **Test:** Live order produces `Exposure` row as before; lifecycle filter does not affect non-deleted path.

**Retirement path (closes the J-A1-OPUS-02 lifecycle invariant — §3.8 Option A, P2 Codex catch):**

- [ ] **Test (P2, Codex catch):** Live order reconciled → `Exposure` row exists with `open_tons > 0` and `is_deleted = False`. Soft-delete the order (`Order.deleted_at = now()`). Re-run `reconcile_from_orders`. The pre-existing `Exposure` row is now retired per Option A: `is_deleted = True` AND `deleted_at` is set. `compute_net_exposure` no longer counts it.
  ```python
  # Per §2.1 (Exposure is state, never event):
  # state must reflect current Order lifecycle. After Order.deleted_at is set,
  # the derived Exposure row's open_tons must NOT count toward net exposure.
  assert exposure.is_deleted is True
  assert exposure.deleted_at is not None
  # compute_net_exposure aggregates over Exposure.is_deleted.is_(False) and
  # returns list[dict] with per-row "commodity" and "net_tons" fields (NOT a
  # scalar Decimal map). Comparing the list to Decimal("0") is a TRAP — the
  # comparison fails for the wrong reason regardless of content. Iterate the
  # list and assert against the "commodity" field instead. Same idiom as §6.3.7.
  # Cleanest assertion: after Option A retirement, the only Exposure row for
  # aluminum is now is_deleted=True, the SUM-grouped query returns no rows
  # for aluminum, and the response shape (per §4 / §10 invariant) drops the
  # commodity entirely — NOT a zero-valued row.
  result = ExposureEngineService.compute_net_exposure(session, commodity="aluminum")
  commodities_in_response = {row["commodity"] for row in result}
  assert "aluminum" not in commodities_in_response, (
      f"Retired Exposure row's commodity should NOT appear in net-exposure "
      f"response after §3.8 retirement sweep (Option A). Got: {result}"
  )
  ```
- [ ] **Test:** A retired `Exposure` row from a soft-deleted order is NOT re-created or un-retired by a subsequent `reconcile_from_orders` while the source order is still soft-deleted (idempotent retirement).
- [ ] **Test (reversibility):** If `Order.deleted_at` is cleared (un-deleted), the next `reconcile_from_orders` produces a live `Exposure` row for that order again — either by un-retiring (clearing `is_deleted` / `deleted_at`) or by creating a fresh row, depending on the implementation choice documented in §9.
- [ ] **Test (deferred fallback — only emit if Option B was selected per §3.8):** Pre-existing `Exposure` row whose source `Order` is soft-deleted — NOT covered in this PR; reproducing fixture documented (Exposure row count remains positive after Order soft-delete) so the follow-up issue has a starting point. Skip this test entirely if Option A was implemented.

### 6.7 Query plan inspection (Postgres-only, optional)

- [ ] **Test (Postgres, skip on SQLite):** `EXPLAIN` the query produced by `compute_global_snapshot` and assert the filter on `HedgeContract.status` and `deleted_at` appears in the plan. Belt-and-suspenders against future refactors silently dropping the filter.

---

## 7. Test coverage required

| Test file | Status | Covers |
|---|---|---|
| `backend/tests/test_exposures_commercial.py` | EXTEND | §6.1, §6.3 commercial-side cases |
| `backend/tests/test_exposures_global.py` | EXTEND | §6.2, §6.3, §6.4 global-side cases (incl. §3.5 linked_by_contract dual-filter) |
| `backend/tests/test_exposure_engine.py` | EXTEND | §6.6 reconcile lifecycle filter (§3.7) + retirement of pre-existing Exposure rows (§3.8) + §6.3.6 `_get_linked_qty_map` parity (§3.9) |
| `backend/tests/test_compute_net_exposure.py` | NEW | §6.3.7 `compute_net_exposure` residual-subtraction rewrite (§3.10) — partly-linked Codex case, response-shape invariant (zero-residual group MUST be skipped), cross-endpoint parity vs `compute_global_snapshot` |
| `backend/tests/test_soft_delete.py` | EXTEND | overall lifecycle behavior — soft-delete an entity, assert all snapshots reflect immediately |
| `backend/tests/test_validate_residuals.py` (NEW or extend if exists) | NEW/EXTEND | §6.5 false-409 prevention |

For each numeric fixture, place the §2.5 formula derivation in a comment next to the expected output. Example:

```python
# Per §2.5: Global Active = Commercial Active + Hedge Short live (unlinked).
# SO Aluminum 100 (live) + Hedge Short Aluminum 80 (active, unlinked):
#   Aluminum.global_active = 100 + 80 = 180
expected_aluminum_global_active = Decimal("180")
```

---

## 8. Critical sequencing

- **Upstream:** PR #15 (Decimal), #13 (UoW), #14 (Classification), #16 (Commodity) all MERGED. Verify by `git log --oneline origin/main | head -10`.
- **Coordinate with PR-4 (linkage hardening):** PR-4 modifies `reconcile_from_orders` to hard-fail on negative residuals; this PR adds `Order.deleted_at IS NULL` filter to the same function. See §3.7. Either merge order works; coordinate with orchestrator.
- **Coordinate with PR-7 (audit emission):** PR-7 wires audit on routes that read snapshots; this PR doesn't touch routes. No conflict.
- **Coordinate with PR-8 (P&L price evidence):** PR-8 changes `compute_deal_pnl` and `DealPNLSnapshot`. Different surface; no conflict.

---

## 9. PR shape

**Title:** `fix(audit-a1): PR-5 — snapshot lifecycle filters (J-A1-OPUS-02)`

**Body skeleton:**

```markdown
## Summary

Add lifecycle filters to commercial and global exposure snapshot queries
so soft-deleted orders, settled/cancelled/deleted hedges, and linkages
from dead hedges no longer inflate or distort live risk KPIs. Phase A1
jury Tier 1 fix per finding J-A1-OPUS-02 (constitutional §2.1, §2.5,
§2.7).

## [BEHAVIOR_SHIFT]
After this PR, settling a hedge that has linkages to a sales order
visibly increases that commodity's commercial exposure (linkage no
longer reduces). This is correct — the order is no longer hedged once
the hedge is settled. Operators may need a release note.

## Files changed
- Services: exposure_service.py (lifecycle filters in
  compute_commercial_snapshot, compute_global_snapshot,
  _linked_by_order_subquery, linked_by_contract subquery
  [now with dual HedgeContract + Order filter per §3.5],
  _validate_residuals_non_negative)
- Services: exposure_engine.py (lifecycle filter in
  reconcile_from_orders' Order query — coordinated with PR-4 — AND
  retirement sweep for pre-existing Exposure rows whose source Order
  was soft-deleted, per §3.8 Option A; dual-filter on
  _get_linked_qty_map at exposure_engine.py:60 per §3.9; hedge-side
  aggregation in compute_net_exposure at exposure_engine.py:199-215
  switched from whole-contract `NOT IN` exclusion to residual
  subtraction (`quantity_mt - SUM(live linkages)` via outerjoin +
  coalesce) per §3.10 — matching compute_global_snapshot's per-contract
  residual formula)
- Tests: test_exposures_commercial.py, test_exposures_global.py,
  test_exposure_engine.py, test_soft_delete.py, test_validate_residuals.py

## §3.8 Exposure retirement strategy
- Strategy chosen: **Option A** (preferred — soft-delete symmetric to
  upstream: `Exposure.is_deleted = True`, `Exposure.deleted_at = now()`).
  Fallbacks (b) zeroing + status=cancelled and (c) hard delete were NOT
  required.
- `compute_net_exposure` consumer audited and updated to filter
  `Exposure.is_deleted.is_(False)` on the retirement path.
- Reversibility behavior on `Order.deleted_at` clear: <un-retire OR
  fresh-row — fill in at execution time>.
- If Option B (deferral) was unavoidable, document the scope blocker
  here and link the follow-up issue covering the retirement sweep +
  `compute_net_exposure` lifecycle alignment.

## Acceptance evidence
- All §6 test cases pass with constitutional formulas in fixture
  comments
- §6.3.5 dual-filter test demonstrates a live hedge linked to a
  soft-deleted order reappears in /exposures/global with FULL residual
  (Codex P1 catch closed)
- §6.6 retirement tests demonstrate pre-existing Exposure rows are
  retired when their source Order is soft-deleted, and
  compute_net_exposure no longer counts them (Codex P2 catch closed)
- §6.3.6 demonstrates _get_linked_qty_map dual-filter: settling or
  soft-deleting a linked hedge causes the next reconcile to restore
  the order's full open_tons (Codex P1 catch §3.9 closed)
- §6.3.7 demonstrates compute_net_exposure parity with the global
  snapshot: a live hedge linked to a soft-deleted order appears in
  /exposures/net with full residual, matching /exposures/global
  (Codex P1 catch §3.10 closed)
- Multi-commodity isolation (post-#16) preserved
- No regression in PR-15/-13/-14/-16 test suites
- Optional EXPLAIN plan test on Postgres confirms filters appear in
  query plans

## Out of scope
- Exposure.is_deleted reconcile semantics (issue #12, deferred)
- DealLink soft-deleted Deal lifecycle (issue #11, deferred)
- Audit emission (PR-7)
- P&L price evidence (PR-8)

## Closes
J-A1-OPUS-02.
```

---

## 10. Constraints — what NOT to do

- DO NOT remove the `deleted_at` columns from `Order` / `HedgeContract` (no schema change in this PR)
- DO NOT change snapshot return shape — frontend consumes it (per #16 contract)
- DO NOT change Decimal substrate (PR-15 preserved)
- DO NOT call `session.commit()` from any service (PR-13 boundary preserved)
- DO NOT touch `Exposure.is_deleted` filtering for the J-A1-OPUS-08 duplicate-source-snapshot semantics — that remains issue #12 territory, latent and out of scope. **The §3.8 retirement is a separate, narrowly-scoped write to `Exposure.is_deleted` / `deleted_at` for rows whose source `Order` was soft-deleted** — that IS in scope per §3.8 because it closes J-A1-OPUS-02 on the reconcile path. Keep the two concerns separate: §3.8 only touches rows whose `Order.deleted_at IS NOT NULL`; do not generalize to other deletion paths in this PR.
- DO NOT touch `DealLink` lifecycle — issue #11 territory
- DO NOT touch hedge classification invariant — PR-14 in main, preserved by FK and CHECK
- DO NOT add audit emission — PR-7 territory
- DO NOT use `Order.deleted_at == False` or `== None` — both produce wrong SQL on a `DateTime | None` column; use `Order.deleted_at.is_(None)` exclusively
- DO NOT use `--no-verify` on git hooks; no force-push (except `--force-with-lease` after Codex-approved rebase if needed); no auto-merge
- DO NOT auto-merge — Codex review mandatory (Codex outranks CI green)
- DO NOT change `compute_net_exposure`'s return shape, net-tons sign convention, or commodity grouping in §3.10 — the §3.10 rewrite changes the AGGREGATION FORMULA on the hedge side (whole-contract `NOT IN` → residual subtraction grouped by `(commodity, classification)`), but the response dict shape, sign convention, and per-commodity grouping are preserved verbatim
- DO NOT keep the whole-contract `NOT IN` semantic on the hedge side of `compute_net_exposure` — `~HedgeContract.id.in_(linked_contract_ids)` diverges from `compute_global_snapshot` for partly-linked hedges (a 100 MT hedge with a 40 MT live-order linkage must contribute 60 MT, not 0). Replace the EXCLUSION with SUBTRACTION per §3.10; do NOT preserve the `~ ... .in_(...)` filter
- DO NOT split the dual-filter (live hedge AND live order) predicate at sites where it is load-bearing per §3.5, §3.9, and §3.10. At those sites the live-hedge clause (`HedgeContract.deleted_at IS NULL` AND `status IN (active, partially_settled)`) and the live-order clause (`Order.deleted_at IS NULL`) MUST appear together, because no upstream consumer narrows the missing side. (`_linked_by_order_subquery` per §3.4 is documented as a belt-and-suspenders site where the consumer — `compute_commercial_snapshot` — already applies `Order.deleted_at IS NULL` upstream per §3.1; there the order-side filter is optional and intentionally omitted to keep the subquery focused on the hedge-side lifecycle. Do NOT silently promote §3.4 to a dual-filter site.)
- DO NOT change `_get_linked_qty_map`'s key type from `str` — `reconcile_from_orders` calls `linked_map.get(str(order.id), ...)` at `exposure_engine.py:77` and a UUID-keyed map silently produces 100% lookup misses, inflating `Exposure.open_tons` for every linked order. Keys MUST be `str(row.order_id)`; the return type stays `dict[str, Decimal]`
- DO NOT include zero-residual commodity rows in `compute_net_exposure`'s response — even though the SUM grouped query returns one row per `(commodity, classification)`, the downstream caller treats the absence of a commodity entry as "no exposure"; emitting a zero-valued row inflates the response shape vs the §4 / §10 invariant. The §3.10 Python-side `if row.total_qty == 0: continue` guard MUST be present in the loop. Do NOT replace it with a SQL `HAVING` clause — Option (a) is rejected per §3.10's decision rationale

---

## 11. Workflow

1. `git fetch origin && git checkout -b audit-a1/snapshot-lifecycle origin/main`
2. Verify upstream: `git log --oneline origin/main | head -10` shows #15, #13, #14, #16, #17 merge commits
3. Read jury §3 J-A1-OPUS-02 + Opus F-A1-OPUS-06 in full
4. Read current state of the 5 helper/snapshot methods in `exposure_service.py`; note line numbers for your own reference
5. Implement (in order — DO NOT skip the engine-side steps; without §3.8/§3.9/§3.10 the J-A1-OPUS-02 lifecycle invariant stays open and `/exposures/net` diverges from `/exposures/global`):
   - **Import prerequisite (per §3.0):**
     - `exposure_service.py`: add `HedgeContractStatus` to the module-scope `from app.models.contracts import ...` line (current line 18).
     - `exposure_engine.py`: add `HedgeContractStatus` to the module-scope `from app.models.contracts import ...` line (alongside the existing `app.models.*` imports at the top of the file); **remove** the function-scope import currently inside `compute_net_exposure` (current ~line 155 — the module-scope version covers it cleanly for both `_get_linked_qty_map` and `compute_net_exposure`).
     - Verify with `grep -n "from app.models.contracts" backend/app/services/exposure_service.py backend/app/services/exposure_engine.py` first; if `HedgeContractStatus` is already at module scope in either file, the ADD step is a no-op for that file (but the function-scope removal in `exposure_engine.py` still applies).
     - **Failure mode if skipped:** `_get_linked_qty_map` (§3.9) and `compute_net_exposure` (§3.10) raise `NameError` on first linked-order reconcile / net-exposure call — `_get_linked_qty_map` is a separate `@staticmethod` whose name-resolution scope does NOT share `compute_net_exposure`'s function-local imports. §3.3 / §3.5 also raise `NameError` at the first affected `exposure_service.py` endpoint without the module-scope add there.
   - `_linked_by_order_subquery` filter (§3.4) — `exposure_service.py`
   - `compute_commercial_snapshot` filters (§3.1) — `exposure_service.py`
   - `compute_global_snapshot` filters: orders, hedges, `linked_by_contract` subquery (§3.2, §3.3, §3.5) — `exposure_service.py`
   - `_validate_residuals_non_negative` filter (§3.6) — `exposure_service.py`
   - `reconcile_from_orders` filter on `Order` (§3.7) — `exposure_engine.py`
   - **`reconcile_from_orders` retirement of pre-existing `Exposure` rows for soft-deleted source orders (§3.8)** — `exposure_engine.py` — **REQUIRED**, do not skip; without this, J-A1-OPUS-02 stays open and §6.6 retirement test fails (the snapshot filters alone do NOT retire the derived state)
   - **`_get_linked_qty_map` dual-filter (live hedge AND live order) + string-key fix (§3.9)** — `exposure_engine.py` — **REQUIRED** for reconcile/snapshot parity (§6.3.6); a UUID-keyed map silently produces 100% lookup misses per §10
   - **`compute_net_exposure` residual-subtraction rewrite (whole-contract `NOT IN` → SUM grouped + zero-residual `continue` guard) (§3.10)** — `exposure_engine.py` — **REQUIRED** for net-exposure/global parity (§6.3.7); without this, partly-linked hedges contribute 0 instead of (qty − linked) and the §6.3.7 cross-endpoint parity test fails
   - Tests covering §6.1–§6.7, plus §6.3.5, §6.3.6, §6.3.7
6. Run targeted tests between each step:
   - `pytest backend/tests/test_exposures_commercial.py -v` — covers §6.1, §6.3 commercial-side
   - `pytest backend/tests/test_exposures_global.py -v` — covers §6.2, §6.3, §6.4 global-side (incl. §3.5 linked_by_contract)
   - `pytest backend/tests/test_exposure_engine.py -v` — covers §6.6 reconcile lifecycle filter + retirement (§3.7, §3.8) and §6.3.6 `_get_linked_qty_map` parity (§3.9)
   - `pytest backend/tests/test_compute_net_exposure.py -v` (NEW file per §7) — covers §6.3.7 net-vs-global parity (§3.10), incl. partly-linked Codex case + cross-endpoint parity assertion
   - `pytest backend/tests/test_validate_residuals.py -v` (NEW or extend) — covers §6.5 false-409 prevention
   - `pytest backend/tests/test_soft_delete.py -v` — overall lifecycle behavior across all snapshots
7. Run full backend test suite to verify no regression: `pytest backend/tests/ -v` (target: ≥ 688 passed, no new flakes)
8. `git push -u origin audit-a1/snapshot-lifecycle`
9. `gh pr create --base main --title "<§9 title>" --body-file <body>`
10. **STOP. Wait for Codex review.** Codex outranks CI green.
11. Address Codex feedback in new commits (no force-push, no amend)

---

## 12. Final report shape

When complete, report:
- Branch + PR URL + final SHA
- Files touched
- Behavior shift evidence: a test that demonstrates the increased commercial after settling a linked hedge (§6.3)
- §6.3.5 evidence: the live-hedge-with-soft-deleted-order-linkage test passes (Codex P1 closed)
- §3.8 retirement strategy chosen (Option A / B / fallback (b) / (c)) with one-line justification, plus the `compute_net_exposure` consumer audit outcome
- §6.6 retirement test evidence: the pre-existing `Exposure` row for a soft-deleted order is retired and `compute_net_exposure` no longer counts it (Codex P2 closed)
- §6.3.6 evidence: the settled-hedge / soft-deleted-hedge reconcile parity tests pass — `Exposure.open_tons` correctly returns to `order_qty` after `_get_linked_qty_map` drops dead-hedge linkages (Codex P1 §3.9 closed)
- §6.3.7 evidence: the `compute_net_exposure` net-vs-global parity test passes — a live hedge linked to a soft-deleted order appears with full residual in `/exposures/net`, matching `/exposures/global`'s post-§3.5 behavior (Codex P1 §3.10 closed). Includes the partly-linked Codex case (100 MT hedge + 40 MT live linkage → 60 MT residual contribution, NOT 0) AND the cross-endpoint parity assertion that net's hedge contribution equals global's per-contract residual sum byte-for-byte
- Reversibility behavior chosen for §3.8 (un-retire vs fresh row) when `Order.deleted_at` is cleared
- Test counts (new, total, vs pre-PR baseline)
- Coordination outcome with PR-4 if its merge happened mid-implementation
- Codex verdict
- Any `[BEHAVIOR_SHIFT]` notes beyond §6.3 / §6.3.5 the executor surfaces during implementation

Under 600 words.

Boa caça.
