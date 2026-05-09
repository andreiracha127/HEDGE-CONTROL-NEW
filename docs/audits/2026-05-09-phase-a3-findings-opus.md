# Phase A3 — Stage 1 Findings — Auditor A (Opus 4.7)

**Phase:** A3 — Valuation (MTM · P&L · Cashflow · Scenario)
**Stage:** 1 — Independent adversarial audit (read-only)
**Repo HEAD:** `609924562` (post-A2 closure, branch `audit/phase-a3`)
**Date:** 2026-05-09
**Auditor:** Opus 4.7 / 1M context (Auditor A)

---

## Posture (overall)

**FAIL-WITH-CRITICAL-CAVEATS.**

The pipeline has a working determinism backbone for the **happy path** (Decimal arithmetic in MTM, single-source D-1 lookup, no LLM in scenario, no DB writes from scenario or analytic). However, there are **multiple T1 constitutional violations** with regulatory-incident potential:

- **Order MTM, cashflow analytic, cashflow projection, and scenario virtual hedges all silently collapse non-aluminum commodities to LME_AL price** — copper / zinc / nickel / lead / tin orders are valued with the wrong commodity benchmark (`J-A3-01`, `J-A3-02`, `J-A3-04`).
- **MTM, P&L and Baseline-Cashflow snapshots persist no `inputs_hash`, no price-source provenance, no symbol/commodity** — they are not reconstructable from disk; the project already has the right shape on `DealPNLSnapshot` (A1) and regressed it for A3 (`J-A3-05`, `J-A3-08`).
- **`cashflow_projection_service` has 4 silent fallback regimes simultaneously** — `try/except: None` over price lookup, `or 0` over null Decimals, three-way method switching (fixed / market / entry), and a hard-coded `commodity="Al"` label (`J-A3-04`, `J-A3-09`).
- **`CashSettlementPrice.price_usd` is a `Float` column** — the canonical price source is non-deterministic by storage type, even though all downstream services convert via `Decimal(str(...))` (which freezes the float-repr drift, it doesn't undo it) (`J-A3-06`).
- **The Ledger amount comes from the HTTP payload directly** — settlement amounts are accepted as input from `trader` role, not derived from contract state + price lookup (`J-A3-13`).
- **5-day calendar lookback in `price_lookup_service`** silently spans missing business-day data — there is no business calendar; `as_of_date − 1 → as_of_date − 6` is a closed window walked in calendar days, not business days (`J-A3-07`).

The reconstrutibilidade gaps (`J-A3-05`, `J-A3-08`) and the commodity-collapse bugs (`J-A3-01`/`J-A3-02`/`J-A3-04`) together mean that, today, an MTM/Cashflow/P&L number for a copper position cannot be regenerated, audited, or reconciled against its source price; a regulator asking "show me the price evidence behind this MTM" will find none.

---

## Tier definitions

- **T1 (CRITICAL):** violation of a governance hard-fail clause; data-loss / evidence-loss / regulatory-incident potential.
- **T2 (HIGH):** institutional invariant violated; audit-trail or reconstrutibilidade gap, but not yet a hard-fail trigger.
- **T3 (MEDIUM):** hygiene / risk-of-regression that strengthens the system without changing semantics.
- **T4 (LOW):** documentation / naming / governance-vs-implementation drift.

---

## Question-by-question summary

### Q1 — Determinismo numérico do MTM (§2.1, §2.3)

- **Decimal-only arithmetic in MTM core?** Mostly **YES**. `mtm_contract_service.py:42-47` and `mtm_order_service.py:55-61` keep every operand `Decimal`. `_as_decimal` in `mtm_snapshot_service.py:15-18` normalises with `Decimal(str(value))`.
- **Float in the price source?** **YES** — `CashSettlementPrice.price_usd: Mapped[float] = mapped_column(Float, …)` at `backend/app/models/market_data.py:23`. The lookup at `price_lookup_service.py:180` does `Decimal(str(row.price_usd))`, which freezes the float-repr but does not eliminate the precision loss that already happened on insert/storage. Finding `J-A3-06`.
- **Aggregation determinism?** Iterations are `query(...).order_by(...created_at.asc()).all()` (analytic, scenario, baseline). Sort key is created_at + (id, settlement_date). No `set()` over UUIDs; no `dict.values()` whose key set is hash-randomised. Within the in-process pipeline, ordering is deterministic.
- **`MtmSnapshot.inputs_hash`?** **NO.** `backend/app/models/mtm.py:19-37` has only `mtm_value, price_d1, entry_price, quantity_mt, correlation_id`. No `inputs_hash`, no `price_source`, no `settlement_date_used`, no `symbol`, no `commodity`. Finding `J-A3-05`. Reconstrutibilidade hard-fail (§2.3).
- **D-1 enforcement?** `price_lookup_service.py:158` computes `price_date = as_of_date - timedelta(days=1)` then walks back up to 5 calendar days (`lookback_limit = price_date - timedelta(days=5)`, `:159`). Finding `J-A3-07` (no business-day calendar; silent multi-day lookback).
- **Hard-fail when D-1 is unprovable?** **YES** — `PriceReferenceUnprovable` is raised at `:173`. The thin wrapper `get_cash_settlement_price_d1` re-raises as 424 (`:209`). MTM caller propagates. Good.

### Q2 — Cashflow always-derived (§2.1)

- **POST/PUT cashflow row?** **YES, partially.** `POST /contracts/{contract_id}/settle` in `routes/cashflow_ledger.py:27-48` accepts `HedgeContractSettlementCreate` whose `legs[].amount` is taken **verbatim** from the payload at `cashflow_ledger_service.py:51` and persisted into `CashFlowLedgerEntry.amount`. Settlement amounts are not derived inside the service; the `trader` posts the number and the server stores it. Finding `J-A3-13`.
- **Baseline derivation source?** `cashflow_baseline_service.py:31` calls `compute_cashflow_analytic(...)`. Baseline = Analytic dump — derivation chain is one hop, but:
  - Baseline reads from Analytic — that is exactly the cross-view example flagged in dispatch §2.1 ("Baseline lendo de cache What-if; Ledger emitindo a partir de Analytic"). Finding `J-A3-11`.
  - Baseline persists `snapshot_data` (jsonb of analytic items + total) but no `inputs_hash`. Finding `J-A3-08`.
- **Ledger emitted only via settlement events?** **YES.** `ingest_hedge_contract_settlement` is the sole writer; uniqueness is `(source_event_type, source_event_id, leg_id, cashflow_date)`. But the `amount` itself is not derived from anything (see `J-A3-13`).

### Q3 — Boundary entre as quatro views (§2.1)

- **Analytic persistence?** **NO.** `cashflow_analytic_service.py` has zero `db.add` / `session.add` / `session.commit`. PASS for Analytic.
- **Baseline import of Analytic?** **YES.** `cashflow_baseline_service.py:10` imports `compute_cashflow_analytic` and `:31` consumes its output for persistence. The schema goes one step further: `ScenarioCashflowSnapshot.analytic` and `.baseline` are both typed `CashFlowAnalyticResponse` (`schemas/scenario.py:86-88`), and the scenario service literally sets `baseline=cashflow_analytic` at `scenario_whatif_service.py:519`. Finding `J-A3-11`.
- **Ledger ↔ Baseline coexistence?** Two parallel sources of truth: Ledger writes settlement-event-driven rows (`ingest_hedge_contract_settlement`); Baseline writes a daily "as-of" rollup of Analytic. They are not reconciled with each other. There is no documented invariant linking them. Finding `J-A3-12` (T2 — soft conflict).
- **`cashflow_projection_service` — 5th view?** **YES.** Governance §2.1 lists exactly four views (Analytic / Baseline / Ledger / What-if). Projection is a forward-looking timeline — not "non-persistent like Analytic" (it has its own response shape) and not on the constitutional list. Finding `J-A3-10`.

### Q4 — P&L provenance (§2.1, §2.3)

- **Provenance triplet on each price input?** **NO.** `pl_calculation_service.compute_pl` calls `compute_mtm_for_contract` for the unrealized leg (`:81`). MTM result drops `(source, settlement_date, symbol)` because `MTMResultResponse` does not carry them, and the snapshot model doesn't either. Finding `J-A3-05`.
- **P&L persisted with provenance?** **NO.** `PLSnapshot` schema at `models/pl.py:13-32` has `entity_type, entity_id, period_start, period_end, realized_pl, unrealized_mtm, correlation_id`. No `price_references` jsonb, no `inputs_hash`. Compare against `DealPNLSnapshot` at `models/deal.py:227-244` — same project already implemented `inputs_hash` + `price_references` + a portable JSON validator for A1's deal-level P&L. A3's `PLSnapshot` regressed that pattern. Finding `J-A3-08`.
- **Compute-on-demand vs snapshot equivalence?** Both paths call the same `compute_pl(...)` (`pl_calculation_service.py:17` for ad-hoc; `pl_snapshot_service.py:27` for persistence). Same number guaranteed at the same `(period_end)`. But on snapshot replay, no input-hash check — drift in the underlying ledger or the price table will produce a different number on a second `compute_pl` and a 409 in `create_pl_snapshot:48`. Detection works; reconstruction does not (no inputs_hash).
- **`partially_settled` zeroes unrealized_mtm.** `pl_calculation_service.py:78-79` returns `Decimal("0")` for any non-active status; `compute_mtm_for_contract` accepts both `active` AND `partially_settled` (`mtm_contract_service.py:27-30`). P&L silently ignores the unrealized-MTM tail of partially settled contracts. Finding `J-A3-15`.

### Q5 — Price lookup sem fallback (§2.1)

- **Return on missing row?** **Raises** `PriceReferenceUnprovable` (`price_lookup_service.py:173`). Wrapper raises HTTP 424. **Hard-fail behaviour at the canonical layer is correct.**
- **Caller-side swallowing?** **YES** — `cashflow_projection_service._get_market_price` at `:37-55` does `try: ...; except Exception: return None` and `logger.debug(...)`. This catches `PriceReferenceUnprovable` AND any other error (network, DB) silently. Finding `J-A3-04`.
- **Multiple price sources?** **NO** — single canonical table `cash_settlement_prices` with a single SQLAlchemy model. Source string is captured in `CashSettlementPrice.source` (e.g. "westmetall"). PASS for "tente A depois B".
- **Weekend / holiday handling?** No business-day calendar. Lookback is `timedelta(days=5)` (calendar days). Implications: a Tuesday holiday + Wednesday data outage silently surfaces Friday's settlement as today's "D-1"; if the source is offline for >5 calendar days the call hard-fails, but inside the window the substitution is silent and the snapshot doesn't record which `settlement_date` was actually used. Finding `J-A3-07`.

### Q6 — Scenario in-memory invariant (§2.2)

- **DB writes inside scenario?** **NO** — grep for `session\.(add|merge|commit|execute)` in `scenario_whatif_service.py` returns zero matches. **PASS.**
- **Scenario tables?** **NO** `scenario_results` / `whatif_runs` table exists in models. **PASS.**
- **Cache?** **NO** — no `lru_cache`, `functools.cache`, redis client. **PASS.**
- **Input format?** Strictly explicit deltas (3 typed delta classes with `Literal[...]` discriminators in `schemas/scenario.py:15-70`). No LLM, no free-text. **PASS.**
- **Scenario commodity collapse.** `AddUnlinkedHedgeContractDelta` (`schemas/scenario.py:19-35`) does NOT include a `commodity` field. The service hard-codes `commodity=DEFAULT_COMMODITY` ("LME_AL") at `scenario_whatif_service.py:178`. Every virtual hedge added in a scenario is priced as aluminum, regardless of intent. Finding `J-A3-02`.
- **Schema collapses Analytic and Baseline.** `ScenarioCashflowSnapshot` declares both fields as `CashFlowAnalyticResponse` (`schemas/scenario.py:86-88`); the service assigns the same object to both (`scenario_whatif_service.py:519`). Boundary mislabelling. Finding `J-A3-11`.
- **Decimal → float on exposure response.** `_compute_commercial_exposure` and `_compute_global_exposure` cast every Decimal to `float(...)` 18× (`scenario_whatif_service.py:281-289`, `:414-428`). This loses precision on the wire and is consumed by downstream risk reporting. Cross-A1 — flagged, not owned by A3. `cross-phase-A1-risk`.

### Q7 — Premium pricing exclusion (§2.1)

- **Premium/discount in valuation?** **NO** — grep for `premium|discount|over_benchmark|spread` in `mtm_*`, `pl_*`, `cashflow_*`, `scenario_*`, `price_lookup_*` returns zero matches. The `HedgeContract` model carries `premium_discount` (`models/contracts.py:116`) but it is consumed only at A2 origination (`rfq_orchestrator.py`, `contract_service.py`, `llm_agent.py`). MTM uses `contract.fixed_price_value` directly (`mtm_contract_service.py:44`). **PASS.**
- **Subtle:** `HedgeContract.entry_price` property at `models/contracts.py:191` collapses `None → Decimal("0")`. A3 valuation does NOT use this property (it accesses `fixed_price_value` directly with explicit None-guard at `:36-40`). Cross-phase risk noted, not a finding inside A3.

### Q8 — Aggregation determinism (§2.3)

- **Cross-commodity aggregation determinism?** Scenario uses `for commodity in sorted(rows): …` (`scenario_whatif_service.py:274`, `:397`) — deterministic. Cashflow analytic, baseline use `_canonicalize_snapshot_payload` to sort `cashflow_items` by `(object_type, object_id)` (`cashflow_baseline_service.py:13-19`) — deterministic. PASS.
- **Decimal → float drift?** Confirmed in scenario exposure response (cross-A1, see Q6). MTM/P&L core arithmetic: pure Decimal. PASS for the values that matter to MTM/PnL/Cashflow.
- **Tenant boundary?** No `tenant_id` column anywhere in `backend/app/models/`. Cross-tenant aggregation cannot be malformed because tenancy does not exist in the schema. Not an A3 issue — system-wide design choice. `cross-phase-A5-risk` if multi-tenancy is ever introduced; not a finding here.

### Q9 — Cross-A1-A3 boundary

- **A1 primitives consumed by A3?** Scenario uses `canonical_commodity` from `price_lookup_service` (originally A1) for exposure aggregation — consistent with A1 invariant.
- **A3 re-aggregation drift?** Scenario re-implements commercial + global exposure aggregation in-process (`_compute_commercial_exposure`, `_compute_global_exposure`). The behaviour is intentional (scenario must replay over virtual deltas), but the implementation does not call A1's exposure service directly, so any future change to A1 semantics could silently diverge. Finding `J-A3-14` (T3 — divergence risk, not an active bug).
- **Audit emission?** All A3 mutating routes emit audit (`mtm.py:55-84`, `pl.py:41-57`, `cashflow.py:46-58`, `cashflow_ledger.py:38-50`). Scenario route (read-only) does not. Consistent.

### Q10 — Cross-A2-A3 boundary + cross-A4 risks

- **HedgeContract field used by A3 but not guaranteed by A2?** `mtm_contract_service` and `cashflow_projection_service` both read `contract.fixed_price_value`. A3 hard-fails if it is None on the MTM path (`mtm_contract_service.py:36-40`); the Projection path silently substitutes 0 (`cashflow_projection_service.py:159`). The Projection's silent substitution is the bug, not the A2 contract — recorded under `J-A3-09`.
- **Cross-A4:** `webhook_processor`, `whatsapp_*`, `llm_agent` are not imported by any A3 service. **No cross-A4 dependency.**
- **Cross-A5 (audit / rate-limit):** All mutating A3 routes go through `audit_event` + `RATE_LIMIT_MUTATION`. Read endpoints are unrate-limited (consistent with platform pattern). Marked as `cross-phase-A5-risk` but not actionable in A3.

---

## Findings

### J-A3-01 — Order MTM silently uses LME_AL price for every commodity — T1

- **Tier:** T1
- **Surface:** `backend/app/services/mtm_order_service.py:18` (`DEFAULT_COMMODITY = "LME_AL"`); `:21-26` function signature; `:55-57` price lookup.
- **Constitutional clause violated:** §2.1 "MTM uses D-1 settlement" + §2.3 "Price reference unprovable → hard-fail" + §2.1 "no fallback pricing regimes".
- **Evidence:**
  ```python
  DEFAULT_COMMODITY = "LME_AL"
  def compute_mtm_for_order(db, order_id, as_of_date, commodity: str = DEFAULT_COMMODITY):
      ...
      price_d1 = get_cash_settlement_price_d1(db, symbol=resolve_symbol(commodity), as_of_date=as_of_date)
  ```
  `Order.commodity` is a populated, indexed column (`backend/app/models/orders.py:67-69`), but `compute_mtm_for_order` does not consult it. The route `backend/app/api/routes/mtm.py:44` calls `compute_mtm_for_order(session, order_id=order_id, as_of_date=as_of_date)` with no `commodity` kwarg — so every variable-priced order, regardless of commodity, gets the LME aluminum cash price as `price_d1`.
- **Reproduction:** Create a copper variable-price order with a known fixing convention. Call `GET /mtm/orders/{order_id}?as_of_date=YYYY-MM-DD`. The returned `price_d1` will be the LME aluminum cash settlement, not copper.
- **Suggested remediation surface:** `mtm_order_service.compute_mtm_for_order` must read `order.commodity` and resolve via `resolve_symbol(order.commodity)`. Remove the `commodity` kwarg / `DEFAULT_COMMODITY` default. The route must remain commodity-free.

---

### J-A3-02 — Scenario virtual hedge contracts hard-coded to LME_AL — T1

- **Tier:** T1
- **Surface:** `backend/app/services/scenario_whatif_service.py:42` (`DEFAULT_COMMODITY = "LME_AL"`); `:178` (`commodity=DEFAULT_COMMODITY` inside `VirtualHedgeContract(...)`); `backend/app/schemas/scenario.py:19-35` (`AddUnlinkedHedgeContractDelta` does not declare a `commodity` field).
- **Constitutional clause violated:** §2.2 "Explicit deltas only" (deltas must be reconstructable; an implicit commodity defeats reconstruction) + §2.1 "No fallback pricing regimes" + §2.3 "price reference cannot be proven".
- **Evidence:** `_apply_deltas` builds every `VirtualHedgeContract` with `commodity=DEFAULT_COMMODITY`. The schema has no commodity field, so the operator cannot specify it. Downstream, `_resolve_price_d1(db, req.as_of_date, lookup, contract.commodity)` (`:469-472`) will resolve to LME aluminum cash for every virtual hedge.
- **Reproduction:** POST to `/scenario/what-if/run` with a single `add_unlinked_hedge_contract` delta. Inspect the returned `mtm_snapshot` `price_d1` against today's LME copper cash — they will not match (LME aluminum will be returned).
- **Suggested remediation surface:** Add a required `commodity: str` field to `AddUnlinkedHedgeContractDelta` (validated via `resolve_symbol`); propagate to `VirtualHedgeContract.commodity`; remove `DEFAULT_COMMODITY` from `_apply_deltas`. Also drop `DEFAULT_COMMODITY` from `_resolve_price_d1` signature default — there is no caller that should be commodity-implicit in scenario.

---

### J-A3-04 — `cashflow_projection_service` silently swallows `PriceReferenceUnprovable` — T1

- **Tier:** T1
- **Surface:** `backend/app/services/cashflow_projection_service.py:34-55`.
- **Constitutional clause violated:** §2.1 "no fallback pricing regimes" + §2.3 "price reference cannot be proven → hard-fail".
- **Evidence:**
  ```python
  def _get_market_price(session, commodity, as_of_date) -> Decimal | None:
      try:
          ...
          return Decimal(str(get_cash_settlement_price_d1(session, symbol=symbol, as_of_date=as_of_date)))
      except Exception:
          logger.debug("market_price_unavailable commodity=%s date=%s", commodity, as_of_date)
          return None
  ```
  The bare `except Exception` catches `PriceReferenceUnprovable` (the canonical hard-fail signal), `HTTPException(424)`, DB errors, network errors — all silenced to a `logger.debug(...)` and `return None`. The caller then chooses an alternative regime (`elif market_price is not None: ... else: ... = entry`, `:105-110`).
- **Reproduction:** Empty `cash_settlement_prices` for the lookback window of any future commodity. `GET /cashflow/projection?as_of_date=…` returns 200 with `price_source="entry"` for every variable-price item, with no surfaced error.
- **Suggested remediation surface:** Remove the `try/except` envelope; let `PriceReferenceUnprovable` propagate to the route (which already maps to 424 via the wrapper). Same surface must drop the `else: price = Decimal(str(order.avg_entry_price or 0)); price_src = "entry"` branch (see `J-A3-09`).

---

### J-A3-05 — `MTMSnapshot` lacks `inputs_hash`, price-source provenance, symbol/commodity — T1

- **Tier:** T1
- **Surface:** `backend/app/models/mtm.py:19-37`; `backend/app/services/mtm_snapshot_service.py:50-63`; `backend/app/schemas/mtm.py` (response model).
- **Constitutional clause violated:** §2.3 "Reconstrutibilidade quebrada — MTM snapshot que não pode ser regenerado a partir de inputs_hash"; "Price source unprovable — `MtmSnapshot` sem ancoragem na fonte original" (governance §159-174).
- **Evidence:** Persisted columns are `mtm_value`, `price_d1`, `entry_price`, `quantity_mt`, `correlation_id`, plus the natural key `(object_type, object_id, as_of_date)`. There is no `inputs_hash`, no `price_source` (the `CashSettlementPrice.source` string), no `settlement_date_used` (which day the lookback actually returned), no `symbol`, no `commodity`. The 5-day lookback (`J-A3-07`) means a snapshot taken on Day-X uses a settlement row whose date is unknown to the snapshot itself.
  Compare with `DealPNLSnapshot` (A1) at `backend/app/models/deal.py:227-244`: that table already has `inputs_hash` and a validated `price_references` jsonb. A3 regressed the pattern.
- **Reproduction:** Create an MTM snapshot. Drop or update the underlying `cash_settlement_prices` row that fed it. The snapshot now references a price that cannot be retrieved — there is nothing in the row that says which price was used.
- **Suggested remediation surface:** Alembic migration adding `inputs_hash CHAR(64) NOT NULL`, `price_source VARCHAR(64) NOT NULL`, `price_settlement_date DATE NOT NULL`, `symbol VARCHAR(64) NOT NULL` to `mtm_snapshots`. `mtm_*_service` to compute `inputs_hash = sha256(canonical_json({contract_id|order_id, as_of_date, entry_price, quantity_mt, price_value, price_source, symbol, settlement_date}))`. `compute_mtm_for_contract`/`compute_mtm_for_order` to call `get_cash_settlement_price_d1_with_provenance` (returns `PriceQuote`) and surface `(value, source, settlement_date, symbol)` to the snapshot writer.

---

### J-A3-06 — `CashSettlementPrice.price_usd` is stored as `Float`, not `Numeric` — T1

- **Tier:** T1
- **Surface:** `backend/app/models/market_data.py:23` (`price_usd: Mapped[float] = mapped_column(Float, nullable=False)`); `backend/app/services/price_lookup_service.py:180` (`Decimal(str(row.price_usd))`).
- **Constitutional clause violated:** §2.3 "Numeric non-determinism — comparação Decimal-via-float que colapsa precisão" + §2.1 "MTM uses D-1 settlement" (the settlement value itself must be deterministic).
- **Evidence:** The canonical price storage column is `Float` — IEEE 754 binary64 — while every consumer downstream (`mtm_*`, `pl_*`, `cashflow_*`, `scenario_*`) uses `Decimal`. The `Decimal(str(row.price_usd))` conversion at `:180` formats the float through Python's `str(float)` (≤17 significant digits), which fixes the *transit* precision but does NOT undo the precision lost when the Numeric→Float coercion happened on insert. Two ingestion runs on identical input may persist `9492.499999999999` and `9492.5` in different rows; downstream Decimals diverge by 1e-13. Compounding through `quantity_mt × (price_d1 − entry_price)` over many contracts amplifies this. Compare `MTMSnapshot.mtm_value` which is `Numeric(18, 6)` (`models/mtm.py:30`) — the model explicitly uses Numeric for derived values but Float for the source. Inconsistent.
- **Reproduction:** Insert two `CashSettlementPrice` rows with the same Numeric input via two different SQLAlchemy paths (e.g., one with Decimal, one with str-converted Decimal). Read back; the float values may differ at the 14th decimal. The downstream MTM differs.
- **Suggested remediation surface:** Migration: `ALTER COLUMN price_usd TYPE Numeric(18, 6)`. Update `models/market_data.py:23` to `Mapped[Decimal] / Numeric(18, 6)`. Audit any ingestion service writing this table to ensure Decimal in / Decimal out.

---

### J-A3-07 — Price lookup uses 5-calendar-day lookback with no business-day calendar — T1

- **Tier:** T1
- **Surface:** `backend/app/services/price_lookup_service.py:158-170`.
- **Constitutional clause violated:** §2.1 "MTM uses D-1 settlement" — D-1 means the previous *business* day, not "the latest of the previous five calendar days". The audit-prompt §2.1 reads explicitly: "Não há 'fallback to D' se D-1 está ausente — é hard-fail."
- **Evidence:**
  ```python
  price_date = as_of_date - timedelta(days=1)
  lookback_limit = price_date - timedelta(days=5)
  row = (db.query(CashSettlementPrice)
           .filter(CashSettlementPrice.symbol == symbol,
                   CashSettlementPrice.settlement_date <= price_date,
                   CashSettlementPrice.settlement_date >= lookback_limit)
           .order_by(CashSettlementPrice.settlement_date.desc())
           .first())
  ```
  No `BusinessCalendar`, no exchange-holiday table, no `commodity → calendar` mapping. The 5-day window silently swallows holiday + weekend + multi-day market closure. The snapshot does not record the actually-used settlement_date (see `J-A3-05`), so the substitution is unauditable from disk.
- **Reproduction:** Have prices only for `Friday` and call with `as_of_date = Wednesday` of next week (Mon-Tue holiday). Lookup returns Friday's price as "D-1" with no warning, no record of the actual age.
- **Suggested remediation surface:** Either (a) introduce a per-commodity business-calendar service and reject when `as_of_date - 1 business_day` is not in `cash_settlement_prices` (strictest, governance-aligned); or (b) keep the lookback but persist the *actual* `settlement_date` used into `MTMSnapshot.price_settlement_date` (paired with `J-A3-05`) so reconstruction is possible. The dispatch text reads (a) as the constitutional answer.

---

### J-A3-08 — `PLSnapshot` and `CashFlowBaselineSnapshot` lack `inputs_hash` / provenance — T1

- **Tier:** T1
- **Surface:**
  - `backend/app/models/pl.py:13-32` — `PLSnapshot` has no `inputs_hash`, no `price_references`.
  - `backend/app/models/cashflow.py:24-42` — `CashFlowBaselineSnapshot` has only `snapshot_data`/`total_net_cashflow`/`correlation_id`.
- **Constitutional clause violated:** §2.3 "Evidence missing" + "Reconstrutibilidade quebrada".
- **Evidence:** `PLSnapshot` persists `realized_pl` and `unrealized_mtm`; no input fingerprint, no price references, no link to the underlying `MTMSnapshot.id` or to the `CashFlowLedgerEntry.id`s that produced `realized_pl`. `CashFlowBaselineSnapshot.snapshot_data` is a JSON dump of the analytic output — convenient for reading, but with no canonical hash. `_canonicalize_snapshot_payload` (`cashflow_baseline_service.py:13-19`) does sort the `cashflow_items` for equality comparison, so the payload IS deterministically ordered, but the result is not hashed and the prices the analytic ran with are not pinned.
  The reference shape exists in the same codebase: `DealPNLSnapshot` has `inputs_hash` + per-commodity `price_references` jsonb (`models/deal.py:227-244`). A3 should mirror it.
- **Reproduction:** Create a Baseline snapshot today. Drop a price row used by yesterday's projection. The Baseline still exists with no fingerprint of which prices it consumed; on regeneration, the 409-conflict logic catches the divergence (`cashflow_baseline_service.py:35-44`) but the operator cannot show *why* they diverge.
- **Suggested remediation surface:** Migration adding `inputs_hash`, `price_references` (jsonb) and FK arrays to source rows on both `PLSnapshot` and `CashFlowBaselineSnapshot`. `pl_snapshot_service.create_pl_snapshot` and `cashflow_baseline_service.create_cashflow_baseline_snapshot` to compute the hash and capture provenance, mirroring `DealPNLSnapshot`'s validator.

---

### J-A3-09 — `cashflow_projection_service` mixes 3 valuation regimes per row, with `or 0` defaults — T1

- **Tier:** T1
- **Surface:** `backend/app/services/cashflow_projection_service.py:92-172`.
- **Constitutional clause violated:** §2.1 "One methodology per endpoint" + "no fallback pricing regimes" + §2.3 "Fallback regime silencioso — `or 0` em campo numérico de valor".
- **Evidence:**
  - `:92` `market_price = _get_market_price(session, "LME_AL", as_of_date)` — single LME aluminum price used for every commodity, every order, every contract in the loop. Same defect as `J-A3-01` but at the projection layer.
  - `:103` `price = Decimal(str(order.avg_entry_price or 0))` — `or 0` silently substitutes zero when `avg_entry_price` is null.
  - `:105-110` three-way regime: fixed-price → use entry; variable + market available → use market; variable + market None → use entry. The endpoint declares one shape but applies up to three methodologies in a single response.
  - `:129` `commodity="Al"` hard-coded for every order in the projection item.
  - `:154` `settle_dt = contract.settlement_date or as_of_date` — silently substitutes today as settlement date when the contract has none.
  - `:159` `fixed_price = Decimal(str(contract.fixed_price_value or 0))` — `or 0` again.
  - `:161-166` two-way regime for hedge contracts: market available → use market for variable leg; else → use fixed (collapses variable to fixed).
- **Reproduction:** Have a single row in `cash_settlement_prices` for `LME_ALU_CASH_SETTLEMENT_DAILY` and zero rows for any other symbol. Mix orders across copper / zinc / nickel / aluminum + hedge contracts in the database. `GET /cashflow/projection?as_of_date=…` returns a 200 mixing aluminum prices, fixed entry prices, and zero-defaulted nulls — all on the same response — with `price_source` strings of "fixed" / "market" / "entry" indicating the regime per row but not flagging the per-row commodity-collapse.
- **Suggested remediation surface:** Either (a) split into per-commodity `compute_cashflow_projection(commodity)` and require the caller to choose; or (b) loop per-commodity using `resolve_symbol(order.commodity)` / `resolve_symbol(contract.commodity)`, hard-fail at the row level when the price is unprovable for the row's commodity (no try/except, no `or 0`), and return a structured error per row rather than mixing methods. Either way: drop the hard-coded "LME_AL" and "Al" string; drop every `or 0`; drop `settle_dt = contract.settlement_date or as_of_date`.

---

### J-A3-10 — `cashflow_projection` is a 5th view not declared in governance §2.1 — T2

- **Tier:** T2
- **Surface:** `backend/app/services/cashflow_projection_service.py` (entire file); `backend/app/api/routes/cashflow.py:62-68`; `backend/app/schemas/cashflow.py` (`CashFlowProjectionResponse`).
- **Constitutional clause violated:** §2.1 "Views: Analytic / Baseline / Ledger / What-if". Projection is not on the list.
- **Evidence:** The codebase exposes a fifth view shape `CashFlowProjectionResponse` with its own service, schemas, and endpoint. It is forward-looking, non-persistent, and computed from contracts + orders + a (single) market price. It does not match the contract of any of the four constitutional views (Analytic is non-persistent over current state; this is non-persistent over future state).
- **Reproduction:** `GET /cashflow/projection?as_of_date=YYYY-MM-DD` returns a `CashFlowProjectionResponse`. There is no governance clause that authorises this view shape.
- **Suggested remediation surface:** Either (a) update governance.md §2.1 to declare Projection as a fifth (non-persistent, forward-looking) view with explicit invariants — including "one commodity per row, no method mixing"; or (b) remove the projection endpoint and fold its semantics into Analytic with explicit `as_of_date >= today` semantics. Should be addressed jointly with `J-A3-09` (the projection's data plane is already broken).

---

### J-A3-11 — Baseline = Analytic; Scenario fields collapse Analytic and Baseline into the same type — T2

- **Tier:** T2
- **Surface:**
  - `backend/app/services/cashflow_baseline_service.py:10`, `:31` — Baseline imports and reads from Analytic.
  - `backend/app/schemas/scenario.py:86-88` — `ScenarioCashflowSnapshot.analytic` and `.baseline` are both typed `CashFlowAnalyticResponse`.
  - `backend/app/services/scenario_whatif_service.py:518-520` — `ScenarioCashflowSnapshot(analytic=cashflow_analytic, baseline=cashflow_analytic)` (literally the same object in both fields).
- **Constitutional clause violated:** §2.1 "Quatro views explícitas e disjuntas" — the dispatch text §2.1 reads: "Cross-contamination (e.g., Baseline lendo de cache What-if; Ledger emitindo a partir de Analytic) é violação." Baseline reading from Analytic is the same class of violation.
- **Evidence:** Baseline creation is a thin wrapper that calls Analytic and stores its dump (`cashflow_baseline_service.py:31-50`). The scenario response declares two distinct fields but the schema and the runtime both treat them as the same shape. This blurs the boundary that governance is trying to keep stanche: Baseline must be its own canonical computation, not "yesterday's analytic frozen as JSON".
- **Reproduction:** Inspect the response of `POST /scenario/what-if/run`. The `cashflow_snapshot.analytic` and `cashflow_snapshot.baseline` payloads are byte-identical.
- **Suggested remediation surface:** Two parts. (a) Baseline service: `create_cashflow_baseline_snapshot` should compute its own derivation from contracts + ledger + price (not by calling `compute_cashflow_analytic`); the response/storage shape should differ from Analytic's. (b) `ScenarioCashflowSnapshot`: introduce a distinct `CashFlowBaselineProjection` schema (or remove the `baseline` field entirely from the scenario response — scenario is in-memory, so a derived "baseline" view in scenario has no canonical meaning).

---

### J-A3-12 — Ledger and Baseline are two parallel sources of truth with no reconciliation — T2

- **Tier:** T2
- **Surface:** `backend/app/services/cashflow_ledger_service.py` (event-driven; entry-per-leg) vs `backend/app/services/cashflow_baseline_service.py` (daily snapshot of analytic). No documented invariant connecting them.
- **Constitutional clause violated:** No specific clause; institutional invariant — "Ledger (accounting)" and "Baseline (persistent)" must reconcile or carry an explicit reason for divergence.
- **Evidence:** Ledger writes settlement-event-driven rows on contract settlement (`ingest_hedge_contract_settlement`). Baseline writes a daily rollup of Analytic (which is MTM-derived). On a settled contract: Baseline does not include settled rows (Analytic filters `status == active` in `cashflow_analytic_service.py:20`); Ledger has the actual settlement entries. There is no surface that says "for date `D`, sum(Ledger entries up to D) + Baseline as-of D = total cashflow". A reporting consumer must know to read both and reconcile manually.
- **Reproduction:** Settle a contract. Inspect Baseline-as-of-tomorrow vs Ledger entries — neither cross-references the other.
- **Suggested remediation surface:** Either (a) Baseline incorporates a snapshot of the Ledger sum-to-date and exposes it as a separate field `realised_to_date` on the schema; or (b) governance documents the disjoint-by-design relation explicitly and adds a reconciliation invariant test. (a) is the audit-friendlier option.

---

### J-A3-13 — `CashFlowLedgerEntry.amount` is taken verbatim from HTTP payload, not derived — T1

- **Tier:** T1
- **Surface:** `backend/app/api/routes/cashflow_ledger.py:27-48` (POST `/contracts/{contract_id}/settle`); `backend/app/services/cashflow_ledger_service.py:42-52` (`_build_expected_entry` uses `leg.amount` directly); `:160-173` (the entry is persisted with `amount=expected["amount"]`, where `expected["amount"]` came from the request).
- **Constitutional clause violated:** §2.1 "CashFlow is always derived, never manually input." The Ledger is the canonical settlement record; if its amounts are accepted from a `trader`-role HTTP body without a server-side derivation step, then the cashflow IS manually input.
- **Evidence:** `HedgeContractSettlementCreate.legs[].amount` is sent by the client. `_build_expected_entry` echoes it: `"amount": leg.amount`. The service performs idempotency / conflict checks against the same payload-supplied amount; it never recomputes the amount from `(contract, settlement_event, settlement_price)`. There is no equivalent of `compute_settlement_legs(contract_id, settlement_date, price_d1)` that the service uses to validate the payload's amount.
- **Reproduction:** As a `trader`, POST a settlement with arbitrary `legs[].amount` values — the persisted Ledger rows will carry exactly those values. Conflict is only triggered if the same `(source_event_id, leg_id)` is re-posted with a *different* arbitrary amount — i.e. the system enforces "stick with the first lie", not "match the derivation".
- **Reproduction (regulatory framing):** Audit asks "show me the price evidence behind this Ledger row" → there is no link from `CashFlowLedgerEntry` to a `CashSettlementPrice` row, no server-side derivation; only the contract status flips to `settled` (`cashflow_ledger_service.py:175`).
- **Suggested remediation surface:** `ingest_hedge_contract_settlement` should compute the expected legs from `(contract, settlement_date, price_lookup_service.get_cash_settlement_price_d1_with_provenance)` and reject any payload whose `legs[].amount` diverges from the computed value (422). Alternatively, the schema should carry a `settlement_price` triplet (value, source, settlement_date) and the service should compute amount from `(contract, qty, price)` on the server side, ignoring `legs[].amount` from the payload entirely.

---

### J-A3-14 — Scenario re-implements exposure aggregation without delegating to A1's exposure service — T3

- **Tier:** T3
- **Surface:** `backend/app/services/scenario_whatif_service.py:222-433` (`_compute_commercial_exposure`, `_compute_global_exposure`).
- **Constitutional clause violated:** Institutional invariant; not a hard-fail.
- **Evidence:** A1's `exposure_service` is not imported or consulted. The 200+ line in-process re-implementation is intentional (scenario must replay over `virtual_contracts` and `order_quantity_overrides`), but the duplication means a future change to the canonical exposure semantics (e.g. handling of `partially_settled`, classification rules, residual sign) will silently diverge from scenario.
- **Reproduction:** Modify A1's exposure rule (e.g. include `partially_settled` contracts in `total_hedge_long`); the live exposure response will change but `/scenario/what-if/run` will continue to use the old rule until the scenario service is updated separately.
- **Suggested remediation surface:** Refactor A1's exposure aggregation into a pure function that accepts in-memory lists `(orders_with_quantity, contracts_with_overrides_applied, virtual_contracts, linkages)` and a `calculation_timestamp`, then have both the live exposure path and the scenario path call it. Cross-phase A1 — flag for jury / future remediation; not a Stage-1 blocker.

---

### J-A3-15 — `pl_calculation_service` zeroes `unrealized_mtm` for `partially_settled` contracts — T1

- **Tier:** T1
- **Surface:** `backend/app/services/pl_calculation_service.py:78-82`.
- **Constitutional clause violated:** §2.3 "Fallback regime silencioso" + §2.1 "MTM uses D-1 settlement" — silently substituting `Decimal("0")` for the unrealized MTM tail of a partially settled contract is exactly the silent fallback the constitution forbids.
- **Evidence:**
  ```python
  if contract.status != HedgeContractStatus.active:
      unrealized_mtm = Decimal("0")
  else:
      mtm = compute_mtm_for_contract(db, contract_id=entity_id, as_of_date=period_end)
      unrealized_mtm = Decimal(mtm.mtm_value)
  ```
  But `compute_mtm_for_contract` (the function this branch is bypassing) ITSELF accepts both `active` and `partially_settled` (`mtm_contract_service.py:27-30`). The P&L service is more restrictive than the MTM service it calls. A `partially_settled` contract has a real, non-zero unrealized MTM on its remaining quantity; P&L silently reports zero.
- **Reproduction:** Settle one of two legs / partial quantity of a hedge contract (transitioning to `partially_settled`). Compute P&L for the period containing the partial settlement. `unrealized_mtm` is reported as `0`, contradicting `GET /mtm/hedge-contracts/{id}` for the same `as_of_date`.
- **Suggested remediation surface:** Replace the branch with `if contract.status not in (active, partially_settled): unrealized_mtm = Decimal("0")`. Better: hard-fail (422) for any other status — silent zeroing of unrealized P&L is not a meaningful default for `cancelled`, `settled`, etc. either. The status semantics should be enumerated explicitly.

---

## Anti-finding declarations (ruled out, with evidence)

- **No LLM in scenario.** `schemas/scenario.py:15-70` discriminator unions are strictly typed; no free-text field accepts a description. **Q6 PASS.**
- **No DB writes in scenario.** Confirmed via grep on `scenario_whatif_service.py` for `session\.(add|merge|commit|execute)` — zero matches. **Q6 PASS.**
- **No premium/discount in valuation.** Grep for `premium|discount|over_benchmark|spread` returns zero matches across `mtm_*`, `pl_*`, `cashflow_*`, `scenario_*`, `price_lookup_*`. The `premium_discount` column on `HedgeContract` is consumed only by A2 origination. **Q7 PASS.**
- **No multi-source price fallback regime.** Single canonical table `cash_settlement_prices`; `price_lookup_service.get_cash_settlement_price_d1_with_provenance` is the sole reader. **Q5 PASS for source canonicity** (lookback finding `J-A3-07` is a separate axis).
- **No hash-randomised iteration in valuation core.** All loops over query results sort by deterministic columns (`created_at`, `settlement_date`, `leg_id`); no `set(uuid…)` collapsing. **Q1/Q8 PASS for in-process aggregation determinism.**
- **No observable cache reuse in scenario or MTM.** No `@lru_cache`, `functools.cache`, `redis.Redis`, or in-process module-level price dict. **Q6 PASS for cache.**
- **Tenant isolation (Q8 last sub-bullet):** `tenant_id` does not exist anywhere in `backend/app/models/`. This is a system-wide design choice predating Phase A3, not an A3 regression. Marked `cross-phase-A5-risk` for the day multi-tenancy is introduced; not a finding here.
- **Cross-A4 dependencies:** `webhook_processor`, `whatsapp_*`, `llm_agent` are not imported by any A3 service. **Q10 PASS for cross-A4 isolation.**

---

## Cross-phase risk register

| Tag                       | Risk                                                                                        | Surface                                                          |
|---------------------------|----------------------------------------------------------------------------------------------|------------------------------------------------------------------|
| `cross-phase-A1-risk`     | Scenario exposure response casts every `Decimal` to `float(...)` 18×                         | `scenario_whatif_service.py:281-289`, `:414-428`                 |
| `cross-phase-A1-risk`     | A3 re-implements exposure aggregation in-process — diverges from A1 on rule changes          | `scenario_whatif_service.py:222-433` (also surfaced as `J-A3-14`)|
| `cross-phase-A2-risk`     | `cashflow_ledger_service` flips `contract.status` to `settled` outside the A2 lifecycle      | `cashflow_ledger_service.py:175`                                 |
| `cross-phase-A5-risk`     | `tenant_id` absent across A1/A2/A3 schema; aggregation cannot scope to tenant                | `backend/app/models/**`                                          |
| `cross-phase-A5-risk`     | Settlement endpoint is `trader`-only, no `auditor` read of payload reconstruction            | `routes/cashflow_ledger.py:43`                                   |

---

## End

Independence note: this report was produced without consulting Auditor B's output. Boa caça.
