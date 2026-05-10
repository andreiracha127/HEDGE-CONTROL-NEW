# Phase A3 — PR-A3-3 Dispatch — Cashflow Projection Hardening

**Wave:** 3 (depends on Wave 1 PR #41 + Wave 2 PR #44 — uses `_with_provenance` lookup + post-Wave-2 commodity-correctness contracts)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-10
**Findings covered:** J-A3-OPUS-02 (T1, projection swallows price hard-fails) + J-A3-OPUS-06 (T1, projection mixes valuation regimes + zero defaults) + J-A3-OPUS-07 (T2, Projection is a 5th cashflow view not declared by governance)
**Branch name:** `audit-a3/cashflow-projection-hardening`
**Base:** `main` (currently `5e25f8bd8`, post-PR-#45 hook v2 implementation merge)

---

## 0. Refresh notes (read first)

This is the **first iteration** of the PR-A3-3 dispatch. Wave 3 depends on:
- Wave 1 PR #41 (`030a49bff`) — `_with_provenance` price lookup, `PriceReferenceUnprovable` exception, MTM/P&L/Baseline provenance fields.
- Wave 2 PR #44 (`babb6289a`) — `compute_mtm_for_order` no longer accepts `commodity` kwarg; resolves from `order.commodity`. `AddUnlinkedHedgeContractDelta` carries explicit required `commodity`. `scenario_whatif_service` uses `_resolve_price_quote` returning `PriceQuote`.

Verified via Serena/grep against `main = 5e25f8bd8`:
- `cashflow_projection_service.py` is **211 lines**; the body has not been touched by Wave 1 or Wave 2 fixes (still pre-Wave-1 patterns).
- `cashflow_projection_service._get_market_price` at lines `34-55` wraps `get_cash_settlement_price_d1(...)` in `try/except Exception` and returns `None` on any failure — including the institutional `HTTPException(424)` raised by the wrapper on `PriceReferenceUnprovable`.
- `compute_cashflow_projection` at lines `87-210` computes ONE global `market_price = _get_market_price(session, "LME_AL", as_of_date)` (line 92) and applies it to every order/contract regardless of their actual `commodity` — re-creating the same single-curve pricing bug Wave 2 closed for `mtm_order_service`.
- The function uses `or 0` defaults in three places: `Decimal(str(order.avg_entry_price or 0))` (lines 103, 109), `Decimal(str(contract.fixed_price_value or 0))` (line 159).
- The function uses fallback regimes in two places: when `market_price is None`, it falls back to `order.avg_entry_price` (lines 109-110, `price_src="entry"`) for orders, and to `fixed_price` (lines 165-166, `price_src="entry"`) for contracts.
- The function hardcodes `commodity="Al"` (line 129) on emitted `CashFlowProjectionItem` for orders, regardless of `order.commodity`. Contracts emit `contract.commodity` (line 186) correctly.
- `contract.settlement_date or as_of_date` (line 154) substitutes `as_of_date` when the contract has no settlement date — silently invents a future-flow date.
- `routes/cashflow.py:62-68` exposes `GET /cashflow/projection` returning `CashFlowProjectionResponse`. Governance lists Analytic, Baseline, Ledger, What-if as the four cashflow views; Projection is a 5th not formally declared.

Wave 3 surface is **medium** — no schema migration, no new tables, no model changes. The hardening is service-body + tests + boundaries. Expected dispatch size: ~500-700 lines.

**This is the FIRST dispatch authored under hook v2 (tool-use review)**, landed in main `5e25f8bd8` (PR #45). Hook v2 will self-review on push; Sonnet 4.6 will use `read_file` / `find_symbol` / `grep_pattern` / `report_findings` to verify identifiers. Calibration data from this run feeds future dispatches.

---

## 1. Mission

Harden `cashflow_projection_service` so it complies with constitutional invariants §2.1 (no fallback pricing regimes), §2.6 (hard fails on evidence missing), and §2.7 (free of speculation). Today, Projection silently substitutes economic facts in five distinct ways: it swallows price hard-fails, prices every row at LME aluminum regardless of commodity, hardcodes `commodity="Al"` on order projections, falls back to entry prices on missing market data, and substitutes `as_of_date` for missing contract settlement dates. Each substitution undermines the institutional output contract.

After PR-A3-3:
- `_get_market_price` no longer wraps the lookup in `except Exception`. `PriceReferenceUnprovable` propagates; the route handler at `routes/cashflow.py` translates it to `HTTPException(424)` — same pattern Wave 1 established for `compute_mtm_for_order`.
- `compute_cashflow_projection` resolves market price **per row** using `order.commodity` / `contract.commodity` — no global `LME_AL` lookup.
- All `or 0` defaults are replaced with explicit absence checks: missing `avg_entry_price` / `fixed_price_value` raise `HTTPException(422)` with field-level detail (the order/contract row is structurally invalid for projection — operator must fix the source row, not have the projection silently zero it).
- The "entry" / "fixed" fallback when market price is unprovable is REMOVED. If price is unprovable, the row is unprovable; the entire endpoint surfaces 424.
- The hardcoded `commodity="Al"` is replaced with `order.commodity`.
- `contract.settlement_date or as_of_date` substitution is replaced with explicit absence check: missing `settlement_date` raises 422.
- **OPUS-07 (5th view)**: Projection stays as an exposed view; this dispatch enumerates its constitutional invariants in §5 (inheriting §2.1 + §2.6 + §2.7), making the institutional contract explicit at the dispatch layer. A separate Phase A5 audit-trail follow-up may decide whether to propagate to `governance.md`; that decision is OUT OF SCOPE for PR-A3-3.

**Persona:** Senior software engineer building an institutional trading platform. Constitution `docs/governance.md` is supreme authority. Pricing-domain awareness obligatory.

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-09-phase-a3-jury-verdict.md`** §J-A3-OPUS-02, §J-A3-OPUS-06, §J-A3-OPUS-07. Read in full.
- **`docs/governance.md`** §131-146 (no fallback pricing regimes), §159-174 (hard fails — evidence missing / price reference unprovable), §208-217 (output contract — free of speculation).
- **`docs/audits/2026-05-09-phase-a3-pr-1-price-provenance-dispatch.md`** — Wave 1 dispatch (in main since `bbd0908d0`). PR-A3-3 inherits the `_with_provenance` lookup + `PriceReferenceUnprovable` exception class.
- **`docs/audits/2026-05-09-phase-a3-pr-2-commodity-correctness-dispatch.md`** — Wave 2 dispatch (in main since `bf021b837`). PR-A3-3 inherits the per-row commodity pricing pattern + `resolve_symbol(<row>.commodity)` discipline.
- **`backend/app/services/cashflow_projection_service.py:34-55`** — `_get_market_price` (the swallowing surface).
- **`backend/app/services/cashflow_projection_service.py:87-210`** — `compute_cashflow_projection` (the global-price + or-0 + fallback surface).
- **`backend/app/services/cashflow_projection_service.py:129`** — hardcoded `commodity="Al"` line.
- **`backend/app/services/cashflow_projection_service.py:154`** — `contract.settlement_date or as_of_date` substitution.
- **`backend/app/api/routes/cashflow.py:62-68`** — `GET /cashflow/projection` route, the 424-translation site.
- **`backend/app/services/price_lookup_service.py`** — `get_cash_settlement_price_d1_with_provenance` (Wave 1) + `PriceReferenceUnprovable` exception class. `resolve_symbol` for commodity-symbol mapping.
- **`backend/app/services/mtm_order_service.py:55-65`** — Wave-1 + Wave-2 pattern for the "try / except PriceReferenceUnprovable / raise HTTPException(424)" translation. PR-A3-3 mirrors this shape.
- **`backend/app/schemas/cashflow.py`** — `CashFlowProjectionItem`, `CashFlowProjectionResponse`, `CashFlowProjectionSummary`, `ProjectionInstrumentType` definitions.

---

## 3. Scope IN — what PR-A3-3 ships

> **Line-number disclaimer:** all line numbers below are validated at `5e25f8bd8` (post-Wave-2). Locate edits by symbol / identifier first; line numbers are advisory and verifiable via `find_symbol` / `grep_pattern` (hook v2 tools).

### 3.1 `_get_market_price` — propagate `PriceReferenceUnprovable`; drop `except Exception`

**Current** at `cashflow_projection_service.py:34-55`:

```python
def _get_market_price(
    session: Session, commodity: str, as_of_date: date
) -> Decimal | None:
    try:
        from app.services.price_lookup_service import (
            get_cash_settlement_price_d1,
            resolve_symbol,
        )

        symbol = resolve_symbol(commodity)
        return Decimal(
            str(
                get_cash_settlement_price_d1(
                    session, symbol=symbol, as_of_date=as_of_date
                )
            )
        )
    except Exception:
        logger.debug(
            "market_price_unavailable commodity=%s date=%s", commodity, as_of_date
        )
        return None
```

**Replacement** (drop the `except Exception` swallow; let `PriceReferenceUnprovable` propagate; use `_with_provenance` to capture the actual settlement date):

```python
def _get_market_price_quote(
    session: Session, commodity: str, as_of_date: date
) -> PriceQuote:
    """Per-row price lookup. Raises PriceReferenceUnprovable on missing
    settlement; the route boundary translates to HTTP 424. NEVER returns
    None; absence of evidence is institutionally a hard-fail per §2.6.
    """
    symbol = resolve_symbol(commodity)
    return get_cash_settlement_price_d1_with_provenance(
        session, symbol=symbol, as_of_date=as_of_date
    )
```

The signature changes from `-> Decimal | None` to `-> PriceQuote` (raises on absence). Caller pattern updates accordingly. The function name becomes `_get_market_price_quote` — the new return shape is `PriceQuote`, not `price`. (Rename mandate consistent with Wave-2's `_resolve_price_d1 → _resolve_price_quote`.)

**Imports to update** at top of `cashflow_projection_service.py` (verified via Serena `find_symbol`: `PriceQuote` is at `backend/app/utils/price_reference.py:26`; `PriceReferenceUnprovable` is at `backend/app/utils/price_reference.py:8`; `price_lookup_service.py:15` re-imports them from `utils/price_reference` — re-export works at runtime BUT `utils/price_reference` is the authoritative source per Wave 2 dispatch §0 stale-citation note; split the imports accordingly):

```python
from app.utils.price_reference import PriceQuote, PriceReferenceUnprovable
from app.services.price_lookup_service import (
    get_cash_settlement_price_d1_with_provenance,
    resolve_symbol,
)
```

The dynamic `from ... import ...` inside `_get_market_price` (lines 38-41) is removed; module-level import is the institutional pattern. **Do NOT** consolidate the two import lines into a single `from app.services.price_lookup_service import ...` block — that would import `PriceQuote` / `PriceReferenceUnprovable` via the re-export, which works but contradicts the Wave 2 §0 declaration of `utils/price_reference.py` as the authoritative location.

### 3.2 `compute_cashflow_projection` — per-row commodity pricing; remove all `or 0` and fallbacks

**Current** at `cashflow_projection_service.py:87-92`:

```python
def compute_cashflow_projection(
    session: Session,
    as_of_date: date,
) -> CashFlowProjectionResponse:
    items: list[CashFlowProjectionItem] = []
    market_price = _get_market_price(session, "LME_AL", as_of_date)
```

**Replacement** — drop the global lookup. Each order/contract is priced by its own commodity inside the per-row loop:

```python
def compute_cashflow_projection(
    session: Session,
    as_of_date: date,
) -> CashFlowProjectionResponse:
    items: list[CashFlowProjectionItem] = []
    # Per-row commodity pricing — no global LME_AL lookup. Each
    # variable-priced row resolves its own commodity via
    # _get_market_price_quote, which raises PriceReferenceUnprovable
    # on absence. The route handler translates to 424.
```

**Per-order block** (lines 95-137) becomes:

```python
orders = session.query(Order).filter(Order.deleted_at.is_(None)).all()
for order in orders:
    settle_dt = _order_settlement_date(order)
    if settle_dt is None or settle_dt < as_of_date:
        continue

    qty = Decimal(str(order.quantity_mt))
    if order.price_type == PriceType.fixed:
        if order.avg_entry_price is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Order {order.id} is fixed-price but avg_entry_price "
                    "is missing; cannot project."
                ),
            )
        price = Decimal(str(order.avg_entry_price))
        price_src = "fixed"
    else:
        # Variable-price: hard-fail on unprovable, no fallback.
        price_quote = _get_market_price_quote(session, order.commodity, as_of_date)
        price = price_quote.value
        price_src = "market"

    amount = qty * price
    is_so = order.order_type == OrderType.sales

    if is_so:
        instr_type = ProjectionInstrumentType.sales_order
        deal_type = DealLinkedType.sales_order
    else:
        instr_type = ProjectionInstrumentType.purchase_order
        deal_type = DealLinkedType.purchase_order
        amount = -amount

    items.append(
        CashFlowProjectionItem(
            instrument_type=instr_type,
            instrument_id=str(order.id),
            reference="",
            counterparty="",
            commodity=order.commodity,             # NOT hardcoded "Al"
            settlement_date=settle_dt,
            quantity_mt=qty,
            price_per_mt=price,
            amount_usd=amount,
            price_source=price_src,
            deal_id=_resolve_deal_id(session, deal_type, order.id),
        )
    )
```

**Per-contract block** (lines 139-194) becomes:

```python
contracts = (
    session.query(HedgeContract)
    .filter(
        HedgeContract.status.in_(
            (
                HedgeContractStatus.active,
                HedgeContractStatus.partially_settled,
            )
        ),
        HedgeContract.deleted_at.is_(None),
    )
    .all()
)
for contract in contracts:
    if contract.settlement_date is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Contract {contract.id} has no settlement_date; "
                "cannot project (no inventing as_of_date)."
            ),
        )
    settle_dt = contract.settlement_date
    if settle_dt < as_of_date:
        continue

    if contract.fixed_price_value is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Contract {contract.id} has no fixed_price_value; "
                "cannot project."
            ),
        )

    qty = Decimal(str(contract.quantity_mt))
    fixed_price = Decimal(str(contract.fixed_price_value))

    # Hard-fail on unprovable variable leg; no fallback to fixed_price.
    variable_quote = _get_market_price_quote(session, contract.commodity, as_of_date)
    est_variable = variable_quote.value
    price_src = "market"

    fixed_side = contract.fixed_leg_side.value
    if fixed_side == "buy":
        amount = qty * (est_variable - fixed_price)
    else:
        amount = qty * (fixed_price - est_variable)

    if contract.classification == HedgeClassification.short:
        instr_type = ProjectionInstrumentType.hedge_sell
    else:
        instr_type = ProjectionInstrumentType.hedge_buy

    items.append(
        CashFlowProjectionItem(
            instrument_type=instr_type,
            instrument_id=str(contract.id),
            reference=contract.reference or "",
            counterparty=contract.counterparty_id or "",
            commodity=contract.commodity,
            settlement_date=settle_dt,
            quantity_mt=qty,
            price_per_mt=fixed_price,
            amount_usd=amount,
            price_source=price_src,
            deal_id=_resolve_deal_id(session, DealLinkedType.contract, contract.id),
        )
    )
