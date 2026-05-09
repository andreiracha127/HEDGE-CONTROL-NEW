# Phase A3 - Stage 3 Jury Verdict - GPT 5.5

## §0 Posture (overall)

FAIL-WITH-CRITICAL-CAVEATS

Phase A3 is not fit for remediation closure. The happy path has several good properties: Decimal arithmetic is used in the core MTM/P&L paths, scenario runs do not persist results, and canonical price lookup hard-fails when no row exists in its configured window. The blocking problem is that several valuation surfaces still lose proof or silently substitute economic facts: order MTM and scenario virtual hedges can price non-aluminum exposure as LME aluminum, persisted MTM/P&L/Baseline snapshots lack reconstructible provenance, the Ledger accepts cashflow amounts from HTTP payload, and cashflow projection mixes fallback regimes. These are constitutional failures under `docs/governance.md:131-146`, `docs/governance.md:159-174`, and `docs/governance.md:208-217`.

## §1 Headline statistics

- Stage 1 raw: 14 findings (Auditor A - Opus)
- Stage 2 raw: 6 findings (Auditor B - Gemini)
- Convergent: 5
- Auditor-A-only validated: 9
- Auditor-B-only validated: 0
- Fresh-from-jury: 0
- Anti-findings: 0
- Subsumed: 0
- Cross-phase deferred: 2
- **Total adjudicated A3 findings: 14** (T1: 12 | T2: 2 | T3: 0 | T4: 0)

Prompt drift check: Stage 1 and Stage 2 dispatches differ only in auditor/model identity and stage header; the audit scope and agenda were materially consistent.

## §2 Convergent findings (both auditors caught)

### J-A3-01 - MTM snapshots lack reconstructible provenance

- Tier: T1
- Convergent (Opus: J-A3-05; Gemini: J-A3-01)
- Surface: `backend/app/models/mtm.py:19-37`; `backend/app/services/mtm_snapshot_service.py:50-59`, `:93-102`
- Constitutional clause: `docs/governance.md:159-174`, `docs/governance.md:208-217`
- Evidence: `MTMSnapshot` persists only object key, `mtm_value`, `price_d1`, `entry_price`, `quantity_mt`, `correlation_id`, and timestamps. The snapshot service constructs rows from computed MTM but does not persist `inputs_hash`, price source, actual settlement date, symbol, or commodity. A stored MTM number therefore cannot prove which market-data row was consumed.
- Suggested remediation surface: add provenance fields and canonical input hashing in `backend/app/models/mtm.py`, Alembic, `backend/app/services/mtm_snapshot_service.py`, and `backend/app/schemas/mtm.py`.

### J-A3-02 - Order MTM ignores `Order.commodity` and defaults to LME_AL

- Tier: T1
- Convergent (Opus: J-A3-01; Gemini: J-A3-06)
- Surface: `backend/app/services/mtm_order_service.py:18-26`, `:55-57`; `backend/app/services/cashflow_analytic_service.py:47-48`
- Constitutional clause: `docs/governance.md:131-146`, `docs/governance.md:159-174`
- Evidence: `compute_mtm_for_order()` declares `commodity: str = DEFAULT_COMMODITY`, where `DEFAULT_COMMODITY = "LME_AL"`, and resolves the price from that argument. The route and analytic cashflow caller do not pass a commodity, so non-aluminum variable orders are priced against aluminum.
- Suggested remediation surface: remove the commodity parameter/default and resolve from `order.commodity`; add focused coverage through MTM route and analytic cashflow.

### J-A3-03 - Ledger settlement amount is manually supplied by HTTP payload

- Tier: T1
- Convergent (Opus: J-A3-13; Gemini: J-A3-02)
- Surface: `backend/app/api/routes/cashflow_ledger.py:27-48`; `backend/app/services/cashflow_ledger_service.py:38-52`, `:159-171`
- Constitutional clause: `docs/governance.md:131-146`, `docs/governance.md:159-174`
- Evidence: `HedgeContractSettlementCreate.legs[].amount` reaches `_build_expected_entry()` as `leg.amount` and is persisted as `CashFlowLedgerEntry.amount`. Idempotency compares future submissions against the first payload value; it does not derive the amount from contract facts plus price evidence.
- Suggested remediation surface: make `ingest_hedge_contract_settlement()` derive or verify settlement legs server-side, with price provenance linked to ledger rows.

