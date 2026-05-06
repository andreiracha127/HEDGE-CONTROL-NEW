# Phase A1 — PR #2 Dispatch — Order Commodity Model

**Wave:** 1 (no dependencies)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-06
**Findings covered:** J-A1-OPUS-05 (Tier 1) + S-A1-J-02 (subsumed F-A1-OPUS-12)
**Branch name:** `audit-a1/order-commodity-model`
**Base:** `main` (latest)

---

## 1. Mission

Add a required `commodity` column to `Order`, populate existing rows by data migration, replace the hardcoded `"ALUMINUM"` in `reconcile_from_orders`, and make commercial/global exposure snapshots commodity-scoped or grouped. PR #5 (snapshot lifecycle) depends on this — it cannot test commodity-scoped lifecycle filters without the commodity dimension on Order.

**Persona:** Senior engineer in an institutional trading platform. Constitution §2.1 (Exposure always in MT, **per commodity**), §2.5 (Global Exposure formula must net per commodity, not across commodities). Cross-commodity netting is a silent risk-management bug — Aluminum exposure netting against Copper hedges is not a hedge, it's accounting fiction.

---

## 2. Reference docs

- **`docs/audits/2026-05-06-phase-a1-jury-verdict.md`** — finding J-A1-OPUS-05 (§3 Opus-only, jury-validated). Read in full.
- **`docs/governance.md`** — constitution §2.1, §2.5.
- **`docs/audits/2026-05-06-phase-a1-findings-opus.md`** — F-A1-OPUS-09 + F-A1-OPUS-12 (subsumed) for mechanism.

---

## 3. Scope IN

### 3.1 Add `Order.commodity` column

File: `backend/app/models/orders.py:49-106`

- Mirror existing `HedgeContract.commodity` **exactly** — column length, case convention, and validation. Before writing the column definition, verify the actual values:
  - `grep -n "commodity" backend/app/models/contracts.py` — the column is `String(length=64)` at the time of writing; use the value you observe, not this number, in case the file evolves before this PR lands.
  - `grep -n "commodity" backend/app/schemas/contracts.py` — the create schema accepts up to ~50 chars; reuse the same `max_length` validator on `OrderCreate.commodity`.
- Add `commodity: Mapped[str] = mapped_column(String(<observed length, match HedgeContract>), nullable=False, index=True)`. Do NOT use a smaller length than `HedgeContract.commodity`; identifiers in the 33–50 char range that are valid for hedge contracts must remain assignable to orders.
- If a `Commodity` enum exists (search `backend/app/models/__init__.py` and `backend/app/models/contracts.py` for `class Commodity` or similar), reuse it. If only a plain `str + max_length` validator exists today (likely), match that — do NOT invent an enum just for orders.

### 3.2 Pydantic schema update

Files: `backend/app/schemas/orders.py` (or wherever `OrderCreate` / `OrderRead` live; grep `class OrderCreate` to locate).

- Add `commodity: str` as **required** in `OrderCreate` (or the existing `Commodity` enum if one is in use for HedgeContract — verify by grep before assuming).
- Read in `OrderRead`.
- Validation: reuse the same `max_length` constraint that `HedgeContractCreate.commodity` already enforces (≈50 at the time of writing — verify by reading `backend/app/schemas/contracts.py`). Do NOT invent a stricter limit.

### 3.3 Alembic migration — schema + data

Migration file: `backend/alembic/versions/<NNNN>_order_commodity.py`

- `op.add_column("orders", sa.Column("commodity", sa.String(32), nullable=True))` (start nullable to allow data migration)
- Data migration: backfill `commodity = 'ALUMINUM'` for all existing rows (matches the current hardcoded behavior — preserves semantics during migration)
- `op.alter_column("orders", "commodity", nullable=False)`
- `op.create_index("ix_orders_commodity", "orders", ["commodity"])`
- Downgrade: drop index, drop column

**Constraint:** the `'ALUMINUM'` backfill is a one-time bridge; document explicitly in the migration docstring that the entire production dataset prior to this migration was implicitly Aluminum and the operator is responsible for correcting any future heterogeneous data manually if it later turns out to have been mis-tagged.

### 3.4 Service-layer changes

Files (per jury §3 J-A1-OPUS-05):
- `backend/app/services/exposure_engine.py:109-117` — replace `commodity="ALUMINUM"` hardcoded literal with `commodity=order.commodity`
- `backend/app/services/exposure_service.py:72-162` — `compute_commercial_snapshot` and `compute_global_snapshot`:
  - GROUP BY commodity (in addition to direction)
  - Return per-commodity rows
  - The aggregate response shape MUST distinguish commodities; do NOT collapse to scalar totals