```

**Imports to update** at top of `cashflow_projection_service.py`:

```python
from fastapi import HTTPException, status
```

(Verified via grep: `cashflow_projection_service.py` does NOT currently import `HTTPException` — it must be added.)

### 3.3 Route boundary — translate `PriceReferenceUnprovable` to 424

**Current function name verified via `read_file`**: the route function is `get_cashflow_projection` (NOT `projection`); the path decorator is `@router.get("/projection", ...)`. Verify decorator stack + role list via `read_file` before authoring.

**Replacement** — wrap the body of `get_cashflow_projection` (preserving its existing signature, role gates, and decorator stack — only the function BODY gains the try/except wrap):

```python
@router.get("/projection", response_model=CashFlowProjectionResponse)
def get_cashflow_projection(
    # ... preserve existing signature verbatim — verify via read_file ...
) -> CashFlowProjectionResponse:
    try:
        return compute_cashflow_projection(session=session, as_of_date=as_of_date)
    except PriceReferenceUnprovable as exc:
        raise HTTPException(
            status_code=status.HTTP_424_FAILED_DEPENDENCY, detail=str(exc),
        ) from exc
```

**Imports to add** at `routes/cashflow.py` top — use the authoritative module per the Wave 2 §0 declaration:

```python
from app.utils.price_reference import PriceReferenceUnprovable
```

`HTTPException` and `status` are already imported in the route module.

### 3.4 No model / migration / schema changes

PR-A3-3 is a service-body + route-boundary fix. No alembic migration. No `CashFlowProjectionItem` schema change. `alembic heads` continues to return `["038_a3_price_provenance"]`.

### 3.5 Frontend / OpenAPI regen — none required

The `CashFlowProjectionResponse` shape is unchanged. The route's success path returns the same fields. The new 424 error path is already representable in the existing FastAPI 4xx schema. **No `docs/api/openapi_v1.json` regen needed**; no `frontend-svelte/src/lib/api/schema.d.ts` regen needed.

(Implementer MUST verify: run the regen script and confirm zero diff. If a diff appears, surface it in the PR body — it indicates an unexpected schema-impacting change.)

---

## 4. Scope OUT — explicitly NOT in PR-A3-3

- **Cashflow boundary fix** (J-A3-04 Baseline reads Analytic; J-A3-OPUS-08 reconciliation) — Wave 4 (PR-A3-4).
- **P&L lifecycle** (J-A3-OPUS-09 partially-settled zeroes unrealized MTM) — Wave 5 (PR-A3-5).
- **Cross-A1 deferred** (X-A3-J-01 deal_engine; X-A3-J-02 scenario duplicates A1 exposure) — future Phase A1 follow-up audit.
- **Removing `/cashflow/projection` route entirely** — out of scope. The route stays; this dispatch enforces invariants on its body. A future Phase A5 audit-trail dispatch may decide to remove or to propagate the invariants to `governance.md`. PR-A3-3 does NOT modify `governance.md` (constitution stable per `feedback_dispatch_self_consistency`).
- **`inputs_hash` provenance for projection rows** — out of scope. Projection is a forward-looking *estimate* surface; persisting hashes would imply replay reconstruction, which is not the projection's institutional purpose. Add to OPUS-08 reconciliation surface in Wave 4 if needed there.
- **Backfilling stale projection responses** — there is no persistence; projection is computed on demand. No backfill applies.
- **Caching the projection response** — out of scope; today the route is recomputed every call.

---

## 5. Constitutional rules (binding)

- **§2.1 — Valuation/MTM/Cashflow** (`governance.md:131-146`): "No fallback pricing regimes." Projection's current `market_price → entry_price` fallback (lines 109-110, 165-166) is a textbook fallback regime. PR-A3-3 removes it.
- **§2.6 — Hard Fails** (`governance.md:159-174`): "Price reference unprovable" must produce HTTP 424. Today projection's `except Exception → return None` swallows the 424 and silently substitutes. PR-A3-3 propagates `PriceReferenceUnprovable` and translates at the route boundary.
- **§2.6 — Hard Fails** (continuation): "Evidence missing" must hard-fail, not zero-default. Today projection's `or 0` shapes (lines 103, 109, 159) silently substitute zero for missing economics. PR-A3-3 raises 422 explicitly.
- **§2.7 — Output Contract** (`governance.md:208-217`): "Free of speculation." Today projection emits `commodity="Al"` for every order regardless of `order.commodity` (line 129) — institutional speculation about which commodity the row represents. PR-A3-3 emits `order.commodity`.
- **§2.7 — Output Contract** (continuation): The substitution `contract.settlement_date or as_of_date` (line 154) emits `as_of_date` as the projected flow date when the contract has no settlement date — speculation about future flow timing. PR-A3-3 raises 422.
- **OPUS-07 institutional contract — Projection's invariants** (declared HERE at the dispatch layer, NOT in `governance.md`): the `/cashflow/projection` view inherits §2.1, §2.6, §2.7. Per-row commodity pricing; no fallback regimes; no `or 0` defaults; absent economics → 422; unprovable price → 424. A Phase A5 audit-trail dispatch may later decide whether to propagate these invariants into `governance.md` formally; until then the dispatch layer is the binding contract for Projection.

---

## 6. Acceptance criteria

- [ ] `_get_market_price` is **renamed to `_get_market_price_quote`** with signature `-> PriceQuote` (raises `PriceReferenceUnprovable` on absence). The `try/except Exception` swallow at lines 34-55 is REMOVED. The dynamic in-function imports are replaced with module-level imports at the top of `cashflow_projection_service.py`.
- [ ] `compute_cashflow_projection` **does not** call `_get_market_price_quote(session, "LME_AL", ...)` at the top of the function. Each variable-priced row resolves its own commodity inside the per-row loop via `_get_market_price_quote(session, <row>.commodity, as_of_date)`.
- [ ] All `or 0` defaults on `avg_entry_price`, `fixed_price_value` are REMOVED. Missing values raise `HTTPException(422)` with a row-identifying detail message.
- [ ] All `else: price = avg_entry_price` / `else: est_variable = fixed_price` fallback regimes are REMOVED. The `price_src="entry"` literal no longer appears in the codebase under `cashflow_projection_service.py`.
- [ ] `CashFlowProjectionItem.commodity` is `order.commodity` (NOT hardcoded `"Al"`) for orders. Contracts already emit `contract.commodity` correctly — verify unchanged.
- [ ] `contract.settlement_date or as_of_date` substitution is REMOVED. Missing `settlement_date` raises 422.
- [ ] Route function `get_cashflow_projection` in `routes/cashflow.py` wraps `compute_cashflow_projection` in `try/except PriceReferenceUnprovable as exc: raise HTTPException(424)`. `PriceReferenceUnprovable` import added to the route module via `from app.utils.price_reference import PriceReferenceUnprovable` (authoritative module per Wave 2 §0 declaration).
- [ ] `alembic heads` continues to return `["038_a3_price_provenance"]` (no migration).
- [ ] `test_alembic_chain.py` continues passing.
- [ ] `docs/api/openapi_v1.json` and `frontend-svelte/src/lib/api/schema.d.ts` show ZERO diff post-regen (no schema-impacting change).
- [ ] `grep -n "or 0" backend/app/services/cashflow_projection_service.py` returns ZERO matches post-fix.
- [ ] `grep -n '"Al"' backend/app/services/cashflow_projection_service.py` returns ZERO matches post-fix (the hardcoded literal is gone).
- [ ] `grep -n "except Exception" backend/app/services/cashflow_projection_service.py` returns ZERO matches post-fix.
- [ ] **Pre-fix test cleanup completed** (per §7.1):
  - `grep -n "_get_market_price[^_]" backend/tests/test_cashflow_projection_service.py` returns ZERO matches (old symbol replaced everywhere).
  - `grep -n 'price_source.*"entry"' backend/tests/test_cashflow_projection_service.py` returns ZERO matches (every test asserting the removed `"entry"` fallback regime — orders AND contracts — is DELETED).
  - `grep -n '\.commodity == "Al"' backend/tests/test_cashflow_projection_service.py` returns ZERO matches (hardcode regression tests removed).
  - The `MARKET_PRICE_PATCH` constant points to `_get_market_price_quote`. Every `@patch(...)` site uses `PriceQuote` for success or `side_effect=PriceReferenceUnprovable(...)` for absence — never `return_value=None` or `return_value=Decimal(...)`.

---

## 7. Test coverage required

### 7.1 Pre-fix test cleanup — MANDATORY before adding new tests

The existing `backend/tests/test_cashflow_projection_service.py` (verified via `grep_pattern`) contains:
- `MARKET_PRICE_PATCH = "app.services.cashflow_projection_service._get_market_price"` (the OLD symbol name, soon-to-be-renamed).
- ~20 `@patch(MARKET_PRICE_PATCH, return_value=...)` decorators across the test bodies.
- At least one test (`test_variable_order_fallback_to_entry_price`) that explicitly asserts `price_source == "entry"` — i.e., it pins the FALLBACK REGIME §10 mandates removing.

After §3.1's rename (`_get_market_price` → `_get_market_price_quote`) and signature change (`Decimal | None` → `PriceQuote`, raises on absence), all existing patches will silently target a non-existent attribute (mock creates it; real service is NOT mocked), and fallback-regime tests will fail because the regime no longer exists.

**Mandatory cleanup steps** (must be done BEFORE adding the new tests in §7.2):

1. Update the patch constant: `MARKET_PRICE_PATCH = "app.services.cashflow_projection_service._get_market_price_quote"` (new name).
2. Update every `@patch(MARKET_PRICE_PATCH, return_value=Decimal("..."))` call site: replace with `return_value=PriceQuote(value=Decimal("..."), source="westmetall", settlement_date=<prior_business_day>, symbol=resolve_symbol("<commodity>"))` for the market-available path. Verify via `find_symbol` that `PriceQuote` is constructible at the cited shape.
3. Update every `@patch(MARKET_PRICE_PATCH, return_value=None)` call site: replace with `@patch(MARKET_PRICE_PATCH, side_effect=PriceReferenceUnprovable("..."))` — the new function raises, it does not return None.
4. **DELETE every test that asserts `price_source == "entry"` regardless of instrument type (orders AND contracts).** The institutional fallback regime is removed for BOTH the order path (line ~170) AND the contract path (line ~294 in the existing test file). Mechanical procedure: run `grep -n 'price_source.*"entry"' backend/tests/test_cashflow_projection_service.py` and DELETE every test function whose body contains a matching assertion. After deletion, the grep MUST return ZERO matches. Note: tests asserting `price_source == "fixed"` on a fixed-price ORDER path are KEPT — `"fixed"` is the legitimate new sentinel for the fixed-price branch (§3.2 prescribes it). The institutional contract is "no fallback regime", not "no `price_source` literal" — `"fixed"` for fixed orders and `"market"` for variable rows are valid; only `"entry"` (the removed fallback) is forbidden.
5. **DELETE** any test that asserts `commodity == "Al"` on a non-aluminum order's projection item (the hardcode is gone). Mechanical procedure: `grep -n '\.commodity == "Al"' backend/tests/test_cashflow_projection_service.py` — DELETE every matching test.

After cleanup: `grep -n "_get_market_price[^_]" backend/tests/test_cashflow_projection_service.py` MUST return ZERO matches (old symbol fully replaced; the `[^_]` excludes matches inside `_get_market_price_quote`).

### 7.2 New tests

- `backend/tests/test_cashflow_projection_service.py` (extend post-§7.1 cleanup):
  - `test_projection_orders_emit_their_commodity_not_hardcoded_aluminum` — fixture: insert a copper sales order + a zinc sales order + canonical settlement seeds for both; call `compute_cashflow_projection`; assert exactly 2 items; assert `items[0].commodity` and `items[1].commodity` are `"COPPER"` / `"ZINC"` (or whichever short codes the test fixture uses); assert NEITHER has `"Al"`.
  - `test_projection_resolves_per_row_commodity_via_per_row_market_price_lookup` — fixture: copper order + zinc order + DISTINCT canonical settlement values for each (e.g., 9500 / 2800); assert `items[i].price_per_mt` differs across rows (proves per-row pricing, not single-aluminum-curve).
  - `test_projection_raises_424_when_any_row_price_unprovable` — fixture: 1 copper order + NO copper settlement seeded; call `compute_cashflow_projection`; assert it raises `PriceReferenceUnprovable` (or that the route returns 424 if testing through the FastAPI client).
  - `test_projection_raises_422_when_fixed_order_avg_entry_price_missing` — fixture: 1 fixed-price order with `avg_entry_price=None`; call; assert 422 with `"avg_entry_price is missing"` in detail.
  - `test_projection_raises_422_when_contract_settlement_date_missing` — fixture: 1 contract with `settlement_date=None`; call; assert 422 with `"settlement_date"` in detail (no fallback to `as_of_date`).
  - `test_projection_raises_422_when_contract_fixed_price_value_missing` — fixture: 1 contract with `fixed_price_value=None`; call; assert 422.
  - `test_projection_no_entry_fallback_when_market_price_unprovable_for_contract` — fixture: 1 contract for a commodity with NO seeded settlement; call; assert 424 (NOT a 200 with `price_src="entry"`).
  - `test_projection_does_not_compute_global_aluminum_price` — fixture: 1 copper sales order + canonical copper settlement; ensure NO aluminum settlement is seeded; call; assert it succeeds (proves the function doesn't unconditionally look up aluminum at the top).

- `backend/tests/test_cashflow_projection_routes.py` (extend if exists, or create):
  - `test_projection_route_translates_PriceReferenceUnprovable_to_424` — fixture via TestClient: insert order with no canonical settlement; call `GET /cashflow/projection?as_of_date=...`; assert response status `== 424`; assert detail mentions the missing settlement.

---

## 8. Critical sequencing

PR-A3-3 ships against **post-Wave-2 main** (`5e25f8bd8`). Wave 1 + Wave 2 dependencies are landed; PR-A3-3 consumes the `_with_provenance` lookup and `PriceReferenceUnprovable` exception introduced in Wave 1.

- **Branch base**: `origin/main` at `5e25f8bd8` or later.
- **Migration chain**: unchanged. `alembic heads` returns `["038_a3_price_provenance"]` post-Wave-3.
- **Downstream dependency**: Waves 4-5 do not directly depend on Wave 3's body changes. They can author in parallel after Wave 3 dispatch lands; merge sequencing depends on shared file conflicts (Waves 4-5 touch baseline / P&L, not projection).
- **Hook v2 first production exercise**: this dispatch is the FIRST authored after hook v2 implementation merged in `5e25f8bd8`. Hook v2 will self-review on push using `read_file` / `find_symbol` / `grep_pattern`. Calibration data feeds future dispatches.

---

## 9. PR shape

**Title:** `fix(audit-a3): PR-A3-3 — cashflow projection hardening (J-A3-OPUS-02 + 06 + 07)`

**Body skeleton:**

```markdown
## Summary

