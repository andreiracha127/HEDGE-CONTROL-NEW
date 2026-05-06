# Phase A1 — PR #8 Dispatch — P&L Price Evidence (Hard-Fail + Provenance)

**Wave:** 2
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-06
**Findings covered:** J-A1-01 (Tier 1) + S-A1-J-01 (subsumed F-A1-OPUS-11)
**Branch name:** `audit-a1/pnl-price-evidence`
**Base:** `main` (latest, post #15 + #13)
**Upstream deps satisfied:** PR #15 (Decimal substrate) MERGED — `_get_market_price`, `compute_deal_pnl`, `_order_value` now operate on Decimal; this PR removes the silent fallbacks while preserving the Decimal substrate.

---

## 1. Mission

Remove every silent fallback on P&L pricing. When a market price is required for a variable-price physical leg or for an active hedge MTM, **the system must hard-fail with a domain-specific exception** — not return `None`, not fall back to `avg_entry_price`, not set `mtm = Decimal("0")`. Additionally, `DealPNLSnapshot` must persist (or hash) **price provenance** so that the same `inputs_hash` cannot map to two different price references over time.

This is the deepest constitutional defect in the audited surface: §2.6 ("Price reference cannot be proven" → hard-fail; "no silent fallback") is being violated three times in a single function path (`_get_market_price` swallows all exceptions, `_order_value` silently swaps to `avg_entry_price`, `compute_deal_pnl` collapses missing market to `Decimal("0")`).

**Persona:** Senior engineer for an institutional risk system. The MTM number on a P&L snapshot is signed evidence; if the price reference is unprovable, the snapshot must not exist. "Safe default" = fraud surface in this domain.

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-06-phase-a1-jury-verdict.md`** — §2 J-A1-01 + §6 S-A1-J-01. Read in full.
- **`docs/governance.md`** — §2.6 (hard-fails), §2.7 (verifiable, audit-friendly).
- **`docs/audits/2026-05-06-phase-a1-findings-opus.md`** — F-A1-OPUS-03, F-A1-OPUS-11 (subsumed).
- **`docs/audits/2026-05-06-phase-a1-findings-gemini.md`** — F-A1-GEMINI-01 (convergent).
- **Code currently in main (read these before writing — line numbers post #15 may have shifted, verify by grep):**
  - `backend/app/services/deal_engine.py` — `_get_market_price` (~line 61-79), `_compute_inputs_hash` (~line 44-58), `DealEngineService._order_value` (~line 391-407), `DealEngineService.compute_deal_pnl` (~line 409-502)
  - `backend/app/services/price_lookup_service.py` — `get_cash_settlement_price_d1` (the underlying lookup); read its current behavior to know which exceptions are legitimate
  - `backend/app/models/deal.py` — `DealPNLSnapshot` definition (~line 129-157); has `inputs_hash` but no price provenance fields today

The current bugs (verbatim from main):

```python
# deal_engine.py:_get_market_price — swallows ALL exceptions
def _get_market_price(session, commodity, as_of_date) -> Decimal | None:
    try:
        ...
        return quantize_price(get_cash_settlement_price_d1(...))
    except Exception:
        logger.debug("market_price_unavailable commodity=%s date=%s", ...)
        return None

# deal_engine.py:_order_value — silent fallback for variable-price
def _order_value(order, market_price) -> Decimal:
    qty = quantize_mt(order.quantity_mt)
    if order.price_type == PriceType.fixed:
        return quantize_money(qty * quantize_price(order.avg_entry_price))
    if market_price is not None:
        return quantize_money(qty * quantize_price(market_price))
    return quantize_money(qty * quantize_price(order.avg_entry_price))  # ← silent fallback

# deal_engine.py:compute_deal_pnl — silent zero MTM
if market_price is not None:
    mtm = quantize_money(...)
else:
    mtm = Decimal("0")  # ← silent zero

# deal_engine.py:_compute_inputs_hash — no price provenance
def _compute_inputs_hash(deal_id, snapshot_date, link_ids):
    data = json.dumps({"deal_id": ..., "snapshot_date": ..., "links": ...}, sort_keys=True)
    return hashlib.sha256(data.encode()).hexdigest()
```

---

## 3. Scope IN

### 3.1 Hard-fail in `_get_market_price`

**Fix directive:**

Replace the `except Exception: return None` swallow with explicit handling:

- **Distinguish two cases:** (a) "no data exists for this commodity/date" (legitimate absence — the underlying service should raise a specific `PriceNotAvailable` or similar; check `price_lookup_service.py` for the actual exception class), versus (b) "lookup itself errored" (network, DB, unexpected condition).

- **(a)** must raise a domain exception (`PriceReferenceUnprovable` or similar — read existing exception hierarchy in `backend/app/services/`; do not invent if a closer one exists). The exception is caught by callers (`compute_deal_pnl`, `_order_value`) and propagated as a hard-fail with HTTP 422 or 503 (executor's call — choose based on pattern of other hard-fails in the codebase).

- **(b)** must let the exception propagate (do not swallow). The route returns 5xx; that's an infrastructure failure, not a domain decision.

- **NO `return None`** — the function returns `Decimal` or raises.

**Expand the lookup service to return structured provenance (REQUIRED — was incorrectly forbidden in an earlier draft).** Per Codex catch on PR #17: provenance fields can only be persisted accurately if the lookup service exposes the actual settlement date used. The current `get_cash_settlement_price_d1` returns only `Decimal`, but its docstring documents a fallback up to 5 calendar days for weekends/holidays — meaning the row's `settlement_date` can be several days before `as_of_date - 1`. Without exposing it, the executor would have to guess (wrong on weekends/holidays).

Required change in `price_lookup_service.py`:

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class PriceQuote:
    """Structured result of a price lookup — what was consulted, where it came from, when it settles."""
    value: Decimal
    source: str          # e.g., "lme_cash_settlement", "westmetall_cash_settlement"
    settlement_date: date # the ACTUAL row.settlement_date used (may differ from as_of_date - 1)
    symbol: str          # the resolved symbol (post resolve_symbol)


def get_cash_settlement_price_d1_with_provenance(
    db: Session, symbol: str, as_of_date: date,
) -> PriceQuote:
    # Body mirrors current get_cash_settlement_price_d1, but returns the full row.
    # Source string is determined by inspecting row.source_table or by a constant
    # if CashSettlementPrice has only one origin today (verify by reading the model).
    ...
```

The original `get_cash_settlement_price_d1` may remain as a thin wrapper returning `.value` for backward compat callers, OR be deleted in favor of the new function — the executor decides based on existing call sites. Whatever the choice, **`_get_market_price` in `deal_engine.py` must use the provenance-returning variant**.

This is a small, scope-local refactor — not the broad rework the earlier draft forbade. The forbidden refactor was things like changing the underlying data sources, adding caching, etc.

If `price_lookup_service.py` does not yet have a clean exception type for "no data within lookback window", add one — but the existing `HTTPException(424)` may already serve. Verify before introducing a new type.

### 3.2 Hard-fail in `_order_value` for variable-price + missing market

**Fix directive:**

```python
# Before
if market_price is not None:
    return quantize_money(qty * quantize_price(market_price))
return quantize_money(qty * quantize_price(order.avg_entry_price))  # silent fallback

# After
if market_price is None:
    raise PriceReferenceUnprovable(
        f"variable-price order {order.id} cannot be valued: no market price for "
        f"{order.commodity} on snapshot date"
    )
return quantize_money(qty * quantize_price(market_price))
```

Fixed-price branch is unchanged — `avg_entry_price` is the contract price, not a fallback.

### 3.3 Hard-fail in `compute_deal_pnl` for hedge MTM

**Fix directive:**

```python
# Before
if market_price is not None:
    mtm = quantize_money(...)
else:
    mtm = Decimal("0")  # silent

# After
if market_price is None:
    raise PriceReferenceUnprovable(
        f"hedge contract {contract.id} cannot be MTM-valued: no market price for "
        f"{contract.commodity} on snapshot date"
    )
mtm = quantize_money(...)
```

The exception propagates; `compute_deal_pnl` does NOT persist a `DealPNLSnapshot` in this case. `unit_of_work` rolls back any partial work.

**Behavior change visible to callers:** previously, `POST /deals/{id}/pnl-snapshot` would return a snapshot with `Decimal("0")` MTM on missing prices. Post-this-PR, it returns 422 (or 503 — pick consistently). Document in PR description as `[BEHAVIOR_SHIFT]` per existing convention.

### 3.4 Price provenance in `DealPNLSnapshot` + `_compute_inputs_hash`

**Two sub-changes:**

#### 3.4.1 Add per-commodity provenance to `DealPNLSnapshot`

**Codex catch on PR #17:** an earlier draft prescribed three scalar columns `(market_price_value, market_price_source, market_price_date)` — one triplet per snapshot. That cannot represent a snapshot consuming **multiple** prices, which a single deal legitimately can: a deal with a fixed Aluminum leg + an active Copper hedge needs the Copper price; a deal with two variable-price legs in different commodities needs both. With one scalar triplet, only one is recorded; corrections to an omitted commodity's price could still return a stale snapshot via hash collision. Per-reference provenance is required.

The model at `backend/app/models/deal.py:129-157` (verify line range) gets a single nullable JSONB column `price_references` that holds a dict keyed by commodity:

```python
from sqlalchemy.dialects.postgresql import JSONB

class DealPNLSnapshot(Base):
    __table_args__ = (
        # price_references is either NULL (no market price was consulted —
        # fixed-price-only deal with no active hedges) OR a non-empty JSON
        # object whose keys are commodities and whose values are the
        # full {value, source, settlement_date} for that commodity's
        # consulted price. NULL is the honest representation of "absent";
        # an empty object {} is rejected (it would be ambiguous with NULL).
        CheckConstraint(
            "price_references IS NULL"
            " OR (jsonb_typeof(price_references) = 'object' AND price_references <> '{}'::jsonb)",
            name="chk_deal_pnl_snapshot_price_references_shape",
        ),
    )
    ...
    price_references: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )
    # JSONB shape (when non-NULL):
    #   {
    #       "ALUMINUM": {"value": "5500.123456", "source": "lme_cash_settlement", "settlement_date": "2026-05-05"},
    #       "COPPER":   {"value": "9120.654321", "source": "lme_cash_settlement", "settlement_date": "2026-05-02"},
    #       ...
    #   }
    # - keys: commodity identifiers, must match commodities used elsewhere in the schema
    #   (verify by grep against existing Commodity enum / HedgeContract.commodity values)
    # - values: every entry MUST have all three fields populated. Decimal values
    #   serialized as strings to avoid float roundtrip; ISO dates as strings.
    # - settlement_date may differ from snapshot_date - 1 for weekend/holiday lookbacks
    #   (the actual row.settlement_date the lookup service consulted, returned via PriceQuote)
    # The application layer (compute_deal_pnl) is responsible for emitting only
    # well-formed entries; the CHECK constraint guards against the empty-object
    # ambiguity. Per-entry shape is enforced by the producing code, not by
    # CHECK — Postgres CHECK on JSONB shape is verbose and brittle.
```

**Population rule (enforced by `compute_deal_pnl`):**
- Snapshot consuming N distinct commodities (variable-price physical or active hedge) → `price_references` has N entries, one per commodity
- Snapshot with only fixed-price legs and no active hedges → `price_references = NULL` (no market price was consulted)
- A snapshot that touches two legs of the **same** commodity contributes one entry (deduped by commodity)

**Migration:** add the single `price_references` column nullable from the start + the CHECK constraint. No backfill needed — existing rows naturally become "provenance unknown / pre-this-PR" with NULL `price_references` (consistent with the CHECK). Document in migration docstring: *"price_references nullable by design; populated only when at least one market price was consulted. Pre-this-PR rows remain NULL — provenance for those was never captured and cannot be reconstructed."*

**No preflight required** since the column is nullable from the start; legacy rows are correctly represented as NULL.

**Do not** introduce a workaround like `'pre_provenance'` source for legacy rows. NULL is the honest representation; sentinel objects/strings are exactly the §2.7 violation we are removing from the runtime path.

**Compute_deal_pnl algorithm (REQUIRED for §3.3 to work coherently):**

1. Walk `links`; for each link that requires market valuation, identify the commodity
2. Build the set of unique commodities needed
3. For each commodity, call the new `get_cash_settlement_price_d1_with_provenance(...)` (one call per unique commodity, not per leg)
4. If any call raises (no price within lookback): propagate `PriceReferenceUnprovable` — no snapshot is persisted; `unit_of_work` rolls back
5. Build `price_references` dict from the PriceQuote results: `{commodity: {"value": str(quote.value), "source": quote.source, "settlement_date": quote.settlement_date.isoformat()}}`
6. Compute MTMs using the dict (look up each leg's commodity in the dict)
7. Persist the `DealPNLSnapshot` with `price_references=<the dict>` (or `None` if no commodity required a market price)

#### 3.4.2 Include `price_references` in `_compute_inputs_hash`

The hash function takes the entire `price_references` dict (or `None`). `json.dumps(..., sort_keys=True)` ensures deterministic byte-for-byte output for the same logical inputs:

```python
def _compute_inputs_hash(
    deal_id: _uuid.UUID,
    snapshot_date: date,
    link_ids: list[_uuid.UUID],
    price_references: dict[str, dict[str, str]] | None,
) -> str:
    """SHA-256 hash that uniquely identifies the inputs to compute_deal_pnl,
    including every market price consulted (per commodity).

    `price_references` shape when non-None:
        {commodity: {"value": str, "source": str, "settlement_date": str}, ...}
    All values must be strings (Decimal-as-str, ISO-date-as-str) so JSON
    serialization is deterministic and free of float roundtrip.
    """
    data = json.dumps(
        {
            "deal_id": str(deal_id),
            "snapshot_date": str(snapshot_date),
            "links": sorted(str(lid) for lid in link_ids),
            "price_references": price_references,  # dict of dicts, or None
        },
        sort_keys=True,  # ensures commodity keys sorted; inner dicts sorted
    )
    return hashlib.sha256(data.encode()).hexdigest()
```

Caller (`compute_deal_pnl`) computes the hash AFTER step 5 of the algorithm (after `price_references` is fully built), then performs the existing-snapshot lookup. Idempotency property:

- Fixed-price-only deal: same `(deal, date, links)` and `price_references=None` → same hash → returns existing
- Multi-commodity deal: same `(deal, date, links)` and same `{Aluminum: {...}, Copper: {...}}` → same hash → returns existing
- Correction to ANY commodity's price (e.g., LME republishes with a corrected Copper value) → different inner dict → different hash → new snapshot row → forensic trail of both old and corrected snapshots
- Adding/removing a commodity from the snapshot (because a link was added/removed or hedge status changed) → different keys → different hash → new snapshot row

This is exactly the property the single-triplet design failed: now a correction in any one commodity's price changes the hash, so no stale snapshot is silently returned.

**Caller-side discipline required:** `compute_deal_pnl` MUST build `price_references` with the canonical Decimal-string format before hashing. If the dict is built with `Decimal` values (not strings), serialization may produce non-deterministic output across Python/JSON library versions. Always serialize Decimals to strings at the point of building the dict, BEFORE hashing and BEFORE persisting.

#### 3.4.3 Migration: do NOT backfill legacy `inputs_hash`

The signature change in §3.4.2 means every existing `DealPNLSnapshot` row in the database has an `inputs_hash` computed by the OLD function (without provenance fields). An earlier draft of this dispatch prescribed a backfill that recomputed `inputs_hash` from the deal's *current* `deal_links`. **That approach is institutionally unsafe and is rejected.**

**Why backfill from current links is wrong (Codex catch on PR #17):**

`DealPNLSnapshot` does NOT persist the historical `link_ids` that produced the snapshot's stored P&L values. Backfill that reads `deal_links` for the deal **today** computes a hash that represents *the current link set, not the link set that existed when the legacy snapshot was created*. If the deal's links have changed since the snapshot was created (a link added, removed, or reassigned), the backfilled hash silently associates a stale snapshot with the current state. Subsequent `compute_deal_pnl` calls would then return the legacy snapshot's STALE P&L as if it represented current inputs — exactly the kind of silent-stale-data violation §2.6 forbids.

This is unrecoverable without storing historical link_ids, which is out of scope here (and would require its own dispatch).

**Correct directive: leave legacy `inputs_hash` values UNCHANGED.**

```python
# backend/alembic/versions/0XX_pnl_provenance.py
def upgrade():
    # Add nullable columns + CHECK constraint (per §3.4.1) ONLY.
    # Do NOT touch existing inputs_hash values.
    op.add_column("deal_pnl_snapshots", sa.Column("market_price_value", sa.Numeric(...), nullable=True))
    op.add_column("deal_pnl_snapshots", sa.Column("market_price_source", sa.String(64), nullable=True))
    op.add_column("deal_pnl_snapshots", sa.Column("market_price_date", sa.Date(), nullable=True))
    op.create_check_constraint(
        "chk_deal_pnl_snapshot_provenance_consistency",
        "deal_pnl_snapshots",
        "(market_price_value IS NULL AND market_price_source IS NULL AND market_price_date IS NULL)"
        " OR (market_price_value IS NOT NULL AND market_price_source IS NOT NULL AND market_price_date IS NOT NULL)",
    )


def downgrade():
    op.drop_constraint("chk_deal_pnl_snapshot_provenance_consistency", "deal_pnl_snapshots")
    op.drop_column("deal_pnl_snapshots", "market_price_date")
    op.drop_column("deal_pnl_snapshots", "market_price_source")
    op.drop_column("deal_pnl_snapshots", "market_price_value")
```

**Consequence — and why this is correct, not a bug:**

After deployment, calling `compute_deal_pnl` for a deal that has a legacy snapshot will compute a NEW `inputs_hash` (post-PR-8 format, includes provenance fields). That hash will NOT match the legacy `inputs_hash` (pre-PR-8 format). Result: a NEW row is inserted with proper provenance. The legacy row remains as a sealed historical artifact.

This is the **forensically correct** behavior:

| Row | inputs_hash format | Provenance | Semantic |
|---|---|---|---|
| Legacy (pre-PR-8) | Old format, sealed | NULL across all 3 columns | Computed pre-rule; provenance unknown; preserved as audit trail |
| Post-PR-8 | New format including provenance | Either populated (variable-price/hedge) or all-NULL (fixed-price-only) | Computed post-rule; full provenance; canonical current snapshot |

There is no risk of hash collision between the two formats: the new format hashes a JSON that includes three additional fields (`market_price_*`), so even a fixed-price-only post-PR-8 hash (which uses `null` for all three) is computed from a different JSON document than any pre-PR-8 hash, producing a different sha256 with overwhelming probability.

**Idempotency contract clarification (binding for §6.2 acceptance):**

The §6.2 idempotency rule applies to **post-PR-8 snapshots only**. A pre-PR-8 legacy snapshot is sealed historical data and is intentionally NOT reachable by post-PR-8 hash lookups. Re-running `compute_deal_pnl` for a deal that has only legacy snapshot(s) will produce a new (post-PR-8) row alongside the legacy row(s). Both rows persist in `deal_pnl_snapshots`; the new row is canonical for current state, the legacy row is the forensic record of the pre-rule snapshot.

This is the correct trade-off: we lose the ability to "deduplicate against legacy" (which we never honestly had — provenance was unknown), and we gain a clean forensic boundary between pre-rule and post-rule snapshots without risk of stale data being silently served as current.

**Migration test (REQUIRED):** assert that a pre-existing `DealPNLSnapshot` row's `inputs_hash` is **byte-equal** before and after the migration (i.e., upgrade does not modify the column). Additionally assert that post-upgrade, calling `compute_deal_pnl` for the same deal+date creates a NEW row (different `inputs_hash`) without affecting the legacy row.

---

## 4. Scope OUT

- **Refactor of `price_lookup_service.py` beyond exception type addition** — Phase A4 (external integrations).
- **Other Westmetall / LME calendar issues** — Phase A4.
- **MTM/Cashflow/P&L for non-deal aggregates** — Phase A3 (per-PR-2 catches, scenario_whatif_service already extended; this PR doesn't touch scenario).
- **Premium pricing** — explicitly excluded by §VALUATION constitution.
- **Audit emission on the snapshot creation route** — PR-7 territory; wire there if not already.
- **Decimal substrate** — PR-1 already in main; preserve.
- **UoW boundary** — PR-3 already in main; service still uses `flush()`.

---

## 5. Constitutional rules (binding)

- **§2.6** — "No silent fallback. No heuristic correction. **Price reference cannot be proven** → hard-fail." This PR's whole point.
- **§2.7** — Output contract: precise, verifiable, audit-friendly. Provenance fields make the snapshot reconstructable; without them the `inputs_hash` is misleading.
- **§Valuation** — "MTM uses D-1 settlement. One methodology per endpoint. No fallback pricing regimes." The current `avg_entry_price` fallback is exactly a "fallback pricing regime".

---

## 6. Acceptance criteria (from jury §2 J-A1-01)

### 6.1 Hard-fail behavior

- [ ] **Test:** `POST /deals/{id}/pnl-snapshot` for a deal with a variable-price physical leg + commodity for which no D-1 settlement price exists → returns 422 (or chosen status); no `DealPNLSnapshot` row persisted
- [ ] **Test:** Same scenario with an active hedge contract → 422; no snapshot persisted
- [ ] **Test:** Fixed-price-only deal (no variable-price legs, no hedges) → snapshot persists; the three provenance columns are `NULL` (legitimately absent — no market price was consulted); CHECK constraint passes (all three NULL together)
- [ ] **Test:** CHECK constraint rejects a manually-injected partial-provenance row (e.g., source set, value NULL) → IntegrityError
- [ ] **Test:** Mixed deal (fixed + variable) where variable-price commodity has no price → 422 (the variable-price leg requires evidence)
- [ ] **Test:** Happy path (all legs valuable) → snapshot persists with provenance fields populated
- [ ] **Test:** `_get_market_price` raises `PriceReferenceUnprovable` (or chosen exception) on missing price; no `return None` path exists (verify by inspection)
- [ ] **Test:** `_order_value` raises on variable + missing market; no fallback to `avg_entry_price` (verify by code grep + dedicated test)

### 6.2 Provenance

- [ ] **Migration:** schema has the single `price_references` JSONB column (nullable) and the `chk_deal_pnl_snapshot_price_references_shape` CHECK constraint
- [ ] **Migration:** legacy `inputs_hash` values are **byte-equal** before and after the migration — the migration does not rewrite them (per §3.4.3 — backfilling from current `deal_links` would silently bind legacy snapshots to current link sets and serve stale P&L)
- [ ] **Test (migration boundary):** create a `DealPNLSnapshot` row at the pre-migration state, run the migration, assert `inputs_hash` byte-equal pre- and post-migration; then call `compute_deal_pnl(...)` for the same deal (fixed-price-only) post-migration and assert it creates a NEW row (different `inputs_hash`), legacy row preserved
- [ ] **Test:** Single-commodity variable-price snapshot has `price_references = {commodity: {value, source, settlement_date}}` populated from `get_cash_settlement_price_d1_with_provenance`
- [ ] **Test (multi-commodity):** Snapshot consuming Aluminum + Copper (e.g., fixed Aluminum order + active Copper hedge) has `price_references` with BOTH commodity keys populated; correcting either price (mock different return) yields a different `inputs_hash` and produces a new snapshot row
- [ ] **Test (weekend lookback):** Snapshot whose `snapshot_date` is a Monday and whose lookup falls back to Friday's price — `price_references[commodity]["settlement_date"]` equals the actual Friday date, NOT `Monday - 1` (Sunday)
- [ ] **Test (deduplication):** Snapshot with two legs of the same commodity → `price_references` has exactly ONE entry for that commodity (one lookup, deduplicated)
- [ ] **Test:** Fixed-price-only `DealPNLSnapshot` row has `price_references = NULL`; CHECK constraint accepts this state
- [ ] **Test (CHECK):** Manually inserting a row with `price_references = {}` (empty object) is rejected by CHECK (ambiguous with NULL)
- [ ] **Idempotency contract scoped to post-PR-8 snapshots:** test asserts two consecutive post-PR-8 calls for the same `(deal, date, links, price_references)` return the SAME row; legacy snapshots are NOT in scope of this rule
- [ ] **Test:** Two snapshots for the same `(deal, date, links)` but with different `market_price_value` (e.g., simulated by mocking price service) produce DIFFERENT `inputs_hash` → both persist; the latest does NOT silently overwrite the earlier
- [ ] **Test:** Re-running `compute_deal_pnl` with no input change returns the existing snapshot (idempotency preserved)
- [ ] **Test:** `inputs_hash` SHA256 includes all provenance fields (verify by inspection of the hash composition)

### 6.3 No regression

- [ ] All PR-15 (Decimal) tests pass
- [ ] All PR-13 (UoW) tests pass
- [ ] No `Decimal("0")` else branch in `compute_deal_pnl` (verify by grep)
- [ ] No `return None` in `_get_market_price` (verify by grep)
- [ ] No `avg_entry_price` fallback in `_order_value` for variable-price (verify by inspection of the function)

---

## 7. Test coverage required

| Test file | Status | Covers |
|---|---|---|
| `backend/tests/test_pnl_price_evidence.py` | NEW | §6.1 hard-fail behaviors |
| `backend/tests/test_pnl_provenance.py` | NEW | §6.2 provenance + idempotency |
| `backend/tests/test_deal_engine.py` | EXTEND | regression / happy path with provenance |
| `backend/tests/test_pnl_migration.py` | NEW (only if migration touches existing rows) | §3.4.1 preflight |

For tests that mock `price_lookup_service`: use the project's existing test fixture pattern (read `backend/tests/conftest.py` to find the mock pattern).

---

## 8. Critical sequencing

- **Upstream:** PR #15 MERGED. Verify Decimal substrate is in `compute_deal_pnl` before starting.
- **Coordinate with PR #16 (Order commodity model):** PR #16 received Codex catches that touched `MTM/cashflow/P&L per commodity` (P2). When #16 lands, `compute_deal_pnl` may be commodity-aware in ways that interact with this PR's hard-fail. Concretely: a deal with multiple commodities might require multiple price lookups (one per commodity), and missing price for any one of them must hard-fail the whole snapshot — do not partially succeed. Verify by `git log origin/main -- backend/app/services/deal_engine.py` after #16 merges; rebase this PR carefully if signatures shifted.
- **Coordinate with PR-7 (audit emission):** PR-7 wires audit on the P&L snapshot route. Either order works; if PR-7 lands first, this PR's behavior change (snapshot doesn't persist on hard-fail) is automatically reflected in audit trail (no audit row for failed mutation, per `unit_of_work` rollback).
- **Coordinate with PR-4 (linkage hardening):** independent surface — no direct interaction.
- **Downstream:** none directly. Phase A3 (valuation) audit will pick up any remaining MTM issues.

---

## 9. PR shape

**Title:** `fix(audit-a1): PR-8 — P&L price evidence (hard-fail + provenance) (J-A1-01)`

**Body skeleton:**

```markdown
## Summary

Remove silent fallbacks in P&L pricing path. Hard-fail when market price
cannot be proven for a variable-price physical leg or for an active hedge
MTM. Persist price provenance (source, value, date) on `DealPNLSnapshot`
and include in `inputs_hash` for forensic-grade idempotency.

Constitutional §2.6 ("price reference cannot be proven → hard-fail"; no
silent fallback) and §2.7 (verifiable, audit-friendly).

## Behavior change [BEHAVIOR_SHIFT]
- Previously: `POST /deals/{id}/pnl-snapshot` returned a snapshot with
  `Decimal("0")` MTM when market price was missing; physical variable-price
  silently fell back to `avg_entry_price`.
- Now: returns 422 (or 503 — see §3.x) and no snapshot is persisted.
- Operator-visible: integrations relying on the silent path will fail.
  Document in operations runbook (out of scope here; flag as follow-up).

## Files changed
- Services: deal_engine.py (3 hard-fail sites; `_compute_inputs_hash` extended)
- Services: price_lookup_service.py (only if exception type added)
- Models: deal.py (`DealPNLSnapshot` 3 new columns)
- Alembic: migration `0XX_pnl_provenance.py` (with preflight per §3.4.1)
- Tests: test_pnl_price_evidence.py (new), test_pnl_provenance.py (new),
  test_deal_engine.py (extended)

## Migration preflight
- Pre-existing `DealPNLSnapshot` rows: N
- Strategy: {empty-table simple ADD COLUMN / fail-closed preflight / chosen
  backfill rationale}

## Acceptance evidence
- Hard-fail tests pass (§6.1)
- Provenance tests pass (§6.2)
- Two-price-version idempotency test (§6.2 row 3)
- No regression in W1 PR test suites

## Out of scope
- Phase A4 external integration hardening
- Premium pricing (constitution-excluded)
- Other valuation paths beyond `compute_deal_pnl` (Phase A3)

## Closes
J-A1-01. Subsumes F-A1-OPUS-11 (S-A1-J-01).
```

---

## 10. Constraints — what NOT to do

- DO NOT silence the new exceptions anywhere — propagate to the route layer
- DO NOT add a "fallback price source" toggle / config flag — institutional system, not a UX-configurable
- DO NOT default new provenance columns to `'unknown'` or empty string — that recreates the bug at the persistence layer
- DO NOT regress to float arithmetic (PR-1 substrate preserved)
- DO NOT call `session.commit()` from any service (PR-3 boundary preserved)
- DO NOT modify `audit_trail_service.py`
- DO NOT touch `scenario_whatif_service.py` (already extended by PR-2 catches; Phase A3 territory beyond)
- DO NOT add new pricing methodologies or "smarter" fallbacks — constitution forbids
- DO NOT use `--no-verify`, no force-push, no auto-merge
- DO NOT auto-merge — Codex review mandatory

---

## 11. Workflow

1. `git fetch origin && git checkout -b audit-a1/pnl-price-evidence origin/main`
2. Verify upstream: `grep -n "Decimal" backend/app/services/deal_engine.py | head -5` shows Decimal in use
3. Read jury §2 J-A1-01 + Opus F-A1-OPUS-03 + F-A1-OPUS-11 in full
4. Read `_get_market_price`, `_order_value`, `compute_deal_pnl`, `_compute_inputs_hash` in current main
5. Read `price_lookup_service.py` to identify legitimate exceptions
6. Choose exception type (existing or new); document in PR description draft
7. Decide migration preflight strategy (§3.4.1); document
8. Implement: exception type → `_get_market_price` → `_order_value` → `compute_deal_pnl` → model + migration → `_compute_inputs_hash` → tests
9. Run `pytest backend/tests/test_deal_engine.py backend/tests/test_pnl_price_evidence.py -v`
10. `git push -u origin audit-a1/pnl-price-evidence`
11. `gh pr create --base main`
12. **STOP. Wait for Codex review.**
13. Address feedback in new commits

---

## 12. Final report shape

- Branch + PR URL + final SHA
- Exception type chosen + rationale
- Migration preflight outcome (rows affected, strategy)
- Behavior change documented
- Test results
- Codex verdict
- Any new findings outside scope

Under 600 words.

Boa caça.
