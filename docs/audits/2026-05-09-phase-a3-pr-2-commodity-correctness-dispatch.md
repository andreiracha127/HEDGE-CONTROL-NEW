# Phase A3 — PR #A3-2 Dispatch — Commodity Correctness

**Wave:** 2 (depends on Wave 1 PR-A3-1 merge — uses the migrated `_with_provenance` lookup)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-09
**Findings covered:** J-A3-02 (T1, Order MTM ignores `Order.commodity`) + J-A3-OPUS-01 (T1, Scenario virtual hedge deltas hard-code commodity to LME_AL)
**Branch name:** `audit-a3/commodity-correctness`
**Base:** `main` (currently `030a49bff`, post-PR #41 Wave 1 implementation)

---

## 0. Refresh notes (read first)

This is the **second iteration** of the PR-A3-2 dispatch. Iteration 1 was reviewed by Codex (PR #42 round 1) and flagged a Tipo I fact-mismatch in §7's prescribed test assertion: it referenced `result.contracts[<id>].price_quote.symbol`, but `ScenarioWhatIfRunResponse` exposes `mtm_snapshot` (not `contracts`), and `_mtm_for_contract` constructs `MTMResultResponse` without populating `price_quote`. The test was doubly unsatisfiable.

Iteration 2 resolves this by **extending the scope** to plumb the existing Wave 1 `PriceQuote` provenance through the scenario MTM call sites — a parallel-persistence-symmetry application of the Wave 1 invariant to the scenario surface. The plumbing is a clean type-flow change (no new concepts): `_build_price_lookup` and `_resolve_price_d1` now return `PriceQuote` instead of `Decimal`; `_mtm_for_contract` and `_mtm_for_order` accept `PriceQuote` and populate `MTMResultResponse.price_quote`. The test then asserts `mtm_snapshot[<i>].price_quote.symbol` against the correct response shape, with the symbol provably matching the operator-supplied commodity. See §3.7.

Wave 1 PR-A3-1 (PR #41) merged at main `030a49bff` introduced the price-provenance machinery (`_with_provenance` lookup, MTM/P&L/Baseline snapshots carrying `price_source` + `price_symbol` + `price_settlement_date` + `inputs_hash` + `price_value`, server-side ledger derivation, business-calendar lookback). Wave 2 builds on that foundation — without it, the commodity-correctness fix would persist non-aluminum snapshots with the same `price_symbol="LME_ALU_CASH_SETTLEMENT_DAILY"` regardless of fix, hiding the bug at the symbol layer.

Verified via Serena against `main = 030a49bff`:
- `mtm_order_service.compute_mtm_for_order` at `:21-79` declares `commodity: str = DEFAULT_COMMODITY` parameter; `DEFAULT_COMMODITY = "LME_AL"` constant.
- `Order.commodity` field exists at `models/orders.py:67` (`Mapped[str]`, `String(length=64)`, nullable=False).
- 5 call sites consume `compute_mtm_for_order` without passing the `commodity` argument: `routes/mtm.py:44`, `routes/mtm.py:73` (via `create_mtm_snapshot_for_order`), `cashflow_analytic_service.py:52`, `mtm_snapshot_service.py:129` (via `create_mtm_snapshot_for_order`), `scenario_whatif_service.py:181` (explicit `commodity=DEFAULT_COMMODITY`).
- `scenario_whatif_service.py:43` declares its own `DEFAULT_COMMODITY = "LME_AL"`; `scenario_whatif_service.py:181` constructs `VirtualHedgeContract(commodity=DEFAULT_COMMODITY, ...)` — operator cannot specify which commodity the virtual hedge is for.
- `AddUnlinkedHedgeContractDelta` schema at `schemas/scenario.py:18-34` has fields for `contract_id`, `quantity_mt`, `fixed_leg_side`, `variable_leg_side`, `fixed_price_value`, `fixed_price_unit`, `float_pricing_convention` — but **no `commodity` field**.
- `scenario_whatif_service._mtm_for_contract` (`:84-103`) and `_mtm_for_order` (`:107-...`) construct `MTMResultResponse` without populating `price_quote` — the field exists on the schema (`MTMResultResponse.price_quote: PriceQuote | None = None`, `schemas/mtm.py:24`) but defaults to `None` in scenario context. After Wave 1, real (non-scenario) MTM/P&L call sites populate `price_quote` via `get_cash_settlement_price_d1_with_provenance`, but the scenario MTM still uses the thin `get_cash_settlement_price_d1` wrapper that discards the provenance triplet.
- `_build_price_lookup` (`:60-72`) callable signature is `Callable[[Session, str, date], Decimal]`; `_resolve_price_d1` (`:75-82`) returns `Decimal`. These are the two pivot points for the Iteration-2 plumbing change.
- `PriceQuote` is a frozen dataclass at **`backend/app/utils/price_reference.py:24-31`** (re-verified via Serena `find_symbol` against `030a49bff` at the time of this dispatch authoring) with 4 required fields: `value: Decimal`, `source: str`, `settlement_date: date`, `symbol: str`. No `inputs_hash`. Constructible by both the override path (with `source="scenario_override"`) and the settlement-table path (delegating to `get_cash_settlement_price_d1_with_provenance`).
  - **Stale-citation note**: the PR-A3-1 dispatch (cited in §2 reference docs) lists `PriceQuote` at `backend/app/services/price_lookup_service.py:42-56`. That citation reflects an earlier draft of Wave 1 that staged `PriceQuote` inside `price_lookup_service` before the eventual Wave 1 final layout moved it to `utils/price_reference`. **The §0 location above (`utils/price_reference.py:24-31`) is authoritative**; trust this dispatch's Serena-verified citation over the PR-A3-1 reference doc when they disagree.

Wave 2 surface is much smaller than Wave 1 (no schema migration; no new utility modules; existing models unchanged). Expected dispatch size: ~400 lines vs Wave 1's 1,176.

---

## 1. Mission

Remove the commodity-defaulting bug from MTM order pricing and scenario virtual-hedge construction. Today, non-aluminum orders priced via `compute_mtm_for_order` are silently valued against the LME aluminum settlement curve because the function defaults `commodity` to `LME_AL` and no caller passes the order's actual commodity. The same bug exists in `scenario_whatif_service`, where every operator-added virtual hedge is constructed with `commodity=DEFAULT_COMMODITY` regardless of what commodity the operator intended to model. Both surfaces violate **§2.1 governance — "no fallback pricing regimes"**: silently substituting one commodity's price for another's is a regime fallback by another name.

After PR-A3-2:
- `compute_mtm_for_order` resolves the commodity from `order.commodity` directly. The function signature drops the `commodity` parameter (or makes it test-only override; see §3.1).
- `AddUnlinkedHedgeContractDelta` carries an explicit `commodity` field. `scenario_whatif_service` reads `delta.commodity` when constructing `VirtualHedgeContract`. The `DEFAULT_COMMODITY` constant in `scenario_whatif_service` is removed.
- Every existing call site that passes `commodity=DEFAULT_COMMODITY` is updated.
- Cross-commodity tests (Cu, Zn, Ni, Pb, Sn) verify each commodity prices against its own curve, persisting the correct `price_symbol` on the resulting `MTMSnapshot` (verifying the Wave 1 provenance machinery surfaces the fix).
- Scenario MTM plumbing (`_build_price_lookup`, `_resolve_price_d1`, `_mtm_for_contract`, `_mtm_for_order`) threads `PriceQuote` end-to-end so that `mtm_snapshot[i].price_quote.symbol` is populated for every scenario MTM result. This is parallel-persistence-symmetry with Wave 1: real MTM surfaces gained provenance plumbing in PR #41; the scenario MTM surface gains it here. The test for J-A3-OPUS-01 then asserts the resulting `price_quote.symbol` matches the operator-supplied commodity directly.

**Persona:** Senior software engineer building an institutional trading platform. Constitution `docs/governance.md` is supreme authority — **§2.1 VALUATION/MTM/CASHFLOW** (governance.md:131-146, "no fallback pricing regimes"), **§2.6 GOVERNANCE HARD FAILS** (governance.md:159-174, "evidence missing" / "price reference unprovable"). Pricing-domain awareness obligatory.

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-09-phase-a3-jury-verdict.md`** §2 J-A3-02 (convergent T1, Order MTM commodity default) + §3 J-A3-OPUS-01 (Auditor-A-only validated T1, scenario virtual hedge commodity hard-code). Read both in full.
- **`docs/governance.md`** §131-146 + §159-174.
- **`docs/audits/2026-05-09-phase-a3-pr-1-price-provenance-dispatch.md`** — Wave 1 dispatch (in main since PR #40). PR-A3-2 inherits its provenance machinery; do NOT re-prescribe `_with_provenance` consumer migration.
- **`backend/app/services/mtm_order_service.py:21-79`** — `compute_mtm_for_order` (the commodity-default surface).
- **`backend/app/services/mtm_order_service.py:43`** — `DEFAULT_COMMODITY = "LME_AL"` constant (to remove or scope to test-only).
- **`backend/app/models/orders.py:55-...`** — `Order` model. Confirm `commodity: Mapped[str]` (String length=64) field at `:67`.
- **`backend/app/services/scenario_whatif_service.py:43`** — `DEFAULT_COMMODITY = "LME_AL"` constant (to remove).
- **`backend/app/services/scenario_whatif_service.py:46-58`** — `VirtualHedgeContract` dataclass (already carries `commodity: str`; consumer of the delta).
- **`backend/app/services/scenario_whatif_service.py:178-191`** — virtual-hedge construction site (the `DEFAULT_COMMODITY` hard-code surface).
- **`backend/app/schemas/scenario.py:18-34`** — `AddUnlinkedHedgeContractDelta` (the schema that needs a new `commodity` field).
- **`backend/app/api/routes/mtm.py:14-...`** — MTM routes (`compute_mtm_for_order` call sites).
- **`backend/app/services/mtm_snapshot_service.py:116-...`** — `create_mtm_snapshot_for_order` (call site).
- **`backend/app/services/cashflow_analytic_service.py:52`** — Analytic call site.

---

## 3. Scope IN — what PR-A3-2 ships

> **Line-number disclaimer:** all line numbers below are validated at `030a49bff` (2026-05-09 post-Wave-1). Locate edits by symbol / identifier first.

### 3.1 `compute_mtm_for_order` — drop default; resolve from `order.commodity`

**Current** at `mtm_order_service.py:21-26`:

```python
def compute_mtm_for_order(
    db: Session,
    order_id: UUID,
    as_of_date: date,
    commodity: str = DEFAULT_COMMODITY,
) -> MTMResultResponse:
    order = db.get(Order, order_id)
```

**Replacement** (drop the `commodity` parameter entirely; resolve from `order.commodity`):

```python
def compute_mtm_for_order(
    db: Session,
    order_id: UUID,
    as_of_date: date,
) -> MTMResultResponse:
    order = db.get(Order, order_id)
    if not order:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Order not found"
        )
    # ... existing pricing-eligibility checks at :33-54 unchanged ...

    try:
        price_quote = get_cash_settlement_price_d1_with_provenance(
            db, symbol=resolve_symbol(order.commodity), as_of_date=as_of_date
        )
    except PriceReferenceUnprovable as exc:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY, detail=str(exc),
        ) from exc
    # ... rest of the function unchanged ...
```

The change is exactly two edits inside the function: drop the `commodity: str = DEFAULT_COMMODITY` parameter (line 26) and replace `resolve_symbol(commodity)` with `resolve_symbol(order.commodity)` (line 58, verified via Serena against `030a49bff`). The rest of the function — pricing-eligibility checks, exception translation, return shape — is untouched.

**Why drop the parameter rather than make it `None`-default**: a `commodity` parameter that callers can override would re-create the bug at the caller layer (any caller forgetting to pass it gets aluminum). Resolving from `order.commodity` directly inside the function makes the data-flow contract explicit: the order knows its commodity; the function asks the order, not the caller.

**Test-only override**: if a unit test legitimately needs to substitute a different commodity (e.g., to test the pricing path without setting up a full Order row), use a fixture-level `Order(commodity=...)` constructor — NOT a function parameter. The function MUST trust the order it's given.

### 3.2 Remove `DEFAULT_COMMODITY` from `mtm_order_service`

The constant at `mtm_order_service.py:43` is no longer referenced by the function body (after §3.1). Delete the constant. If any test imports it, the test must be updated to construct fixtures with explicit commodities.

### 3.3 Update 4 call sites that no longer pass the now-removed parameter

The 4 callers (verified via Serena `find_referencing_symbols`):

- **`backend/app/api/routes/mtm.py:44`** — current: `return compute_mtm_for_order(session, order_id=order_id, as_of_date=as_of_date)`. The `commodity` arg was already not passed; this site works by accident today (gets aluminum). Post-§3.1 the function no longer accepts the kwarg, so the call is unchanged but the behavior corrects. Verify route signature does NOT accept a `commodity` query parameter that operators could legitimately need to pass (it does not — confirm via Serena `find_symbol`).
- **`backend/app/api/routes/mtm.py:73`** — via `create_mtm_snapshot_for_order(session, order_id=..., as_of_date=...)`. Same shape — already not passing commodity; works correctly post-§3.1.
- **`backend/app/services/mtm_snapshot_service.py:129`** — via `compute_mtm_for_order(db, order_id=order_id, as_of_date=as_of_date)`. Already not passing commodity; works correctly post-§3.1.
- **`backend/app/services/cashflow_analytic_service.py:52`** — via `compute_mtm_for_order(db, order_id=order.id, as_of_date=as_of_date)`. Already not passing commodity; works correctly post-§3.1.

**Note**: all 4 call sites today DO NOT pass `commodity`, which is why every order's MTM has been priced against aluminum. The §3.1 signature change makes the bug a compile-time / runtime hard-fail (function would reject extra kwarg) for any future caller that tries to pass `commodity=DEFAULT_COMMODITY` explicitly.

### 3.4 Update the 5th call site — `scenario_whatif_service.py:181`

This call site DOES explicitly pass `commodity=DEFAULT_COMMODITY` — but it's not calling `compute_mtm_for_order`; it's constructing `VirtualHedgeContract`. The fix here is in §3.5 (operator-supplied delta commodity).

### 3.5 `AddUnlinkedHedgeContractDelta` — add explicit `commodity` field

**Current** at `schemas/scenario.py:18-34`:

```python
class AddUnlinkedHedgeContractDelta(ScenarioDeltaBase):
    delta_type: Literal["add_unlinked_hedge_contract"]
    contract_id: UUID
    quantity_mt: Decimal
    fixed_leg_side: Literal["buy", "sell"]
    variable_leg_side: Literal["buy", "sell"]
    fixed_price_value: Decimal
    fixed_price_unit: Literal["USD/MT"]
    float_pricing_convention: str = Field(..., max_length=64)

    @model_validator(mode="after")
    def validate_quantity(self) -> "AddUnlinkedHedgeContractDelta":
        # ...
```

**Replacement** — add `commodity` as a required field with validation against the supported set:

```python
class AddUnlinkedHedgeContractDelta(ScenarioDeltaBase):
    delta_type: Literal["add_unlinked_hedge_contract"]
    contract_id: UUID
    commodity: str = Field(..., max_length=64)  # required: operator MUST specify
    quantity_mt: Decimal
    fixed_leg_side: Literal["buy", "sell"]
    variable_leg_side: Literal["buy", "sell"]
    fixed_price_value: Decimal
    fixed_price_unit: Literal["USD/MT"]
    float_pricing_convention: str = Field(..., max_length=64)

    @model_validator(mode="after")
    def validate(self) -> "AddUnlinkedHedgeContractDelta":
        if self.quantity_mt <= 0:
            raise ValueError("quantity_mt must be greater than zero")
        if self.fixed_price_value <= 0:
            raise ValueError("fixed_price_value must be greater than zero")
        # Verify commodity resolves to a known settlement symbol; reject early
        # so the scenario doesn't fail mid-run with an obscure 400 from
        # resolve_symbol. This mirrors the institutional pattern that
        # boundary validation belongs at the schema layer.
        try:
            resolve_symbol(self.commodity)
        except HTTPException as exc:
            raise ValueError(
                f"commodity {self.commodity!r} has no settlement-symbol mapping"
            ) from exc
        return self
```

**Why required, not optional with default**: an optional `commodity` with a default of `LME_AL` would re-create the bug at the schema layer. Per `feedback_dispatch_self_consistency` "MVP fallback phrasing": defaults that silently re-create the bug being fixed are the highest-risk shape.

**Schema validation**: the `resolve_symbol` round-trip in the validator catches typos / unsupported commodities at request-parse time. Mirrors the institutional pattern from §3.1: the function trusts what it's given because the boundary validated it.

**Imports to add** at `backend/app/schemas/scenario.py` (verified via grep against `030a49bff`: neither `resolve_symbol` nor `HTTPException` is currently imported in this file):

```python
from fastapi import HTTPException                              # NEW — caught and re-raised by the validator
from app.services.price_lookup_service import resolve_symbol   # NEW — round-trip target for commodity validation
```

The validator catches `HTTPException` because `resolve_symbol` raises `HTTPException(400)` on unsupported commodity (verified via Serena against `price_lookup_service.py`). The `except HTTPException` block translates it to a Pydantic `ValueError`, which Pydantic then surfaces as a structured 422 with field-level error info — preserving the institutional "boundary validates" pattern. Without the imports, `resolve_symbol` is `NameError` and `HTTPException` is `NameError` — the validator path itself fails to load.

**`[BEHAVIOR_SHIFT]` flag in PR description**: existing scenario API consumers (frontend, integration tests, operator scripts) supplying `add_unlinked_hedge_contract` deltas without `commodity` will receive 422 from the new validator. Document in §9 PR body that operators must update their delta payloads to include `commodity`.

### 3.6 `scenario_whatif_service` — read commodity from delta; remove `DEFAULT_COMMODITY`

**Current** at `scenario_whatif_service.py:178-191`:

```python
virtual_contracts.append(
    VirtualHedgeContract(
        id=delta.contract_id,
        commodity=DEFAULT_COMMODITY,  # ← bug
        quantity_mt=Decimal(delta.quantity_mt),
        # ...
    )
)
```

**Replacement**:

```python
virtual_contracts.append(
    VirtualHedgeContract(
        id=delta.contract_id,
        commodity=delta.commodity,  # ← from the schema, validated at boundary
        quantity_mt=Decimal(delta.quantity_mt),
        # ...
    )
)
```

**Remove the `DEFAULT_COMMODITY = "LME_AL"` constant** at `scenario_whatif_service.py:43`. After this commit, the constant is unreferenced.

**Remove the `_resolve_price_d1` default** at `scenario_whatif_service.py:79`: change `commodity: str = DEFAULT_COMMODITY` to a required argument `commodity: str`. Walk every caller of `_resolve_price_d1` and ensure it passes the commodity explicitly. Verified via Serena against `030a49bff`: `_resolve_price_d1` is called from **5 call sites** within `scenario_whatif_service.py`. The line numbers in this section (`:472, :485, :499, :550, :595`) reference the lines where the **`_resolve_price_d1(...)` text appears** — these are the kwarg positions inside the enclosing `_mtm_for_contract(...)` / `_mtm_for_order(...)` invocations whose call lines (`:467, :480, :495, :545, :590`) are listed in §3.7.5 / §6. Both line-number sets describe the SAME 5 logical call sites at different syntactic positions; they are NOT contradictory. Each of these already passes `commodity` explicitly today (`contract.commodity`, `order.commodity`); removing the default is a defensive lockdown so future call sites cannot rely on the implicit aluminum default.

### 3.7 Scenario MTM provenance plumbing (parallel-persistence-symmetry with Wave 1)

This subsection extends Iteration 2 of the dispatch (see §0 refresh notes). It threads the existing Wave 1 `PriceQuote` shape through the scenario MTM call sites so the scenario `mtm_snapshot` carries `price_quote.symbol` evidence — closing the provenance gap that made the J-A3-OPUS-01 test assertion unsatisfiable in Iteration 1.

The change is a clean type-flow plumbing — no new schemas, no new conceptual model. The `MTMResultResponse.price_quote` field already exists (`schemas/mtm.py:24`); we are populating it on the scenario surface, paralleling what Wave 1 did for non-scenario MTM.

#### 3.7.1 Lookup callable returns `PriceQuote`

**Current** at `scenario_whatif_service.py:60-72`:

```python
def _build_price_lookup(
    overrides: dict[tuple[str, date], Decimal],
) -> Callable[[Session, str, date], Decimal]:
    def lookup(db: Session, symbol: str, as_of_date: date) -> Decimal:
        prior_bd = _prior_business_day(
            as_of_date, lambda year: _market_calendar_for_symbol(symbol, year)
        )
        key = (symbol, prior_bd)
        if key in overrides:
            return overrides[key]
        return get_cash_settlement_price_d1(db, symbol=symbol, as_of_date=as_of_date)

    return lookup
```

**Replacement**:

```python
def _build_price_lookup(
    overrides: dict[tuple[str, date], Decimal],
) -> Callable[[Session, str, date], PriceQuote]:
    def lookup(db: Session, symbol: str, as_of_date: date) -> PriceQuote:
        prior_bd = _prior_business_day(
            as_of_date, lambda year: _market_calendar_for_symbol(symbol, year)
        )
        key = (symbol, prior_bd)
        if key in overrides:
            return PriceQuote(
                value=overrides[key],
                source="scenario_override",
                settlement_date=prior_bd,
                symbol=symbol,
            )
        # Settlement-table path: delegate to the Wave-1 provenance-bearing
        # lookup. The HTTPException(424) translation that the thin wrapper
        # used to provide is no longer applied here; raise the underlying
        # PriceReferenceUnprovable and let the caller decide how to expose
        # it (the scenario service's existing exception-handling layer
        # translates it consistently with non-scenario MTM).
        return get_cash_settlement_price_d1_with_provenance(
            db, symbol=symbol, as_of_date=as_of_date
        )

    return lookup
```

**Override `source="scenario_override"`**: this is a new canonical source identifier specific to scenario what-if runs. The caller asserting `price_quote.source == "scenario_override"` proves the result derives from the operator's hypothetical override rather than the canonical settlement table — institutionally important for audit-trail readers. No DB column constraint applies (`PriceQuote.source` is a string; `MTMSnapshot.price_source` is also a string per Wave 1 schema). Document the literal in `price_lookup_service.py` or `utils/price_reference.py` constants if a constants module is the convention; otherwise keep inline.

**HTTPException translation — concrete mandate (no either/or)**: the Iteration-1 lookup raised `HTTPException(424)` via the thin `get_cash_settlement_price_d1` wrapper. The new shape raises `PriceReferenceUnprovable` directly. To preserve the §2.6 governance contract ("price reference unprovable" → HTTP 424, never silent 500), the executor MUST:

1. **Grep `backend/app/api/routes/scenario.py` (and any FastAPI exception-handler module like `app/main.py` / `app/core/exception_handlers.py`) for `PriceReferenceUnprovable`**. If a handler already translates it to 424, document the file:line in the PR body and skip step 2.
2. **If no handler exists**, add `try/except PriceReferenceUnprovable as exc` translation at each of the 5 `_resolve_price_quote` call sites (`:472, :485, :499, :550, :595`), re-raising as `HTTPException(status_code=status.HTTP_424_FAILED_DEPENDENCY, detail=str(exc)) from exc`. This mirrors the Wave-1 pattern in `compute_mtm_for_order`.
3. **Either way, §7 must include a targeted test** (`test_scenario_returns_424_when_price_reference_unprovable`) that POSTs `/scenario` with an `as_of_date` whose prior-business-day cash settlement is unseeded; assert response status `424`, NOT 500. This pins the contract regardless of which translation path the executor chose.

The "either/or" framing in earlier dispatch iterations was insufficient — an executor could satisfy §6 acceptance by claiming the FastAPI handler exists without verifying or adding one, and the bug being fixed (silent fallback when price unprovable) would resurface as a 500.

#### 3.7.2 `_resolve_price_d1` returns `PriceQuote`

**Current** at `scenario_whatif_service.py:75-82`:

```python
def _resolve_price_d1(
    db: Session,
    as_of_date: date,
    lookup: Callable[[Session, str, date], Decimal],
    commodity: str = DEFAULT_COMMODITY,
) -> Decimal:
    symbol = resolve_symbol(commodity)
    return lookup(db, symbol, as_of_date)
```

**Replacement** (drop default per §3.6; change return type):

```python
def _resolve_price_quote(
    db: Session,
    as_of_date: date,
    lookup: Callable[[Session, str, date], PriceQuote],
    commodity: str,
) -> PriceQuote:
    symbol = resolve_symbol(commodity)
    return lookup(db, symbol, as_of_date)
```

**Rename mandate**: the function now returns a `PriceQuote`, not a `price_d1` Decimal. Rename `_resolve_price_d1` → `_resolve_price_quote` — the new name IS the API contract. The 5 call sites (4 in `_mtm_for_contract` + 1 in `_mtm_for_order`) are updated in lockstep with the signature changes in §3.7.3 / §3.7.4. The old name is deleted; no aliasing.

#### 3.7.3 `_mtm_for_contract` accepts `PriceQuote`; populates `MTMResultResponse.price_quote`

**Current** at `scenario_whatif_service.py:84-103`:

```python
def _mtm_for_contract(
    contract_id: UUID,
    quantity_mt: Decimal,
    entry_price: Decimal,
    as_of_date: date,
    price_d1: Decimal,
) -> MTMResultResponse:
    quantity_mt = quantize_mt(quantity_mt)
    entry_price = quantize_price(entry_price)
    price_d1 = quantize_price(price_d1)
    mtm_value = quantize_money(quantity_mt * (price_d1 - entry_price))
    return MTMResultResponse(
        object_type=MTMObjectType.hedge_contract,
        object_id=str(contract_id),
        as_of_date=as_of_date,
        mtm_value=mtm_value,
        price_d1=price_d1,
        entry_price=entry_price,
        quantity_mt=quantity_mt,
    )
```

**Replacement**:

```python
def _mtm_for_contract(
    contract_id: UUID,
    quantity_mt: Decimal,
    entry_price: Decimal,
    as_of_date: date,
    price_quote: PriceQuote,
) -> MTMResultResponse:
    quantity_mt = quantize_mt(quantity_mt)
    entry_price = quantize_price(entry_price)
    price_d1 = quantize_price(price_quote.value)
    mtm_value = quantize_money(quantity_mt * (price_d1 - entry_price))
    return MTMResultResponse(
        object_type=MTMObjectType.hedge_contract,
        object_id=str(contract_id),
        as_of_date=as_of_date,
        mtm_value=mtm_value,
        price_d1=price_d1,
        entry_price=entry_price,
        quantity_mt=quantity_mt,
        price_quote=price_quote,
    )
```

**Quantization note**: `price_quote.value` is quantized into `price_d1` for the `MTMResultResponse.price_d1` field but the `price_quote` itself is passed unmodified. This matches Wave 1's pattern in `compute_mtm_for_order`: the persisted `MTMSnapshot.price_value` is the quantized value, but the audit-trail `price_quote` reflects the canonical-source raw value. Verify against Wave-1 `compute_mtm_for_order` body before authoring — if Wave 1 quantizes inside the `PriceQuote` too, mirror that here for parallel-persistence-symmetry.

#### 3.7.4 `_mtm_for_order` accepts `PriceQuote`; populates `MTMResultResponse.price_quote`

Symmetric change for the order path. Current signature accepts `price_d1: Decimal` (`scenario_whatif_service.py:107-...`). Replace with `price_quote: PriceQuote`; populate `MTMResultResponse(price_quote=price_quote, ...)`.

**Preserve all existing NULL-guards verbatim**: `_mtm_for_order` has guards rejecting orders that cannot be MTMed (e.g., fixed-price orders, non-`avg`/`avginter` pricing convention, NULL `avg_entry_price`). The signature change ONLY swaps `price_d1: Decimal` → `price_quote: PriceQuote` and the `MTMResultResponse(...)` constructor — leave every existing guard, exception type, and error message untouched. Quantization (`quantize_price(price_quote.value)`) happens AFTER all guards, mirroring the current order of operations in the function body.

#### 3.7.5 Update all 5 call sites

Verified via Serena against `030a49bff` — the 4 `_mtm_for_contract` call sites at `scenario_whatif_service.py:467, 480, 545, 590` and the 1 `_mtm_for_order` call site at `scenario_whatif_service.py:495` all currently pass `price_d1=_resolve_price_d1(db, ..., commodity=...)`. Each must be updated to:

```python
price_quote=_resolve_price_quote(db, ..., lookup, commodity=...)
```

(post-rename per §3.7.2 the function is `_resolve_price_quote`; the kwarg on `_mtm_for_*` becomes `price_quote=...`).

**Imports to update** at `scenario_whatif_service.py` top (verified against `030a49bff` via Serena):

The current import block at lines 35-39 is:

```python
from app.services.price_lookup_service import (
    canonical_commodity,
    get_cash_settlement_price_d1,
    resolve_symbol,
)
```

Post-fix:

```python
from app.utils.price_reference import PriceQuote, PriceReferenceUnprovable  # NEW import (top-of-file)
from app.services.price_lookup_service import (
    canonical_commodity,                               # unchanged — already present
    get_cash_settlement_price_d1_with_provenance,      # NEW — replaces _d1 wrapper
    resolve_symbol,                                    # unchanged — already present
)
```

The existing `get_cash_settlement_price_d1` import is removed — the thin wrapper is no longer used inside `scenario_whatif_service`. The new line is `get_cash_settlement_price_d1_with_provenance`. `canonical_commodity` and `resolve_symbol` were already imported and are KEPT (not duplicated, not re-added). Verify via grep that no remaining reference to `get_cash_settlement_price_d1` (without `_with_provenance` suffix) exists in the file before deleting the import.

#### 3.7.6 Scope guard: do NOT extend plumbing beyond scenario MTM

`MTMResultResponse.price_quote` plumbing in scenario context stops at `mtm_snapshot[i].price_quote`. Do NOT thread `PriceQuote` into:
- `CashFlowItem` (scenario cashflow snapshot) — that's a Wave 4 concern (cashflow boundary fix).
- `ScenarioPLSnapshotItem` — the P&L unrealized field consumes `_mtm_for_contract().mtm_value`, but the P&L snapshot does NOT need the underlying `PriceQuote`. Leave P&L snapshots untouched.
- Real non-scenario MTM call sites (Wave 1 already handled these).

Out-of-scope plumbing here would expand PR-A3-2 into a Wave-1.5-style cross-cutting refactor. The line is: scenario `mtm_snapshot` gains parity; nothing else in the scenario response shape changes.

### 3.8 Frontend regen

The `AddUnlinkedHedgeContractDelta` schema change adds a required field — OpenAPI + frontend `schema.d.ts` regen is required. Per Wave 1 PR-A3-1 §11 step 15:

```
cd backend && DATABASE_URL=sqlite:///:memory: SECRET_KEY=dummy JWT_SIGNING_SECRET=dummy AUDIT_HMAC_KEY=dummy AUDIT_SIGNING_KEY=test python -c "from app.main import app; import json; json.dump(app.openapi(), open('../docs/api/openapi_v1.json', 'w'), indent=2, sort_keys=True)"
cd ../frontend-svelte && OPENAPI_SOURCE=../docs/api/openapi_v1.json node scripts/regen-schema.mjs
```

If the frontend has any UI for adding scenario deltas (e.g., a form), add a commodity-picker field. The `commodity` enum / dropdown should mirror `COMMODITY_SYMBOL_MAP.keys()` from `price_lookup_service.py`. If no UI exists today, document the gap in the PR body and defer to Phase A6 (frontend audit).

### 3.9 No migration, no model change

PR-A3-2 is a service-layer + schema-layer fix. No new alembic migration is needed; `alembic heads` continues to return `["038_a3_price_provenance"]`. No Order model change (the `commodity` field already exists). No MTMSnapshot/PLSnapshot model change (Wave 1 already added price provenance fields). No `MTMResultResponse` schema change (the `price_quote` field already exists per `schemas/mtm.py:24`; we are populating it on the scenario path, not introducing it).

**Legacy MTMSnapshot rows with wrong `price_symbol`**: rows persisted between PR-A3-1 merge (Wave 1 added `price_symbol` to MTMSnapshot) and PR-A3-2 merge for non-aluminum orders carry `price_symbol="LME_ALU_CASH_SETTLEMENT_DAILY"` despite the order being copper/zinc/etc. Per `feedback_dispatch_self_consistency` "Hash/key signature changes — backfill only if you have all the inputs": legacy rows stay sealed (do NOT mass-update; they are forensic artifacts of the buggy regime). Post-PR-A3-2 snapshots persist correct provenance. The boundary is a **deployment timestamp** — operators recomputing MTM/P&L for a date in the buggy window can detect the gap via `MTMSnapshot.price_symbol` not matching the order's `commodity`.

---

## 4. Scope OUT — explicitly NOT in PR-A3-2

- **Cashflow projection hardening** (J-A3-OPUS-02 swallowed hard-fails / OPUS-06 zero defaults / OPUS-07 5th-view declaration) — Wave 3 (PR-A3-3).
- **Cashflow boundary fix** (J-A3-04 Baseline reads Analytic; J-A3-OPUS-08 reconciliation) — Wave 4 (PR-A3-4).
- **P&L lifecycle** (J-A3-OPUS-09 partially-settled zeroes unrealized MTM) — Wave 5 (PR-A3-5).
- **Cross-A1 deferred** (X-A3-J-01 deal_engine; X-A3-J-02 scenario duplicates A1 exposure) — future Phase A1 follow-up audit.
- **Backfill of legacy MTMSnapshot rows with wrong `price_symbol`** — out of scope. Legacy stays sealed (per §3.9). Documenting the regime boundary in operator runbook is a Phase A5 audit-trail concern.
- **Adding new commodity → settlement symbol mappings** to `COMMODITY_SYMBOL_MAP` — out of scope. The current six (AL/CU/ZN/NI/PB/SN) are fixed; new commodities land via separate dispatches with full price-source review.
- **Frontend UI for commodity selection** in scenario delta form — out of scope (Phase A6).

---

## 5. Constitutional rules (binding)

- **§2.1 — Valuation/MTM/Cashflow** (governance.md:131-146): "No fallback pricing regimes." Defaulting non-aluminum orders to the LME aluminum curve is a regime fallback by another name — silently substituting one commodity's price for another's. PR-A3-2 closes this at two surfaces (mtm_order_service + scenario_whatif_service).
- **§2.6 — Hard Fails** (governance.md:159-174): "Price reference unprovable" already raises via `PriceReferenceUnprovable` from Wave 1. PR-A3-2 ensures the lookup is for the correct commodity in the first place — no silent commodity substitution.
- **§2.7 — Output Contract** (governance.md:208-217): "Free of speculation." Persisting `price_symbol="LME_ALU_CASH_SETTLEMENT_DAILY"` on a copper order's MTMSnapshot is institutional speculation about which curve was consulted — false evidence. PR-A3-2 ensures the persisted symbol matches the input commodity.

---

## 6. Acceptance criteria

- [ ] `compute_mtm_for_order` signature drops the `commodity` parameter; resolves `order.commodity` via `resolve_symbol(order.commodity)` directly inside the function.
- [ ] `DEFAULT_COMMODITY` constant removed from `mtm_order_service.py`.
- [ ] All 4 call sites of `compute_mtm_for_order` (routes/mtm.py × 2, mtm_snapshot_service.py, cashflow_analytic_service.py) are unchanged — they were already not passing `commodity`; the function now resolves it internally from `order.commodity`.
- [ ] `AddUnlinkedHedgeContractDelta` schema has a new required `commodity: str` field with `Field(..., max_length=64)`. Schema validator rejects 422 if `resolve_symbol(commodity)` raises. **Imports added at `backend/app/schemas/scenario.py`**: `from fastapi import HTTPException` and `from app.services.price_lookup_service import resolve_symbol` (per §3.5).
- [ ] `scenario_whatif_service` reads `delta.commodity` when constructing `VirtualHedgeContract` (no `DEFAULT_COMMODITY`).
- [ ] `DEFAULT_COMMODITY` constant removed from `scenario_whatif_service.py`.
- [ ] `_resolve_price_d1` is renamed to `_resolve_price_quote` (cleaner contract — function now returns `PriceQuote`, not Decimal) and no longer has a `commodity` default; every one of the 5 call sites passes the commodity explicitly.
- [ ] `_build_price_lookup` callable returns `PriceQuote` instead of `Decimal`. Override path constructs `PriceQuote(source="scenario_override", ...)`. Settlement-table path delegates to `get_cash_settlement_price_d1_with_provenance` (Wave 1).
- [ ] `_mtm_for_contract` accepts `price_quote: PriceQuote` (replacing the `price_d1: Decimal` parameter); populates `MTMResultResponse(price_quote=price_quote, ...)`.
- [ ] `_mtm_for_order` accepts `price_quote: PriceQuote` symmetrically; populates `MTMResultResponse(price_quote=price_quote, ...)`.
- [ ] All 5 call sites (`scenario_whatif_service.py:467, 480, 495, 545, 590`) updated to thread the `PriceQuote` end-to-end.
- [ ] Scenario request handler translates `PriceReferenceUnprovable` to `HTTPException(424)` consistently with non-scenario MTM (either via `try/except` at call sites or via FastAPI exception handler — see §3.7.1).
- [ ] No `MTMResultResponse.price_quote == None` for any item in `mtm_snapshot` returned from `/scenario` (every scenario MTM result carries provenance after this PR).
- [ ] OpenAPI + `schema.d.ts` regenerated to reflect the new required `commodity` field on `AddUnlinkedHedgeContractDelta` and the now-always-populated `price_quote` field on scenario `MTMResultResponse` items.
- [ ] `[BEHAVIOR_SHIFT]` flag in PR body: scenario API consumers must update payloads to include `commodity`.
- [ ] **Pre-fix test cleanup completed** (per §11 step 12): existing `test_multi_commodity.py` tests that pass `commodity=` kwarg to `compute_mtm_for_order` are deleted or rewritten; existing `test_scenario_whatif_run.py` tests posting `add_unlinked_hedge_contract` deltas have a `commodity` field added.
- [ ] `alembic heads` continues to return `["038_a3_price_provenance"]` (no new migration).
- [ ] `test_alembic_chain.py` continues passing.

---

## 7. Test coverage required

- `backend/tests/test_mtm_order_service.py`:
  - `test_compute_mtm_for_order_uses_order_commodity_not_default` — fixture: persist `Order(commodity="COPPER", ...)` + canonical copper price; assert `result.price_quote.symbol == resolve_symbol("COPPER")` (i.e., `LME_CU_CASH_SETTLEMENT_DAILY`); assert `mtm_value` computed against the copper price (not aluminum's).
  - `test_compute_mtm_for_order_function_signature_does_not_accept_commodity_kwarg` — call `compute_mtm_for_order(db, order_id=..., as_of_date=..., commodity="LME_AL")` raises `TypeError` (the kwarg was removed). Pin the signature regression so a future caller cannot reintroduce the bug.

- `backend/tests/test_multi_commodity.py` (extension):
  - `test_mtm_order_aluminum_copper_zinc_nickel_lead_tin_distinct_results` — fixture: persist 6 orders with different commodities + 6 distinct canonical settlement rows; compute MTM for each; assert each `result.price_quote.symbol` matches the order's commodity-resolved symbol; assert no two MTM values collapse to the same value (prove cross-commodity isolation).

- `backend/tests/test_mtm_snapshot_service.py`:
  - `test_create_mtm_snapshot_for_order_persists_commodity_resolved_symbol` — fixture: copper order; `create_mtm_snapshot_for_order` runs; assert persisted `MTMSnapshot.price_symbol == "LME_CU_CASH_SETTLEMENT_DAILY"` (not aluminum). Wave 1 provenance machinery surfaces the fix.

- `backend/tests/test_cashflow_analytic_service.py`:
  - `test_analytic_prices_each_order_against_its_own_commodity` — fixture: portfolio with orders across 3 commodities; assert each `CashFlowItem.price_symbol` matches the source order's commodity.

- `backend/tests/test_scenario_whatif_run.py` (extension):
  - `test_scenario_add_unlinked_hedge_contract_requires_commodity` — POST `/scenario` with delta missing `commodity` → 422 with field-level error.
  - `test_scenario_add_unlinked_hedge_contract_validates_known_commodity` — delta with `commodity="UNKNOWN_FAKE"` → 422 with structured message about settlement-symbol mapping.
  - `test_scenario_virtual_hedge_uses_provided_commodity_not_default` — delta with `commodity="ZINC"` + canonical zinc settlement seeded for the prior business day with `source="westmetall"` (the canonical source returned by `_canonical_source_for_symbol("LME_ZN_CASH_SETTLEMENT_DAILY")` per `utils/market_calendar.py:173-176`); POST `/scenario`; locate the virtual hedge in `response.mtm_snapshot` by `object_id == str(delta.contract_id)` and `object_type == MTMObjectType.hedge_contract`; assert `item.price_quote.symbol == resolve_symbol("ZINC")` (i.e., `"LME_ZN_CASH_SETTLEMENT_DAILY"`); assert `item.price_quote.source == "westmetall"`; assert `item.mtm_value == quantize_money(qty * (zinc_settlement - entry_price))`. **Note**: assertion path is `mtm_snapshot[i].price_quote.symbol`, NOT `contracts[id].price_quote.symbol` — the response shape exposes `mtm_snapshot: list[MTMResultResponse]`, not a `contracts` mapping.
  - `test_scenario_price_override_constructs_scenario_override_provenance` — delta of type `add_cash_settlement_price_override` with `symbol="LME_ALU_CASH_SETTLEMENT_DAILY"`, `settlement_date=<prior business day of req.as_of_date>`, `price_usd=Decimal("2500.00")`; fixture additionally persists an active aluminum hedge contract so the override has a contract to price; POST `/scenario`; locate the aluminum MTM result in `mtm_snapshot`; assert `item.price_quote.source == "scenario_override"` and `item.price_quote.value == Decimal("2500.00")` (post-quantization equality — apply `quantize_price` if Wave 1 quantizes inside the `PriceQuote`; otherwise raw equality) and `item.price_quote.symbol == "LME_ALU_CASH_SETTLEMENT_DAILY"` and `item.price_quote.settlement_date == <prior_bd>`. Pins the override-path `PriceQuote` construction; this is the ONLY test that exercises the override branch end-to-end with provenance assertions.
  - `test_scenario_real_contract_mtm_carries_price_quote` — fixture: persist 1 active hedge contract for copper + canonical copper settlement (source `"westmetall"`); POST `/scenario` with no deltas; locate the real contract result in `response.mtm_snapshot` by `object_id == str(contract.id)`; assert `item.price_quote is not None`, `item.price_quote.symbol == "LME_CU_CASH_SETTLEMENT_DAILY"`, and `item.price_quote.source == "westmetall"`. Pins parallel-persistence-symmetry on the non-virtual scenario MTM path.
  - `test_scenario_returns_424_when_price_reference_unprovable` — fixture: persist 1 active hedge contract for aluminum; do NOT seed any cash settlement row for the prior business day of `req.as_of_date`; POST `/scenario`; assert response status code `== 424` (NOT 500); assert response body `detail` mentions the missing settlement (i.e., institutional governance §2.6 hard-fail surfaced cleanly to the operator, not silently as a 500). Pins the §3.7.1 HTTPException-translation contract — verifies that whichever path the executor chose (existing handler OR per-call-site `try/except`), the 424 fires.

---

## 8. Critical sequencing

PR-A3-2 ships against **post-Wave-1 main** (`030a49bff`). Wave 1 PR-A3-1 (PR #41) merged the price-provenance machinery; PR-A3-2 consumes it.

- **Branch base**: `origin/main` at `030a49bff` or later.
- **Migration chain**: unchanged. `alembic heads` returns `["038_a3_price_provenance"]` post-Wave-2.
- **Downstream dependency**: Waves 3-5 do not directly depend on Wave 2's changes (their findings touch projection / boundaries / P&L lifecycle, not commodity defaulting). Waves 3-5 can author in parallel after Wave 2 dispatch lands; they merge after Wave 2 implementation lands to keep linear main.
- **No rebase coordination required** — PR-A3-2 is a single PR; no sibling PRs in flight.

---

## 9. PR shape

**Title:** `fix(audit-a3): PR-A3-2 — commodity correctness (J-A3-02, J-A3-OPUS-01)`

**Body skeleton:**

```markdown
## Summary

Wave 2 of Phase A3 remediation. Closes the commodity-defaulting bug at
two surfaces:
- `compute_mtm_for_order` no longer defaults `commodity` to `LME_AL`;
  resolves from `order.commodity` directly. Non-aluminum orders are now
  priced against their own commodity's settlement curve.
- `AddUnlinkedHedgeContractDelta` carries an explicit required
  `commodity` field. `scenario_whatif_service` reads it when constructing
  `VirtualHedgeContract`. `DEFAULT_COMMODITY = "LME_AL"` constants
  removed from both services.

Phase A3 jury verdict (FAIL-WITH-CRITICAL-CAVEATS @ commit `bbd0908d0`)
— addresses Tier 1 findings J-A3-02 + J-A3-OPUS-01. Constitution §2.1
("no fallback pricing regimes"), §2.7 ("free of speculation").

[BEHAVIOR_SHIFT] Scenario API consumers (frontend, integration tests,
operator scripts) supplying `add_unlinked_hedge_contract` deltas
without `commodity` now receive 422 from the schema validator.
Operators must update their delta payloads.

## Files changed

- `backend/app/services/mtm_order_service.py` — drop `commodity` parameter; resolve from `order.commodity`; remove `DEFAULT_COMMODITY` constant
- `backend/app/services/scenario_whatif_service.py` — read `delta.commodity`; remove `DEFAULT_COMMODITY` constant; remove `_resolve_price_d1` default; thread `PriceQuote` through `_build_price_lookup` / `_resolve_price_d1` (or rename to `_resolve_price_quote`) / `_mtm_for_contract` / `_mtm_for_order`; populate `MTMResultResponse.price_quote` on every scenario MTM call site
- `backend/app/schemas/scenario.py` — `AddUnlinkedHedgeContractDelta` gains required `commodity` field with `resolve_symbol` validation
- `docs/api/openapi_v1.json` — regen
- `frontend-svelte/src/lib/api/schema.d.ts` — regen
- Tests: `test_mtm_order_service.py`, `test_multi_commodity.py`, `test_mtm_snapshot_service.py`, `test_cashflow_analytic_service.py`, `test_scenario_whatif_run.py`

## Acceptance evidence

- [ ] All criteria from dispatch §6 met
- [ ] `alembic heads` returns single `["038_a3_price_provenance"]` (no new migration)
- [ ] Cross-commodity tests pass for all six supported commodities

## Constitutional impact

§2.1 (no fallback pricing regimes — commodity defaulting was a fallback
by another name), §2.7 (free of speculation — persisted `price_symbol`
now matches input commodity; scenario `mtm_snapshot` items now carry
`price_quote.symbol` evidence in the response, paralleling Wave 1's
provenance plumbing for non-scenario MTM).

## Out of scope

- Wave 3-5 of Phase A3
- Backfill of legacy MTMSnapshot rows with wrong `price_symbol` (operator-runbook concern)
- Frontend UI for commodity selection (Phase A6)

## Closes

J-A3-02 + J-A3-OPUS-01.
```

---

## 10. Constraints — what NOT to do

- DO NOT make `commodity` a parameter with a default (e.g., `commodity: str = order.commodity`). The fix is to REMOVE the parameter so callers cannot accidentally bypass the order's commodity. Resolve from `order.commodity` inside the function.
- DO NOT make `AddUnlinkedHedgeContractDelta.commodity` optional with a default of `"LME_AL"`. Optional defaults re-create the bug at the schema layer. Required field; 422 on missing.
- DO NOT add a `commodity` query parameter to the MTM route. The route doesn't need it (the order knows its commodity); adding one would re-introduce the operator-override bypass.
- DO NOT backfill legacy MTMSnapshot rows whose `price_symbol` is wrong. Legacy stays sealed; the regime boundary is the deployment timestamp.
- DO NOT add new commodities to `COMMODITY_SYMBOL_MAP` in this PR. The six existing commodities are fixed scope; new commodities land via separate dispatches with full price-source review.
- DO NOT use `strip(...)` with character classes that include hyphen `-`, plus `+`, period `.`, comma `,` anywhere in the changed files. Pricing-domain awareness mandatory.
- DO NOT thread `PriceQuote` plumbing into surfaces other than scenario MTM. Specifically: do NOT add `price_quote` to `CashFlowItem` (Wave 4 concern), do NOT add it to `ScenarioPLSnapshotItem` (P&L consumes only `mtm_value`), do NOT touch non-scenario MTM call sites (Wave 1 already handled them). Out-of-scope plumbing turns PR-A3-2 into a cross-cutting refactor.
- DO NOT introduce a `PriceQuote.inputs_hash` field or any new `PriceQuote` attribute to support this PR. The existing 4-field shape (`value`, `source`, `settlement_date`, `symbol`) is sufficient. Schema evolution requires its own dispatch.
- DO NOT silently coerce the override-path `source` to anything other than `"scenario_override"`. The literal must be unique and grep-able for audit-trail readers. Do NOT use `"override"`, `"manual"`, `"adjustment"`, or unset (None defaults are not acceptable on a `frozen=True` dataclass with a required field).
- DO NOT auto-merge — wait for Codex review.
- DO NOT use `--no-verify` to skip git hooks.

---

## 11. Workflow

1. `git fetch origin && git worktree add D:\Projetos\Hedge-Control-New-pr-a3-2 origin/main && cd D:\Projetos\Hedge-Control-New-pr-a3-2 && git checkout -b audit-a3/commodity-correctness`
2. Configure `.claude/settings.local.json` per A1/A2 worktree pattern (`defaultMode: bypassPermissions`, allow `git`/`gh`/`pytest`/`python`/`alembic`, deny raw `--force`, `--auto`, `--no-verify`, push to `main`).
3. Read jury §2 J-A3-02 + §3 J-A3-OPUS-01 in full.
4. Read Wave 1 dispatch sections that established the price-provenance machinery (`docs/audits/2026-05-09-phase-a3-pr-1-price-provenance-dispatch.md` §3.1–§3.4) — Wave 2 inherits this contract.
5. Drop `commodity` parameter from `compute_mtm_for_order` (`mtm_order_service.py:21-26`); replace `resolve_symbol(commodity)` with `resolve_symbol(order.commodity)`.
6. Remove `DEFAULT_COMMODITY` constant at `mtm_order_service.py:43`.
7. Add `commodity` field to `AddUnlinkedHedgeContractDelta` (`schemas/scenario.py:18-34`); extend the validator.
8. Update virtual-hedge construction at `scenario_whatif_service.py:178-191` to read `delta.commodity`.
9. Remove `DEFAULT_COMMODITY` constant at `scenario_whatif_service.py:43`.
10. Remove default from `_resolve_price_d1` at `scenario_whatif_service.py:79`; walk the 5 callers via Serena `find_referencing_symbols` and update each. The 5 callers correspond to the kwarg positions `:472, :485, :499, :550, :595` (lines where `_resolve_price_d1(...)` text appears) — equivalently the enclosing `_mtm_for_contract(...)` / `_mtm_for_order(...)` invocations at `:467, :480, :495, :545, :590` (lines where the outer call starts). Both line-number references describe the same 5 logical call sites; see §3.6 for the disambiguation note.
11. **Provenance plumbing (§3.7)**:
    - Update `_build_price_lookup` callable signature: `Callable[[Session, str, date], PriceQuote]`. Override path constructs `PriceQuote(value=overrides[key], source="scenario_override", settlement_date=prior_bd, symbol=symbol)`. Settlement-table path delegates to `get_cash_settlement_price_d1_with_provenance`.
    - Update `_resolve_price_d1` (or rename to `_resolve_price_quote` per §3.7.2) to return `PriceQuote`.
    - Update `_mtm_for_contract` signature: drop `price_d1: Decimal`, add `price_quote: PriceQuote`. Quantize `price_quote.value` into `price_d1` for `MTMResultResponse.price_d1`. Pass `price_quote` unmodified into `MTMResultResponse(price_quote=price_quote, ...)`.
    - Update `_mtm_for_order` symmetrically.
    - Update all 5 call sites (`:467, :480, :495, :545, :590`) to pass the `PriceQuote` returned by `_resolve_price_d1` (or `_resolve_price_quote`) as `price_quote=...`.
    - Add imports: `from app.utils.price_reference import PriceQuote, PriceReferenceUnprovable`; `from app.services.price_lookup_service import get_cash_settlement_price_d1_with_provenance`. Remove import of `get_cash_settlement_price_d1` (verify no remaining references via grep).
    - Audit `routes/scenario.py` for `PriceReferenceUnprovable` translation. If no FastAPI handler exists, add `try/except PriceReferenceUnprovable` translation at each `_resolve_price_d1` call site mirroring the Wave-1 pattern in `compute_mtm_for_order`.
12. **Pre-fix test cleanup** — delete or rewrite existing tests that depend on the dropped `commodity` kwarg shape OR the old commodity-less scenario delta. Verified via Serena against `030a49bff`:
    - `backend/tests/test_multi_commodity.py::TestMTMOrderMultiCommodity`: handle each existing test individually:
      - **(a) `test_order_with_copper_commodity` — DELETE OR REWRITE**. Passes `compute_mtm_for_order(..., commodity="LME_CU")`; the kwarg no longer exists post-§3.1, so the call would raise `TypeError`. The replacement test in §7 (`test_compute_mtm_for_order_uses_order_commodity_not_default`) covers the same scenario by setting `order.commodity="LME_CU"` and asserting the resolution.
      - **(b) `test_order_default_commodity_is_aluminium` — KEEP, optionally RENAME**. Verified via grep against `030a49bff`: this test does NOT pass `commodity=` kwarg, and `_insert_order` (helper at `test_multi_commodity.py:72-86`) sets `order.commodity="LME_AL"`. Post-§3.1 the function resolves `order.commodity → "LME_AL" → aluminum`, and the test STILL PASSES (asserts `price_d1==Decimal("2400.0")` against the seeded LME_AL settlement). The test is a valid regression for the new "function trusts the order's commodity field" contract — keep it. Optional rename for clarity: `test_order_with_lme_al_commodity_resolves_from_order_commodity`.
      - **(c) `test_order_with_unknown_commodity_raises_400` — DELETE OR REWRITE**. Passes `commodity="NOPE"` to a function that no longer accepts the kwarg. The replacement coverage is implicit: no caller can pass an invalid commodity once the parameter is removed. If a regression is desired for "order with invalid `order.commodity` raises", construct an `Order(commodity="NOPE")` fixture and assert the 400; otherwise delete.
      The new tests prescribed in §7 (`test_compute_mtm_for_order_uses_order_commodity_not_default`, `test_compute_mtm_for_order_function_signature_does_not_accept_commodity_kwarg`, plus the cross-commodity isolation test) provide the post-fix coverage envelope.
    - `backend/tests/test_scenario_whatif_run.py::test_add_unlinked_contract_affects_global_exposure` (and any other test posting `add_unlinked_hedge_contract` deltas) currently posts the delta WITHOUT a `commodity` field. Post-§3.5 these will receive 422 from the schema validator. **Audit every existing scenario test that posts an `add_unlinked_hedge_contract` delta** and add `"commodity": "<some valid commodity, e.g. LME_AL>"` to the payload. Use `grep -n "add_unlinked_hedge_contract" backend/tests/test_scenario_whatif_run.py` to enumerate.
    - General rule: any test fixture that constructs a value in a format that this PR newly validates MUST be audited (per `feedback_dispatch_self_consistency` rule "Parser-introducing PRs need pre-merge fixture-compat audit").
13. Run targeted pytest: `pytest backend/tests/test_mtm_order_service.py backend/tests/test_multi_commodity.py backend/tests/test_mtm_snapshot_service.py backend/tests/test_cashflow_analytic_service.py backend/tests/test_scenario_whatif_run.py backend/tests/test_alembic_chain.py -v`
14. Full backend suite: `pytest backend/tests/ -v` — green except known failures (3 pre-existing `test_ws.py` Python 3.14 failures).
15. **Frontend regen**:
    - `cd backend && DATABASE_URL=sqlite:///:memory: SECRET_KEY=dummy JWT_SIGNING_SECRET=dummy AUDIT_HMAC_KEY=dummy AUDIT_SIGNING_KEY=test python -c "from app.main import app; import json; json.dump(app.openapi(), open('../docs/api/openapi_v1.json', 'w'), indent=2, sort_keys=True)"`
    - `cd ../frontend-svelte && OPENAPI_SOURCE=../docs/api/openapi_v1.json node scripts/regen-schema.mjs`
16. `git push -u origin audit-a3/commodity-correctness && gh pr create --base main --title "<§9 title>" --body-file <body>` — DO NOT use `--draft` (the PR-A3-1 incident with draft-state-blocking-merge is fresh; open as ready-for-review).
17. **STOP. Wait for Codex review.** Address each catch as a new commit. Expected catch count: 2-5 (the plumbing extension is a wider type-flow change; matches Wave-1 surface complexity for the affected functions).
18. Report back to orchestrator with PR URL, final SHA, Codex review state, files-touched grouping, test counts, frontend regen evidence.

---

## 12. Final report shape

When complete, report to orchestrator:
- Branch + PR URL + final SHA.
- Files touched (grouped: services / schemas / tests / frontend).
- Test pass/fail counts vs main baseline.
- Codex review status + catches absorbed.
- Frontend regen evidence (`schema.d.ts` + `openapi_v1.json` diff line counts).
- Any unexpected rebase against main (none anticipated).

Keep report under 600 words.

Boa caça.