- `backend/app/services/exposure_engine.py:157` — aggregation loop already keys by commodity (`agg[c]`); validate that with the schema change, all input rows now have a commodity
- `backend/app/api/routes/exposures.py:38-43` (`/global` route) — return per-commodity payload

### 3.5 Response shape change

The `/exposures/global` and `/exposures/commercial` responses now return per-commodity. **API contract change** — frontend consumers will break.

- Update `frontend-svelte/src/lib/api/schema.d.ts` (regen via openapi codegen)
- Find frontend callsites that consume `/exposures/global` / `/exposures/commercial` (grep `lib/api`)
- Update frontend rendering to iterate per-commodity (do NOT silently sum across commodities — that's the bug we're fixing)

**Frontend rendering is non-negotiable: render every commodity row in the response.** Silently rendering only the first row recreates the exact silent risk-reporting blindness this PR is fixing — operators would see Aluminum exposure but Copper / Zinc / etc. exposures would be invisibly hidden, producing the same downstream decisions the netting bug produced. Constitution §2.1, §2.5, §2.7 forbid this.

If implementing a polished multi-commodity layout is too large for this PR, the **only** acceptable fallback is to render an explicit user-visible notice (`"⚠️ Multiple commodities present — UI rendering of N additional commodities not yet implemented; consult /api/exposures/* for full data"`) **whenever** the response contains more than one commodity row. Never display a partial subset without that notice. Open a follow-up issue for the polished UI; do NOT use the issue as cover to ship silent dropping.

---

## 4. Scope OUT

- **Lifecycle filters (deleted_at on Order/HedgeContract)** — PR-5 problem
- **Decimal primitives** — PR-1 problem (independent; both can land in parallel; service code in this PR should NOT regress to `float` on quantity)
- **Audit emission on reconcile** — PR-7 problem
- **`HedgeContract.commodity` already exists** — do not modify (read-only reference)
- **Multi-commodity UI redesign** — out of scope; document follow-up
- **Per-commodity exposure aggregation in scenario engine, MTM, P&L** — those services are out of Phase A1 scope; extending them is Phase A3 territory
- **Backfill of historical heterogeneous data** — `'ALUMINUM'` backfill is the canonical bridge; out of scope to mine other systems for true commodity

---

## 5. Constitutional rules (binding)

- **§2.1** — Exposure is state, always in MT, **per commodity** (commodity is part of the state identity)
- **§2.5** — Global Exposure formulas must operate per commodity. Cross-commodity netting is undefined/illegal.
- **§2.7** — Output contract: precise. Hardcoded `'ALUMINUM'` violates verifiability — anyone reading the snapshot cannot tell which commodity it represents without knowing the historical context.

---

## 6. Acceptance criteria (from jury §3 J-A1-OPUS-05)

- [ ] `Order.commodity` exists, is required (NOT NULL), and is populated by migration
- [ ] Existing data backfilled to `'ALUMINUM'`; documented in migration
- [ ] `reconcile_from_orders` writes `Exposure.commodity = order.commodity` (no hardcoded literal)
- [ ] Commercial snapshot groups by commodity; multi-commodity test confirms rows are NOT netted across commodities
- [ ] Global snapshot groups by commodity; multi-commodity test confirms rows are NOT netted across commodities
- [ ] **Commercial isolation test (no hedges):** insert variable-price SO Aluminum 100 + variable-price SO Copper 50 → response contains per-commodity rows `Aluminum.active=100, Copper.active=50`; NEVER a single shared bucket `active=150`. Do NOT introduce hedges in this fixture — commercial exposure formula is order-quantity minus `HedgeOrderLinkage` quantities only; per §2.4 an unlinked `HedgeContract` does NOT reduce commercial exposure, so adding one would muddle what the test verifies.
- [ ] **Commercial isolation test with linkage:** insert variable-price SO Aluminum 100 + variable-price SO Copper 50 + Hedge **Short** Aluminum 100 + a `HedgeOrderLinkage` row tying that hedge to the Aluminum SO at quantity 100 → response shows `Aluminum.active=0, Copper.active=50`. (Asserts that linkage reduction is per-commodity, not pooled. Note: SO ↔ Hedge Short is the direction-correct pairing; SO ↔ Hedge Long would also work in current code only because `LinkageService` does not yet validate direction — that bug is J-A1-OPUS-03 and PR-4 will fix it. Use Hedge Short here so the fixture survives PR-4.)
- [ ] **Global isolation test:** insert variable-price SO Aluminum 100 + variable-price SO Copper 50 + Hedge Short Aluminum 80 (unlinked) + Hedge Short Copper 30 (unlinked) → per §2.5 (`Global Active = Commercial Active + Hedge Short unlinked`), response shows `Aluminum.active = 100 + 80 = 180`, `Copper.active = 50 + 30 = 80`; NEVER a single shared bucket `active=260`. (Asserts the global formula is per-commodity. Earlier draft said `Copper.active=30` — that was wrong; it dropped the SO Copper 50 contribution and would have trained the test to silently strip commercial Copper exposure whenever a same-commodity hedge exists.)
- [ ] API response shape change documented in PR
- [ ] `frontend-svelte` schema regenerated and committed
- [ ] Existing single-commodity tests still pass (Aluminum baseline)

