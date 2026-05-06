# Phase A1 — PR #1 Dispatch — Decimal Primitives

**Wave:** 1 (foundational, no dependencies)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-06
**Findings covered:** J-A1-04 (Tier 1) + S-A1-J-03 (subsumed F-A1-OPUS-13) + S-A1-J-04 (subsumed F-A1-OPUS-14)
**Branch name:** `audit-a1/decimal-primitives`
**Base:** `main` (latest)

---

## 1. Mission

Migrate institutional MT quantity and financial-price primitives end-to-end from Python `float` (IEEE-754 binary64) to `Decimal` / SQLAlchemy `Numeric`. This is the **foundational PR of Wave 1**; PRs #4 (linkage hardening) and #8 (P&L price evidence) depend on this landing first.

**Persona:** Senior software engineer building an institutional trading platform. Constitution `docs/governance.md` is supreme authority — §2.1 (MT consistency), §2.6 (no silent fallback / hard-fail boundaries), §2.7 (output contract: precise / verifiable / audit-friendly). Float arithmetic in risk-boundary comparisons is constitutionally unacceptable.

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-06-phase-a1-jury-verdict.md`** — source of truth for finding J-A1-04 (§2 Convergent findings). Read in full.
- **`docs/governance.md`** — constitution. Cláusulas §2.1, §2.6, §2.7 são vinculantes.
- **`docs/audits/2026-05-06-phase-a1-findings-opus.md`** — F-A1-OPUS-05 (this PR) + F-A1-OPUS-13 + F-A1-OPUS-14 (subsumed) for additional mechanism context.
- **`docs/audits/2026-05-06-phase-a1-findings-gemini.md`** — F-A1-GEMINI-05 (convergent) Q6 Tier 2 evidence.

---

## 3. Scope IN — what PR-1 ships

### 3.1 Models — switch `Float` → `Numeric` with explicit precision/scale

Files to edit:
- `backend/app/models/orders.py:61-66` — `Order.quantity_mt`, `Order.avg_entry_price`
- `backend/app/models/contracts.py:68-89` — `HedgeContract.quantity_mt`, `HedgeContract.fixed_price_value`, any other monetary leg fields (read full file; do not miss `*_price` columns)
- `backend/app/models/linkages.py:25` — `HedgeOrderLinkage.quantity_mt`
- `backend/app/models/exposure.py` — verify all MT fields are `Numeric` (jury says `Exposure` already uses `Numeric`; preserve)
- `backend/app/models/deal.py` — verify and extend if any `Float` MT/price column exists
- `backend/app/models/cashflow.py`, `pl.py`, `mtm.py` — scan for `Float` columns that hold MT or price; convert if any (DO NOT change non-economic fields)

**Precision/scale policy (single source of truth — define in one place):**
- MT quantities: `Numeric(15, 3)` (mirrors existing `Exposure.original_tons`)
- Prices: `Numeric(18, 6)` (USD/MT or equivalent — verify that scale is sufficient for the smallest tick on LME aluminum which is the minimum reference)
- Document the policy in a module-level constant or comment in `models/__init__.py` or a new `models/_precision.py` helper.

### 3.2 Pydantic schemas — switch `float` → `Decimal`

Files to edit (scan for usage of `float` in fields that hold quantity_mt / price / monetary value):
- `backend/app/schemas/exposure_engine.py`
- `backend/app/schemas/contracts.py`
- `backend/app/schemas/orders.py` (if exists; else `schemas/*.py` that touches Order)
- `backend/app/schemas/linkages.py`
- `backend/app/schemas/deal.py`
- `backend/app/schemas/cashflow.py`, `pl.py`, `mtm.py` if they expose MT/price

Use **stdlib** `Decimal` (Pydantic 2.12 does not export a `pydantic.Decimal` type — importing it will fail). The idiomatic Pydantic 2.x pattern is `Annotated[Decimal, Field(...)]`:

```python
from decimal import Decimal
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field

MTQuantity = Annotated[Decimal, Field(max_digits=15, decimal_places=3)]
Price       = Annotated[Decimal, Field(max_digits=18, decimal_places=6)]

class OrderCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    quantity_mt: MTQuantity
    avg_entry_price: Price | None = None
```

Plain `Field(max_digits=..., decimal_places=...)` directly on the field is also acceptable. Define the `MTQuantity` / `Price` aliases in a single module (e.g., `app/schemas/_types.py` or alongside the precision helpers in `app/core/precision.py`) so schemas across the codebase stay consistent. Do NOT import `Decimal` from `pydantic`.

### 3.3 Service-layer arithmetic — eliminate `float()` conversions on MT/price

Files to edit (each cite is from jury §2 J-A1-04):
- `backend/app/services/linkage_service.py:52-57` — boundary checks `float(order_linked_qty or 0.0) + quantity_mt > order.quantity_mt` MUST use Decimal
- `backend/app/services/exposure_engine.py:73-81` — `max(float(order.quantity_mt) - hedged_qty, 0.0)` — Decimal-native (also touches J-A1-OPUS-01 territory; PR-4 will harden the clamp into a hard-fail; for THIS PR, just preserve current behavior with Decimal)
- `backend/app/services/exposure_service.py:214` and similar — query `cast` and `coalesce` paths; ensure Decimal arithmetic
- `backend/app/services/deal_engine.py` — `_order_value`, `compute_deal_pnl`, hedge MTM math — Decimal end-to-end (PR-8 will harden hard-fail; this PR ensures Decimal substrate)
- `backend/app/services/exposure_engine.py:157` `_recompute_tons` ratio division — Decimal with explicit `quantize(...)` and `ROUND_HALF_EVEN`

**Quantization policy:**
- Define a helper `quantize_mt(d: Decimal) -> Decimal` and `quantize_price(d: Decimal) -> Decimal` in a single module (e.g., `app/core/precision.py`).
- Apply quantization **before** boundary comparisons (over-allocation checks, fully-hedged thresholds).
- Default rounding mode: `ROUND_HALF_EVEN` (banker's rounding) for general arithmetic. **Conservative rounding (`ROUND_CEILING` for caps, `ROUND_FLOOR` for floors) only if explicitly required by a hard-fail boundary** — discuss in PR description if you choose conservative.

### 3.4 Alembic migration

Generate migration that alters the column types. SQLAlchemy `Float` → `Numeric` in PostgreSQL is `ALTER COLUMN ... TYPE numeric(15,3) USING quantity_mt::numeric`. Sample template:

```python
def upgrade():
    op.alter_column(
        "orders", "quantity_mt",
        existing_type=sa.Float(),
        type_=sa.Numeric(15, 3),
        existing_nullable=False,
        postgresql_using="quantity_mt::numeric",
    )
    # ... repeat for all changed columns
```

**Migration constraints:**
- Up + down + up roundtrip must pass cleanly on local Postgres
- **Preflight data-loss check (REQUIRED, fail-closed default).** The current schema accepts unbounded floats, so existing rows MAY have more than 3 fractional digits for MT or more than 6 for prices. Naive `ALTER COLUMN ... TYPE numeric(15,3)` would silently round those values — a §2.7 violation (precise, verifiable, audit-friendly) and exactly the kind of silent mutation §2.6 forbids. Before performing the cast, the migration must run a preflight per affected column:

  ```python
  def _assert_no_loss(op, table, col, scale):
      result = op.get_bind().execute(sa.text(f"""
          SELECT COUNT(*) AS n,
                 COALESCE(MAX(scale_decimals), 0) AS max_scale
          FROM (
              SELECT length(split_part(({col})::text, '.', 2)) AS scale_decimals
              FROM {table}
              WHERE {col} IS NOT NULL
          ) AS sub
          WHERE scale_decimals > :scale
      """), {"scale": scale}).one()
      if result.n > 0:
          raise RuntimeError(
              f"{table}.{col}: {result.n} rows have more than {scale} fractional "
              f"digits (max observed = {result.max_scale}). Refusing to migrate "
              f"with silent rounding. Resolve the data first or pick a wider scale."
          )
  ```

  Run this for each MT column at `scale=3` and each price column at `scale=6` BEFORE the `alter_column` call. If any preflight fails, the migration aborts and reports the offending table/column/count to the operator — no rounding without explicit operator action.

- If a preflight reports loss, the operator's options are: (a) clean the data manually with explicit audit emission, (b) widen the target scale in this migration to preserve all observed values (and update `app/core/precision.py` to match), or (c) run a separate "round + audit" migration first that records every rounded value in audit_events. Default behavior of THIS migration is to refuse to silently round.
- Do NOT run a data migration that mutates existing rows beyond the implicit cast (jury §6 subsumed S-A1-J-03/04 do NOT require data backfill, only type — but the preflight is required before the cast).
- Document in migration docstring: "Type-only migration with preflight data-loss assertion; refuses silent rounding. precision/scale match existing `Exposure.original_tons` policy."

### 3.5 Frontend types regeneration

After backend lands locally, regenerate `frontend-svelte/src/lib/api/schema.d.ts` via the project's openapi codegen workflow (check `frontend-svelte/package.json` scripts). Commit the regenerated schema.

---

## 4. Scope OUT — explicitly NOT in PR-1

- **Hard-fail conversion at boundaries** — PR-4 (linkage hardening) and PR-8 (P&L price evidence) will replace silent fallbacks with hard-fails. PR-1 only changes the substrate; semantic behavior is preserved.
- **Audit emission** — PR-7 problem.
- **Commodity column on Order** — PR-2 problem.
- **Reconcile clamp removal** — PR-4 problem.
- **`HedgeContract.classification` DB invariant** — PR-6 problem.
- New tables, new endpoints, schema redesigns — out of scope.

---

## 5. Constitutional rules (binding)

- **§2.1** — Exposure always in MT. This PR ensures MT is represented losslessly.
- **§2.6** — Hard-fails: this PR does NOT introduce new hard-fails; it ensures comparisons that already exist (and future ones in PR-4/-8) operate on exact Decimal, not approximated float.
- **§2.7** — Output contract: precise, verifiable, audit-friendly. Float in risk boundary fails this. Decimal with documented quantization satisfies it.

---

## 6. Acceptance criteria (from jury §2 J-A1-04)

- [ ] All `Order`, `HedgeContract`, `HedgeOrderLinkage`, `Exposure`, `Deal`, P&L MT/price columns are `Numeric` with documented precision/scale
- [ ] Boundary checks (linkage capacity, fully-hedged threshold, P&L valuation) compare quantized Decimals
- [ ] Test asserts `Decimal('0.1') + Decimal('0.2') == Decimal('0.3')` after quantization at MT scale (currently fails on float)
- [ ] Test asserts exact fully-hedged status flip at `quantity_mt == hedged_qty` (no float drift)
- [ ] Test asserts boundary check rejects `linked + new_qty > order.quantity_mt` precisely (no off-by-epsilon)
- [ ] Existing aggregate tests pass without float-tolerance comparisons (`pytest.approx` removed where present in MT/price assertions)
- [ ] Alembic migration up/down/up roundtrip clean on local Postgres
- [ ] Generated `frontend-svelte/src/lib/api/schema.d.ts` committed and consistent (string Decimal representation per OpenAPI policy)

---

## 7. Test coverage required

Add or extend (project test layout: `backend/tests/`):

- `backend/tests/test_decimal_primitives.py` — **NEW** — unit tests for the `quantize_mt`/`quantize_price` helpers and the `0.1+0.2` regression
- `backend/tests/test_linkages.py` — extend with exact-boundary over-allocation rejection (no epsilon)
- `backend/tests/test_exposure_engine.py` — extend with exact fully-hedged status flip
- `backend/tests/test_orders.py` (if exists) — extend with Decimal payload accepted, float-string accepted via Pydantic coercion
- Any test currently using `pytest.approx(...)` on MT/price values — replace with exact Decimal equality

Test posture: **no `pytest.approx` on MT/price assertions** going forward — that's a litmus for whether you achieved the migration.

---

## 8. Critical sequencing

- **Wave 1 — no upstream dependencies.** Start any time after `audit/phase-a1` (docs PR) merges.
- **Downstream:** PR-4 (linkage hardening) and PR-8 (P&L price evidence) must wait for THIS PR to merge. Coordinate with the orchestrator before starting #4 or #8.
- **No branch-level dependencies on PR-2/-3/-6** — these can run truly in parallel.

If you discover during implementation that a Decimal change forces a behavior shift (e.g., a test that passed at float epsilon now fails because the real bug surfaces), surface it in the PR description as `[BEHAVIOR_SHIFT]` and explain — DO NOT silently re-introduce float to make a test pass.

---

## 9. PR shape

**Title:** `fix(audit-a1): PR-1 — Decimal primitives for MT and price (J-A1-04)`

**Body skeleton:**

```markdown
## Summary

Migrate institutional MT quantity and financial-price primitives from Python
`float` to `Decimal` / SQLAlchemy `Numeric`. Foundational fix per Phase A1
jury verdict (FAIL @ commit f1420524) — addresses Tier 1 finding J-A1-04
(constitutional §2.1, §2.6, §2.7).

This PR changes the substrate only. Hard-fail behavior changes (linkage
hardening, P&L price evidence) ship in subsequent Wave 2 PRs that depend on
this.

## Files changed
- Models: orders.py, contracts.py, linkages.py, [others as needed]
- Schemas: [list]
- Services: linkage_service.py, exposure_engine.py, exposure_service.py, deal_engine.py
- Alembic: migration `XXXX_decimal_primitives.py`
- New: `app/core/precision.py` (quantize_mt / quantize_price helpers)
- Frontend: `schema.d.ts` regen

## Quantization policy
- MT: Numeric(15, 3), ROUND_HALF_EVEN by default
- Price: Numeric(18, 6), ROUND_HALF_EVEN by default
- Conservative modes documented inline where used (default unchanged)

## Acceptance evidence
- [ ] All criteria from dispatch §6 met
- [ ] Migration roundtrip verified locally
- [ ] No `pytest.approx` remains on MT/price assertions

## Constitutional impact
- §2.1, §2.6, §2.7 — substrate now allows exact compliance; downstream PRs
  enforce hard-fails.

## Out of scope
- Linkage hardening (PR-4)
- P&L price evidence (PR-8)
- Commodity model (PR-2)
- UoW boundary (PR-3)
- Classification invariant (PR-6)

## Closes
Phase A1 jury finding J-A1-04. Subsumes F-A1-OPUS-13 (S-A1-J-03), F-A1-OPUS-14
(S-A1-J-04).
```

---

## 10. Constraints — what NOT to do

- DO NOT introduce new hard-fails in this PR (PR-4 / PR-8 territory)
- DO NOT add `Order.commodity` column (PR-2)
- DO NOT remove silent fallback in `_get_market_price` (PR-8)
- DO NOT change reconcile clamp semantics (PR-4)
- DO NOT skip migration roundtrip verification
- DO NOT use `--no-verify` to skip git hooks
- DO NOT amend the merge commit; create new commits if hooks fail
- DO NOT auto-merge — wait for Codex review (mandatory)
- DO NOT widen scope to fix unrelated `float` usage outside MT/price (e.g., percentage calculations in narrative paths) — out of scope unless on a risk-boundary path

---

## 11. Workflow

1. `git fetch origin && git checkout -b audit-a1/decimal-primitives origin/main`
2. Read jury verdict in full (§2 J-A1-04)
3. Implement model changes first → schemas → services → migration → tests → frontend regen
4. Run full backend test suite locally; resolve any failures (a behavior shift surfacing real bugs is OK — flag in PR; a regression is not OK — fix it)
5. `git push -u origin audit-a1/decimal-primitives`
6. `gh pr create --base main --title "<§9 title>" --body-file <body>`
7. **STOP. Wait for Codex review.** Do NOT request human review or merge until Codex completes.
8. Address Codex feedback in new commits (no force-push, no amend)
9. Report back to orchestrator: branch name, PR URL, final SHA, Codex verdict

---

## 12. Final report shape

When complete, report to orchestrator:
- Branch + PR URL + final SHA
- Files touched (grouped: models / schemas / services / migration / tests / frontend)
- Migration roundtrip evidence (alembic upgrade/downgrade output)
- Test pass/fail counts vs main baseline
- Codex review status
- Any `[BEHAVIOR_SHIFT]` notes from §8

Keep report under 600 words.

Boa caça.