### J-A3-04 - Baseline cashflow reads Analytic and scenario labels Analytic as Baseline

- Tier: T1
- Convergent (Opus: J-A3-11; Gemini: J-A3-03)
- Surface: `backend/app/services/cashflow_baseline_service.py:10`, `:31-33`; `backend/app/schemas/scenario.py:86-88`; `backend/app/services/scenario_whatif_service.py:518-520`
- Constitutional clause: `docs/governance.md:131-146`
- Evidence: Baseline imports and calls `compute_cashflow_analytic()` before persisting the analytic dump. Scenario then exposes both `analytic` and `baseline` fields as `CashFlowAnalyticResponse` and assigns the same object to both. Worst-of severity applies because Gemini classified this as T1; the boundary collapse is real.
- Suggested remediation surface: decouple Baseline computation from Analytic and introduce a distinct scenario baseline contract or remove the misleading scenario baseline field.

### J-A3-05 - P&L output and snapshots drop price provenance

- Tier: T1
- Convergent (Opus: J-A3-08; Gemini: J-A3-05)
- Surface: `backend/app/services/pl_calculation_service.py:78-84`; `backend/app/models/pl.py:13-33`; `backend/app/schemas/pl.py:11-13`, `:23-32`
- Constitutional clause: `docs/governance.md:159-174`, `docs/governance.md:208-217`
- Evidence: `compute_pl()` returns only `realized_pl` and `unrealized_mtm`; `PLSnapshot` persists those two numbers plus identity/period metadata. There is no provenance triplet, `inputs_hash`, underlying MTM snapshot reference, or price-reference payload.
- Suggested remediation surface: extend `PLResultResponse`, `PLSnapshot`, snapshot creation, and migrations to carry input hash and market-data provenance.

## §3 Auditor-A-only validated

### J-A3-OPUS-01 - Scenario virtual hedge deltas hard-code commodity to LME_AL

- Tier: T1
- Auditor-A-only validated by jury via `backend/app/services/scenario_whatif_service.py:42`, `:175-186`; `backend/app/schemas/scenario.py:19-35`
- Constitutional clause: `docs/governance.md:149-156`, `docs/governance.md:159-174`
- Evidence: `AddUnlinkedHedgeContractDelta` has no `commodity` field, while `_apply_deltas()` creates `VirtualHedgeContract(commodity=DEFAULT_COMMODITY)`. The downstream MTM path resolves that implicit commodity.
- Suggested remediation surface: require a validated commodity in the delta schema and remove `DEFAULT_COMMODITY` from scenario pricing.

### J-A3-OPUS-02 - Cashflow projection swallows price hard-fails

- Tier: T1
- Auditor-A-only validated by jury via `backend/app/services/cashflow_projection_service.py:34-55`
- Constitutional clause: `docs/governance.md:131-146`, `docs/governance.md:159-174`
- Evidence: `_get_market_price()` wraps lookup in `except Exception`, logs at debug, and returns `None`. That catches `HTTPException(424)` from `get_cash_settlement_price_d1()` and causes fallback behavior instead of hard-fail.
- Suggested remediation surface: propagate price lookup failure and map it explicitly at the route boundary.

### J-A3-OPUS-03 - Canonical cash settlement price is stored as Float

- Tier: T1
- Auditor-A-only validated by jury via `backend/app/models/market_data.py:20-23`; `backend/app/services/price_lookup_service.py:179-184`
- Constitutional clause: `docs/governance.md:159-174`, `docs/governance.md:208-217`
- Evidence: `CashSettlementPrice.price_usd` is `Float`; lookup then freezes `Decimal(str(row.price_usd))`. The conversion does not undo storage-level binary float drift at the canonical price source.
- Suggested remediation surface: migrate `price_usd` to `Numeric`, update ingestion, and add regression coverage around exact decimal preservation.

### J-A3-OPUS-04 - Price lookup uses a 5-calendar-day lookback without business-calendar proof