Wave 3 of Phase A3 remediation. Hardens `cashflow_projection_service`
to comply with constitutional invariants §2.1 (no fallback pricing),
§2.6 (hard fails), §2.7 (free of speculation):

- `_get_market_price` (renamed `_get_market_price_quote`) no longer
  swallows `PriceReferenceUnprovable`; it propagates. Route boundary
  translates to HTTP 424.
- `compute_cashflow_projection` resolves market price per row
  (`order.commodity` / `contract.commodity`), not via a global
  `LME_AL` lookup. Hardcoded `commodity="Al"` removed.
- All `or 0` defaults removed (avg_entry_price, fixed_price_value);
  missing values raise 422 with row-identifying detail.
- All "entry" / "fixed" fallback regimes removed; missing market
  price for a variable row → 424 (not silent substitution).
- `contract.settlement_date or as_of_date` substitution removed;
  missing settlement_date → 422.

Phase A3 jury verdict (FAIL-WITH-CRITICAL-CAVEATS @ commit
`bbd0908d0`) — addresses Tier 1 findings J-A3-OPUS-02 + J-A3-OPUS-06
and Tier 2 finding J-A3-OPUS-07. Constitution §2.1, §2.6, §2.7.

OPUS-07 (Projection-as-5th-view): the `/cashflow/projection` route
stays; this PR's §5 declares its constitutional invariants at the
dispatch layer. Phase A5 audit-trail dispatch may later decide
whether to propagate to `governance.md`. governance.md is NOT
modified in this PR (constitution stable).

