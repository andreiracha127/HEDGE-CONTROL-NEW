# Cluster 1 Remediation Dispatch — PR-CL1-2 — Deal P&L Hard-Fail on Total Price Unavailability

**Cluster:** 1 — A1 follow-up (deal-engine + exposure + scenario boundaries)
**Wave:** PR-CL1-2 (2 of 4)
**Authoring date:** 2026-05-13
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `ea08d9868` post-PR-#73; should also reflect any PR-CL1-1 landing if that wave merges first — see §11)
**Required branch:** `audit-followup/cluster-1-pnl-hard-fail-unprovable`
**Source verdict:** `docs/audits/2026-05-13-cluster-1-jury-verdict.md` §J-CL1-03, §D-1.3 Institutional Decision, §PR-CL1-2 wave entry

## 1. Objective

Close **J-CL1-03** (Tier 1 / Blocking) — total price unavailability silently substitutes stale valuation. Two coupled fixes:

1. **Service layer**: remove the `if unprovable_errors:` candidate-probe branch in `DealEngineService.compute_deal_pnl`. When zero live quotes are available, propagate the first `PriceReferenceUnprovable` unconditionally. No snapshot reuse.
2. **Route layer**: change the `_raise_price_unprovable` helper in `deals.py` from `HTTP 422` to **`HTTP 424 Failed Dependency`** per `docs/governance.md:152`. This brings deals.py into alignment with the rest of the system — `cashflow.py:75-78` and `scenario.py:31-34` already map this exception to 424. The 422 mapping in `deals.py` is a stale PR-8-era contract that conflicts with both governance and the rest of the codebase.

