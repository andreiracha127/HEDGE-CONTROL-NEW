# Phase A1 — PR #4 Dispatch — Linkage Hardening

**Wave:** 2
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-06
**Findings covered:** J-A1-03 (Tier 1) + J-A1-OPUS-01 (Tier 1) + J-A1-OPUS-03 (Tier 1)
**Branch name:** `audit-a1/linkage-hardening`
**Base:** `main` (latest, post #15 Decimal + #13 UoW + ideally also #14 Classification + #16 Commodity)
**Upstream deps satisfied:** PR #15 (Decimal substrate) MERGED; PR #13 (UoW boundary) MERGED.

---

## 1. Mission

Harden `LinkageService.create` and `ExposureEngineService.reconcile_from_orders` so that **over-allocation cannot be committed** under any concurrency scenario, **direction-mismatched** hedge/order pairs are rejected by construction, and the reconcile path **hard-fails** instead of silently clamping a negative residual to zero.

This PR bundles three constitutional Tier 1 findings on the same surface (linkage / reconcile) into one coordinated remediation. Splitting them produces churn — the mechanisms interact.

**Persona:** Senior engineer hardening primitives. Constitution §2.4 (linkage reduces commercial+global; unlinked affects global only — and "by construction") and §2.6 (`Exposure would be over-allocated` is a hard-fail). "Almost atomic" is not atomic. "Almost direction-correct" is direction-incorrect. "Almost zero residual" is hidden over-allocation.

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-06-phase-a1-jury-verdict.md`** — sections §2 J-A1-03, §3 J-A1-OPUS-01, §3 J-A1-OPUS-03. Read in full. Source of truth for findings.
- **`docs/governance.md`** — §2.3 (classification absolute), §2.4 (linkage construction), §2.6 (hard-fail in over-allocation, no silent fallback).
- **`docs/audits/2026-05-06-phase-a1-findings-opus.md`** — F-A1-OPUS-01, F-A1-OPUS-03, F-A1-OPUS-04, F-A1-OPUS-07.
- **`docs/audits/2026-05-06-phase-a1-findings-gemini.md`** — F-A1-GEMINI-04 (TOCTOU convergent).
- **Code currently in main (read these before writing):**
  - `backend/app/services/linkage_service.py:18-109` — current `LinkageService.create` (Decimal-aware after PR-1; flushes per PR-3)
  - `backend/app/services/exposure_engine.py:73-81` — current clamp logic to remove
  - `backend/app/services/deal_engine.py:151-219` — existing `_validate_hedge_direction` pattern at deal level (reuse the rules, not the function — different aggregate)
  - `backend/app/models/linkages.py:12-29` — `HedgeOrderLinkage` schema (no commodity column today; jury implies #16 may add commodity validation in this service — see §3.4 below)
  - `backend/app/api/dependencies/uow.py:9-28` — `unit_of_work` context manager (commits + audit atomic boundary; do NOT call `session.commit()` from service code — PR-3 already enforced this)

---

## 3. Scope IN

### 3.1 Hard-fail in `reconcile_from_orders` over-allocation (J-A1-OPUS-01)

**File:** `backend/app/services/exposure_engine.py` (current line range ~73-81; verify by grep at coding time — PR-15 may have shifted lines).

**Current behavior (the bug):**

```python
hedged_qty = linked_map.get(str(order.id), 0.0)
open_qty = max(float(order.quantity_mt) - hedged_qty, 0.0)  # clamp
...
elif open_qty <= 0:
    exp_status = ExposureStatus.fully_hedged
```

`max(..., 0)` silently maps negative residual → 0 → fully_hedged. The over-allocation is hidden, not flagged.

**Fix directive:**

Replace the clamp with an **explicit residual assertion** before status calculation. Assertion fires whenever `linked > order.quantity_mt` (negative residual). Behavior on assertion failure: raise a domain exception that propagates up (`ExposureOverAllocationError` or equivalent — read existing exception hierarchy in `backend/app/services/` before inventing one). Reconcile must NOT persist a snapshot in this case.

Note: with PR-1 in main, `order.quantity_mt` is now `Decimal`, and the existing code may already use `quantize_mt` in places. Use Decimal arithmetic + explicit comparison; do NOT cast to float.

### 3.2 Direction validation in `LinkageService.create` (J-A1-OPUS-03)

**File:** `backend/app/services/linkage_service.py:22-78` (verify line range by grep — current `create` method body).

**Current behavior (the bug):**

```python
def create(session, order_id, contract_id, quantity_mt):
    order = session.get(Order, order_id) ...
    contract = session.get(HedgeContract, contract_id) ...
    # capacity checks
    # NO direction check
    linkage = HedgeOrderLinkage(...)
    session.add(linkage); session.flush()
```

**Fix directive:**

Insert direction validation **between the get-and-capacity checks**. Rule (per economics + constitution §2.3 + §2.4):

| Order side | Hedge classification |
|---|---|
| `OrderType.sales` (SO) | `HedgeClassification.short` (sell-forward hedges sales price exposure) |
| `OrderType.purchase` (PO) | `HedgeClassification.long` (buy-forward hedges purchase price exposure) |

Other pairings → `HTTPException(422, detail="Linkage direction mismatch: ...")` with explicit message naming the offending pair.

Pattern reference: `DealEngineService._validate_hedge_direction` at `deal_engine.py:151-219` already implements this rule for `DealLink` aggregate. Read that function, extract the rule, apply to the `HedgeOrderLinkage` aggregate. Do NOT call `_validate_hedge_direction` from linkage service — different aggregate; copying the rule is correct.

Additional check: per `_validate_hedge_direction` at `deal_engine.py:201-207`, fixed-price orders must NOT be hedged ("Cannot hedge a fixed-price order"). Apply the same rejection at linkage level — `LinkageService.create` should refuse to link a fixed-price order regardless of direction match.

### 3.3 TOCTOU atomicity in `LinkageService.create` (J-A1-03)

**File:** `backend/app/services/linkage_service.py:22-78`.

**Current behavior (the bug):**

```python
order_linked_qty = session.query(... sum(...)).filter(order_id=order_id).scalar()
contract_linked_qty = session.query(... sum(...)).filter(contract_id=contract_id).scalar()
# capacity checks
# NO lock between read and INSERT — concurrent transactions both see the same available capacity
linkage = HedgeOrderLinkage(...)
session.add(linkage); session.flush()
```

Two concurrent operators creating linkages for the same `(order_id, contract_id)` can both pass the capacity check and both flush; commit is at route level (`unit_of_work`), so both commits succeed — over-allocation persisted.

**Fix directive — three-layer defense (choose at minimum two, ideally all three):**

**Layer 1 (REQUIRED) — Row-level lock on the constraining rows.**

Before reading aggregates, acquire `SELECT ... FOR UPDATE` on the `Order` and `HedgeContract` rows that constrain the capacity:

```python
order = (
    session.query(Order)
    .filter(Order.id == order_id)
    .with_for_update()
    .one_or_none()
)
contract = (
    session.query(HedgeContract)
    .filter(HedgeContract.id == contract_id)
    .with_for_update()
    .one_or_none()
)
```

This serializes concurrent linkage creates against the same order/contract pair. Read jury §2 J-A1-03 for the mechanism analysis.

**Layer 2 (REQUIRED) — DB-level invariant.**

Add a deferred check or trigger that enforces `SUM(quantity_mt) WHERE order_id = X <= orders.quantity_mt[X]` and the analogous for contracts. Concrete options:

- (a) Trigger on `INSERT/UPDATE` of `hedge_order_linkages` that re-aggregates and rejects on violation
- (b) Materialized allocation ledger (separate table) with a CHECK constraint that mirrors the rule
- (c) `EXCLUDE` constraint with a custom operator

Option (a) is the most pragmatic for SQL-Alchemy + Postgres. Option (b) is more robust but larger scope. Choose and document in PR description.

**Layer 3 (OPTIONAL but recommended) — Postgres advisory lock per `(order_id, contract_id)` pair.**

`SELECT pg_advisory_xact_lock(hashtext('linkage:' || order_id || ':' || contract_id))` at the start of `create()`. Provides cross-transaction serialization without blocking unrelated linkages. Cheap.

**Acceptance:** the trigger/constraint (Layer 2) is the verifiable invariant; Layer 1 prevents the race in the common path; Layer 3 is the defense-in-depth.

### 3.4 Coordination with PR #16 (Order commodity model)

PR #16 received a Codex catch ("P1: rejeitar linkagens cross-commodity"). When #16 lands in main, `LinkageService.create` will already have a commodity match check (`order.commodity == contract.commodity`).

Two scenarios for the executor:

- **If PR #16 has merged before you start this PR:** the commodity check is in place. Add direction check + atomicity layers ALONGSIDE — do not replace or remove the commodity check. The order of validations in `create()` should be: existence → commodity match (already there from #16) → direction match (this PR) → fixed-price rejection (this PR) → atomicity layers around capacity (this PR).

- **If PR #16 has NOT merged yet:** implement direction + atomicity. Be aware that #16 will rebase on top of this PR and add commodity check. Coordinate with the orchestrator about merge order to avoid double rebase.

**Verify before coding:**
```bash
git log --oneline origin/main -- backend/app/services/linkage_service.py | head -5
grep -n "commodity" backend/app/services/linkage_service.py
```

If commodity check is already present, skip §3.4(a); else proceed knowing #16 will land it later.

### 3.5 Tests required (replace pseudo-fixtures with constitution-derived)

See §7 below. Critical: every test that asserts a numeric expected output MUST re-derive it from the constitutional formula (§2.4, §2.5) and place the formula in a comment next to the assertion. Memory `feedback_dispatch_self_consistency` covers why.

---

## 4. Scope OUT — explicitly NOT in PR-4

- **Audit emission on linkage delete/update routes** — out of scope (no in-scope delete/update path today; PR-7 covers create-route audit which is already wired).
- **Hedge classification DB invariant** — PR-6 (#14) territory; do not touch `HedgeContract.classification` invariant.
- **Decimal substrate** — PR-1 (#15) already in main; preserve, do not regress.
- **UoW boundary mechanism** — PR-3 (#13) already in main; do not call `session.commit()` from service.
- **Commodity model on Order** — PR-2 (#16) territory.
- **P&L price evidence** — PR-8 territory (depends on #15 same as this PR).
- **Snapshot lifecycle filters** (`deleted_at`/`status`) — PR-5 territory (depends on #16).
- **Audit emission for reconcile** — covered by PR-7.
- **Reconcile run identity / persisted reconciliation_run row** — discussed in PR-7 dispatch; this PR only adds the residual hard-fail, not the audit-anchor entity.

---

## 5. Constitutional rules (binding)

- **§2.3** — Hedge classification is deterministic and absolute. Linkage that pairs a `HedgeClassification.long` with a `OrderType.sales` violates this implicitly (a long-position hedging a sales is not "buy-fixed" against sales price exposure).
- **§2.4** — "Linked hedge contracts reduce commercial exposure and global exposure." Implicit: the link is meaningful — it ties matching directions. Pairing wrong directions doesn't reduce exposure; it produces accounting noise.
- **§2.6** — "Exposure would be over-allocated" is a hard-fail. No silent clamp. No best-effort. No race-survival.

---

## 6. Acceptance criteria (from jury §2 J-A1-03 + §3 J-A1-OPUS-01 + §3 J-A1-OPUS-03)

### 6.1 Direction (J-A1-OPUS-03)

- [ ] **Test:** `LinkageService.create(SO, HedgeContract(classification=long), 100)` → 422 with message naming the mismatch
- [ ] **Test:** `LinkageService.create(PO, HedgeContract(classification=short), 100)` → 422
- [ ] **Test:** `LinkageService.create(SO, HedgeContract(classification=short), 100)` → succeeds (direction-correct)
- [ ] **Test:** `LinkageService.create(PO, HedgeContract(classification=long), 100)` → succeeds
- [ ] **Test:** `LinkageService.create(fixed-price SO, ...)` → 422 with "Cannot hedge a fixed-price order" (per `_validate_hedge_direction` precedent at `deal_engine.py:201-207`)

### 6.2 Atomicity / TOCTOU (J-A1-03)

- [ ] **Test (concurrency):** Two sessions racing on the same `(order_id, contract_id)` with capacities that allow each individually but exceed jointly → exactly one commits, the other rolls back with capacity error
- [ ] **Test (DB-level invariant):** Direct SQL INSERT bypassing the service that would over-allocate → fails with constraint/trigger error
- [ ] **Test:** `with_for_update` is on the read of `Order` and `HedgeContract` — verify by inspection of the SQL emitted (use SQLAlchemy `compile(compile_kwargs={"literal_binds": True})` if needed in test)
- [ ] **Test:** Failed concurrent allocation leaves no partial linkage row in the DB

### 6.3 Reconcile hard-fail (J-A1-OPUS-01)

- [ ] **Test:** Construct fixture with linkages summing > order.quantity_mt for some order, run `reconcile_from_orders` → raises `ExposureOverAllocationError` (or whatever name the executor picks; document in PR)
- [ ] **Test:** No `Exposure` row is created or updated when the assertion fails
- [ ] **Test:** Normal case (linkages ≤ order.quantity_mt) still produces correct snapshot
- [ ] **Constitutional acceptance:** The assertion message names the offending order_id and the over-allocation amount (`linked - order.quantity_mt`)

### 6.4 No regression of W1 work

- [ ] All tests added in PR-1 (#15) `test_decimal_primitives.py` still pass
- [ ] All tests added in PR-3 (#13) `test_uow_boundary.py` still pass
- [ ] No `session.commit()` reintroduced in `LinkageService` or `ExposureEngineService` (PR-3 boundary preserved)

---

## 7. Test coverage required

| Test file | Status | Covers |
|---|---|---|
| `backend/tests/test_linkages.py` | EXTEND | §6.1 direction, §6.2 atomicity (sequential cases) |
| `backend/tests/test_linkages_concurrency.py` | NEW | §6.2 concurrency (two-session race; consider `pytest-xdist` or `threading` based test) |
| `backend/tests/test_exposure_engine.py` | EXTEND | §6.3 reconcile hard-fail |
| `backend/tests/test_uow_boundary.py` | EXTEND if behavior shifted | confirm rollback semantics still hold under new exceptions |

For each numeric fixture, place the constitutional formula derivation in a comment next to the expected output:

```python
# Per §2.4: linkage reduces commercial exposure of the order.
# SO Aluminum 100 + Hedge Short Aluminum 100 (linked, direction-correct, qty 100):
#   commercial Aluminum = 100 (SO) - 100 (linkage) = 0
expected_aluminum_active = Decimal("0")
```

This is anti-Codex-Tipo-II hardening per memory `feedback_dispatch_self_consistency`.

---

## 8. Critical sequencing

- **Upstream:** PR #15 (Decimal) and PR #13 (UoW) MERGED. Verify before starting: `git log --oneline origin/main | head -10`.
- **Coordinate:** PR #16 (Commodity) may merge before/during/after this PR. See §3.4 for branching behavior.
- **Downstream:** none — this PR closes 3 of the remaining Tier 1 findings.

If you find during implementation that the existing `_validate_hedge_direction` (at deal level) shares >50% of the validation logic with what you're adding to `LinkageService.create`, consider extracting a private helper to a shared module (`backend/app/services/_hedge_direction.py` or similar). This is **scope creep** — only do it if the duplication is egregious AND the extraction doesn't expand the diff materially. Default: copy the rule, don't refactor.

---

## 9. PR shape

**Title:** `fix(audit-a1): PR-4 — linkage hardening (direction + atomicity + reconcile hard-fail) (J-A1-03, J-A1-OPUS-01, J-A1-OPUS-03)`

**Body skeleton:**

```markdown
## Summary

Harden `LinkageService.create` and `ExposureEngineService.reconcile_from_orders`
to remove three Tier 1 constitutional violations in linkage / reconcile
surface. Bundle of 3 jury findings on the same code path. Constitutional
§2.3, §2.4, §2.6.

## Findings closed
- J-A1-03: TOCTOU over-allocation race in `LinkageService.create`
- J-A1-OPUS-01: Reconcile silently clamps over-allocation
- J-A1-OPUS-03: Direction-mismatched hedge/order pairs allowed

## Files changed
- Services: linkage_service.py, exposure_engine.py
- Models: linkages.py (if Layer 2 adds DB-level invariant via trigger or
  EXCLUDE/CHECK; no schema change otherwise)
- Alembic: migration `0XX_linkage_invariants.py` (only if Layer 2 lands as
  schema change)
- Tests: test_linkages.py, test_linkages_concurrency.py (new),
  test_exposure_engine.py, test_uow_boundary.py (verify regressions)
- New: backend/app/services/_hedge_direction.py (only if extraction is
  warranted per §8)

## Defense layers chosen
- Layer 1 (row lock with_for_update): {applied / not applied — reason}
- Layer 2 (DB-level invariant): {trigger / EXCLUDE constraint / materialized
  ledger; brief justification}
- Layer 3 (advisory lock): {applied / not applied}

## Constitutional impact
- §2.3, §2.4, §2.6 — over-allocation is now structurally impossible
- §2.7 — error messages name offending IDs and quantities for audit

## Out of scope
- Commodity match (PR-2 / #16)
- Audit emission (PR-7)
- Lifecycle filters (PR-5)
- P&L price evidence (PR-8)

## Closes
J-A1-03, J-A1-OPUS-01, J-A1-OPUS-03.
```

---

## 10. Constraints — what NOT to do

- DO NOT remove the existing capacity check (`linked + new > order.quantity_mt`); it stays AS IS plus the new layers
- DO NOT call `session.commit()` from the service (PR-3 boundary preserved)
- DO NOT regress to `float` arithmetic (PR-1 substrate preserved)
- DO NOT touch `HedgeContract.classification` invariant (PR-6 / #14)
- DO NOT add audit emission to linkage routes (already there per linkages route at `routes/linkages.py:48-64`)
- DO NOT widen scope to `LinkageService.delete/update` (no in-scope routes today)
- DO NOT use `--no-verify`, no force-push (except `--force-with-lease` after Codex-approved rebase if needed), no auto-merge
- DO NOT auto-merge — Codex review mandatory (Codex outranks CI green)

---

## 11. Workflow

1. `git fetch origin && git checkout -b audit-a1/linkage-hardening origin/main`
2. Verify upstream deps: `git log --oneline origin/main | head -10` should show #15 and #13 commits
3. Read jury verdict §2 J-A1-03, §3 J-A1-OPUS-01, §3 J-A1-OPUS-03 in full
4. Read current state of `linkage_service.py`, `exposure_engine.py`, `_validate_hedge_direction` in `deal_engine.py` — copy the rule, do not call across aggregates
5. Choose Layer 2 invariant strategy; document in PR description draft
6. Implement: direction validation → atomicity layers → reconcile hard-fail → tests
7. Run `pytest backend/tests/test_linkages.py backend/tests/test_exposure_engine.py backend/tests/test_uow_boundary.py -v` between each step
8. `git push -u origin audit-a1/linkage-hardening`
9. `gh pr create --base main --title "<§9 title>" --body-file <body>`
10. **STOP. Wait for Codex review.** Codex outranks CI green.
11. Address feedback in new commits

---

## 12. Final report shape

- Branch + PR URL + final SHA
- Layer 2 invariant strategy chosen + rationale
- Files touched grouped
- Concurrency test evidence (sample log of two sessions racing)
- Reconcile assertion test evidence
- Codex verdict
- Any `[BEHAVIOR_SHIFT]` notes (e.g., a previously-passing test now fails because the silent over-allocation it relied on is now hard-fail — that's the bug being fixed; document, don't suppress)

Under 600 words.

Boa caça.
