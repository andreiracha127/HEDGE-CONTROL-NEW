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

### 3.5 Apply same lifecycle predicate to `linked_by_contract` subquery

**File:** `backend/app/services/exposure_service.py` — the inline `linked_by_contract` subquery inside `compute_global_snapshot` (~257-265 in current main).

Even though the outer query filters dead hedges out (per §3.3), this subquery is constructed BEFORE the outer filter is applied; the residual computation joins it with `HedgeContract` outerjoin, then the outer filter excludes the dead rows. So technically dead hedges' linkages are computed in the subquery but excluded later. This is fragile — a future refactor that changes the join order could re-introduce the bug.

**Defensive fix (recommended):** apply the live-hedge filter at the subquery level too, mirroring §3.4:

```python
linked_by_contract = (
    session.query(
        HedgeOrderLinkage.contract_id.label("contract_id"),
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
    .group_by(HedgeOrderLinkage.contract_id)
    .subquery()
)
```

Belt-and-suspenders: outer filter (§3.3) is the institutional invariant; subquery filter is defense-in-depth.

### 3.6 Filter `Order.deleted_at IS NULL` in `_validate_residuals_non_negative`

**File:** `backend/app/services/exposure_service.py` — `_validate_residuals_non_negative` (~45-65).

This helper validates that no order has negative residual after linkages. If it queries Order without filtering deleted_at, it could fail with a misleading 409 on a soft-deleted order whose linkages weren't cleaned up. Inspect the function body and add the filter consistent with §3.1. Do NOT skip — defense-in-depth, prevents misleading error messages.

### 3.7 Coordinate with `reconcile_from_orders` (PR-4 territory — soft scope)

**File:** `backend/app/services/exposure_engine.py` — `reconcile_from_orders` queries `Order` to derive `Exposure` rows.

PR-4 (linkage hardening, J-A1-OPUS-01) modifies this function to hard-fail on negative residuals. **Do NOT re-implement that fix here.** But the same `Order.deleted_at IS NULL` filter is needed in `reconcile_from_orders` so soft-deleted orders don't generate `Exposure` rows.

**Coordination plan:**
- If PR-4 lands first: rebase this PR on top of PR-4's reconcile changes; add the `Order.deleted_at IS NULL` filter to the order query in `reconcile_from_orders`. Verify PR-4's residual hard-fail still works on the filtered query (it should — the filter narrows the input set, doesn't change the assertion).
- If this PR lands first: PR-4 rebases on top; PR-4's residual assertion runs on the lifecycle-filtered orders.
- Either order works; the filter and the assertion are orthogonal.

Document the coordination in PR description; the orchestrator will sequence the merges to minimize rebase work.

---

## 4. Scope OUT — explicitly NOT in PR-5

- **Audit emission for the routes that consume snapshots** — PR-7 territory.
- **Reconcile residual hard-fail** — PR-4 territory; this PR only adds the lifecycle filter to reconcile's order query.
- **Decimal primitives** — PR-1 in main; preserve.
- **UoW boundary** — PR-3 in main; preserve.
- **Classification invariant** — PR-6/#14 in main; preserve.
- **Per-commodity grouping** — PR-2/#16 in main; preserve.
- **`Exposure.is_deleted` reconcile semantics (J-A1-OPUS-08)** — Tier 3 deferred; tracked as GitHub issue #12. This PR does NOT touch the `Exposure` model's own soft-delete fields; only the upstream `Order` and `HedgeContract` lifecycle filters.
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

### 6.4 Multi-commodity isolation preserved (post-#16)

- [ ] **Test:** SO Aluminum 100 + SO Copper 50 + Hedge Short Aluminum 80 (live, unlinked) + Hedge Short Copper 30 (settled) → global.Aluminum.active = 180, global.Copper.active = 50 (NOT 80; the settled Cu hedge is excluded).
  - *Formula:* `Aluminum: 100 + 80 = 180. Copper: 50 + 0 (settled) = 50.`

### 6.5 No false 409 from `_validate_residuals_non_negative` on dead orders

- [ ] **Test:** Soft-delete an order whose residual would be negative (e.g., over-linked from before lifecycle filtering). `compute_commercial_snapshot()` does NOT raise 409 — the dead order is filtered out before validation.

### 6.6 Reconcile (coordinate with PR-4)

- [ ] **Test:** Soft-deleted variable-price order does NOT cause `reconcile_from_orders` to create or update an `Exposure` row.
- [ ] **Test:** Live order produces `Exposure` row as before; lifecycle filter does not affect non-deleted path.

### 6.7 Query plan inspection (Postgres-only, optional)

- [ ] **Test (Postgres, skip on SQLite):** `EXPLAIN` the query produced by `compute_global_snapshot` and assert the filter on `HedgeContract.status` and `deleted_at` appears in the plan. Belt-and-suspenders against future refactors silently dropping the filter.

---

## 7. Test coverage required

| Test file | Status | Covers |
|---|---|---|
| `backend/tests/test_exposures_commercial.py` | EXTEND | §6.1, §6.3 commercial-side cases |
| `backend/tests/test_exposures_global.py` | EXTEND | §6.2, §6.3, §6.4 global-side cases |
| `backend/tests/test_exposure_engine.py` | EXTEND | §6.6 reconcile lifecycle filter |
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
  _linked_by_order_subquery, linked_by_contract subquery,
  _validate_residuals_non_negative)