The verdict's institutional decision on **D-1.3** is binding: "Reject current reuse. Always propagate `PriceReferenceUnprovable` when zero live quotes are available." The HTTP boundary clarification in the verdict (added per the Codex P2 fix on PR #73) is also binding: 424 not 422.

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`. Governance §152 is the source; this wave implements it, not amends it.
- Do **not** add a separate "outage repair" code path with caller opt-in or a `force_repair_from_snapshot` flag. The verdict explicitly rejects that as out-of-scope for this wave. If product later demands outage repair, it becomes its own audit-cycle proposal.
- Do **not** broaden the route-layer change beyond `_raise_price_unprovable` in `deals.py`. The cashflow and scenario routes already map to 424; leave them alone.
- Do **not** change the `_compute_inputs_hash` shape. The verdict accepted that the hash's current content is fine for the **happy-path idempotency lookup** at `deal_engine.py:734-740`. Extending the hash to include linked-entity content is what the *rejected* alternative would have required; we are removing the reuse branch instead.
- Do **not** touch wave PR-CL1-1's territory (`compute_pnl_breakdown`, `_recompute_tons`, archived-link filter). If PR-CL1-1 has not yet merged, work against its base. If it has merged, work against post-merge main.
- Do **not** touch wave PR-CL1-3's territory (scenario, `ExposureService`).
- Do **not** add a migration. Single alembic head must remain `043_a5_audit_payload_input`.
- Do **not** alter the public response shape of `compute_deal_pnl` on the happy path. Only the failure-path HTTP code changes (422 → 424).

## 3. Findings and Evidence

Verified at HEAD `ea08d9868`.

### The candidate-probe reuse branch

- `backend/app/services/deal_engine.py:657-703` — `compute_deal_pnl` total quote unavailability path. When `unprovable_errors` is non-empty, the code queries existing `DealPNLSnapshot` rows with matching `(deal_id, snapshot_date)`, recomputes their hash against the candidate's persisted `price_references`, and returns the first hash match. Comment at `:670-684` documents the PR-8 ordering fix; that fix was correct under the old contract but is being removed by this wave.
- `backend/app/services/deal_engine.py:50-78` — `_compute_inputs_hash` binds `(deal_id, snapshot_date, link_ids, price_references)` only. It does not bind underlying linked-entity content (price type, quantity, avg price, fixed price, hedge status). That is the reason a content-mutated link can still match a stale snapshot hash and produce wrong P&L.
- `backend/app/services/deal_engine.py:734-740` — the standard hash-match lookup (separate from the reuse branch). Documented as the "global same-inputs → same-row idempotency guarantee" for repeated POSTs that produced identical `price_references`. **Stays as-is.** Its idempotency is real because the live lookup actually succeeded both times.

### Route-layer mapping (the second half of the fix)

- `backend/app/api/routes/deals.py:34-48` — `_raise_price_unprovable` helper. Maps `PriceReferenceUnprovable` to `HTTP 422`. The comment block justifies it as "canonical mapping for 'request was well-formed but semantically invalid given current data'". That reasoning predates governance §152, which is now binding.
- `backend/app/api/routes/deals.py:146-147` and `:237-238` — two call sites for `_raise_price_unprovable`. Both are POST routes: deal-create (line ~90 onward) and compute-pnl (line ~214 onward). Both invoke the helper inside an `except PriceReferenceUnprovable` block.
- `backend/app/api/routes/cashflow.py:75-78` — already maps to `HTTP 424`. Reference implementation.
- `backend/app/api/routes/scenario.py:31-34` — already maps to `HTTP 424`. Reference implementation.

The `deals.py` 422 mapping is an isolated governance violation: every other route in the system that maps `PriceReferenceUnprovable` already uses 424.

### Governance binding

- `docs/governance.md:152` — "Hard-fail propagation: price reference unprovable → HTTP 424". This is the canonical contract for live-price hard-fails.
- `docs/governance.md:155-157` — 422 is reserved for distinct cases: missing zero-default economics (`avg_entry_price`, `fixed_price_value`) and missing `settlement_date`. The current deals.py 422 mapping conflates two governance categories.

### Tests that must invert

- `backend/tests/test_pnl_provenance.py:2202-2245` — `test_compute_deal_pnl_total_unavailability_reuses_candidate` pins the reuse-success contract. Invert: expected behavior becomes `PriceReferenceUnprovable` raised, no snapshot returned, no new row.
- `backend/tests/test_pnl_provenance.py:2134-2136` and `:2189-2191` — two assertions of `assert r2.status_code == 422`. Flip both to `424`. The accompanying comments referencing "Route must map PriceReferenceUnprovable to 422 (4xx contract)" must be updated to reference governance §152 and 424.
- `backend/tests/test_pnl_price_evidence.py` — sweep for any 422 assertion on `PriceReferenceUnprovable` paths; flip to 424. (Verify in §8 sweep.)

## 4. Required Implementation Boundary

### 4.1 Service-layer change in `backend/app/services/deal_engine.py`

Remove the candidate-probe branch entirely. Replace lines 657-703 (the `if unprovable_errors:` block) with a single hard-fail:

```python
if unprovable_errors:
    # D-1.3 closure (Cluster 1 verdict): no snapshot reuse on total
    # price unavailability. The hash check binds link ids and persisted
    # price_references, not underlying entity content; a content-mutated
    # link with a stale persisted reference can hash-match a sealed
    # historical snapshot and produce wrong P&L. Per governance §2.6
    # ("no silent fallback") and §"evidence missing is hard-fail",
    # propagate the first unprovable error. Historical retrieval lives
    # in `GET /deals/{id}/pnl-history`, not in this compute endpoint.
    raise unprovable_errors[0][1]
```

Preserve the surrounding code: the partial-success branch above (mixed unprovable + live) keeps its existing semantics. Only the total-unavailability branch is collapsed to a hard-fail.

Do **not** delete `_compute_inputs_hash` or change its shape. The happy-path idempotency lookup at `:734-740` still uses it and is unchanged.

### 4.2 Route-layer change in `backend/app/api/routes/deals.py`

Replace the `_raise_price_unprovable` helper and its comment block:

```python
# ── PriceReferenceUnprovable → 424 mapping ────────────────────────────
# Governance §"Projection invariants" (docs/governance.md:152) binds:
# "Hard-fail propagation: price reference unprovable → HTTP 424".
# 422 is reserved by governance for distinct cases (missing zero-default
# economics, missing settlement_date — governance lines 155-157).
# cashflow.py and scenario.py already map this exception to 424; this
# helper brings deals.py into alignment.
def _raise_price_unprovable(exc: PriceReferenceUnprovable) -> None:
    raise HTTPException(
        status_code=status.HTTP_424_FAILED_DEPENDENCY,
        detail=str(exc),
    )