## Files changed

- `backend/app/services/cashflow_projection_service.py` — `_get_market_price` →
  `_get_market_price_quote` (signature, body, raises); per-row pricing in
  `compute_cashflow_projection`; remove `or 0` and fallbacks; remove
  hardcoded `"Al"`; module-level imports replace dynamic in-function imports
- `backend/app/api/routes/cashflow.py` — `try/except PriceReferenceUnprovable`
  translation to HTTP 424 around `compute_cashflow_projection` call; new
  import of `PriceReferenceUnprovable`
- Tests: `test_cashflow_projection_service.py` (~8 new tests),
  `test_cashflow_projection_routes.py` (1 new route test)

## Acceptance evidence

- [ ] All criteria from dispatch §6 met
- [ ] grep for `"or 0"`, `'"Al"'`, `except Exception` in projection service returns zero
- [ ] OpenAPI + schema.d.ts regen produces ZERO diff
- [ ] `alembic heads` returns single `["038_a3_price_provenance"]`

## Constitutional impact

§2.1 (no fallback pricing — entry/fixed fallbacks removed), §2.6
(hard fails — PriceReferenceUnprovable propagates; missing
economics raise 422), §2.7 (free of speculation — emitted commodity
matches the source row, no `as_of_date` substitution for missing
settlement_date).

