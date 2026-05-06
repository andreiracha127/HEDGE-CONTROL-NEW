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

If `price_lookup_service.py` does not yet have a clean exception type, add one (small, in `price_lookup_service.py`). Do not refactor that service — out of scope.

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

#### 3.4.1 Add provenance columns to `DealPNLSnapshot`

The model at `backend/app/models/deal.py:129-157` (verify line range) currently has `inputs_hash: String(64)` and the P&L decimal columns. Add three **nullable** provenance columns plus a CHECK constraint that ties them together — nullability is the only honest representation of fixed-price-only snapshots that legitimately did not consult any market price:

```python
class DealPNLSnapshot(Base):
    __table_args__ = (
        # Provenance is all-or-nothing: either the snapshot consumed a market
        # price (fixed-price-only deals do not) and all three columns are
        # populated, or none of them are. No fake/sentinel provenance ever.
        CheckConstraint(
            "(market_price_value IS NULL AND market_price_source IS NULL AND market_price_date IS NULL)"
            " OR (market_price_value IS NOT NULL AND market_price_source IS NOT NULL AND market_price_date IS NOT NULL)",
            name="chk_deal_pnl_snapshot_provenance_consistency",
        ),
    )
    ...
    market_price_value: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_NUMERIC_PRECISION, PRICE_NUMERIC_SCALE), nullable=True
    )
    market_price_source: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # e.g., "westmetall_cash_settlement", "lme_official", or whatever the
    # price_lookup_service emits; coordinate the source-name vocabulary
    # with the service so it's deterministic
    market_price_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # The actual settlement date used (D-1 of snapshot_date typically)
```

**Population rule (enforced by `compute_deal_pnl`, not by the schema):**
- Snapshot **with** at least one variable-price physical leg or active hedge contract → all 3 columns populated with real values
- Snapshot **with** only fixed-price legs and no active hedges → all 3 columns NULL (no market price was consulted; provenance is legitimately empty)
- The CHECK constraint above prevents partial states (e.g., source set but value NULL)

**Migration:** add 3 columns nullable from the start. No backfill needed — existing rows naturally become "provenance unknown / pre-this-PR" with NULL across all three (consistent with the CHECK). Document in migration docstring: *"Provenance columns nullable by design; populated only when a market price was consulted to compute the snapshot. Pre-this-PR rows remain NULL across all three — provenance for those was never captured and cannot be reconstructed."*

**No preflight required** for this migration since the columns are nullable from the start; legacy rows are correctly represented as NULL (provenance unknown, predates the rule). This is the legitimate use of NULL as "absent" — distinct from the forbidden "fake sentinel" pattern.

**Do not** introduce a workaround like `'pre_provenance'` source string for legacy rows. NULL is the honest representation; sentinel strings are exactly the §2.7 violation we are removing from the runtime path.

#### 3.4.2 Include provenance in `_compute_inputs_hash`

The provenance fields are optional in the function signature (mirroring the schema). When the snapshot did not consult a market price (fixed-price-only deal), all three are `None` and serialize as JSON `null`:

```python
def _compute_inputs_hash(
    deal_id: _uuid.UUID,
    snapshot_date: date,
    link_ids: list[_uuid.UUID],
    market_price_source: str | None,
    market_price_value: Decimal | None,
    market_price_date: date | None,
) -> str:
    data = json.dumps(
        {
            "deal_id": str(deal_id),
            "snapshot_date": str(snapshot_date),
            "links": sorted(str(lid) for lid in link_ids),
            "market_price_source": market_price_source,  # str or None
            "market_price_value": (
                str(market_price_value) if market_price_value is not None else None
            ),  # str avoids float roundtrip; None preserves "no market price consulted"
            "market_price_date": (
                str(market_price_date) if market_price_date is not None else None
            ),
        },
        sort_keys=True,
    )
    return hashlib.sha256(data.encode()).hexdigest()
```

Caller (`compute_deal_pnl`) computes hash AFTER fetching `market_price` (or determining it isn't needed) so the provenance is in scope. Idempotency property:
- Fixed-price-only deal: same `(deal, date, links)` and `(None, None, None)` provenance → same hash → returns existing snapshot
- Variable-price/hedge deal: same `(deal, date, links)` and same `(source, value, date)` → same hash → returns existing snapshot
- Different price ref (e.g., service patched and now returns corrected value) → different hash → new snapshot row → forensic trail preserved

The all-NULL provenance for fixed-price-only must be encoded into the hash deterministically (per the JSON dump above) so different fixed-price-only snapshots for the same `(deal, date, links)` collapse into one row, while a variable-price snapshot for the same identifiers produces a distinct hash.

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

- [ ] **Migration:** schema has `market_price_value`, `market_price_source`, `market_price_date` columns (all nullable) and the `chk_deal_pnl_snapshot_provenance_consistency` CHECK constraint
- [ ] **Test:** Variable-price/hedge `DealPNLSnapshot` row contains the three provenance fields populated from the actual price lookup
- [ ] **Test:** Fixed-price-only `DealPNLSnapshot` row has all three provenance fields NULL — and the CHECK constraint accepts this state
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