```

The two call sites at `:146-147` and `:237-238` are unchanged — they continue to call `_raise_price_unprovable(exc)` inside the except blocks. Only the helper's status code changes.

### 4.3 Test-side changes (binding)

In `backend/tests/test_pnl_provenance.py`:

- **`test_compute_deal_pnl_total_unavailability_reuses_candidate`** at `:2202-2245`: rename to `test_compute_deal_pnl_total_unavailability_hard_fails` (or similar). The test:
  - Arranges the same setup (deal + persisted snapshot + price-feed outage).
  - Calls `compute_deal_pnl`.
  - Asserts `PriceReferenceUnprovable` is raised (use `pytest.raises`).
  - Asserts no new `DealPNLSnapshot` row was written for the failed compute (query before/after).
  - Asserts the existing snapshot is **not** mutated (timestamp, hash, content unchanged).
- **`assert r2.status_code == 422`** at `:2136` and `:2191`: flip both to `424`. Update the inline comment at `:2135` to reference governance §152.

In `backend/tests/test_pnl_price_evidence.py`: sweep for any 422 assertion on `PriceReferenceUnprovable` route paths and flip to 424. Update accompanying comments.

Add one new regression test in `backend/tests/test_pnl_provenance.py`:

- **`test_compute_deal_pnl_total_unavailability_does_not_reuse_after_link_mutation`**: arrange a deal with a persisted snapshot, mutate a linked Order's price type or quantity (without remapping the link), trigger total price unavailability, assert `PriceReferenceUnprovable` is raised (not a stale-content snapshot returned). This documents the institutional reason the reuse branch is being removed.

### 4.4 What stays

- `_compute_inputs_hash`: unchanged shape.
- Happy-path hash-match lookup at `deal_engine.py:734-740`: unchanged. Idempotency for repeated POSTs with identical live `price_references` is preserved.
- Partial-success branch (some prices live, some unprovable): unchanged. The 4xx propagation for that branch already flows through `_raise_price_unprovable`, which will now correctly map to 424.
- `GET /deals/{id}/pnl-history`: unchanged. Historical retrieval remains the legitimate read path for sealed snapshots.

## 5. Constitutional Rules

- `docs/governance.md` §2.6 ("no silent fallback") — the reuse branch was a silent extrapolation of stale price evidence; removing it closes the violation.
- `docs/governance.md` §2.7 (audit reconstructability) — the route's `event_type="created"` audit row could not distinguish fresh computation from outage reuse; removing the reuse branch eliminates the ambiguity.
- `docs/governance.md:152` ("Hard-fail propagation: price reference unprovable → HTTP 424") — the route-layer 422 → 424 fix.
- `docs/governance.md:155-157` (422 reserved for missing zero-default economics + missing settlement_date) — the rationale for why this case is distinctly 424, not 422.

No changes to `docs/governance.md` are part of this wave.

## 6. Acceptance Criteria

A merged PR closes J-CL1-03 iff every item below is true.

### 6.1 Service layer

- [ ] `backend/app/services/deal_engine.py` — the `if unprovable_errors:` candidate-probe branch (formerly lines 657-703) is replaced with `raise unprovable_errors[0][1]` plus the doc-comment from §4.1.
- [ ] `backend/app/services/deal_engine.py` — `_compute_inputs_hash` shape unchanged.
- [ ] `backend/app/services/deal_engine.py` — the happy-path hash-match lookup near `:734-740` is unchanged.

### 6.2 Route layer

- [ ] `backend/app/api/routes/deals.py` — `_raise_price_unprovable` raises `HTTPException(status_code=status.HTTP_424_FAILED_DEPENDENCY, ...)`.
- [ ] `backend/app/api/routes/deals.py` — the comment block above `_raise_price_unprovable` references governance §152 and the 422 vs 424 distinction.
- [ ] `backend/app/api/routes/deals.py` — both call sites at `:146-147` and `:237-238` continue to call `_raise_price_unprovable(exc)` and are otherwise unchanged.
- [ ] `backend/app/api/routes/cashflow.py` and `backend/app/api/routes/scenario.py` — diff against main is empty (they already use 424; not touched here).

### 6.3 Tests

- [ ] `backend/tests/test_pnl_provenance.py` — the former `test_compute_deal_pnl_total_unavailability_reuses_candidate` is renamed and asserts `PriceReferenceUnprovable` raised, no new snapshot, existing snapshot unchanged.
- [ ] `backend/tests/test_pnl_provenance.py` — both `status_code == 422` assertions (formerly `:2136` and `:2191`) are now `status_code == 424`.
- [ ] `backend/tests/test_pnl_provenance.py` — new test `test_compute_deal_pnl_total_unavailability_does_not_reuse_after_link_mutation` exists and passes.
- [ ] `backend/tests/test_pnl_price_evidence.py` — any 422 assertion on `PriceReferenceUnprovable` paths is now 424.

### 6.4 Sweeps

- [ ] `rg -nP "status_code == 422" backend/tests/test_pnl_provenance.py backend/tests/test_pnl_price_evidence.py` returns zero matches (in PriceReferenceUnprovable contexts).
- [ ] `rg -nP "HTTP_422_UNPROCESSABLE_ENTITY" backend/app/api/routes/deals.py` returns zero matches inside the `_raise_price_unprovable` body (other 422 sites in the file, if any, are unrelated and stay).
- [ ] `rg -nP "HTTP_424_FAILED_DEPENDENCY" backend/app/api/routes/deals.py` returns at least one match in `_raise_price_unprovable`.
- [ ] `rg -nP "unprovable_errors\\[0\\]\\[1\\]" backend/app/services/deal_engine.py` returns exactly one or two matches (the new total-unavailability raise; potentially one in the existing partial-success path if that pattern was already used).
- [ ] `python -m alembic heads` prints `043_a5_audit_payload_input`.

### 6.5 Cross-cutting

- [ ] `docs/governance.md` diff is empty.
- [ ] No frontend file changed.
- [ ] OpenAPI regeneration (`docs/api/openapi_v1.json`) reflects the 422 → 424 change on the two deal routes that previously returned 422; no other endpoint shape changes.
- [ ] `frontend-svelte/src/lib/api/schema.d.ts` regenerated and diff is bounded to the same two endpoint response codes.

## 7. Required Tests

The acceptance §6.3 above already enumerates the required test changes. Restated as a sweep:

1. Invert `test_compute_deal_pnl_total_unavailability_reuses_candidate` to hard-fail expectation.
2. Flip both `status_code == 422` assertions in `test_pnl_provenance.py` to `424`.
3. Add `test_compute_deal_pnl_total_unavailability_does_not_reuse_after_link_mutation` for the link-mutation regression.
4. Sweep `test_pnl_price_evidence.py` for similar 422 assertions; flip to 424.
5. If any cashflow / scenario test asserted 424 against a deals path (it shouldn't, since cashflow / scenario use their own routes), leave them alone.

## 8. Required Verification

```powershell
# Service-side sweeps
rg -nP "unprovable_errors\\s*:" backend/app/services/deal_engine.py
rg -nP "candidate_snapshots" backend/app/services/deal_engine.py    # should return zero matches
rg -nP "if unprovable_errors:" backend/app/services/deal_engine.py  # should match exactly once (the new raise)