- Tier: T1
- Auditor-A-only validated by jury via `backend/app/services/price_lookup_service.py:138-184`
- Constitutional clause: `docs/governance.md:131-146`, `docs/governance.md:159-174`
- Evidence: lookup computes `price_date = as_of_date - timedelta(days=1)` and accepts the latest row between that date and five calendar days earlier. This can silently substitute an older business date as "D-1"; although `PriceQuote` returns the actual `settlement_date`, most A3 callers use the thin Decimal wrapper and lose that evidence.
- Suggested remediation surface: use a per-symbol business calendar or require the exact previous business-day row, and force callers to retain actual settlement-date provenance.

### J-A3-OPUS-05 - CashFlowBaselineSnapshot lacks input hash and provenance

- Tier: T1
- Auditor-A-only validated by jury via `backend/app/models/cashflow.py:24-42`; `backend/app/services/cashflow_baseline_service.py:47-52`
- Constitutional clause: `docs/governance.md:159-174`, `docs/governance.md:208-217`
- Evidence: Baseline persists JSON `snapshot_data`, total, and `correlation_id`, but no canonical `inputs_hash`, source row links, or price references. Conflict detection compares values, but reconstruction evidence is absent.
- Suggested remediation surface: add baseline hash/provenance fields and compute them from a canonical payload plus source references.

### J-A3-OPUS-06 - Cashflow projection mixes valuation regimes and zero defaults

- Tier: T1
- Auditor-A-only validated by jury via `backend/app/services/cashflow_projection_service.py:87-210`
- Constitutional clause: `docs/governance.md:131-146`, `docs/governance.md:159-174`
- Evidence: the endpoint computes one global aluminum market price, uses `avg_entry_price or 0` for fixed orders, falls back to entry price when market price is unavailable, hard-codes order `commodity="Al"`, substitutes `contract.settlement_date or as_of_date`, and uses `fixed_price_value or 0`.
- Suggested remediation surface: price each row by its own commodity, reject missing required economics, and remove all `or 0`/entry fallback regimes.

### J-A3-OPUS-07 - Cashflow projection is a fifth cashflow view not declared by governance

- Tier: T2
- Auditor-A-only validated by jury via `backend/app/api/routes/cashflow.py:62-68`; `backend/app/services/cashflow_projection_service.py:1-11`
- Constitutional clause: `docs/governance.md:131-146`
- Evidence: governance lists Analytic, Baseline, Ledger, and What-if. The code exposes `/cashflow/projection` as its own forward-looking response shape and service. This may be a useful product feature, but its invariants are not constitutionally defined.
- Suggested remediation surface: either define Projection as an allowed view with strict invariants or fold/remove it during cashflow remediation.

### J-A3-OPUS-08 - Ledger and Baseline lack a reconciliation invariant

- Tier: T2
- Auditor-A-only validated by jury via `backend/app/services/cashflow_ledger_service.py:76-181`; `backend/app/services/cashflow_baseline_service.py:22-56`; `backend/app/services/cashflow_analytic_service.py:18-25`
- Constitutional clause: `docs/governance.md:131-146`, `docs/governance.md:208-217`
- Evidence: Ledger is settlement-event-driven; Baseline is a persisted analytic rollup. There is no invariant or route-level contract that reconciles realized ledger flows with baseline exposure/cashflow snapshots, and analytic excludes non-active contracts.
- Suggested remediation surface: define a reconciliation contract or include ledger realized-to-date evidence in Baseline.

### J-A3-OPUS-09 - P&L zeroes unrealized MTM for partially settled contracts

- Tier: T1
- Auditor-A-only validated by jury via `backend/app/services/pl_calculation_service.py:74-84`; `backend/app/services/mtm_contract_service.py:27-43`
- Constitutional clause: `docs/governance.md:131-146`, `docs/governance.md:159-174`
- Evidence: `compute_pl()` sets `unrealized_mtm = Decimal("0")` for every status other than `active`, while `compute_mtm_for_contract()` explicitly supports both `active` and `partially_settled`. The P&L path silently drops the remaining MTM tail for partially settled contracts.
- Suggested remediation surface: align P&L status semantics with MTM and hard-fail or explicitly handle unsupported statuses.

## §4 Auditor-B-only validated