---

## 7. Test coverage required

- `backend/tests/test_orders.py` — extend: OrderCreate without commodity → 422; OrderCreate with invalid commodity → 422
- `backend/tests/test_exposure_engine.py` — extend: reconcile honors per-row commodity; no hardcoded literal; existing exposure rows with commodity preserved
- `backend/tests/test_exposures_commercial.py` — **NEW or extend** — cross-commodity isolation test (the one in §6 above)
- `backend/tests/test_exposures_global.py` — **NEW or extend** — cross-commodity isolation
- Migration test: apply migration on fixture DB with N existing orders; assert all backfilled to 'ALUMINUM'; assert NOT NULL constraint enforced post-migration

---

## 8. Critical sequencing

- **Wave 1, no upstream dependencies** — can run in parallel with PR-1, PR-3, PR-6.
- **Downstream:** PR-5 (snapshot lifecycle) depends on THIS PR (cannot test "deleted Aluminum hedge does not affect Copper snapshot" without commodity dimension).
- If PR-1 (Decimal) merges before this PR, rebase and ensure no `float` regression slipped in. If PR-1 merges after, rebase your branch when PR-1 lands.

---

## 9. PR shape

**Title:** `fix(audit-a1): PR-2 — Order commodity model + commodity-scoped snapshots (J-A1-OPUS-05)`

**Body skeleton:**

```markdown
## Summary

Add required `commodity` column to `Order`; eliminate hardcoded `'ALUMINUM'`
in `reconcile_from_orders`; commodity-scope commercial/global exposure
snapshots. Phase A1 jury Tier 1 fix per finding J-A1-OPUS-05 (§2.1, §2.5).

## Files changed
- Models: orders.py
- Schemas: orders.py
- Services: exposure_engine.py, exposure_service.py
- Routes: exposures.py
- Alembic: migration `XXXX_order_commodity.py`
- Frontend: schema.d.ts regen, /exposures/* consumer adjustments

## API contract change
- `GET /exposures/global` and `GET /exposures/commercial` now return per-commodity rows.
- Existing single-commodity (Aluminum) consumers will see one-element list.

## Data migration
- Existing rows backfilled to `'ALUMINUM'`. Documented in migration docstring.

## Acceptance evidence
- Cross-commodity isolation tests in `test_exposures_commercial.py` and
  `test_exposures_global.py`
- Migration roundtrip verified

## Out of scope
- Lifecycle filters (PR-5)
- Decimal primitives (PR-1)
- Multi-commodity UI redesign (issue #TBD follow-up)

## Closes
J-A1-OPUS-05. Subsumes F-A1-OPUS-12 (S-A1-J-02).
```

---

## 10. Constraints — what NOT to do

- DO NOT make `Order.commodity` nullable in the final schema (transient nullable during migration is OK)
- DO NOT auto-detect commodity from product names or any heuristic — this is institutional data, the operator inputs it
- DO NOT extend MTM/P&L/Cashflow/Scenario engines (Phase A3 scope)
- DO NOT remove the existing `HedgeContract.commodity` (already correct)
- DO NOT use `--no-verify` to skip git hooks
- DO NOT auto-merge — wait for Codex review

---

## 11. Workflow

1. `git fetch origin && git checkout -b audit-a1/order-commodity-model origin/main`
2. Read jury verdict §3 J-A1-OPUS-05 in full
3. Implement: model → schema → migration → service → route → tests → frontend
4. Run migration locally on Postgres; verify backfill
5. Run full backend test suite
6. `git push -u origin audit-a1/order-commodity-model`
7. `gh pr create --base main --title "<§9 title>" --body-file <body>`
8. **STOP. Wait for Codex review.**
9. Address Codex feedback in new commits

---

## 12. Final report shape

- Branch + PR URL + final SHA
- Files touched
- Migration evidence (count of backfilled rows, post-migration NOT NULL verified)
- Test counts (new vs main)
- API contract change summary (which endpoints; backward-compat note)
- Codex verdict

Under 500 words.

Boa caça.
