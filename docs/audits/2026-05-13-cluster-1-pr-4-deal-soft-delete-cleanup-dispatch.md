# Cluster 1 Remediation Dispatch — PR-CL1-4 — Deal Soft-Delete Contract Cleanup

**Cluster:** 1 — A1 follow-up (deal-engine + exposure + scenario boundaries)
**Wave:** PR-CL1-4 (4 of 4)
**Authoring date:** 2026-05-13
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main` (HEAD `ea08d9868` post-PR-#73)
**Required branch:** `audit-followup/cluster-1-deal-soft-delete-cleanup`
**Source verdict:** `docs/audits/2026-05-13-cluster-1-jury-verdict.md` §J-CL1-02, §PR-CL1-4 wave entry, §Self-Bias Confession

## 1. Objective

Close **J-CL1-02** (Tier 3 / Medium) — the Deal soft-delete contract is half-wired. `Deal.is_deleted` and `Deal.deleted_at` exist on the model, Deal readers filter on them, one linked-entity resolver (`find_deal_by_linked_entity`) bypasses the filter, but **no current route writes `Deal.is_deleted = True`**. The contract is internally inconsistent and a future Deal archive endpoint would immediately activate the original D-1.1 hazard (invisible-Deal-owns-active-DealLinks).

This wave is a **decision-fork dispatch**. The implementer must run a pre-step against production data and pick exactly one of two paths:

- **Path A (remove dead fields):** No Deal archive feature exists or is planned. Remove `Deal.is_deleted` and `Deal.deleted_at` columns and all readers that filter on them. Restore `find_deal_by_linked_entity` to consistency by removing the half-wired filter logic everywhere.

- **Path B (implement Deal archive properly):** Production data already contains `deals WHERE is_deleted = true`, or the product team has signalled that Deal archive is needed. Implement a `PATCH /deals/{id}/archive` route with signed audit event, RBAC, **explicit DealLink cascade or block semantics**, and reader filters everywhere (including `find_deal_by_linked_entity`).

The verdict's self-bias confession is explicit: "if production data already contains `deals.is_deleted = true` rows… J-CL1-02 should be promoted from Tier 3 to Tier 2 and handled before new lifecycle work." That promotion gate is the binding criterion for path selection.

## 2. Non-Negotiable Constraints

- Do **not** edit `docs/governance.md`.
- Do **not** start implementation before the production-data pre-step has produced a recorded result. The path choice is binding once made.
- Do **not** mix Path A and Path B. The verdict explicitly says "either remove `Deal.is_deleted` / `Deal.deleted_at` until Deal archive is actually supported, or add a proper `/deals/{id}/archive` contract… Do not add a Deal archive route without resolving DealLink semantics."
- Do **not** widen scope into any other wave (PR-CL1-1, PR-CL1-2, PR-CL1-3). Soft-delete contract cleanup stays in its own file set.
- Do **not** add a Deal archive route along Path A. Path A removes the lifecycle fields; it does not add an endpoint.
- Do **not** add a Deal archive route along Path B without also wiring **DealLink cascade or block semantics** + signed audit event + RBAC. The half-wired-with-route state is the worst of all worlds — it activates the D-1.1 hazard the original A1 audit identified.

### 2.1 Migration discipline

Path A **requires a migration** to drop `Deal.is_deleted` and `Deal.deleted_at` columns. Path B **may require a migration** if it adds `DealLink.deleted_at` (or `DealLink.is_deleted`) symmetrically to the soft-delete cascade. **Cluster 2's single-alembic-head invariant carries forward** as a hard constraint:

- If Path A: the dispatch authorizes exactly one new migration that drops the two columns. New head becomes `044_drop_deal_lifecycle_fields` (or equivalent name). Single-head chain preserved.
- If Path B without cascade column: no migration needed. Single-head chain preserved trivially.
- If Path B **with** `DealLink.deleted_at` cascade column: the wave must add one migration. New head becomes `044_dealink_lifecycle_columns` (or equivalent). Single-head chain preserved.
- If Path B **requires more than one migration** (e.g. column add + backfill + index + constraint): **fail loud**. Defer this wave to a separate cycle. Multi-migration waves break the §6.3 invariant carried forward from Cluster 2.

The single-head property must be assertable via `python -m alembic heads` after the migration is added.

## 3. Findings and Evidence

Verified at HEAD `ea08d9868`.

### Half-wired Deal lifecycle

- `backend/app/models/deal.py:160-163` — `Deal` has `is_deleted: Mapped[bool]` and `deleted_at: Mapped[datetime | None]` columns.
- `backend/app/models/deal.py:171-194` — `DealLink` has **no** lifecycle columns. Two unique constraints: `(deal_id, linked_type, linked_id)` and `(linked_type, linked_id)`. The second one is the cross-deal block that becomes the D-1.1 hazard if a Deal archive route is added without cascade semantics.
- `backend/app/services/deal_engine.py:886`, `:893`, `:1183`, `:1194` — Deal readers (list / get / detail) filter `Deal.is_deleted == False`. These work today only because no writer sets `is_deleted = True`.
- `backend/app/api/routes/deals.py:71-87` — `find_deal_by_linked_entity` resolves the Deal via `session.get(Deal, link.deal_id)` without the standard `is_deleted == False` filter. This is the half-wired inconsistency: a future archived Deal would still be returned by this endpoint.
- `rg -nP "Deal\\.is_deleted\\s*=\\s*True|Deal\\.deleted_at\\s*=" backend/app` — must be re-verified by the implementer. The verdict reports zero matches; if any writer exists at implementation time, the path selection automatically becomes Path B.

### Production-data pre-step (binding for path selection)

The implementer must run the following query against a representative production-equivalent database (staging snapshot or production read-replica; **not** a fresh empty test DB):

```sql
SELECT COUNT(*) FROM deals WHERE is_deleted = true;
SELECT COUNT(*) FROM deals WHERE deleted_at IS NOT NULL;
```

Record both counts in the PR body.

- **Both counts are zero** → Path A is the binding choice.
- **Either count is non-zero** → Path B is the binding choice, and the J-CL1-02 severity is implicitly promoted to Tier 2 per the verdict's self-bias confession.

If no production-equivalent database is accessible to the implementer, **stop and escalate to Andrei**. Do not pick a path on speculation. The dispatch authorizes a stop here.

## 4. Required Implementation Boundary — Path A

Only execute this section if the §3 pre-step produced zero rows.

### 4.1 Model

- `backend/app/models/deal.py:160-163` — remove the `is_deleted` and `deleted_at` columns from `Deal`.

### 4.2 Schema (DealRead) — required, not optional

`backend/app/schemas/deal.py:83-96` defines `DealRead` with `is_deleted: bool` as a required field at line 97. After Path A drops the model column, every Deal response (`GET /deals`, `POST /deals`, `GET /deals/by-linked-entity`, `GET /deals/{id}`, plus any consumer of `DealDetailRead` which inherits from `DealRead`) would fail Pydantic validation in `from_attributes` mode because the ORM object no longer carries the field. Path A must therefore:

- Remove the `is_deleted: bool` line from `DealRead` in `backend/app/schemas/deal.py`.
- Verify `DealDetailRead` (and any other subclass of `DealRead`) inherits the cleanup automatically; remove any local override of `is_deleted` if present.
- The schema currently has **no** `deleted_at` field, so no `deleted_at` removal is required at the schema layer (it never existed there).
- Regenerate `docs/api/openapi_v1.json` and `frontend-svelte/src/lib/api/schema.d.ts` after the schema edit. The OpenAPI delta is bounded to dropping `is_deleted` from the Deal-related response components; no other endpoint shape changes.
- Verify no frontend route consumes `Deal.is_deleted` (verified clean at HEAD `ea08d9868` via `rg "deal.*is_deleted|deal.*deleted_at|\\.is_deleted\\b" frontend-svelte/src/routes/` returning zero matches; the implementer must re-confirm at branch tip; if a new consumer has appeared, add it to the wave's frontend follow-up scope).

### 4.3 Migration

Add one alembic revision `044_drop_deal_lifecycle_fields.py` (or equivalent name) with:

```python
def upgrade() -> None:
    op.drop_column("deals", "deleted_at")
    op.drop_column("deals", "is_deleted")


