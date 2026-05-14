# Cluster 1 Remediation Dispatch — PR-CL1-1 — DealEngine Live-Linked Traversal

**Cluster:** 1 — A1 follow-up (deal-engine + exposure + scenario boundaries)
**Wave:** PR-CL1-1 (1 of 4)
**Authoring date:** 2026-05-13
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `ea08d9868` post-PR-#73, the Cluster 1 findings + verdict)
**Required branch:** `audit-followup/cluster-1-deal-engine-live-traversal`
**Source verdict:** `docs/audits/2026-05-13-cluster-1-jury-verdict.md` §J-CL1-01 + §PR-CL1-1 wave entry

## 1. Objective

Close **J-CL1-01** (Tier 1 / Blocking) — DealEngine consumes archived linked Orders and HedgeContracts as live economics today. Three service methods (`compute_deal_pnl`, `compute_pnl_breakdown`, `_recompute_tons`) traverse `DealLink` rows and read the linked Order / HedgeContract via `session.get(...)` without filtering `deleted_at`. Archive routes for Orders (`/orders/{id}/archive`) and HedgeContracts (`/contracts/hedge/{id}/archive`) are already live, so the failure is reachable today: an archived linked entity still contributes to deal tons and P&L while exposure has retired it.

The fix is narrow: at every linked-entity read inside the three methods, skip rows where `deleted_at is not None`. No model migration. No new endpoint. No change to `DealLink` lifecycle (that is wave PR-CL1-4's scope).

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`.
- Do **not** add a `DealLink.is_deleted` column or any migration. That decision belongs to wave PR-CL1-4 (J-CL1-02). Single alembic head must remain `043_a5_audit_payload_input`.
- Do **not** widen scope to wave PR-CL1-2 (snapshot reuse) — the `unprovable_errors` candidate-probe branch and `_compute_inputs_hash` shape are out of scope here even though both live in the same file.
- Do **not** widen scope to wave PR-CL1-3 (scenario / shared exposure primitive). Scenario reads its own primitives and is fixed in its own wave.
- Do **not** alter the soft-delete contract for `Order` or `HedgeContract`. Those models already expose `deleted_at`; only the DealEngine traversal side changes.
- Do **not** change the public response shape of `compute_deal_pnl`, `compute_pnl_breakdown`, or `_recompute_tons` beyond what is implied by skipping archived rows. The integer counts and Decimal aggregates simply exclude archived entities.
- Do **not** silently produce a zero P&L for a deal whose only links are now archived. If the archive sweep removes every linked entity, propagate the existing "no linked entities" code path (or hard-fail consistent with the empty-link contract); do not coerce the result to a fake zero.

Live economics across the system must remain coherent: if exposure has retired an Order, deal-level reads must agree.

## 3. Findings and Evidence

Verified at HEAD `ea08d9868`.

### Linked-entity reads inside DealEngine

- `backend/app/services/deal_engine.py:559-611` — `compute_deal_pnl` iterates `deal.links`, resolves each via `session.get(Order, link.linked_id)` / `session.get(HedgeContract, link.linked_id)` and uses the row's economics (price type, quantity, average price, fixed price) directly. No `deleted_at` filter.
- `backend/app/services/deal_engine.py:918-957` — `compute_pnl_breakdown` repeats the same traversal shape, building per-link breakdown rows.
- `backend/app/services/deal_engine.py:1036` — second linked-entity read inside `compute_pnl_breakdown` (the hedge breakdown path).
- `backend/app/services/deal_engine.py:1245-1269` — `_recompute_tons` iterates links and accumulates `total_physical_tons` and `total_hedge_tons` from raw `Order.quantity_mt` / `HedgeContract.quantity_mt`. No lifecycle filter.

### Lifecycle source of truth

- `backend/app/models/orders.py` — `Order.deleted_at: datetime | None` (set by `/orders/{id}/archive` route).
- `backend/app/models/contracts.py` — `HedgeContract.deleted_at: datetime | None` (set by `/contracts/hedge/{id}/archive` route).
- `backend/app/services/exposure_engine.py:122` — exposure reconcile already reads only `Order.deleted_at.is_(None)`.
- `backend/app/services/exposure_engine.py:218-235` — exposure retirement sweep retires `Exposure` rows whose source `Order` is archived.

The exposure layer and the deal-engine layer must converge on a single live-set definition: an Order or HedgeContract with `deleted_at is not None` is **not** part of the deal's live economics.

### Archive routes that produce the failure

- `backend/app/api/routes/orders.py:129-144` — `archive_order` sets `Order.deleted_at = now_utc()` and emits a signed audit event.
- `backend/app/api/routes/contracts.py:89-104` — `archive_hedge_contract` sets `HedgeContract.deleted_at = now_utc()` and emits a signed audit event.

Both are live in production; the failure mode of J-CL1-01 is reachable today, not theoretical.

## 4. Required Implementation Boundary

### 4.1 Pattern: filter at every linked-entity read

In each of the three methods, every `session.get(Order, link.linked_id)` and `session.get(HedgeContract, link.linked_id)` site must skip the link when the resolved row has `deleted_at is not None`. The skip is a `continue` in the iteration; it must not abort the whole computation.

**`DealLinkedType` has four variants, not two** (verified at `backend/app/models/deal.py:119-123`): `sales_order`, `purchase_order`, `hedge`, `contract`. The Order side is the **tuple** `(DealLinkedType.sales_order, DealLinkedType.purchase_order)`; the HedgeContract side is the **tuple** `(DealLinkedType.hedge, DealLinkedType.contract)`. Every existing site in `deal_engine.py` that branches on `link.linked_type` uses these two tuples (verified across `:213`, `:219`, `:332`, `:580-581`, `:590-591`, `:751-752`, `:773-774`, `:925-926`, `:935-936`, `:1033-1034`). Following this dispatch must preserve that convention; using a fictional `DealLinkedType.order` would `AttributeError` and using `DealLinkedType.hedge` alone would silently skip every `contract`-aliased link.

The canonical shape (sketch):

```python
for link in deal.links:
    if link.linked_type in (DealLinkedType.sales_order, DealLinkedType.purchase_order):
        entity = session.get(Order, link.linked_id)
        if entity is None or entity.deleted_at is not None:
            continue
        # ... use entity.price_type, entity.quantity_mt, etc.
    elif link.linked_type in (DealLinkedType.hedge, DealLinkedType.contract):
        entity = session.get(HedgeContract, link.linked_id)
        if entity is None or entity.deleted_at is not None:
            continue
        # ... use entity.quantity_mt, entity.fixed_price_value, etc.
```

If the existing call site already classifies the link via a helper (e.g. `_order_value`, `_recompute_tons` may not need an explicit `linked_type` check because they iterate a typed sub-list), preserve that helper and add only the `entity.deleted_at is not None` predicate at the resolved-entity boundary. Do **not** introduce a new `linked_type` switch where one does not already exist.

The existing `if entity is None: ...` handler (where present) stays; the only addition is the `or entity.deleted_at is not None` predicate.

### 4.2 Method-by-method changes

- **`compute_deal_pnl` (`deal_engine.py:559-611`)**: filter at both the Order and the HedgeContract traversal. If the archived entity was the source of a variable-price quote requirement, the price lookup for that link is also skipped (the link is gone from the computation entirely). The `unprovable_errors` aggregation continues to apply to the **remaining live** entities only — this is the natural composition and is not in tension with wave PR-CL1-2's scope.
- **`compute_pnl_breakdown` (`deal_engine.py:918-957` and `:1036`)**: filter at both sites. Archived links produce no breakdown row.
- **`_recompute_tons` (`deal_engine.py:1245-1269`)**: filter before adding to `total_physical_tons` / `total_hedge_tons`. Archived links contribute zero tons.

### 4.3 Behavior when every link is archived

If after filtering, no live links remain, `compute_deal_pnl` and `compute_pnl_breakdown` follow the pre-existing "no linked entities" path (whichever it is — currently the deal degenerates to zero P&L / empty breakdown). Do **not** introduce a new error condition. `_recompute_tons` produces `total_physical_tons = 0` and `total_hedge_tons = 0`. This is a real economic state (the deal has no live exposure) and is consistent with what `ExposureEngineService.reconcile_from_orders` already reports for the same archived Orders.

### 4.4 Logging / observability (optional, narrow)

A single `logger.debug("deal_engine_skipped_archived_link", deal_id=..., link_id=..., linked_type=...)` at each filter site is acceptable. Do **not** raise a warning or surface an operator-visible message; the live-set convergence is the contract.

## 5. Constitutional Rules

This wave is governed by:

- `docs/governance.md` §2.1 — Economic primitives integrity. Exposure and deal P&L must agree on the live set.
- `docs/governance.md` §2.7 — Audit reconstructability. An operator must be able to reconstruct a single canonical economic state across dashboards.

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes J-CL1-01 iff every item below is true.

### 6.1 Code

- [ ] `backend/app/services/deal_engine.py` — `compute_deal_pnl` skips links whose resolved Order or HedgeContract has `deleted_at is not None`.
- [ ] `backend/app/services/deal_engine.py` — `compute_pnl_breakdown` applies the same filter at both linked-entity read sites.
- [ ] `backend/app/services/deal_engine.py` — `_recompute_tons` applies the same filter before accumulating `total_physical_tons` / `total_hedge_tons`.
- [ ] No new column, no new model, no migration. `python -m alembic heads` must still print `043_a5_audit_payload_input`.
- [ ] No edit to `backend/app/models/deal.py`, no `DealLink.is_deleted` introduction.
- [ ] No edit to `backend/app/services/scenario_whatif_service.py`, `backend/app/services/exposure_service.py`, or `backend/app/services/exposure_engine.py`.
- [ ] No edit to `docs/governance.md`.

### 6.2 Sweeps

- [ ] `rg -nP "session\\.get\\((Order|HedgeContract)" backend/app/services/deal_engine.py` — every match is followed by a `deleted_at is not None` predicate (either inline or in a helper) before the entity is read.
- [ ] `rg -nP "deleted_at" backend/app/services/deal_engine.py` — at least three new sites compared to HEAD `ea08d9868`.
- [ ] `rg -nP "DealLinkedType\\.order\\b|DealLinkedType\\.hedge_contract\\b" backend/app/services/deal_engine.py backend/tests/` — returns zero matches. The enum has no `.order` or `.hedge_contract` variant; valid values are exactly `sales_order`, `purchase_order`, `hedge`, `contract` (verified at `backend/app/models/deal.py:119-123`). Any new code site that introduces a singular `.order` reference is a bug that would `AttributeError` at runtime.

## 7. Required Tests

New test file: `backend/tests/test_deal_engine_archived_link_traversal.py`. Mark every test with the fixtures already used by `test_deal_engine.py`.

1. **Archive a linked Order, recompute deal P&L** — create a Deal with two Orders linked (one variable-price, one fixed-price). Archive the variable-price Order. Call `compute_deal_pnl`. Assert the returned `DealPNLSnapshot` excludes the archived Order from its contribution and its `price_references` does not contain a quote for the archived Order's commodity (when the archived Order was the only consumer of that commodity).
2. **Archive a linked HedgeContract, recompute deal P&L** — same setup but archive a HedgeContract. Assert P&L excludes the archived hedge.
3. **Archive all links, recompute deal P&L** — assert no `PriceReferenceUnprovable` is raised solely because of the archive; the deal degenerates to the pre-existing no-link branch.
4. **Archive a linked Order, recompute breakdown** — call `compute_pnl_breakdown`. Assert the returned breakdown does not contain a row for the archived Order, and that the global aggregates exclude the archived Order's contribution.
5. **Archive a linked Order, recompute tons** — call `_recompute_tons` via the existing public path (`add_link` / `remove_link` / `update_deal_status` recomputes; pick the shape that already exercises `_recompute_tons`). Assert `Deal.total_physical_tons` and `Deal.total_hedge_tons` exclude the archived Order's quantity.
6. **Exposure / deal-P&L convergence** — full-loop test: archive an Order, run `ExposureEngineService.reconcile_from_orders`, then call `compute_deal_pnl` on a Deal linking the archived Order. Assert that the Order does not appear in either the live exposure aggregation OR the deal P&L computation. This is the institutional convergence proof.
7. **Un-archive (defensive)** — if the codebase exposes an un-archive route or a test pattern that clears `deleted_at`, add a regression test that asserts the Order returns to deal P&L when it is no longer archived. If no un-archive path exists in production code, skip this test rather than building it.

## 8. Required Verification

```powershell
# Sweep new filters
rg -nP "deleted_at" backend/app/services/deal_engine.py

# Sweep that no foreign service was touched
git diff main -- backend/app/services/scenario_whatif_service.py
git diff main -- backend/app/services/exposure_service.py
git diff main -- backend/app/services/exposure_engine.py
git diff main -- backend/app/models/deal.py
git diff main -- backend/app/models/exposure.py
git diff main -- backend/app/api/routes/

# Alembic invariant
cd backend ; python -m alembic heads ; cd ..

# Test suite
pytest -q backend/tests/test_deal_engine.py backend/tests/test_deal_engine_archived_link_traversal.py
pytest -q backend/tests

# Generated artifacts
git diff -- docs/api/openapi_v1.json frontend-svelte/src/lib/api/schema.d.ts
git diff --check

# Governance invariant
git diff main -- docs/governance.md
```

The `git diff main -- docs/governance.md` must produce zero output. The `python -m alembic heads` must print exactly one head: `043_a5_audit_payload_input`. The cross-service diffs must all be empty (this wave is scoped to `deal_engine.py` only).

## 9. Out of Scope

- Wave PR-CL1-2 (snapshot reuse hard-fail). The `unprovable_errors` branch at `deal_engine.py:657-703` is not touched here.
- Wave PR-CL1-3 (shared exposure primitive). Scenario aggregation and `ExposureService` are not touched here.
- Wave PR-CL1-4 (Deal soft-delete contract cleanup). `Deal.is_deleted` and `DealLink` lifecycle stay as today.
- New `DealLink.is_deleted` column or any migration — explicitly forbidden per §2.
- Changing the `_compute_inputs_hash` shape to include linked-entity content. That is PR-CL1-2's territory if the snapshot-reuse decision had gone the other way; it did not.
- Soft-delete writers on `Deal` itself. No new route, no archive of a Deal.
- Frontend changes. The frontend already reads from the public response of `compute_deal_pnl` / `compute_pnl_breakdown`; the response shape does not change in this wave so no frontend follow-up is required.

## 10. PR Requirements

The implementing PR title must be:

```
fix(audit-followup): close Cluster 1 PR-CL1-1 (DealEngine archived-link traversal)
```

The PR body must include:

- **Findings closed:** explicit `J-CL1-01` reference + Cluster 1 verdict citation.
- **Files changed:** inventory grouped by backend code / tests. Single-file backend change is expected (`deal_engine.py`).
- **Verification matrix:** §8 sweep results.
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-1-deal-engine-live-traversal-{sha}.json` per push.
- **Governance statement:** `docs/governance.md` diff is empty.
- **Alembic statement:** single head `043_a5_audit_payload_input`.

## 11. Workflow

1. `git checkout -b audit-followup/cluster-1-deal-engine-live-traversal` from `main @ ea08d9868`.
2. Apply §4 changes to the three methods in `deal_engine.py` in this order:
   1. `_recompute_tons` (smallest, simplest).
   2. `compute_deal_pnl` (largest, most callers).
   3. `compute_pnl_breakdown` (mirrors `compute_deal_pnl`).
3. Add `backend/tests/test_deal_engine_archived_link_traversal.py` with the 6 (or 7 if un-archive path exists) tests in §7.
4. Update existing `backend/tests/test_deal_engine.py` if and only if a previous test implicitly relied on an archived link being counted (rare; verify by reading existing fixtures before editing).
5. Run §8 verification locally; fix every pre-push hook v2 P1/P2 in place.
6. Push branch and open PR per §10.
7. Codex Connector review is the final gate. Address every Codex inline catch. **Do not merge** — Andrei merges with explicit authorization only.

## 12. Hook v2 + Codex calibration notes

- **Expected hook v2 surface area**: the diff is single-file backend with three filter sites. Hook may surface false positives around "Tipo-I fact mismatch" for the new helper / inline predicate (prescription-vs-evidence class — see `feedback_codex_companion_doc_not_yet_merged` for the FP class precedent on dispatch authoring; this is the implementation-side equivalent). Hook may also flag partial-diff blindness on test-only follow-up pushes.
- **Expected Codex catches**: missed filter at one of the three methods (e.g. `_recompute_tons` skipped while `compute_deal_pnl` filtered); a helper inadvertently used elsewhere that bypasses the filter; a `session.get(Order, ...)` introduced later in the file that doesn't follow the new pattern; the un-archive regression test missing if an un-archive path exists; the exposure / deal-P&L convergence test missing or weak; **a `DealLinkedType.order` reference (which does not exist as an enum member) introduced by following the §4.1 sketch literally without verifying enum membership** — this is the v1 dispatch error Codex caught (see PR #74 review). The valid 4-variant enum convention is `(sales_order, purchase_order)` for the Order side and `(hedge, contract)` for the HedgeContract side; the §6.2 sweep enforces it.
- **The 8-section sweep checklist from `feedback_dispatch_self_consistency` applies**: confirm §3 evidence, §4 boundary, §6 acceptance, §7 tests, §8 verification, §11 workflow all enumerate the same three methods. The three method names (`compute_deal_pnl`, `compute_pnl_breakdown`, `_recompute_tons`) must appear in every list.
- This wave is the simplest of the four Cluster 1 waves. Resist the temptation to bundle in any of PR-CL1-2 / PR-CL1-3 / PR-CL1-4 work even if it looks adjacent.