# Route-side sweeps
rg -nP "HTTP_422_UNPROCESSABLE_ENTITY" backend/app/api/routes/deals.py
rg -nP "HTTP_424_FAILED_DEPENDENCY" backend/app/api/routes/deals.py

# Cross-route consistency (read-only; must show 424 already in cashflow + scenario, unchanged)
rg -nP "PriceReferenceUnprovable" backend/app/api/routes/

# Test sweeps
rg -nP "status_code == 422" backend/tests/test_pnl_provenance.py backend/tests/test_pnl_price_evidence.py
rg -nP "status_code == 424" backend/tests/test_pnl_provenance.py backend/tests/test_pnl_price_evidence.py

# Alembic invariant
cd backend ; python -m alembic heads ; cd ..

# Test suites
pytest -q backend/tests/test_pnl_provenance.py backend/tests/test_pnl_price_evidence.py
pytest -q backend/tests

# Generated artifacts
git diff -- docs/api/openapi_v1.json frontend-svelte/src/lib/api/schema.d.ts
git diff --check

# Governance + cross-wave isolation
git diff main -- docs/governance.md
git diff main -- backend/app/services/scenario_whatif_service.py
git diff main -- backend/app/services/exposure_service.py
git diff main -- backend/app/services/exposure_engine.py
```

`git diff main -- docs/governance.md` must be empty. `python -m alembic heads` must print `043_a5_audit_payload_input`. Cross-service / cross-wave diffs must be empty.

## 9. Out of Scope

- Wave PR-CL1-1 (archived-link traversal). Even though `compute_deal_pnl` is touched in both waves, the line ranges are disjoint: PR-CL1-1 changes the linked-entity reads (`:559-611`, `:918-957`, `:1036`, `:1245-1269`); PR-CL1-2 changes the unprovable-error branch (`:657-703`) and the route helper.
- Wave PR-CL1-3 (scenario / shared exposure primitive). Not touched.
- Wave PR-CL1-4 (Deal soft-delete contract cleanup). Not touched.
- Future "outage repair" feature with caller opt-in + signed audit. The verdict explicitly defers this to a separate cycle if product later demands it. **Do not** add a feature flag or environment toggle that preserves the reuse branch.
- Extending `_compute_inputs_hash` to bind linked-entity content. Was the rejected alternative; not in scope here.
- Hash-extension migrations or new audit event types. None of those apply when the branch is removed.
- Changes to `GET /deals/{id}/pnl-history`. Historical retrieval continues to serve sealed snapshots; that path is the legitimate consumer for what the reuse branch used to short-circuit.
- Changes to other 422 mappings in `deals.py` that are unrelated to `PriceReferenceUnprovable` (e.g. validation errors on deal create). Those are governance §155-157 territory and stay.

## 10. PR Requirements

The implementing PR title must be:

```
fix(audit-followup): close Cluster 1 PR-CL1-2 (P&L hard-fails on unprovable price; 424 mapping)
```

The PR body must include:

- **Findings closed:** explicit `J-CL1-03` reference + D-1.3 institutional decision citation.
- **Files changed:** inventory grouped by backend service / backend route / tests / generated artifacts.
- **Verification matrix:** §8 sweep results.
- **HTTP boundary statement:** explicit mention of governance §152 and the 422 → 424 alignment with `cashflow.py` and `scenario.py`.
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-1-pnl-hard-fail-unprovable-{sha}.json` per push.
- **Governance statement:** `docs/governance.md` diff is empty.
- **Alembic statement:** single head `043_a5_audit_payload_input`.