## Out of scope

- Wave 4-5 of Phase A3
- Removing `/cashflow/projection` route (Phase A5 audit-trail concern)
- Modifying governance.md (constitution stable)
- inputs_hash provenance for projection (projection is forward-looking estimate)

## Closes

J-A3-OPUS-02 + J-A3-OPUS-06 + J-A3-OPUS-07.
```

---

## 10. Constraints — what NOT to do

- DO NOT keep the `try/except Exception` swallow in any form. The new shape MUST let `PriceReferenceUnprovable` propagate. A `try/except PriceReferenceUnprovable` ONLY exists at the route boundary (per §3.3), nowhere in the service body.
- DO NOT preserve any `or 0` default for `avg_entry_price` or `fixed_price_value`. Missing values raise 422 with field-level detail.
- DO NOT preserve the `else: price = avg_entry_price` / `else: est_variable = fixed_price` fallback regimes. The `price_src="entry"` literal MUST disappear from the file.
- DO NOT keep `commodity="Al"` hardcoded on orders' `CashFlowProjectionItem`. Use `order.commodity`.
- DO NOT keep the `contract.settlement_date or as_of_date` substitution. Missing `settlement_date` raises 422.
- DO NOT compute a global `_get_market_price_quote(session, "LME_AL", ...)` at the top of `compute_cashflow_projection`. Per-row pricing is the only acceptable pattern.
- DO NOT modify `docs/governance.md`. The OPUS-07 invariants live in this dispatch's §5; a Phase A5 audit-trail dispatch may decide whether to propagate.
- DO NOT remove the `/cashflow/projection` route. It stays; the body is hardened.
- DO NOT add `inputs_hash` / provenance fields to `CashFlowProjectionItem`. Projection is forward-looking estimate, not replay-persisted evidence.
- DO NOT introduce caching of the projection response. The endpoint is recomputed per call.
- DO NOT use `strip(...)` with character classes that include hyphen `-`, plus `+`, period `.`, comma `,` anywhere in the changed files. Pricing-domain awareness mandatory.
- DO NOT auto-merge — wait for Codex review.
- DO NOT use `--no-verify` to skip git hooks (hook v2 is now ACTIVE; bypass invalidates the institutional first-sieve).

---

## 11. Workflow

1. `git fetch origin && git worktree add D:/Projetos/Hedge-Control-New-pr-a3-3 origin/main && cd D:/Projetos/Hedge-Control-New-pr-a3-3 && git checkout -b audit-a3/cashflow-projection-hardening`
2. Configure `.claude/settings.local.json` per the worktree pattern (allow `git`/`gh`/`pytest`/`python`; deny `--force` raw, `--auto`, `--no-verify`, push to `main`).
3. `python scripts/install_git_hooks.py` — confirm hook v2 active (`git config core.hooksPath` returns `.githooks`).
4. Read jury §J-A3-OPUS-02, J-A3-OPUS-06, J-A3-OPUS-07 in full.
5. Read Wave 1 dispatch §3.1-§3.4 (the `_with_provenance` machinery + `PriceReferenceUnprovable` translation pattern). Read Wave 2 dispatch §3.7.1 (the per-row commodity + try/except translation pattern). PR-A3-3 mirrors both.
6. Update `cashflow_projection_service.py` imports (top of file): add `from fastapi import HTTPException, status`; add **two** import lines per §3.1 (split for the `utils/price_reference` authoritative-location convention): `from app.utils.price_reference import PriceQuote, PriceReferenceUnprovable` AND `from app.services.price_lookup_service import get_cash_settlement_price_d1_with_provenance, resolve_symbol`. Remove the dynamic in-function imports inside `_get_market_price`.
7. Rename `_get_market_price` → `_get_market_price_quote`; replace body per §3.1. The function now raises `PriceReferenceUnprovable` (it does NOT return `None`).
8. Update `compute_cashflow_projection` per §3.2: remove the global `market_price = _get_market_price(...)` line; resolve per-row inside the order and contract loops; emit `order.commodity` (not `"Al"`); raise 422 on missing `avg_entry_price` / `fixed_price_value` / `settlement_date`; remove all "entry" fallback paths.
9. Update `routes/cashflow.py:projection` per §3.3: wrap the call in `try/except PriceReferenceUnprovable: raise HTTPException(424)`; add the import.
10. Run `grep -n "or 0\|except Exception\|\"Al\"\|price_src.*\"entry\"" backend/app/services/cashflow_projection_service.py` — confirm ZERO matches. This is the institutional contract that the `or 0` / fallback / hardcode patterns are gone.
11. **Pre-fix test cleanup per §7.1**: update `MARKET_PRICE_PATCH` constant; update all `@patch` decorators to PriceQuote / PriceReferenceUnprovable side_effect; DELETE fallback-regime tests; verify `grep -n "_get_market_price[^_]" backend/tests/test_cashflow_projection_service.py` returns ZERO. Then author NEW tests per §7.2. Each new test pins a specific institutional contract; no NEW test should be deleted in iterations.
12. Run targeted pytest: `pytest backend/tests/test_cashflow_projection_service.py backend/tests/test_cashflow_projection_routes.py backend/tests/test_alembic_chain.py -v`
13. Full backend suite: `pytest backend/tests/ -v` — green except known failures (3 pre-existing `test_ws.py` Python 3.14 failures).
14. Verify ZERO openapi/schema diff:
    - `cd backend && DATABASE_URL=sqlite:///:memory: SECRET_KEY=dummy JWT_SIGNING_SECRET=dummy AUDIT_HMAC_KEY=dummy AUDIT_SIGNING_KEY=test python -c "from app.main import app; import json; json.dump(app.openapi(), open('../docs/api/openapi_v1.json', 'w'), indent=2, sort_keys=True)"`
    - `cd ../frontend-svelte && OPENAPI_SOURCE=../docs/api/openapi_v1.json node scripts/regen-schema.mjs`
    - `git diff --stat docs/api/openapi_v1.json frontend-svelte/src/lib/api/schema.d.ts` — expect ZERO files changed. If diff appears, surface in PR body.
