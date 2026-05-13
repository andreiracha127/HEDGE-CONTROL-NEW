# Cluster 1 Follow-Up Audit — Stage 1 Findings — Auditor A (Opus 4.7)

**Cluster:** 1 — A1 follow-up (deal-engine + exposure + scenario boundaries)
**Stage:** 1 of 3
**Auditor:** Opus 4.7
**Date:** 2026-05-13
**Repository:** `D:/Projetos/Hedge-Control-New`
**Branch / SHA:** `main` @ `ba032f476`
**Dispatch:** `docs/audits/2026-05-13-cluster-1-stage1-opus-prompt.md`

---

## §0 Executive Summary

| Surface | Status | Tier 1 | Tier 2 | Tier 3 | Notes |
| --- | --- | --- | --- | --- | --- |
| **D-1.1** DealLink lifecycle vs Deal soft-delete | Latent (no Deal archive route) **but** entity-side gap is live via Order/HedgeContract archive routes | 0 | 1 | 2 | Real failure mode reachable today through `/orders/{id}/archive` and `/contracts/hedge/{id}/archive`. |
| **D-1.2** Exposure soft-delete duplicate source semantics | **Closed** by §3.8 retirement sweep + Codex P2 task cancellation + 7 readers filtering `is_deleted == False` | 0 | 0 | 0 | A1 J-A1-OPUS-08 is fully retired; covered by `test_pr5_lifecycle_acceptance.py`. |
| **D-1.3** Snapshot reuse on total price unavailability | **Open** — institutional decision required; concrete staleness failure mode found | 0 | 2 | 1 | Hash binds link set + price_references but not underlying entity state. |
| **D-1.4** Scenario duplicates A1 aggregation | **Open** — concrete divergence today, not just drift potential | 3 | 1 | 0 | Scenario reads soft-deleted Orders / archived HedgeContracts / orphan linkages. |
| **Cross-deferral (Q5)** Deal P&L vs Exposure retirement | **Open** — fresh interaction A1 and A3 didn't see independently | 1 | 0 | 0 | Archived Order shows zero exposure but full Deal P&L contribution. |

Total accepted findings: **11** (4 Tier 1 / 4 Tier 2 / 3 Tier 3).
Mandatory institutional decisions returned: **2** (D-1.3, D-1.4).

---

## §1 Operating Notes

- Read-only audit. No code, test, schema, migration, or governance file mutated.
- Surface derived from current `main @ ba032f476`. Line citations are against that SHA.
- Commands executed: none (build/test sandbox unavailable in this session). Direct code evidence used throughout. The full backend test suite was not invoked; targeted file reads against `backend/tests/` were used to inventory coverage.
- Single alembic head invariant per §6.3 was not re-verified by `python -m alembic heads`; the dispatch explicitly forbids migration proposals so the audit does not depend on it.
- `git ls-tree HEAD -- backend/app/services/deal_engine.py backend/app/services/exposure_engine.py backend/app/services/exposure_service.py backend/app/services/scenario_whatif_service.py` was the spine of the audit; each finding cites those files.

---

## §2 Audit Questions — Answers and Evidence

### Q1 — DealLink lifecycle vs Deal soft-delete (D-1.1)

**Surface re-derivation:**
- `backend/app/models/deal.py:160-163` — `Deal.is_deleted` + `Deal.deleted_at` are present.
- `backend/app/models/deal.py:171-194` — `DealLink` has **no** lifecycle column; unique constraint `uq_deal_link_entity (linked_type, linked_id)` at line 175-179 enforces cross-deal uniqueness regardless of parent state; `ForeignKey("deals.id", ondelete="CASCADE")` at line 186 fires only on hard delete (and soft-delete does not issue DELETE).
- `backend/app/services/deal_engine.py:158-165, 311-318` — cross-deal uniqueness query in `create_deal` and `add_link` does NOT filter `Deal.is_deleted`, `Order.deleted_at`, or `HedgeContract.deleted_at`.
- `backend/app/services/deal_engine.py:886, 893, 1183, 1194` — `Deal.is_deleted == False` filter present in `compute_pnl_breakdown`, `list_deals`, `get_by_id`. Read-side coverage exists.
- **No** route writes `Deal.is_deleted` or `Deal.deleted_at` (`rg "\.is_deleted\s*=\s*True"` returns one hit at `counterparty_service.py:95` and another at `exposure_engine.py:234`; neither touches `Deal`).
- `/orders/{order_id}/archive` (`backend/app/api/routes/orders.py:129`) and `/contracts/hedge/{contract_id}/archive` (`backend/app/api/routes/contracts.py:89`) **are** live. These soft-delete the underlying entity that a `DealLink.linked_id` references.

**Verdict:** Deal-side soft-delete is partially wired (read filters only, no writer). The originally-cited J-A1-OPUS-07 scenario ("soft-deleted deal still owns a DealLink") is unreachable today. **The functional analog — "soft-deleted Order / HedgeContract still owns a DealLink" — is reachable today**, and creates concrete inconsistencies between Exposure (which retires the dead entity) and Deal (which still values it). Findings J-CL1-OPUS-01 through J-CL1-OPUS-04 below.

### Q2 — Exposure soft-delete duplicate-source semantics (D-1.2)

**Surface re-derivation:**
- `backend/app/services/exposure_engine.py:206-256` — §3.8 retirement sweep. Pre-existing Exposure rows whose source `Order.deleted_at IS NOT NULL` are soft-deleted (`is_deleted=True`, `deleted_at=func.now()`). Pending HedgeTasks under the retired Exposure are cancelled inline (lines 244-254 — Codex P2 follow-up).
- `backend/app/services/exposure_engine.py:167-174` — existing-row lookup filters `is_deleted == False`. An un-archived Order will therefore land on a fresh Exposure row; the prior retired row is preserved as audit history.
- Readers that filter `Exposure.is_deleted == False`:
  - `reconcile_from_orders` existing-row lookup (`exposure_engine.py:171`).
  - `compute_net_exposure` (`exposure_engine.py:314`).
  - `create_hedge_tasks` (`exposure_engine.py:463`).
  - `list_pending_tasks` (`exposure_engine.py:549`).
  - `execute_task` (`exposure_engine.py:585`).
  - `list_exposures` (`exposure_engine.py:612`).
  - `get_exposure` (`exposure_engine.py:638`).