## 11. Workflow

1. `git checkout -b audit-followup/cluster-1-pnl-hard-fail-unprovable`.
   - If PR-CL1-1 has merged: base off `main` post-merge. Run the §8 cross-wave sweep first to confirm `deal_engine.py:559-611` / `:918-957` / `:1036` / `:1245-1269` already filter `deleted_at`.
   - If PR-CL1-1 has not merged: base off `main @ ea08d9868`. The two waves' line ranges don't conflict, but resolving merge conflicts after both push is cheaper than chaining.
2. Apply §4.1 (remove the candidate-probe branch).
3. Apply §4.2 (route helper 422 → 424 + comment rewrite).
4. Apply §4.3 (test inversions + new regression test).
5. Regenerate OpenAPI + `schema.d.ts`.
6. Run §8 verification locally; fix every hook v2 P1/P2 in place.
7. Push branch and open PR per §10.
8. Codex Connector review is the final gate. Address every Codex inline catch. **Do not merge** — Andrei merges with explicit authorization only.

## 12. Hook v2 + Codex calibration notes

- **Expected hook v2 surface area**: service-side remove-and-raise (small diff), route-side helper update (single function), test inversion (2 assertions flipped, 1 test renamed, 1 test added), OpenAPI regen (2 endpoint response codes change). 
- **Expected Codex catches**:
  - Test inversion missing for `test_pnl_price_evidence.py` if that file also asserts 422 on the route — sweep `rg -nP "status_code == 422" backend/tests/test_pnl_price_evidence.py` before pushing.
  - A residual `candidate_snapshots` query left in the file (dead code) — sweep confirms removal.
  - The `unprovable_errors` first-element propagation in the partial-success branch (above the deleted block) sharing the same shape — verify no off-by-one ordering bug after the surrounding code moves.
  - OpenAPI regen showing 422 → 424 change on **both** affected deal routes (deal create + compute-pnl). Codex may flag if only one of them is updated.
  - Stale comment text elsewhere in the file referencing "PR-8 J-A1-01 → 422 mapping" — sweep for any reference and update or remove.
- The 8-section sweep checklist from `feedback_dispatch_self_consistency` applies: §3 evidence, §4 boundary, §6 acceptance, §7 tests, §8 verification, §11 workflow all must consistently enumerate both the service-side and the route-side changes. A test that flips 422 → 424 without the corresponding route helper change (or vice versa) is the canonical drift to watch for.
- **Self-defeating risk** unique to this wave: if the route helper is updated to 424 but the test assertions remain at 422, the test suite fails closed in CI — which is fine. The inverse (helper at 422, tests updated to 424) would silently pass at first run because the route is still raising 422, but then break the implementing PR's own CI. Either way the contradiction is loud, not silent.