None. Gemini's only non-convergent code claim is real in `deal_engine`, but the surface is outside the Phase A3 service set and is deferred in §8 rather than counted as an A3 finding.

## §5 Fresh-from-jury

None. The jury did not identify a new A3 issue not already surfaced by Opus or Gemini.

## §6 Anti-findings

None. No auditor finding was rejected as factually false after code verification. Positive non-issues were also verified: scenario has no DB write/cache path (`rg` over `scenario_whatif_service.py` found no `session/db.add|commit|execute`), premium/discount is not consumed by A3 valuation services, and A3 services do not import `webhook_processor`, `whatsapp_*`, or `llm_agent`.

## §7 Subsumed

None. Several findings share files, especially `cashflow_projection_service.py`, but they are distinct constitutional violations: suppressing hard-fails, mixing methodologies, zero defaults, hard-coded commodity labels, and unauthorized view shape are not the same defect.

## §8 Cross-phase deferred

### X-A3-J-01 - Deal Engine repair path reuses prior snapshot price references

- Defer to: Phase A1 / deal P&L follow-up
- A3 surface: Gemini J-A3-04 cites A3 price-hard-fail policy, but the verified code is `backend/app/services/deal_engine.py:657-703`
- Why deferred: `deal_engine.py` and `DealPNLSnapshot` are the pre-existing deal-level P&L path, not one of the Phase A3 target services named in the Stage 3 prompt. The code does intentionally search reusable snapshots when all live price quotes are unavailable, then recomputes the hash against persisted price references before returning.
- Future audit must verify: whether total price unavailability may legitimately reuse a sealed snapshot, or whether `PriceReferenceUnprovable` must always propagate even when a stored hash matches.

### X-A3-J-02 - Scenario duplicates A1 exposure aggregation logic

- Defer to: Phase A1/A3 integration remediation
- A3 surface: Opus J-A3-14 cites `backend/app/services/scenario_whatif_service.py:222-433`
- Why deferred: scenario must run over virtual deltas, so the duplication is not automatically a valuation hard-fail. The durable risk is cross-phase drift from A1 exposure semantics.
- Future audit must verify: extraction of shared pure exposure-calculation primitives usable by both live exposure and scenario what-if paths.

## §9 Self-bias confession

I noticed two bias risks. First, Gemini's `deal_engine` claim was tempting to count as a B-only A3 validation because the cited code exists and the failure mode sounds like the same no-fallback rule; after checking the Stage 3 scope and the file's deal-P&L ownership, I treated it as cross-phase instead. Second, Opus was much broader and more precise in code citations, which made its additional findings easier to trust; I still verified each major surface directly before carrying them into the verdict.

## §10 Remediation plan recommendation

- Wave 1 (foundational price/provenance, no upstream deps): PR-A3-1 closes J-A3-01, J-A3-03, J-A3-05, J-A3-OPUS-03, J-A3-OPUS-04, J-A3-OPUS-05. This wave should introduce exact price storage, provenance-returning lookup contracts, MTM/P&L/Baseline hashes, and ledger source evidence.
- Wave 2 (commodity correctness): PR-A3-2 closes J-A3-02 and J-A3-OPUS-01. Remove default commodity behavior from MTM order and scenario virtual hedge deltas, then add cross-commodity tests for copper/zinc/nickel orders and scenario contracts.
- Wave 3 (cashflow projection hardening): PR-A3-3 closes J-A3-OPUS-02, J-A3-OPUS-06, and J-A3-OPUS-07. Decide whether Projection is constitutional; if kept, enforce per-row commodity pricing, no silent entry fallback, and no `or 0` economics.
- Wave 4 (cashflow boundaries and reconciliation): PR-A3-4 closes J-A3-04 and J-A3-OPUS-08. Split Baseline from Analytic, fix scenario's duplicate Analytic/Baseline response, and define Ledger/Baseline reconciliation evidence.
- Wave 5 (P&L lifecycle semantics): PR-A3-5 closes J-A3-OPUS-09. Align partially-settled contract handling with MTM and reject unsupported statuses explicitly.
- Cross-phase: X-A3-J-01 goes to Phase A1/deal P&L follow-up; X-A3-J-02 goes to A1/A3 shared exposure primitives.