15. `git push -u origin audit-a3/cashflow-projection-hardening` — **hook v2 will self-review** the dispatch artifact + cited file excerpts. Absorb each P1 as a new commit; bypass with `--no-verify` ONLY under explicit orchestrator authorization (not the executor's discretion).
16. `gh pr create --base main --title "<§9 title>" --body-file <body>` — DO NOT use `--draft`.
17. **STOP. Wait for Codex review.** Address each catch as a new commit. Expected catch count: 2-5 (medium-surface body change; per-row-pricing pattern + governance contract enforcement).
18. Report back to orchestrator with: PR URL, final SHA, Codex review state (silent 👍 or catches), files-touched grouping, test counts (focused + full backend), grep evidence (zero `or 0` / `except Exception` / `"Al"` / `price_src="entry"` matches), openapi/schema-diff evidence (zero files changed).

---

## 12. Final report shape

When complete, report to orchestrator:
- Branch + PR URL + final SHA.
- Files touched (grouped: services / routes / tests).
- Test pass/fail counts vs main baseline.
- Codex review status + catches absorbed.
- Hook v2 self-review JSON artifact path + tool_calls summary.
- grep evidence: `or 0`, `except Exception`, `"Al"`, `price_src.*"entry"` in projection service all zero matches.
- OpenAPI / schema.d.ts diff: zero files changed.

Keep report under 600 words.

Boa caça.