- Services: exposure_engine.py (lifecycle filter in
  reconcile_from_orders' Order query — coordinated with PR-4)
- Tests: test_exposures_commercial.py, test_exposures_global.py,
  test_exposure_engine.py, test_soft_delete.py, test_validate_residuals.py

## Acceptance evidence
- All §6 test cases pass with constitutional formulas in fixture
  comments
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
- DO NOT touch `Exposure.is_deleted` filtering — that's J-A1-OPUS-08 issue #12 territory, latent and out of scope
- DO NOT touch `DealLink` lifecycle — issue #11 territory
- DO NOT touch hedge classification invariant — PR-14 in main, preserved by FK and CHECK
- DO NOT add audit emission — PR-7 territory
- DO NOT use `Order.deleted_at == False` or `== None` — both produce wrong SQL on a `DateTime | None` column; use `Order.deleted_at.is_(None)` exclusively
- DO NOT use `--no-verify` on git hooks; no force-push (except `--force-with-lease` after Codex-approved rebase if needed); no auto-merge
- DO NOT auto-merge — Codex review mandatory (Codex outranks CI green)

---

## 11. Workflow

1. `git fetch origin && git checkout -b audit-a1/snapshot-lifecycle origin/main`
2. Verify upstream: `git log --oneline origin/main | head -10` shows #15, #13, #14, #16, #17 merge commits
3. Read jury §3 J-A1-OPUS-02 + Opus F-A1-OPUS-06 in full
4. Read current state of the 5 helper/snapshot methods in `exposure_service.py`; note line numbers for your own reference
5. Implement: `_linked_by_order_subquery` filter → `compute_commercial_snapshot` filters → `compute_global_snapshot` filters (orders + hedges + linked_by_contract) → `_validate_residuals_non_negative` filter → `reconcile_from_orders` filter → tests
6. Run targeted tests between each step:
   - `pytest backend/tests/test_exposures_commercial.py -v`
   - `pytest backend/tests/test_exposures_global.py -v`
   - `pytest backend/tests/test_exposure_engine.py -v`
   - `pytest backend/tests/test_soft_delete.py -v`
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
- Behavior shift evidence: a test that demonstrates the increased commercial after settling a linked hedge
- Test counts (new, total, vs pre-PR baseline)
- Coordination outcome with PR-4 if its merge happened mid-implementation
- Codex verdict
- Any `[BEHAVIOR_SHIFT]` notes beyond §6.3 the executor surfaces during implementation

Under 600 words.

Boa caça.