def downgrade() -> None:
    op.add_column("deals", sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("deals", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    # The columns are restored; data is not restored (none existed before drop).
```

`down_revision` must be the current single head (`043_a5_audit_payload_input`). New head `044_drop_deal_lifecycle_fields`. Single head invariant preserved.

### 4.4 Service filters

- `backend/app/services/deal_engine.py:886`, `:893`, `:1183`, `:1194` — remove the `.filter(Deal.is_deleted == False)` / equivalent clauses. The readers no longer need a soft-delete predicate.

### 4.5 Route filter (`find_deal_by_linked_entity`)

- `backend/app/api/routes/deals.py:71-87` — already does not filter `is_deleted`. Path A makes that absence consistent: no action required at this site.

### 4.6 Tests

- Any test that asserts a Deal can be soft-deleted via direct model mutation (e.g. `deal.is_deleted = True` in a fixture) must be updated to either:
  - Hard-delete the Deal via `session.delete(deal)`, OR
  - Mark the test xfail / remove it if the underlying scenario no longer exists.

Sweep `rg -nP "Deal\\.is_deleted|\\.is_deleted = True" backend/tests/` and resolve every match.

## 5. Required Implementation Boundary — Path B

Only execute this section if the §3 pre-step produced at least one row, or if Andrei explicitly authorizes Path B based on product roadmap intent.

### 5.0 Schema (DealRead)

Path B preserves `Deal.is_deleted` and `Deal.deleted_at` on the model. The current `DealRead` schema (`backend/app/schemas/deal.py:83-96`) already exposes `is_deleted: bool` (line 97) but **does not** expose `deleted_at`. The archive route added in §5.1 sets `Deal.deleted_at = now_utc()`; without a corresponding read field, the operator-visible response cannot show when the archive happened. Path B must:

- Add `deleted_at: Optional[datetime] = None` to `DealRead` immediately after `is_deleted: bool`. Use `Optional[datetime]` with default `None` so existing pre-archive rows continue to validate (their `deleted_at` is `NULL`).
- Inherited subclasses (`DealDetailRead`) pick up the new field automatically.
- Regenerate `docs/api/openapi_v1.json` and `frontend-svelte/src/lib/api/schema.d.ts`. The OpenAPI delta is bounded to adding the optional `deleted_at` field on Deal-related response components.
- The frontend currently does not consume `Deal.deleted_at` (verified clean at HEAD via `rg "deal.*deleted_at" frontend-svelte/src/routes/`); the new field surface is available for future operator UI work but is not a frontend follow-up requirement of this wave.

### 5.1 Route

Add `PATCH /deals/{id}/archive` to `backend/app/api/routes/deals.py`:

- Path: `PATCH /deals/{deal_id}/archive`
- Response: `DealRead` (the archived deal)
- RBAC: `require_role("risk_manager")` (or `require_any_role("risk_manager", "trader")` if product confirms trader-level archive is acceptable; default to risk_manager only).
- Audit event: `audit_event(entity_type="deal", event_type="archived")` decorator following the pattern from `archive_order` / `archive_hedge_contract`.
- Behavior: set `Deal.is_deleted = True` and `Deal.deleted_at = now_utc()` inside `unit_of_work` + `mark_audit_success`.

### 5.2 DealLink cascade decision

The verdict mandates that Path B resolves DealLink semantics. Choose **exactly one**:

- **Cascade-with-soft-delete**: add `DealLink.deleted_at: Mapped[datetime | None]` column via migration; archive route marks each linked DealLink with `deleted_at = now_utc()`; cross-deal uniqueness query in `add_link` filters live links only (`DealLink.deleted_at.is_(None)`). **Critical (Codex P2 catch on PR #74 v3)**: this option also requires **replacing the existing unconditional unique constraints** on `DealLink` with **partial unique indexes** scoped to live rows. Verified at HEAD `ea08d9868` that `backend/app/models/deal.py:171-194` declares two unconditional `UniqueConstraint`s — `("deal_id", "linked_type", "linked_id", name="uq_deal_link")` and `("linked_type", "linked_id", name="uq_deal_link_entity")`. The cross-deal `uq_deal_link_entity` is the killer: even after Deal X archives and the DealLink soft-deletes (`deleted_at = now()`), inserting a new DealLink for Deal Y with the same `(linked_type, linked_id)` would fail at the **DB level** with `IntegrityError` **before** the app-level filter helps. The §5.5 test #3 ("Relink a freed entity") would fail. The migration must therefore: (a) add `DealLink.deleted_at` column, (b) drop both existing `UniqueConstraint`s, and (c) create two partial unique indexes scoped to `WHERE deleted_at IS NULL` (PostgreSQL syntax: `CREATE UNIQUE INDEX uq_deal_link_live ON deal_links (deal_id, linked_type, linked_id) WHERE deleted_at IS NULL` and similarly `uq_deal_link_entity_live`). All three operations live in **one** alembic revision (multiple `op.*` calls in one file is single-head-compliant). If the implementer determines that splitting into multiple revisions is necessary (e.g. for backfill or data correction), per §2.1 this option becomes deferral-eligible and the implementer must escalate to Andrei before proceeding.
- **Cascade-with-hard-delete**: archive route issues `session.delete(link)` for every DealLink belonging to the archived Deal. No new column. Cross-deal uniqueness query unchanged. Trade-off: link history is lost; signed audit event must capture the snapshot before deletion.
- **Block-on-active-links**: archive route raises 409 if the Deal has any DealLink rows; operator must `remove_link` each link first. No new column.

The chosen path is final; do not implement two and let the caller choose.

### 5.3 Migration (only if cascade-with-soft-delete chosen)

Add one alembic revision `044_dealink_lifecycle_columns.py` (or equivalent name) that performs **three** operations in a single revision:

1. `op.add_column("deal_links", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))` — add the lifecycle column. (Optionally also `is_deleted` for symmetry with `Order` / `HedgeContract` / `Exposure`, but `deleted_at IS NULL` alone is sufficient as the live predicate.)
2. `op.drop_constraint("uq_deal_link", "deal_links", type_="unique")` and `op.drop_constraint("uq_deal_link_entity", "deal_links", type_="unique")` — drop the existing unconditional unique constraints (verified at HEAD `ea08d9868`, `backend/app/models/deal.py:171-194`).
3. `op.create_index("uq_deal_link_live", "deal_links", ["deal_id", "linked_type", "linked_id"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))` and `op.create_index("uq_deal_link_entity_live", "deal_links", ["linked_type", "linked_id"], unique=True, postgresql_where=sa.text("deleted_at IS NULL"))` — create partial unique indexes scoped to live rows. PostgreSQL native syntax. SQLite supports the same `WHERE` clause on `CREATE UNIQUE INDEX` (alembic generates it via the `sqlite_where` keyword if the target dialect is SQLite — verify the project's alembic config).

Update `backend/app/models/deal.py` `__table_args__` to remove the two `UniqueConstraint`s and add `Index(..., unique=True, postgresql_where=text("deleted_at IS NULL"))` declarations matching the new partial indexes.

`down_revision` must be the current single head (`043_a5_audit_payload_input`). New head becomes `044_dealink_lifecycle_columns` (or your chosen name). `python -m alembic heads` must print exactly one head after the revision.

The three operations together close the §5.5 test #3 ("Relink a freed entity") — without the partial-index replacement, the relink would fail at the DB level with `IntegrityError` even after the soft-delete sets `deleted_at`. The unconditional `uq_deal_link_entity` is the cross-deal block that prevents reuse; only the partial-index variant correctly scopes uniqueness to live rows.

If the implementer determines that the three operations cannot fit in a single alembic revision (e.g. backfill requirements, dialect-specific incompatibility), per §2.1 this entire option becomes deferral-eligible — escalate to Andrei before proceeding. Do not split into multiple revisions silently.

If the cascade decision chosen is **not** cascade-with-soft-delete, no migration is needed.

### 5.4 Reader filter on `find_deal_by_linked_entity`

`backend/app/api/routes/deals.py:71-87` — add `.filter(Deal.is_deleted == False)` to the Deal resolution (or use the same helper that other readers use). The half-wired filter inconsistency is closed.

### 5.5 Tests

Add `backend/tests/test_deal_archive.py` covering:

1. **Archive a Deal with no links** — assert `Deal.is_deleted == True` and a signed audit event row exists with `entity_type="deal"` and `event_type="archived"`.
2. **Archive a Deal with active links** — assert the chosen cascade semantics:
   - Cascade-with-soft-delete: assert each DealLink has `deleted_at` set.
   - Cascade-with-hard-delete: assert no DealLink rows remain for the archived Deal.
   - Block-on-active-links: assert 409 raised and Deal remains `is_deleted == False`.
3. **Relink a freed entity** — after archiving Deal X (or after removing its links if block path), assert a brand-new Deal Y can claim the same `linked_id` without the "already linked to deal X" error.
4. **`find_deal_by_linked_entity` excludes archived Deals** — archive Deal X, query `find_deal_by_linked_entity` with one of X's link IDs, assert 404.
5. **Reader endpoints exclude archived Deals** — `GET /deals` and `GET /deals/{id}` filter archived rows.
6. **RBAC** — non-risk_manager user receives 403 on archive.
7. **Audit row content** — signed audit event includes Deal id, link inventory snapshot, and RBAC actor JWT sub (from Cluster 2 `get_current_actor_sub`).

## 6. Constitutional Rules

- `docs/governance.md` §2.7 (audit reconstructability) — explicit lifecycle semantics. Half-wired states violate §2.7 by leaving the contract ambiguous.

No changes to `docs/governance.md` are part of this wave.

## 7. Acceptance Criteria (path-specific)

### 7.1 Path A acceptance

- [ ] §3 pre-step recorded both counts as zero. Counts cited in the PR body.
- [ ] `backend/app/models/deal.py` — `is_deleted` and `deleted_at` columns removed.
- [ ] `backend/app/schemas/deal.py` — `DealRead.is_deleted: bool` field removed (line 97). `DealDetailRead` and any other subclass cleaned automatically via inheritance; verify no local override remains.
- [ ] `docs/api/openapi_v1.json` and `frontend-svelte/src/lib/api/schema.d.ts` regenerated; diff is bounded to dropping `is_deleted` from Deal-related response components.
- [ ] One new migration `044_drop_deal_lifecycle_fields` (or equivalent) with `down_revision = "043_a5_audit_payload_input"`. `python -m alembic heads` prints the new single head.
- [ ] `backend/app/services/deal_engine.py` — all `Deal.is_deleted` filter clauses removed (sweep returns zero matches in this file).
- [ ] `backend/app/api/routes/deals.py` — no change to `find_deal_by_linked_entity` body needed; verify it still passes its existing tests.
- [ ] No new endpoint added.
- [ ] `rg -nP "Deal\\.is_deleted|deal\\.is_deleted" backend/app backend/tests` returns zero matches outside the migration file.
- [ ] `rg -nP "is_deleted\\s*:\\s*bool" backend/app/schemas/deal.py` returns zero matches.
- [ ] `rg -nP "deal.*is_deleted|\\.is_deleted" frontend-svelte/src/routes/` returns zero matches (verify no frontend regression added a Deal-archive consumer between v1 dispatch authoring and implementation; verified clean at HEAD `ea08d9868`).
- [ ] No edit to `docs/governance.md`.

### 7.2 Path B acceptance

- [ ] §3 pre-step recorded at least one non-zero count, OR Andrei explicitly authorized Path B in the PR body.
- [ ] `PATCH /deals/{deal_id}/archive` route exists with `audit_event(entity_type="deal", event_type="archived")` decorator and `require_role` RBAC.
- [ ] Archive writes both `Deal.is_deleted = True` and `Deal.deleted_at = now_utc()` inside `unit_of_work` + `mark_audit_success`.
- [ ] `backend/app/schemas/deal.py` — `DealRead.deleted_at: Optional[datetime] = None` field added immediately after `is_deleted: bool`. `DealDetailRead` inherits.
- [ ] `docs/api/openapi_v1.json` and `frontend-svelte/src/lib/api/schema.d.ts` regenerated; diff is bounded to adding the optional `deleted_at` field on Deal-related response components.
- [ ] DealLink cascade semantics chosen and implemented (exactly one of the three options in §5.2; documented in the PR body).
- [ ] If cascade-with-soft-delete chosen: one new migration performing all **three** operations per §5.3 (add `DealLink.deleted_at`; drop both unconditional `UniqueConstraint`s; create partial unique indexes `WHERE deleted_at IS NULL` for both `(deal_id, linked_type, linked_id)` and `(linked_type, linked_id)` shapes). `__table_args__` in `backend/app/models/deal.py` updated to mirror. Single-head preserved (`python -m alembic heads` prints exactly one head). The §5.5 test #3 "Relink a freed entity" passes — without the partial-index replacement, this test would fail at the DB level with `IntegrityError` even though the app-level filter is in place.
- [ ] If cascade-with-hard-delete or block-on-active-links: no migration.
- [ ] `find_deal_by_linked_entity` filters archived Deals.
- [ ] `backend/tests/test_deal_archive.py` exists with the 7 tests in §5.5.
- [ ] All 7 tests pass.

### 7.3 Cross-cutting acceptance (both paths)

- [ ] No edit to `backend/app/services/scenario_whatif_service.py`, `backend/app/services/exposure_service.py`, `backend/app/services/exposure_engine.py` (PR-CL1-3 territory).
- [ ] No edit to the `_compute_inputs_hash` or `unprovable_errors` paths in `deal_engine.py` (PR-CL1-2 territory).
- [ ] No edit to the archived-link traversal sites in `deal_engine.py` (PR-CL1-1 territory).
- [ ] No edit to `docs/governance.md`.
- [ ] Single alembic head preserved (no more than one new migration; if Path B chose a non-migration option, zero new migrations).

## 8. Required Tests

§4.6 (Path A) and §5.5 (Path B). The implementer runs only the section matching their chosen path.

## 9. Required Verification

```powershell
# Pre-step (binding for path selection — capture and paste counts into PR body)
# (Run against the production-equivalent database.)
# SQL:
#   SELECT COUNT(*) FROM deals WHERE is_deleted = true;
#   SELECT COUNT(*) FROM deals WHERE deleted_at IS NOT NULL;

# Path A sweeps
rg -nP "Deal\\.is_deleted|deal\\.is_deleted" backend/app backend/tests
rg -nP "Deal\\.deleted_at|deal\\.deleted_at" backend/app backend/tests
rg -nP "is_deleted\\s*:\\s*bool" backend/app/schemas/deal.py    # must return zero
rg -nP "deal.*is_deleted|\\.is_deleted" frontend-svelte/src/routes/    # must return zero (frontend isolation)

# Path B sweeps
rg -nP "/deals/\\{.+\\}/archive|PATCH.*deals.*archive" backend/app/api/routes/deals.py
rg -nP "entity_type=\"deal\".*event_type=\"archived\"" backend/app/api/routes/deals.py
rg -nP "deleted_at.*Optional\\[datetime\\]|deleted_at: datetime \\| None" backend/app/schemas/deal.py    # must return at least one (the new DealRead.deleted_at field)

# Path B cascade-with-soft-delete sweeps (only if that cascade option chosen)
rg -nP "UniqueConstraint.*uq_deal_link" backend/app/models/deal.py    # must return ZERO matches (the unconditional constraints were dropped)
rg -nP "uq_deal_link_live|uq_deal_link_entity_live" backend/app/models/deal.py backend/alembic/versions/    # must return at least two matches (the partial unique indexes)
rg -nP "deleted_at IS NULL" backend/alembic/versions/    # must return at least two matches in the new revision (one per partial unique index)

# Alembic invariant (both paths)
cd backend ; python -m alembic heads ; cd ..

# Test suites
pytest -q backend/tests/test_deal_engine.py
pytest -q backend/tests/test_deal_archive.py  # Path B only
pytest -q backend/tests

# Cross-wave isolation (both paths)
git diff main -- backend/app/services/scenario_whatif_service.py
git diff main -- backend/app/services/exposure_service.py
git diff main -- backend/app/services/exposure_engine.py
git diff main -- docs/governance.md

# Generated artifacts
git diff -- docs/api/openapi_v1.json frontend-svelte/src/lib/api/schema.d.ts
git diff --check
```

`python -m alembic heads` after the migration step must print exactly one head. Cross-wave diffs must be empty. `docs/governance.md` diff must be empty.

## 10. Out of Scope

- Wave PR-CL1-1 (archived-link traversal). Not touched.
- Wave PR-CL1-2 (snapshot reuse / 424 mapping). Not touched.
- Wave PR-CL1-3 (shared exposure primitive / scenario filters). Not touched.
- Adding lifecycle columns to other models (Counterparty, etc.) beyond what cascade requires.
- Implementing both Path A and Path B in the same wave or providing a feature flag to switch between them at runtime. The path is final.
- Building a "restore archived Deal" route. Even on Path B, this dispatch does not authorize an unarchive endpoint. If product later needs it, it becomes its own audit-cycle proposal.
- Frontend Deal-archive UI. The frontend audit (A6) explicitly did not add a Deal archive surface; if Path B is chosen, the frontend follow-up is a separate (post-Cluster-1) wave.
- Multi-migration sequences. As stated in §2.1, anything requiring more than one new alembic revision must be deferred to a separate cycle.

## 11. PR Requirements

The implementing PR title must be one of:

- Path A: `fix(audit-followup): close Cluster 1 PR-CL1-4 (remove dead Deal lifecycle fields)`
- Path B: `fix(audit-followup): close Cluster 1 PR-CL1-4 (Deal archive contract with DealLink cascade)`

The PR body must include:

- **Findings closed:** explicit `J-CL1-02` reference + Cluster 1 verdict citation.
- **Pre-step results:** the two production-data counts cited verbatim. If Path B was chosen because Andrei explicitly authorized despite zero rows, note that in the body.
- **Path chosen:** A or B; if B, the cascade option (cascade-with-soft-delete / cascade-with-hard-delete / block-on-active-links) and its rationale.
- **Files changed:** inventory grouped by model / migration / service / route / tests.
- **Verification matrix:** §9 sweep results.
- **Migration statement:** explicit alembic head before/after + single-head assertion.
- **Hook artifact paths:** `.cache/dispatch_review/audit-followup-cluster-1-deal-soft-delete-cleanup-{sha}.json` per push.
- **Governance statement:** `docs/governance.md` diff is empty.

## 12. Workflow

1. **Pre-step (mandatory before branching):** run the §3 SQL against a production-equivalent database. Record both counts. Decide the path.
   - If both counts are zero → Path A.
   - If either count is non-zero → Path B (with severity promotion to Tier 2 acknowledged).
   - If no DB is accessible → stop and escalate to Andrei.
2. `git checkout -b audit-followup/cluster-1-deal-soft-delete-cleanup`.
3. Execute §4 (Path A) or §5 (Path B). Do not mix. The schema layer (§4.2 for Path A, §5.0 for Path B) is mandatory in either path — without it the API responses will fail validation (Path A) or silently omit the archive timestamp (Path B).
4. Add the chosen-path test file (§4.6 / §5.5).
5. Regenerate `docs/api/openapi_v1.json` and `frontend-svelte/src/lib/api/schema.d.ts` after the schema edit (mandatory both paths).
6. Run §9 verification locally. The alembic single-head check is mandatory before opening the PR. The schema sweep (§9 Path A `is_deleted: bool` returns zero; Path B `deleted_at: Optional[datetime]` returns at least one) is also mandatory.
7. Fix every hook v2 P1/P2 in place.
8. Push branch and open PR per §11.
9. Codex Connector review is the final gate. Address every Codex inline catch. **Do not merge** — Andrei merges with explicit authorization only.

## 13. Hook v2 + Codex calibration notes

- **Expected hook v2 surface area** is path-dependent:
  - Path A: model column removal + migration + filter cleanup. Hook may flag the migration as `Tipo-I fact mismatch` (revision not yet existing) — known FP class.
  - Path B: new route + new audit decorator + cascade semantics + tests. Larger diff; hook may flag schema drift on OpenAPI regen if the new route's response model differs from existing patterns. Use existing `archive_order` / `archive_hedge_contract` as the precedent.
- **Expected Codex catches**:
  - Path A: a leftover filter on `Deal.is_deleted` in a less-trafficked code path (e.g. an analytics query, a serializer). Sweep `rg -nP "is_deleted" backend/app | rg -i deal` to find every site before pushing.
  - Path A: **schema cleanup missed** — if the model column drops but `DealRead.is_deleted: bool` stays, every Deal response fails Pydantic `from_attributes` validation. This is the v1 dispatch gap Codex caught (PR #74 review). The §4.2 schema subsection plus the §7.1 `is_deleted: bool` sweep are the structural protection; cross-section sweep must verify both before pushing.
  - Path B: missing RBAC on the archive route; missing audit event on the cascade column writes; reader inconsistency (`find_deal_by_linked_entity` filter applied but another reader missed); missing `actor_sub` in the audit payload (Cluster 2 established the JWT-sub pattern; archive must use it).
  - Path B: **schema field missing** — if the archive route writes `Deal.deleted_at = now_utc()` but `DealRead` doesn't expose `deleted_at`, the operator-visible response cannot show when the archive happened. The §5.0 schema subsection adds the field; the §7.2 + §9 sweeps verify it landed.
  - Path B cascade-with-soft-delete: **DB-level unique constraint blocks relink even with app-level filter (v3 catch)**. The unconditional `UniqueConstraint("linked_type", "linked_id", name="uq_deal_link_entity")` at `backend/app/models/deal.py:171-194` is the cross-deal block; soft-deleting a `DealLink` (`deleted_at = now()`) does not remove the row from the constraint's view, so a brand-new `INSERT` for the same `(linked_type, linked_id)` fails with `IntegrityError` at the DB level **before** the app-level `add_link` filter has a chance to run. The fix is the partial-unique-index replacement prescribed in §5.2 + §5.3: drop both unconditional `UniqueConstraint`s and create partial unique indexes scoped to `WHERE deleted_at IS NULL`. Three operations in one alembic revision. Without this, the §5.5 test #3 "Relink a freed entity" lands as `IntegrityError`, not as the prescribed pass — and the cascade-with-soft-delete option is structurally broken. The §7.2 + §9 sweeps verify the constraint→partial-index migration is in place.
  - Either path: a migration that fails `python -m alembic heads` because the `down_revision` is wrong; this would surface in CI on the openapi_diff job and in the §9 sweep.
  - Either path: OpenAPI / `schema.d.ts` regeneration skipped — would surface in CI's `openapi_diff` job. Mandatory regen step is §12 step 5.
- The 8-section sweep checklist from `feedback_dispatch_self_consistency` applies, but with a twist: this wave has **two non-overlapping implementation sections** (§4 Path A, §5 Path B). The implementer chooses one; the dispatch reviewer (jury / Codex) should treat the chosen path's section as binding and the unchosen section as out-of-scope text. Do not authorize both.
- **Single-head invariant** is the load-bearing institutional check. If Path B requires more than one migration, stop and defer. Do not bundle multiple migrations into PR-CL1-4 even if they look small individually.
- **Severity promotion**: if the pre-step records non-zero rows, J-CL1-02 is implicitly Tier 2 (per verdict self-bias confession). The wave should be implemented before any new lifecycle work; if PR-CL1-1 / PR-CL1-2 / PR-CL1-3 have not yet shipped, the implementer should still pursue this wave in parallel rather than chain it strictly after.