- The only Exposure reader that does NOT filter `is_deleted` is `cancel_stale_tasks` (`exposure_engine.py:506-516`), which filters `Exposure.status in (fully_hedged, cancelled)`. Because the retirement sweep proactively cancels tasks for retired Exposures (lines 244-254), no executable HedgeTask is reachable through this path against a retired Exposure.
- Tests covering the retirement contract: `backend/tests/test_pr5_lifecycle_acceptance.py:356, 489, 525, 540, 713, 742, 767` — retirement, idempotency, un-retire-fresh-row, task cancellation, list filter, execute-side reject.

**Verdict:** D-1.2 is **CLOSED**. Logged in §4 Anti-findings considered. No Tier 1/2/3 finding promoted against D-1.2 itself.

### Q3 — Deal Engine snapshot reuse on total price unavailability (D-1.3)

**Surface re-derivation:**
- `backend/app/services/deal_engine.py:474-703` — `compute_deal_pnl`. The decision tree:
  - All commodities priced fresh → standard path (line 705+).
  - Partial success (some fresh, ≥1 unprovable) → fail closed; propagate `PriceReferenceUnprovable` (line 644-655).
  - Total unavailability (zero fresh) → candidate probe at lines 657-703 (`order_by(DealPNLSnapshot.sequence.desc())`, recompute hash against current `link_ids` + candidate's persisted `price_references`, return first match; else propagate).
- `backend/app/services/deal_engine.py:51-79` — `_compute_inputs_hash` includes `(deal_id, snapshot_date, link_ids, price_references)`. **Not** included: order `price_type`, `quantity_mt`, `avg_entry_price`; hedge contract `status`, `quantity_mt`, `fixed_price_value`.
- `backend/app/api/routes/deals.py:216-239` — `trigger_pnl_snapshot` audits `event_type="created"` regardless of whether the returned snapshot is fresh or a reused candidate.
- Tests: `backend/tests/test_pnl_provenance.py:2202-2245` — happy-path multi-commodity reuse. No test exercising underlying-entity mutation between snapshots.

**Verdict:** D-1.3 surface is **open** and the institutional decision is **owed** by this audit. Findings J-CL1-OPUS-05 and J-CL1-OPUS-06 below. **Decision** in §3.

### Q4 — Scenario duplicates A1 exposure aggregation (D-1.4)

**Surface re-derivation:**
- `backend/app/services/exposure_service.py:32-58` — A1 commercial linkage subquery filters `HedgeContract.deleted_at IS NULL` + `HedgeContract.status in (active, partially_settled)`.
- `backend/app/services/exposure_service.py:108-194` — A1 `compute_commercial_snapshot` filters `Order.deleted_at IS NULL` on every read (lines 119, 131, 154, 177).
- `backend/app/services/exposure_service.py:295-313` — A1 `linked_by_contract` subquery also adds `Order.deleted_at IS NULL` (dual filter).
- `backend/app/services/exposure_service.py:296-405` — A1 `compute_global_snapshot` filters all hedge reads by `HedgeContract.deleted_at IS NULL` AND status in (active, partially_settled) (lines 305-307, 327, 352-353, 376-378).
- `backend/app/services/scenario_whatif_service.py:213-229` — scenario loaders:
  - `_load_orders` — `db.query(Order).order_by(...).all()`. **No filter on `Order.deleted_at`**.
  - `_load_contracts` — `db.query(HedgeContract).order_by(...).all()`. **No filter on `HedgeContract.deleted_at` and no filter on status**.
  - `_load_linkages` — `db.query(HedgeOrderLinkage).all()`. **No filter on parent state**.
- `backend/app/services/scenario_whatif_service.py:232-302` — `_compute_commercial_exposure`. Aggregates all variable-price orders without lifecycle awareness. Returns `CommercialExposureRead` with `float(...)` casts (lines 291-300) — vs A1 returning `Decimal`.
- `backend/app/services/scenario_whatif_service.py:305-443` — `_compute_global_exposure`. Iterates **all** contracts regardless of status (line 364). Settled, cancelled, and archived hedges all flow into `total_hedge_long`/`total_hedge_short`.

**Verdict:** D-1.4 is **open with concrete divergence today**, not just drift potential. Findings J-CL1-OPUS-07/08/09/10 below. **Decision** in §3.

### Q5 — Cross-deferral interactions

**Sequence checked:** D-1.1 × D-1.2 — archive Order → §3.8 retires its Exposure → DealLink rows persist.

- `backend/app/services/deal_engine.py:583, 593, 1036, 1255` — Deal-side reads of Order/HedgeContract use `session.get(Order, link.linked_id)` / `session.get(HedgeContract, link.linked_id)` / unfiltered `session.query(...).filter(Order.id == ...).first()`. **No `Order.deleted_at IS NULL` or `HedgeContract.deleted_at IS NULL` filter** anywhere in `_recompute_tons`, `compute_deal_pnl`, or `compute_pnl_breakdown`.
- `backend/app/services/exposure_engine.py:218-232` retires the Exposure for the same archived Order.
- Result: `Net Exposure (ALU) = 0` (Exposure path), `Deal.total_physical_tons = 100`, `Deal P&L includes the archived order's revenue/cost` (deal path). Divergent views of the same underlying state.

This is the genuinely-new interaction. Finding J-CL1-OPUS-11.

**Sequence checked:** D-1.2 × D-1.4 — scenario reads soft-deleted Orders. Confirmed at `_load_orders`. Folded into J-CL1-OPUS-07 (no separate finding to avoid duplication).

**Sequence checked:** D-1.3 × D-1.4 — does scenario reuse stale snapshots? Scenario does NOT use `DealPNLSnapshot`; it recomputes MTM/P&L from `_mtm_for_contract` + ledger entries each run. No reuse path.

**Sequence checked:** D-1.1 × D-1.3 — can a snapshot reuse against a soft-deleted-link set hash-match? The hash includes the `DealLink.id` list at the moment of the snapshot. If a `DealLink` row is later hard-deleted (the only path today: `remove_link` at `deal_engine.py:411-434` issues `session.delete(link)`), the current-call `link_ids` set differs from the candidate's set → candidate hash recomputes differently → no match. No additional failure mode found here. The reuse staleness is captured by J-CL1-OPUS-05.

### Q6 — Audit / reconstruction coverage

- **Reconcile** emits a signed audit event tied to the `ReconciliationRun.id` anchor (`backend/app/api/routes/exposures.py:56-70`). Retirement sweep counts (`retired`, `tasks_cancelled`) flow into `run.summary` and the audit payload. **Sufficient** for §2.7.
- **Deal create / add_link / remove_link / pnl_snapshot** all wrap `audit_event(...)` + `mark_audit_success(...)` (`backend/app/api/routes/deals.py:90-239`). Coverage of mutation events is present.
- **Deal soft-delete** — no route, so no audit. Cluster 1 follow-up audit cannot fault its absence; flagged as part of J-CL1-OPUS-02 (the contract is incomplete).
- **Snapshot reuse decision** is **not separately auditable**: when `compute_deal_pnl` returns an existing candidate via lines 685-702, the route writes the same `entity_type="deal_pnl_snapshot", event_type="created"` row with the candidate's id. From audit history, an operator cannot distinguish a fresh computation from a reused candidate sealed at an earlier T. Finding J-CL1-OPUS-06.
- **Scenario run_what_if** has no `audit_event` dependency (`backend/app/api/routes/scenario.py:16-34`). Governance §"SCENARIO / WHAT-IF RULES" says scenario is in-memory only with no persistence — audit emission is therefore not required by §2.7. Logged in §4 Anti-findings considered.

### Q7 — Test coverage

- **D-1.1:** no test for `Deal.is_deleted` writes (because no route writes). No test for cross-deal uniqueness against an archived Order/HedgeContract. Coverage gap is partly impossible (no Deal soft-delete) and partly missing (archived-Order × DealLink × Deal P&L interaction).
- **D-1.2:** **strong coverage** at `backend/tests/test_pr5_lifecycle_acceptance.py:354, 489, 525, 540, 713, 742, 767` — retirement, idempotency, un-retire-fresh-row, HedgeTask cancellation chain, list filter, execute-side reject.
- **D-1.3:** `backend/tests/test_pnl_provenance.py:2202-2245` covers happy-path multi-commodity reuse. **No** test exercising underlying-entity mutation between snapshots. Becomes finding J-CL1-OPUS-12 because production code does not make the failure impossible.
- **D-1.4:** `backend/tests/test_scenario_whatif_run.py` covers behavioral cases (delta application, override provenance, virtual contracts) but **no** parity test comparing scenario aggregation against A1 live aggregation under shared inputs, and **no** test exercising archived-Order / archived-HedgeContract / dead-linkage entry into scenario inputs.

---

## §3 Findings

### Finding J-CL1-OPUS-01 — DealLink cross-deal uniqueness check ignores underlying Order/HedgeContract lifecycle

**Severity:** Tier 2 / High
**Status:** Open
**Deferral source:** D-1.1 (re-shaped — the entity-side analog of the original Deal-side gap is reachable today)

**Evidence:**
- `backend/app/services/deal_engine.py:158-165` — `create_deal` cross-deal uniqueness query: filters on `(DealLink.linked_type, DealLink.linked_id)` only.
- `backend/app/services/deal_engine.py:311-318` — `add_link` cross-deal uniqueness query: same pattern, no parent-entity filter.
- `backend/app/models/deal.py:175-179` — DB unique constraint `uq_deal_link_entity (linked_type, linked_id)` enforces uniqueness at the database boundary regardless of `Order.deleted_at` / `HedgeContract.deleted_at`.
- `backend/app/api/routes/orders.py:129-144` — `archive_order` sets `Order.deleted_at`.
- `backend/app/api/routes/contracts.py:89-104` — `archive_hedge_contract` sets `HedgeContract.deleted_at`.

**Failure mode:**
1. Operator creates Deal A linking Order O (variable-price ALU sales, 100 MT).
2. Operator archives Order O via `/orders/{O}/archive` — `Order.deleted_at` is set; the §3.8 retirement sweep retires the Exposure row.
3. Operator creates Deal B and tries to link a different Order O' that happens to share an identifier with O. Cross-deal uniqueness rejects with 409 ("This sales_order is already linked to deal A"), even though the entity is lifecycle-retired. The operator cannot reuse the identifier or release ownership; the only escape is `remove_link` on Deal A, which is also opaque (Deal A still presents the archived order as a member).
4. The 409 message references Deal A as the blocker, but `get_by_id` (deal_engine.py:1191) filters `Deal.is_deleted == False` — if the lifecycle is later extended to Deal, the reason for the block becomes irreconstructable.

**Governance impact:** §2.7 (audit reconstructability) — operator cannot reconstruct why a link is blocked when the owning entity is in a lifecycle-retired state. §2.1 (economic primitives integrity) — DealLink retains ownership over a retired entity that the rest of the system treats as gone.

**Recommended remediation boundary:** Add `Order.deleted_at IS NULL` / `HedgeContract.deleted_at IS NULL` joins to the cross-deal uniqueness query in both `create_deal` and `add_link`. Replace the DB `uq_deal_link_entity` unique constraint with a partial unique index (PG) excluding rows whose parent entity is archived, OR keep the constraint and add `is_deleted` to `DealLink` itself with a cascade-on-archive hook in `OrderService.archive` / `ContractService.archive`. Either path closes the gap; the partial-index path is smaller blast radius.

### Finding J-CL1-OPUS-02 — Deal soft-delete contract is partially wired (lifecycle field exists, no writer)

**Severity:** Tier 3 / Medium
**Status:** Open
**Deferral source:** D-1.1 (original Deal-side surface)

**Evidence:**
- `backend/app/models/deal.py:160-163` — `Deal.is_deleted` + `Deal.deleted_at` declared.
- `backend/app/services/deal_engine.py:886, 893, 1183, 1194` — four read-side filters on `Deal.is_deleted == False`.
- `backend/app/api/routes/contracts.py:200` — `contracts.py` reads `deal.is_deleted` in a guard.
- `rg "\.is_deleted\s*=\s*True" backend/app` returns no hit for `Deal`. No route, service method, or migration writes the lifecycle.
- `backend/app/api/routes/deals.py:81` — `find_deal_by_linked_entity` uses `session.get(Deal, link.deal_id)` (bypasses `Deal.is_deleted`); the same shape recurs in `compute_deal_pnl` at `deal_engine.py:553-557` via `get_by_id` (which DOES filter), but the polymorphic lookup `session.get(Deal, ...)` is the asymmetric one.

**Failure mode:** The model carries lifecycle metadata but no production path exercises it. A future PR that wires `/deals/{id}/archive` without an accompanying review of the read-side gaps will re-introduce the J-A1-OPUS-07 hazard verbatim: the cross-deal uniqueness check still won't filter `Deal.is_deleted`, and `find_deal_by_linked_entity` will silently surface deleted deals as resolvable. The lifecycle field is a loaded gun.

**Governance impact:** §2.7 — the absence of an explicit archive contract makes Deal soft-delete semantically undefined; any future writer makes the read-side regressions immediate.

**Recommended remediation boundary:** Either (a) **complete the contract** in a dedicated wave — add `/deals/{id}/archive` (POST) with cascade rules to DealLink (cascade or block-on-active-links), audit event emission, and Test coverage for cross-deal uniqueness vs archived deals; OR (b) **remove the dead lifecycle columns** until the route is needed (Migration: drop `is_deleted` / `deleted_at` from `deals`; service code stops filtering them; future re-introduction requires a deliberate spec). Option (b) is safer until the cascade contract is decided.

### Finding J-CL1-OPUS-03 — `find_deal_by_linked_entity` does not filter soft-deleted deals

**Severity:** Tier 3 / Medium
**Status:** Open
**Deferral source:** D-1.1 (latent today; activates the moment J-CL1-OPUS-02 option (a) is chosen)

**Evidence:**
- `backend/app/api/routes/deals.py:71-87` — `find_deal_by_linked_entity`:
  - Line 71-75 queries `DealLink` without a Deal-side filter.
  - Line 81 resolves the deal via `session.get(Deal, link.deal_id)` — bypasses `Deal.is_deleted`.
  - Line 82-86 only checks `if not deal`. A soft-deleted deal passes the check.

**Failure mode:** Once Deal soft-delete is wired, this route silently surfaces a deleted deal as the lookup target, contradicting `list_deals` and `get_by_id` which hide it.

**Governance impact:** §2.7 — read consistency across deal-resolution endpoints.

**Recommended remediation boundary:** Replace `session.get(Deal, link.deal_id)` with `DealEngineService.get_by_id(session, link.deal_id)`. One-line change. Bundle with the Deal soft-delete wave (or the J-CL1-OPUS-02 option-b removal).

### Finding J-CL1-OPUS-04 — Deal P&L and tonnage traversal includes archived Order / HedgeContract

**Severity:** Tier 2 / High
**Status:** Open
**Deferral source:** D-1.1 (entity-side analog) — see also Q5 cross-deferral.

**Evidence:**
- `backend/app/services/deal_engine.py:578-611` — `compute_deal_pnl` walks DealLink rows: `session.get(Order, link.linked_id)` at 583 and `session.get(HedgeContract, link.linked_id)` at 593. **No `Order.deleted_at` or `HedgeContract.deleted_at` filter.**
- `backend/app/services/deal_engine.py:918-957, 1036` — `compute_pnl_breakdown` repeats the same unfiltered traversal.
- `backend/app/services/deal_engine.py:1245-1269` — `_recompute_tons` queries Order/HedgeContract by id with no lifecycle filter. The `Deal.total_physical_tons`, `Deal.total_hedge_tons`, and `Deal.hedge_ratio` therefore include archived entities.
- `backend/app/services/exposure_engine.py:218-256` — §3.8 retirement sweep retires the Exposure for the same archived Order. The two surfaces disagree.

**Failure mode:**
1. Deal A has 100 MT SO of ALU linked.
2. Operator archives the SO. Reconcile runs → Exposure retired; `compute_net_exposure` shows zero ALU commercial active.
3. Operator triggers `POST /deals/A/pnl-snapshot` → `compute_deal_pnl` still values the archived SO at the current ALU market price; the snapshot rows show `physical_revenue = 100 * market_price`.
4. The operator's two dashboards (Exposure and Deal P&L) disagree about whether the 100 MT exists. There is no canonical answer reachable from code.

For a variable-price archived order, the inconsistency is worse: `compute_deal_pnl` requires a fresh market quote for a commodity that no longer has a live exposure, can hit `PriceReferenceUnprovable` purely because of an archived row, and (per J-CL1-OPUS-05) can also fall into the snapshot-reuse repair branch returning a sealed pre-archive valuation.

**Governance impact:** §2.1 (economic primitives integrity — Exposure and Deal must agree on which entities are live), §2.7 (reconstructability — operator cannot reconcile the views).

**Recommended remediation boundary:** Add `if order.deleted_at is not None: continue` (and the HedgeContract equivalent) inside the link traversal of `compute_deal_pnl`, `compute_pnl_breakdown`, and `_recompute_tons`. Three local changes; no schema impact. Bundle with J-CL1-OPUS-11 (same surface).

### Finding J-CL1-OPUS-05 — Snapshot reuse path hashes only link set and price_references; underlying entity mutations slip through

**Severity:** Tier 2 / High
**Status:** Open
**Deferral source:** D-1.3

**Evidence:**
- `backend/app/services/deal_engine.py:51-79` — `_compute_inputs_hash` payload = `{deal_id, snapshot_date, links (sorted UUIDs), price_references}`. **Order `price_type`, `quantity_mt`, `avg_entry_price` are not hashed.** **HedgeContract `status`, `quantity_mt`, `fixed_price_value` are not hashed.**
- `backend/app/services/deal_engine.py:685-703` — total-unavailability candidate probe recomputes `candidate_hash = _compute_inputs_hash(deal_id, snapshot_date, link_ids, candidate.price_references)`. Match returns the candidate.

**Failure mode (concrete):**
1. Deal A holds DealLink L → Order O (fixed-price 100 MT @ $2500, ALU). Snapshot S1 is created with `price_references = NULL` (no market price needed); hash H1 = sha256(deal, date, [L], None).
2. Operator edits Order O via the order-update path to change `price_type = variable` (link set unchanged). The deal's variable-price ALU position now requires a market lookup.
3. Westmetall feed is down. `compute_deal_pnl` enters the total-unavailability branch, iterates candidates ordered by sequence DESC. S1 hashes against `(deal, date, [L], None)` = H1 = stored. Match → S1 is returned.
4. The returned snapshot's `physical_revenue` was computed at $2500 × 100 = $250,000 (fixed-price methodology). The current state expected a variable-price valuation, but the operator now sees the stale fixed-price number masquerading as today's P&L.

The same shape fires for: a hedge contract moving `active → settled` (open MTM should now contribute zero, but the candidate's MTM is still in the row); a quantity edit (50 → 100 MT but candidate physical_revenue is still on 50 MT); an `avg_entry_price` correction.

**Governance impact:** §"no silent fallback" + §"evidence missing is hard-fail" — the reuse branch silently serves a sealed valuation as the current state when the underlying entity state has shifted. §2.7 — the snapshot's `inputs_hash` no longer proves the inputs are unchanged; it proves only that the link-id set and the recorded price references are unchanged.

**Recommended remediation boundary:** See **Decision** below. Either widen `_compute_inputs_hash` to include canonical content hashes of every linked Order / HedgeContract (large surface, deal-engine-only), or — the recommended path — remove the candidate-probe branch entirely.

**Decision (D-1.3, mandatory):** **REMOVE the candidate-probe branch; always propagate `PriceReferenceUnprovable` on total unavailability.**

Constitutional rationale: governance §"no silent fallback" is explicit. The snapshot-reuse branch is a fallback regime — it substitutes a sealed historical valuation for an absent live one without surfacing the substitution to the caller. The branch was justified in the original PR-8 commentary by an "idempotency under outage" goal: repeated POSTs during a price-feed outage should not toggle between 422 and a stale 200. That goal is already met by the standard hash-match lookup at `deal_engine.py:734-740` on the success path (identical inputs → identical hash → existing row). The outage path's idempotency need is operationally weak: an outage rarely persists past one operator retry, and the historical snapshot remains accessible via `GET /deals/{id}/pnl-history` independent of the compute endpoint. Conflating "retrieve historical" with "compute current" creates the silent-fallback hazard the governance forbids. The hash-extension alternative is feasible but invasive; the simpler reading of governance — "evidence missing is hard-fail" — favors removal.

Softer fallback (if removal is judged operationally unacceptable): require all three of (a) an explicit caller flag `force_repair_from_snapshot: bool = False` on the request body, (b) a distinct signed audit event per reuse (closes J-CL1-OPUS-06), and (c) hash extension to include underlying entity content. Implementing only one or two of (a)/(b)/(c) preserves the gap.

### Finding J-CL1-OPUS-06 — Snapshot reuse decision is not separately auditable

**Severity:** Tier 2 / High
**Status:** Open
**Deferral source:** D-1.3 (Q6 cross-cut)

**Evidence:**
- `backend/app/api/routes/deals.py:216-239` — `trigger_pnl_snapshot` wraps `compute_deal_pnl` in `audit_event(entity_type="deal_pnl_snapshot", event_type="created")` and calls `mark_audit_success(request, snapshot.id)` regardless of whether the returned snapshot was fresh or reused.
- `backend/app/services/deal_engine.py:702` — reuse return path; no audit hook on the service side either.

**Failure mode:** A signed audit row in the trail says "deal_pnl_snapshot X created at T2", but the snapshot's `inputs_hash` was actually sealed at T1 (the original creation time) and merely returned at T2 because the price feed was down. A future reviewer reconstructing the institutional state at T2 cannot distinguish "we computed fresh P&L at T2" from "we served the T1 snapshot because the feed was down at T2".

**Governance impact:** §2.7 — reconstructability requires that institutional decisions are distinguishable in the audit trail. Reusing a sealed snapshot during an outage is a distinct institutional decision from computing a fresh one; conflating them in audit history hides the outage event.

**Recommended remediation boundary:** This finding is **subsumed** by the J-CL1-OPUS-05 decision if the reuse branch is removed. If instead the softer fallback (J-CL1-OPUS-05 alternative) is adopted, the reuse path MUST emit a distinct audit event — `event_type="reused_during_outage"` with payload `{candidate_id, candidate_inputs_hash, unprovable_commodities: [...]}` — written before the return.

**Decision (D-1.3 corollary):** Tied to J-CL1-OPUS-05 decision. If the candidate-probe branch is removed, this finding closes; if it is preserved under the softer fallback, the audit emission is mandatory.

### Finding J-CL1-OPUS-07 — Scenario aggregation reads soft-deleted Orders / archived HedgeContracts

**Severity:** Tier 1 / Blocking
**Status:** Open
**Deferral source:** D-1.4

**Evidence:**
- `backend/app/services/scenario_whatif_service.py:213-221` — `_load_orders` returns `db.query(Order).order_by(Order.created_at.asc()).all()` with no `Order.deleted_at IS NULL` filter.
- `backend/app/services/scenario_whatif_service.py:224-225` — `_load_contracts` similarly returns all HedgeContracts unfiltered.
- `backend/app/services/scenario_whatif_service.py:228-229` — `_load_linkages` returns all `HedgeOrderLinkage` rows.
- `backend/app/services/scenario_whatif_service.py:259-281, 342-386` — both `_compute_commercial_exposure` and `_compute_global_exposure` consume the raw lists.
- Compare A1 — `backend/app/services/exposure_service.py:119, 131, 154, 177, 243, 256, 277, 305-310` — every A1 read filters `Order.deleted_at IS NULL`.

**Failure mode:** An operator archives Order O. Live A1 commercial exposure drops O from aggregation. Operator runs `POST /scenario/what-if/run` with an empty delta list. Scenario's `commercial_exposure_snapshot` still includes O. The operator's what-if state is *not* what-if-vs-current-live; it is what-if-vs-pre-archive. Decisions made on the scenario's projection are based on stale state.

**Governance impact:** §2.1 (economic primitives integrity — scenario and live must agree on which entities are economic primitives; lifecycle-retired entities are not primitives). §"SCENARIO / WHAT-IF RULES — Explicit deltas only" — scenario's baseline must be the current canonical live state; including archived entities is an *implicit* delta from live, which the governance forbids.

**Recommended remediation boundary:** Add `Order.deleted_at.is_(None)` filter in `_load_orders`, `HedgeContract.deleted_at.is_(None)` in `_load_contracts`. Three-line change. But the better boundary is the **D-1.4 decision** below: extract a shared primitive so scenario and live both consume already-filtered lists.

### Finding J-CL1-OPUS-08 — Scenario aggregation includes settled / cancelled HedgeContracts in global aggregation

**Severity:** Tier 1 / Blocking
**Status:** Open
**Deferral source:** D-1.4

**Evidence:**
- `backend/app/services/exposure_service.py:305-310, 327, 352-353, 376-378` — A1 global aggregation filters `HedgeContract.status.in_([active, partially_settled])` on every read.
- `backend/app/services/scenario_whatif_service.py:364-386` — scenario `_compute_global_exposure` iterates **all** contracts with no status filter. Settled hedges contribute their full `quantity_mt` to `total_hedge_long`/`total_hedge_short`, and the unlinked residual to `unlinked_hedge_long`/`unlinked_hedge_short`.
- `backend/app/services/scenario_whatif_service.py:466-467` — only the **MTM** computation in `run_what_if` filters non-active (`if contract.status != HedgeContractStatus.active: continue`). The exposure aggregation does not share that filter.

**Failure mode:** A historical settled hedge of 1000 MT short ALU still flows into scenario's `hedge_short_mt`. Live A1 `global_active_mt` excludes that 1000 MT. Scenario's `global_net_mt` differs from live's by the sum of settled hedge sides. The operator reading both side-by-side cannot reconcile.

**Governance impact:** §2.1; same as J-CL1-OPUS-07.

**Recommended remediation boundary:** Same as J-CL1-OPUS-07 — filter inside `_load_contracts` OR (preferred) close via D-1.4 decision below.

### Finding J-CL1-OPUS-09 — Scenario aggregation uses raw HedgeOrderLinkage rows without lifecycle filter

**Severity:** Tier 1 / Blocking
**Status:** Open
**Deferral source:** D-1.4

**Evidence:**
- `backend/app/services/exposure_service.py:42-58` — A1 `_linked_by_order_subquery` filters by hedge contract liveness.
- `backend/app/services/exposure_service.py:295-313` — A1 `linked_by_contract` filters by both hedge contract liveness AND `Order.deleted_at IS NULL`.
- `backend/app/services/scenario_whatif_service.py:228-229, 237-241, 312-323` — scenario's `linked_by_order` and `linked_by_contract` dicts are built from the raw `_load_linkages` list with no filter.

**Failure mode:** A linkage from an archived order to a live hedge still subtracts from the hedge's residual in scenario. A linkage from a live order to a settled hedge still reduces the order's residual in scenario. Both subtractions are absent in live A1. Scenario's `commercial_active_mt` and `global_active_mt` divergence stack on top of J-CL1-OPUS-07/08.

**Governance impact:** §2.1; same surface.

**Recommended remediation boundary:** Same — close via D-1.4 decision below.

### Finding J-CL1-OPUS-10 — Scenario aggregation casts Decimal residuals to `float()` in returned DTOs

**Severity:** Tier 3 / Medium
**Status:** Open
**Deferral source:** D-1.4

**Evidence:**
- `backend/app/services/scenario_whatif_service.py:291-300, 422-441` — `CommercialExposureRead` / `GlobalExposureRead` fields are populated via `float(item["..."])`.
- A1's `compute_commercial_snapshot` and `compute_global_snapshot` build `Decimal` values quantized at `MT_NUMERIC_SCALE`; the route serializes them as Decimals.

**Failure mode:** Scenario aggregation values display drift from A1 live aggregation values by float-rounding error (e.g. a 5723.456 MT residual becomes 5723.4560000000003 MT or rounded variant). The deltas are sub-MT and below operational reporting precision — but they break byte-equal reconciliation between scenario and live snapshots, which would otherwise serve as a regression test.

**Governance impact:** §2.7 — reconstructability across views is degraded when scenario and live disagree on numeric type.

**Recommended remediation boundary:** Change `float(...)` to `quantize_mt(...)` in the scenario DTO builders. Two-line change. Bundle with D-1.4 decision wave.

**Decision (D-1.4, mandatory):** **Extract a shared pure exposure primitive in `ExposureService`.**

Constitutional rationale: §2.1 is explicit that exposure is the canonical economic primitive; two implementations of the same primitive is a §2.1 violation by construction, and the four concrete divergences above (J-CL1-OPUS-07/08/09/10) are direct symptoms. The smallest fix boundary is:

```python
# in backend/app/services/exposure_service.py
class ExposureService:
    @staticmethod
    def compute_commercial_exposure_pure(
        *,
        orders: list[tuple[Order, Decimal]],
        linkages: list[HedgeOrderLinkage],
        calculation_timestamp: datetime,
    ) -> list[CommercialExposureRead]: ...

    @staticmethod
    def compute_global_exposure_pure(
        *,
        orders: list[tuple[Order, Decimal]],
        contracts: list[HedgeContract],
        virtual_contracts: list[VirtualHedgeContract],
        linkages: list[HedgeOrderLinkage],
        calculation_timestamp: datetime,
    ) -> list[GlobalExposureRead]: ...
```

The pure primitives accept already-filtered input lists, apply canonical aggregation rules (residual non-negative validation, sign conventions, `canonical_commodity` normalisation, MT-scale quantize), and return Decimal-typed DTOs. Then:

- Live A1 routes (`compute_commercial_snapshot`, `compute_global_snapshot`) become thin SQL-side filters + calls into the pure primitives.
- Scenario `_compute_commercial_exposure` / `_compute_global_exposure` shrink to: filter `_load_orders` / `_load_contracts` / `_load_linkages` for lifecycle + status (matching A1's SQL filters), append virtual contracts, then call the pure primitives.

The total fix boundary is one new module-level primitive (≈80 lines), two thin call sites in A1 routes (refactor), and one thin call site in scenario (refactor). No production aggregation logic changes — the pure primitive is *the* canonical aggregation; both consumers delegate to it. Any future A1 evolution (e.g. a new commodity canonicalization, a new clamp rule, a sign-convention correction) reaches scenario automatically.

### Finding J-CL1-OPUS-11 — Cross-deferral: Deal P&L view diverges from Exposure retirement view

**Severity:** Tier 1 / Blocking
**Status:** Open
**Deferral source:** Fresh (D-1.1 × D-1.2 interaction; neither A1 nor A3 audit saw this independently)

**Evidence:** See J-CL1-OPUS-04. The traversal evidence is the same; the *cross-cluster* failure mode is what is new:

| Surface | Reads archived Order? | Result |
| --- | --- | --- |
| `ExposureService.compute_commercial_snapshot` (A1 closed) | No — filters `Order.deleted_at IS NULL` | Archived order is invisible |
| `ExposureEngineService.reconcile_from_orders` §3.8 sweep | No — retires the Exposure for the archived Order | Exposure shows zero |
| `ExposureEngineService.compute_net_exposure` | No — filters `Exposure.is_deleted == False` AND `Order.deleted_at IS NULL` | Archived order is invisible |
| `DealEngineService._recompute_tons` | **Yes** — no filter | 100 MT counted |
| `DealEngineService.compute_deal_pnl` | **Yes** — no filter | physical_revenue/cost includes archived order |
| `DealEngineService.compute_pnl_breakdown` | **Yes** — no filter | same |

**Failure mode:** Two dashboards built on the same canonical model report disagree about which entities are live. There is no canonical answer reachable from the code — both readers believe themselves authoritative. The economic-correctness invariant (§2.1) requires exactly one canonical state; this surfaces two.

**Governance impact:** §2.1 (single canonical economic state across views) + §2.7 (reconstructability — operator cannot determine which view to believe).

**Recommended remediation boundary:** Add `Order.deleted_at IS NULL` filter to the Order traversal in `_recompute_tons`, `compute_deal_pnl`, and `compute_pnl_breakdown`. Add `HedgeContract.deleted_at IS NULL` to the HedgeContract traversal in the same three functions. This is a 3-file local change; the alternative is a wider refactor extracting a shared "live-only link iterator", which is overkill for this surface.

### Finding J-CL1-OPUS-12 — Test gap for snapshot-reuse staleness under entity mutation

**Severity:** Tier 3 / Medium
**Status:** Open
**Deferral source:** D-1.3 (Q7 test coverage)

**Evidence:**
- `backend/tests/test_pnl_provenance.py:2202-2245` — `test_compute_deal_pnl_total_unavailability_reuses_candidate` covers happy-path reuse where the candidate hash matches because no mutation has happened.
- No test in `backend/tests/` mutates `Order.price_type`, `Order.quantity_mt`, `Order.avg_entry_price`, or `HedgeContract.status` between snapshot creation and a subsequent `compute_deal_pnl` call.

**Failure mode:** J-CL1-OPUS-05's failure mode is not protected by any test today. A future regression — say, dropping `price_type` from the hash payload was an accident that the hash extension was supposed to capture — would land green.

**Governance impact:** This is a Tier 3 because production code does not otherwise make the failure impossible. If the J-CL1-OPUS-05 decision (remove the reuse branch) is adopted, this gap closes by construction. If the softer fallback is chosen, this test must land alongside.

**Recommended remediation boundary:** A single property-style test that: (a) creates a deal + link + snapshot; (b) edits the underlying Order's `price_type` (or quantity); (c) monkeypatches `_get_market_quote` to raise `PriceReferenceUnprovable`; (d) asserts the snapshot is NOT reused (i.e. the call raises). If the J-CL1-OPUS-05 decision lands, the assertion is "raises PriceReferenceUnprovable". If the softer fallback lands, the assertion is "raises unless force_repair_from_snapshot=True AND audit event emitted".

---

## §4 Anti-findings considered

### A-CL1-OPUS-01 — D-1.2 Exposure soft-delete duplicate-source semantics

**Inspected:** retirement sweep, un-retire path, HedgeTask cancellation chain, list/execute readers, idempotency.
**Disposition:** Closed. The §3.8 sweep retires Exposure for soft-deleted Orders; Codex P2 cancels pending HedgeTasks inline; seven readers filter `Exposure.is_deleted == False`; `test_pr5_lifecycle_acceptance.py` covers retirement, idempotency, un-retire-fresh-row, task cancellation, list filter, and execute reject. No promotable Tier 1/2/3 finding remains on the D-1.2 surface itself. The interaction with Deal (J-CL1-OPUS-11) is logged separately as cross-deferral.

### A-CL1-OPUS-02 — Scenario should emit audit events under §2.7

**Inspected:** `backend/app/api/routes/scenario.py:16-34` — no audit dependency.
**Disposition:** Not a finding. Governance §"SCENARIO / WHAT-IF RULES" explicitly forbids persistence and constrains scenario to "in-memory only / No timeline / No cache reuse". §2.7 reconstructability does not apply to a path the constitution says is not a mutation. The route's request body is captured by the standard request-log surface (FastAPI access logs), which is sufficient for "what was asked".

### A-CL1-OPUS-03 — `cancel_stale_tasks` does not filter `Exposure.is_deleted`

**Inspected:** `backend/app/services/exposure_engine.py:506-516`.
**Disposition:** Not a finding. The retirement sweep proactively cancels pending tasks for retired Exposures (lines 244-254). `cancel_stale_tasks` only catches `Exposure.status in (fully_hedged, cancelled)`; a retired Exposure with `status=open` could in principle slip through, but its tasks are cancelled at sweep time, and downstream reads (`list_pending_tasks`, `execute_task`) filter `is_deleted` defensively. No reachable failure mode.

### A-CL1-OPUS-04 — `DealLink` lacks lifecycle column

**Inspected:** `backend/app/models/deal.py:171-194`.
**Disposition:** Not a standalone finding. Whether DealLink needs `is_deleted` depends on the Deal soft-delete remediation decision (J-CL1-OPUS-02 option a vs b). If option (a) is chosen and the cascade strategy is "soft-delete links symmetrically with the parent deal", the column is required. If option (a) chooses "cascade-hard-delete with audit", the column is unnecessary. If option (b) is chosen, the question is moot. Filed under J-CL1-OPUS-02's remediation, not as its own finding.

---

## §5 Cross-cluster deferrals

These items surfaced during Cluster 1 inspection but belong to a different cluster:

- **Cluster 3 (D-3.1 RBAC matrix):** Several Cluster 1 remediations (e.g. `/deals/{id}/archive` route in J-CL1-OPUS-02 option a) require an explicit RBAC role assignment. The current `require_any_role("trader", "risk_manager")` pattern in `deals.py` is consistent with peers, but the institutional question "who can archive a deal" warrants the D-3.1 RBAC matrix being defined first. Not a Cluster 1 finding.
- **Cluster 4 (D-4.1 market-data governance):** The J-CL1-OPUS-05 decision interacts with market-data outage handling. If the platform's stale-feed contract (part of D-4.1) is later defined to allow a bounded staleness window for D-1 prices, the J-CL1-OPUS-05 decision can be revisited. As of `ba032f476`, the constitution forbids fallback regimes, so the audit's recommendation stands.
- **No spillover to Cluster 2:** Cluster 2 (PR #71) closed RFQ actor JWT derivation + status endpoint settled rejection. None of the Cluster 1 findings re-litigate those surfaces.

---

## §6 Recommended remediation waves

The findings cluster naturally into four waves. Wave 1 has the smallest blast radius and highest closure density; later waves depend on the institutional decisions in J-CL1-OPUS-05 / J-CL1-OPUS-10 / J-CL1-OPUS-02.

### Wave 1 — Deal-side lifecycle parity (closes J-CL1-OPUS-04 + J-CL1-OPUS-11)

**Scope:** Add `Order.deleted_at IS NULL` and `HedgeContract.deleted_at IS NULL` filters to the three Deal-side traversals: `compute_deal_pnl`, `compute_pnl_breakdown`, `_recompute_tons`. New test: archive an order linked to a deal, assert that:
- `_recompute_tons` excludes it from `total_physical_tons`.
- `compute_deal_pnl` does not request a market quote for it.
- `compute_pnl_breakdown` does not include it in `physical_items`.

**Blast radius:** 1 service file, ~10 lines. No schema, no migration.

### Wave 2 — D-1.4 shared exposure primitive (closes J-CL1-OPUS-07/08/09/10)

**Scope:** Extract `ExposureService.compute_commercial_exposure_pure` and `compute_global_exposure_pure`. Refactor A1 routes (`/exposures/commercial`, `/exposures/global`) and scenario `_compute_commercial_exposure` / `_compute_global_exposure` to call into them. Scenario also filters `_load_orders` / `_load_contracts` for lifecycle + status before passing to the pure primitives. Replace `float(...)` with `quantize_mt(...)` in scenario DTO builders. New tests: parity test asserting `scenario.commercial_exposure_snapshot == A1.compute_commercial_snapshot()` when scenario's delta list is empty AND no archived entities exist.

**Blast radius:** 1 new module-level primitive (~80 lines), 4 thin call-site refactors, 1 parity test class. No schema, no migration.

### Wave 3 — D-1.3 snapshot reuse decision (closes J-CL1-OPUS-05/06/12)

**Scope (recommended path):** Remove the candidate-probe branch from `compute_deal_pnl`. Always propagate `PriceReferenceUnprovable` on total unavailability. Add a test asserting the propagation. The existing happy-path test (`test_compute_deal_pnl_total_unavailability_reuses_candidate`) inverts: expected behavior becomes 422, not a returned snapshot.

**Scope (softer fallback):** If institutional review at Stage 3 prefers preserving the reuse path, mandate all three of: (a) `force_repair_from_snapshot` request flag, (b) `event_type="reused_during_outage"` audit emission with candidate id + unprovable commodities + original inputs_hash, (c) hash extension to include canonical content hashes of every linked Order / HedgeContract (≈40 lines of new `_compute_inputs_hash` payload + ≈10 lines of caller plumbing).

**Blast radius (recommended path):** ~20 lines removed from `compute_deal_pnl`, 1 test refactor, 1 new propagation test. **The softer fallback is roughly 4× the blast radius and preserves a known-fragile branch.**

### Wave 4 — Deal soft-delete contract decision (closes J-CL1-OPUS-01/02/03)

**Scope:** Choose one of:
- **Option a — complete the contract.** New `/deals/{deal_id}/archive` POST route with `audit_event`. New cascade rule on DealLink (recommended: soft-delete-symmetric; new `DealLink.is_deleted` column + alembic head). Filter join `Deal.is_deleted == False` added to cross-deal uniqueness in `create_deal` + `add_link`. `find_deal_by_linked_entity` switched to `get_by_id`. Tests: archive, cross-deal uniqueness vs archived, find_by_linked_entity rejects archived. RBAC role assignment (typically `risk_manager`).
- **Option b — remove the dead lifecycle.** Drop `Deal.is_deleted` / `Deal.deleted_at`. Drop the four read-side filters. Drop `contracts.py:200` guard. Drop the asymmetric `session.get(Deal, ...)` issue (becomes moot). New alembic head.

Wave 4 is **decision-blocked** until product-side commitment to whether Deal soft-delete is a needed operation. Until then, Option b is the lower-risk default (no loaded gun).

**Blast radius (option a):** 1 route, 1 service method, 1 cascade hook, 1 column + migration, 4 test classes. Medium.
**Blast radius (option b):** 1 service deletion of 4 filter lines, 1 column drop + migration, 1 small contracts.py guard removal. Small.

---

## §7 Mandatory institutional decisions

For traceability, the two D-* decisions returned by this Stage 1 audit:

| Surface | Decision | Rationale anchor |
| --- | --- | --- |
| **D-1.3** | **Remove the candidate-probe reuse branch from `compute_deal_pnl`; always propagate `PriceReferenceUnprovable` on total unavailability.** Softer fallback documented in J-CL1-OPUS-05 if the jury overrides. | §"no silent fallback" + §"evidence missing is hard-fail"; J-CL1-OPUS-05 demonstrates concrete staleness; idempotency goal already met by hash-match success-path. |
| **D-1.4** | **Extract `ExposureService.compute_commercial_exposure_pure` / `compute_global_exposure_pure`; refactor A1 routes and scenario to delegate.** | §2.1 (single canonical economic primitive); four concrete divergences today (J-CL1-OPUS-07/08/09/10) prove drift is realised, not hypothetical. |

---

## §8 Workflow attestation

Per dispatch §10 the following sequence was executed:

1. Read `docs/governance.md`. ✓
2. Read `docs/audits/2026-05-13-cross-phase-deferral-backlog.md` §Cluster 1. ✓
3. Read A1 jury verdict J-A1-OPUS-07/08 at `docs/audits/2026-05-06-phase-a1-jury-verdict.md:328-374`. ✓
4. Read A3 jury verdict X-A3-J-01/02 at `docs/audits/2026-05-09-phase-a3-jury-verdict.md:163-175`. ✓
5. Derived current backend surface via `rg`-style queries (deal lifecycle touchpoints, DealLink readers/writers, exposure soft-delete filters, scenario aggregation, snapshot reuse, PriceReferenceUnprovable). ✓
6. Inspected primary scope files at `main @ ba032f476`:
   - `backend/app/models/deal.py` (full file).
   - `backend/app/models/exposure.py` (full file).
   - `backend/app/services/deal_engine.py` (full file).
   - `backend/app/services/exposure_engine.py` (full file).
   - `backend/app/services/exposure_service.py` (full file).
   - `backend/app/services/scenario_whatif_service.py` (full file).
   - `backend/app/api/routes/deals.py` (full file).
   - `backend/app/api/routes/scenario.py` (run_what_if_scenario via symbolic read).
   - `backend/app/api/routes/exposures.py` (audit_event surface via grep).
   - `backend/tests/test_pr5_lifecycle_acceptance.py` (retirement / un-retire / task chain coverage via grep).
   - `backend/tests/test_pnl_provenance.py:2190-2245` (snapshot-reuse coverage).
   - `backend/tests/test_deal_engine.py` (TestDealLinks / TestPNLSnapshot via symbolic overview).
   - `backend/tests/test_scenario_whatif_run.py` (symbol overview).
7. Validated each finding against current code at `main @ ba032f476`; cited line ranges are derived from re-reads at that SHA, not from the original A1/A3 verdicts.
8. Produced explicit decisions for D-1.3 and D-1.4 in §3 and consolidated in §7.
9. Wrote this report to `docs/audits/2026-05-13-cluster-1-findings-opus.md`.
10. No other file edited.

Commands executed: none (read-only via Read / Grep / Glob / Serena symbolic tools). `pytest` and `python -m alembic heads` were not run in this session; the dispatch allows continuing with direct code evidence when commands are unavailable.

---

End of Stage 1 findings — Auditor A (Opus 4.7).
