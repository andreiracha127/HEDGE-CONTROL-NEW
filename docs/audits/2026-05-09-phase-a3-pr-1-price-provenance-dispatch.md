# Phase A3 — PR #A3-1 Dispatch — Foundational Price/Provenance

**Wave:** 1 (foundational; prerequisite for Waves 2–5)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-09
**Findings covered:** J-A3-01 (T1, MTM provenance) + J-A3-03 (T1, Ledger HTTP-payload amount) + J-A3-05 (T1, P&L provenance) + J-A3-OPUS-03 (T1, Float storage) + J-A3-OPUS-04 (T1, business calendar) + J-A3-OPUS-05 (T1, Baseline provenance)
**Branch name:** `audit-a3/price-provenance`
**Base:** `main` (currently `659e5ba9d`, post-PR #39 audit-cycle backfill)

---

## 0. Refresh notes (read first)

**Codex P2 absorbed against commit `61446f204` — fail-closed on calendar coverage gap.** Round-11 §3.6 prescribed `_LME_HOLIDAYS: frozenset[date]` as a single-year static set covering only 2026. Codex caught: a 2027 lookup walking `_prior_business_day` would silently treat 2027 LME holidays as ordinary business days (they're not in the 2026-only set), querying the wrong date as "the prior business day". Worse: the lookup might return a valid row for that date (a Friday non-holiday in 2027 that happens to follow a 2027 LME holiday) and persist the wrong proof on MTM/P&L snapshots. Operator-maintained static maps need explicit coverage validation — silent degradation when the calendar lapses violates the no-fallback rule. **Fix:** §3.6 calendar refactored to `_LME_HOLIDAYS_BY_YEAR: dict[int, frozenset[date]]`; `_market_calendar_for_symbol(symbol, year)` raises `PriceReferenceUnprovable` for years outside the keyed coverage; `_prior_business_day(price_date, calendar_for_year)` consumes a year-aware callable that fail-closes when the cursor walks into uncovered territory. §10 new DO NOT codifies "year-keyed calendar with fail-closed coverage check, NOT single-year frozenset". §6 acceptance updated. §7 adds two regression tests (year-outside-coverage + cursor-crosses-year-boundary).

**Two Codex catches absorbed against commit `7a62ea0b0` (1 P1 + 1 P2):**

1. **Key `_CANONICAL_SOURCE_BY_SYMBOL` by RESOLVED long-form settlement symbols (P1).** Round-10 §3.6 introduced `_CANONICAL_SOURCE_BY_SYMBOL` keyed by short codes (`LME_AL`, `LME_CU`, etc.). Codex caught: the lookup chain is `resolve_symbol(contract.commodity)` → LONG form (`LME_ALU_CASH_SETTLEMENT_DAILY`) → `_canonical_source_for_symbol(long_form)`. The short-code-keyed map raises `PriceReferenceUnprovable` for every legitimate lookup. Plus PB/SN (lead/tin) commodities supported by `COMMODITY_SYMBOL_MAP` were missing entirely. **Fix:** §3.6 map rewritten with all SIX supported commodities (AL/CU/ZN/NI/PB/SN) keyed by their resolved long-form symbols. §10 new DO NOT codifies the keying rule + COMMODITY_SYMBOL_MAP cross-reference. §7 adds two tests (six-commodity coverage + end-to-end short-code-input regression). **Self-blame:** classic factual cross-check miss — I prescribed short-code keys without verifying what `resolve_symbol` actually returns. Sub-rule 10 (Serena-verify identifiers) didn't catch this because the keys are NEW values, not existing identifiers; the rule expands to: **when a NEW lookup key is prescribed, verify the lookup chain end-to-end via Serena (caller → producer → consumer) — not just one endpoint.**

2. **Limit ledger provenance acceptance to PRICED legs only (P2).** §6 acceptance round-3/5 said `_build_expected_entry` populates `price_source + price_symbol + price_settlement_date` on every constructed dict. Round-7 then introduced the FIXED-leg-NULL design in §3.7. Sibling-bullet inconsistency: the §6 acceptance bullet still required population on every dict, contradicting §3.7. Per the all-four-or-NULL CHECK, the FIXED leg's NULL provenance is admissible — but the §6 wording would either force fabricated provenance or fail the CHECK. **Fix:** §6 bullet rewritten to scope population to FLOAT legs explicitly; FIXED legs construct all-four-NULL dicts. **Self-blame:** sibling-bullet sweep miss again (round 9 had analogous; round 11 had analogous; this is the third instance) — sub-rule 17 (sibling-bullet sweep within single section) was not applied to the §6 acceptance list when round-7 changed §3.7's design. The rule must propagate retroactively: **when a §3.X redesign establishes a NULL/non-NULL boundary on a schema, every §6 acceptance bullet referencing that schema's fields must be re-read and the boundary explicitly enumerated**.

**Two Codex catches absorbed against commit `1b13e66c0` (1 P1 + 1 P2):**

1. **Quantize derived ledger amounts before comparison and persistence (P1).** Round-7 §3.7 derived `amount = quantity × price` directly. Codex caught: `quantity_mt` and `price_value` each carry their own decimal scales; their unrounded product can have > 6 fractional digits. `CashFlowLedgerEntry.amount` is `Numeric(18, 6)` — DB rounds on insert. Idempotent re-ingest then recomputes the unrounded product; `_ledger_entry_matches` compares exact Decimal values → false 409 conflict on legitimately identical re-ingest. Same problem for the payload-vs-derived 422 check: an operator-supplied amount rounded to 6 digits would mismatch the unrounded derived value. **Fix:** §3.7 sketch now `quantize`s `derived_amount` to `Decimal("0.000001")` with `ROUND_HALF_EVEN` BEFORE both the 422 comparison and persistence. §10 new DO NOT codifies the rule. §7 adds two regression tests. §6 gains a quantize criterion.

2. **Use in-repo static calendar, not `holidays` package (P2).** Round-2 §3.6 prescribed `_market_calendar_for_symbol(symbol) -> holidays.HolidayBase`. Codex verified `backend/requirements.txt` does NOT have `holidays` / `python-holidays`. Direct `import holidays` in the new helper would raise `ModuleNotFoundError` on every backend startup and CI test run. **Fix:** §3.6 paragraph rewritten to prescribe an in-repo `_LME_HOLIDAYS: frozenset[date]` static map. `_prior_business_day` signature updated to `(price_date: date, calendar: frozenset[date])`. Operator-auditable, no new dependency, year-by-year updates rolled in via small follow-up PRs. §10 new DO NOT forbids `import holidays`. §7 adds an explicit regression test asserting the absence of the `holidays` import.

**Two Codex catches absorbed against commit `18b38b159` (1 P1 + 1 P2):**

1. **Guard NULL ledger `price_value` before normalizing (P1).** Round-6 added `_normalize_decimal(entry.price_value) == _normalize_decimal(expected["price_value"])` to `_ledger_entry_matches`. Round-7 then introduced FIXED-leg-NULL-provenance design (§3.7). Codex caught: when re-ingesting a settlement whose FIXED leg has `price_value=None`, the comparator calls `_normalize_decimal(None)` which becomes `Decimal('None')` and raises `decimal.InvalidOperation` — every FIXED-leg idempotency check returns 500. **Fix:** added `_decimal_or_none_eq(a, b)` helper (None-safe Decimal equality); `_ledger_entry_matches` uses it for `price_value`. String + date columns compare safely with `==` (None == None is True). §10 new DO NOT codifies the rule. §7 adds `test_ledger_idempotency_no_op_on_fixed_leg_with_null_provenance`. **Self-blame:** classic cross-round inconsistency — round-6 added the comparator field assuming non-NULL; round-7 added the NULL design without revisiting round-6's comparator. The propagation rule from round 7 ("when a quadruple is established as canonical provenance shape, every parallel surface must mirror it") expands to: **when a NULL-able shape is introduced, every comparator that touches the affected fields must be re-audited for NULL-safety**.

2. **Select a deterministic price source (P2).** §3.6 round-2 changed lookup to exact-date query but filtered only `(symbol, settlement_date)`. Codex caught: `cash_settlement_prices` unique constraint is `(source, symbol, settlement_date)` (verified at `models/market_data.py:13`). Multiple sources can publish for the same `(symbol, date)`; `.first()` without source filter returns whichever row the DB orders first → MTM / P&L provenance non-deterministic across environments and over time as new sources are onboarded. **Fix:** new `_canonical_source_for_symbol(symbol)` helper with `_CANONICAL_SOURCE_BY_SYMBOL` mapping (initial: LME_* → westmetall); raises `PriceReferenceUnprovable` for unknown commodities. Lookup query adds `CashSettlementPrice.source == canonical_source` — three-column filter matches the unique constraint, so `.first()` is deterministic by construction. §6 gains three acceptance criteria. §7 adds three tests including a multi-source fixture regression. §10 new DO NOT codifies the rule.

**Two Codex P1 absorbed against commit `33b0f66cb`:**

1. **Require `PriceReferenceEntry` only for PRICED ledger rows (P1).** §6 acceptance round-7 said "≥1 PriceReferenceEntry per ledger entry consumed in realized_pl". Codex caught: `compute_pl` consumes BOTH FIXED and FLOAT rows; FIXED rows deliberately have NULL provenance per §3.7 (their economics come from `contract.fixed_price_value`, not a market lookup). Requiring a reference for FIXED rows forces either fabricated provenance or makes the acceptance test impossible. **Fix:** §6 criterion now says "per **priced** ledger entry (i.e., row with non-NULL price provenance — FLOAT legs only)"; FIXED legs are explicitly excluded from the count. §7 test renamed to `test_compute_pl_settled_period_with_priced_rows_does_not_emit_empty_price_references` + new `test_compute_pl_collects_only_priced_ledger_entries_into_price_references` regressing the FIXED-vs-FLOAT boundary.

2. **Dedupe P&L `price_references` on the full quadruple including `value` (P1).** §6 acceptance line 747 said "one entry per distinct `(symbol, source, settlement_date)`". Codex caught: §3.3 step 2 (round-5) and §6 line 741 already dedupe on the four-key `(symbol, source, settlement_date, value)` — line 747 was a stale three-key criterion that contradicts the round-7 in-place-correction invariant. Triple-only dedupe collapses two distinct values under the same `(source, symbol, date)` (e.g., a corrected canonical price republished mid-period) — exactly the silent-drift hole that the round-6 ledger comparator extension closed. **Fix:** §6 line 747 updated to four-key dedupe with explicit reference to the in-place-correction scenario. **Self-blame:** another stale-criterion-after-redesign sweep miss — round-5 promoted the dedupe key to four fields in §3.3 + §6 line 741 but missed §6 line 747 (sibling acceptance criterion in the same numbered list). The 8-section sweep checklist must include "all entries within a single section that reference the same identifier or shape — not just one per section".

**Codex P2 absorbed against commit `9db30a848` — derive FLOAT direction from `variable_leg_side`, not "opposite of fixed".** Round-7 §3.7 derived FLOAT direction as the inverse of FIXED direction (assumption: contracts have inverse fixed/variable sides). Codex caught: the DB CHECK constraint at `models/contracts.py:78-80` only ties `classification` to `fixed_leg_side`; there is NO invariant forcing `variable_leg_side != fixed_leg_side`. A contract with both sides equal is degenerate but admissible at the schema layer; deriving FLOAT direction from "opposite of fixed" would silently rewrite the stored variable side and let an inconsistent contract generate realized P&L from a fabricated direction. **Fix:** §3.7 sketch now reads each leg's direction from its OWN stored side field — FIXED from `contract.fixed_leg_side`, FLOAT from `contract.variable_leg_side`. A `_direction_from_side(HedgeLegSide) -> LedgerDirection` helper centralizes the side→direction mapping. §10 new DO NOT codifies "do NOT derive FLOAT direction as opposite of fixed". §7 adds `test_settlement_float_direction_derived_from_variable_leg_side_not_fixed_inverse` regressing the degenerate-contract scenario. **Self-blame:** another factual cross-check miss — I assumed inverse symmetry between the two side fields without consulting the DB CHECK constraints. The 10th sweep-check sub-rule (Serena-verify identifier definitions) should expand to "Serena-verify schema invariants too — DB-level CHECK constraints document what the codebase actually enforces, vs what the developer assumes is enforced".

**Two Codex P1 absorbed against commit `2df6bcb23`:**

1. **Derive ledger entries PER LEG, not twice from net (P1, doubling).** Round-5 §3.7 sketch derived `gross = qty × (settlement − fixed)` and applied it once. Codex caught: `HedgeContractSettlementCreate` validates exactly 2 legs {FIXED, FLOAT}; `_build_expected_entry` is invoked ONCE PER LEG. Round-5's formula, applied to BOTH legs, persists two IN rows with the SAME net amount; `compute_pl` adds both → realized_pl is DOUBLED (qty=10/fixed=100/settlement=110 yields `+200` instead of correct `+100`). **Fix:** §3.7 fully redesigned with per-leg derivation. FIXED leg: `amount = qty × contract.fixed_price_value`; provenance NULL (no lookup). FLOAT leg: `amount = qty × settlement_quote.value`; provenance quadruple populated. Direction per leg from `contract.fixed_leg_side` (buy → FIXED OUT, FLOAT IN; sell → opposite). Per-leg payload-vs-derived verification with two distinct 422 paths (direction + amount). §6 gains four matching acceptance criteria + the long/short net P&L verification. §7 adds five tests including `test_settlement_compute_pl_realized_long_side` regressing the doubling bug. §10 new DO NOT codifies "do NOT derive both legs from a single net formula".

2. **Persist baseline `price_value` with row provenance (P1, parity with ledger).** Round-4's §3.4 expansion added three provenance fields to `CashFlowItem` (source, symbol, settlement_date) but NOT `price_value`. Codex caught: a canonical `cash_settlement_prices` row corrected in-place under the same `(source, symbol, date)` key cannot be detected as drift in baseline (the JSON shape and hash inputs both miss the value). Round-7 already added `price_value` to ledger rows for exactly this scenario; baseline must reach parity. **Fix:** `CashFlowItem` extended to FOUR optional provenance fields (full quadruple). `compute_cashflow_analytic` populates all four directly from `PriceQuote`. Snapshot JSON shape gains `price_value`. §6 acceptance updated to "FOUR fields"; §7 adds `test_cashflow_baseline_inputs_hash_drifts_when_canonical_price_corrected_in_place` regression.

**Self-blame (round 7 catch 2)**: same disciplinary class as the comparator-sweep-miss pattern. Round 5 added `price_value` to ledger rows; the parallel baseline path (§3.4) was NOT updated. Round-by-round propagation discipline must include: **when a quadruple is established as the canonical provenance shape on ONE persistence surface (ledger), every parallel persistence surface (baseline rows, future cashflow projection rows, future MTM-snapshot extensions) must immediately mirror it — institutional symmetry across persistence layers.**

**Codex P1 absorbed against commit `0f82d24ca` — `price_value` in idempotency.** Round-5 added `price_value` to the ledger entry schema (full quadruple per row) AND to `_build_expected_entry`'s constructed dict, but the `_ledger_entry_matches` equality sketch still compared only `source/symbol/date`. Codex caught: when a canonical settlement row is corrected in-place (same `(source, symbol, settlement_date)` but a new `value` — e.g., westmetall republishes with a corrected price), re-ingest of the same `source_event_id` would silently no-op because the comparator missed the divergent `value`. Realized P&L evidence stays tied to the OLD value; the snapshot becomes ambiguous. **Fix:** `_ledger_entry_matches` extended to include `_normalize_decimal(entry.price_value) == _normalize_decimal(expected["price_value"])`. §6 acceptance enumerates all four provenance fields explicitly and adds the in-place-correction scenario as a criterion. §7 adds `test_ledger_entry_matches_detects_price_value_only_divergence`.

**Self-blame:** this is the SAME 4-offense cross-section sweep miss pattern from PR-5 cycle, now hitting PR-A3-1 round 6. Round-5 expanded the schema (added `price_value` column) and the dict construction (`_build_expected_entry`'s returned dict) but did NOT update the comparator. Mechanically identical to round-3's "missing `price_symbol` in `_ledger_entry_matches` after schema added it". Two consecutive sweep misses on the SAME function `_ledger_entry_matches` proves the discipline must include: **every time a column is added to a model that has an idempotency / equality / conflict comparator function, the comparator MUST be edited in the same commit. Comparators are not optional cross-section targets — they are load-bearing institutional defense against silent-drift no-ops.**

**Three Codex catches absorbed against commit `a9e6780ca` (2 P1 + 1 P2):**

1. **Store ledger amounts UNSIGNED — direction carries the sign (P1).** §3.7 round-4 sketch made `amount` signed (`sign * quantity * (settlement_quote.value - fixed_price)`). Codex caught: `compute_pl` (`pl_calculation_service.py:16-83`) applies sign by direction (IN adds, OUT subtracts) when reading `CashFlowLedgerEntry`. For an OUT leg with `gross > 0`, the sketch persists negative amount; downstream P&L applies `−1 × negative = positive`, flipping the realized P&L contribution. **Fix:** §3.7 sketch now derives `direction` from `gross` sign and persists `amount = abs(gross)`. §10 DO NOT codifies the magnitude-vs-sign convention. §6 gains acceptance criteria for non-negative amount, derived direction, and 422 on payload-direction mismatch. §7 adds two tests pinning the convention.

2. **Include ledger price provenance in P&L `price_references` for settled periods (P1).** §3.3 round-3 directive limited `price_references` collection to PriceQuotes consumed directly by `compute_pl` (i.e., the unrealized-MTM lookup). Codex caught: `compute_pl` reads `CashFlowLedgerEntry` rows for `realized_pl`; after §3.7 those rows carry provenance. A settled-only period emits realized_pl populated but an empty `price_references` list — J-A3-05 stays open at the snapshot layer. **Fix:** §3.7 adds `price_value` column to ledger entries (full quadruple per row, self-contained provenance). §3.3 step 2 expanded with two-path collection (realized via ledger rows + unrealized via lookup), deterministic order, dedupe rule. §6 gains two acceptance criteria. §7 adds three tests including a settled-only-period regression. §10 new DO NOT codifies "ledger row provenance MUST flow into P&L references".

3. **Reflect Analytic provenance plumbing in §3.1 Scope IN (P2).** §3.4 round-4 expansion added Analytic provenance plumbing as in-scope, but §3.1 still listed `cashflow_analytic_service.py` as out of scope. An executor reading §3.1 first could skip the only producer of baseline row provenance. **Fix:** §3.1 entry for `cashflow_analytic_service.py` rewritten to call out scope-local provenance plumbing IS in scope (with explicit Wave 3 hardening boundary). **Self-blame:** classic 8-section sweep miss across §3 sub-sections — round-4 fix updated §3.4 + §10 but skipped §3.1's bullet on the same identifier. The 4-offense pattern from PR-5 strikes again at round 5.

**Two Codex catches absorbed against commit `ecbc5b6c9` (1 P1 + 1 P2):**

1. **Do not defer the only baseline provenance path (P1).** §3.4 round-3 said baseline `inputs_hash` only, with per-row provenance "inside snapshot_data" — but §10 forbade modifying `cashflow_analytic_service` "beyond the lookup-contract migration", AND `CashFlowItem` schema at `schemas/cashflow.py:33-38` had no provenance fields. The only path from price lookup → baseline `snapshot_data` is via `compute_cashflow_analytic` building `CashFlowItem`s. Codex caught: with §10 forbidding the path and `CashFlowItem` not carrying the data, the J-A3-OPUS-05 finding **remains open** despite the §6 acceptance claiming closure. **Fix:** §3.4 expanded with explicit three-step plumbing (`CashFlowItem` schema extension + `compute_cashflow_analytic` population + `cashflow_baseline_service` json-mode persistence). §10 DO NOT relaxed for Analytic provenance plumbing only — Wave 3 hardening of Analytic (OPUS-02/06/07) remains out of scope. §6 acceptance gains three matching criteria; §7 adds four matching tests across `test_cashflow_baseline_service.py` and (new) `test_cashflow_analytic_service.py`. **Self-blame:** this is the `feedback_dispatch_self_consistency` rule "An 'out of scope' forbid can deny the executor evidence they need" — exact pattern, fourth time it appears in the cycle. The §10 must always be paired against §3 directives that describe data flow; if §3 says X persists Y, every upstream service that produces Y must be in scope.

2. **Use the existing ledger direction enum values (P2).** §3.7 sketch said `LedgerDirection.credit`. Codex caught: `LedgerDirection` at `schemas/cashflow.py:68-70` has `in_ = "IN"` and `out = "OUT"` — no `.credit` member. Copying the sketch would `AttributeError` before any settlement could derive. **Fix:** §3.7 sketch now reads `sign = +1 if leg.direction == LedgerDirection.in_ else -1` with a comment explaining the institutional accounting convention (IN=credit, OUT=debit). **Self-blame:** another concrete-code-example sweep miss + missing factual cross-check. The 9th sweep-check item I added in round 3 ("every concrete code example must enumerate the new field") would have caught this — except this is a different shape: not "missing field" but "wrong identifier referencing a fictitious enum member". The discipline expands: **every identifier (enum member, attribute, method) in a concrete code template must be Serena-verified against the actual definition before sealing.**

**Three Codex catches absorbed against commit `148e31d60` (1 P1 + 2 P2):**

1. **Serialize P&L price references with `mode="json"` BEFORE persistence and hash construction (P1).** §3.3 step 3 said `[entry.model_dump() for entry in result.price_references]`. Codex caught: in Pydantic v2, plain `model_dump()` keeps Python `date` and `Decimal` objects; SQLAlchemy's JSON/JSONB serializer rejects them at insert time. AND: hashing the plain-mode dump while persisting the json-mode dump produces a hash that cannot be reproduced from the persisted shape — silent drift on replay. **Fix:** §3.3 step 3 now uses `model_dump(mode="json")` for BOTH persistence and `inputs_hash` construction explicitly, with a "hash and persisted shape MUST match by construction" callout.

2. **Resolve ledger price symbol from `contract.commodity` via `resolve_symbol(...)` (P2).** §3.7 sketch called `contract.commodity_symbol`. Codex caught: `HedgeContract` exposes `commodity` (not `commodity_symbol`) at `models/contracts.py:92`; pricing services use `resolve_symbol(contract.commodity)` per the existing convention. Copying the bad attribute name into `_build_expected_entry` would `AttributeError` before any settlement could derive. **Fix:** §3.7 now reads `resolve_symbol(contract.commodity)` with an explanatory comment.

3. **Wrap CHECK creations in `batch_alter_table` for SQLite portability (P2).** §3.8 used plain `op.create_check_constraint(...)`. Codex caught: SQLite cannot ALTER an existing TABLE to add a CHECK via plain ALTER TABLE; existing migration 035 uses `batch_alter_table(...).create_check_constraint(...)` for that dialect. The migration roundtrip on SQLite would fail. **Fix:** §3.8 now wraps every `add_column` + `create_check_constraint` pair in `op.batch_alter_table(...)` (transparent passthrough on Postgres, copy-and-move on SQLite). Downgrade also wrapped. Cross-section: §3.8 NOTE block explains the dialect mechanics.

**Two Codex P1 absorbed against commit `84292ec9c`:**

1. **Persist P&L provenance in the SNAPSHOT service, not the calculation service.** The first round-1 §3.3 directive said `compute_pl` collects + persists. Codex caught: `compute_pl` (in `pl_calculation_service.py`) only returns `PLResultResponse`; `PLSnapshot` rows are created and conflict-checked in a SEPARATE service `pl_snapshot_service.py:create_pl_snapshot`. Without explicit two-service propagation, the executor would persist nothing and J-A3-05 stays open. **Fix:** §3.3 now prescribes a four-step propagation chain: (1) extend `PLResultResponse` with structured `price_references: list[PriceReferenceEntry]`; (2) `compute_pl` populates the field; (3) `create_pl_snapshot` reads from the response and persists; (4) idempotency / conflict logic in `create_pl_snapshot` compares the new fields and raises 409 on divergence. §6/§7 list four matching acceptance criteria + six matching test cases.

2. **Include `price_symbol` in ledger-entry construction AND idempotency.** The §3.7 implementation sketch from round-1 still populated only `price_source + price_settlement_date` in `_build_expected_entry`'s returned dict — even though round-1's catch had added `price_symbol` to the column set + CHECK constraint. With the all-or-none CHECK, persisting the dict would violate; if the CHECK were relaxed, the ledger would remain ambiguous across multi-commodity-same-source-same-date (the same shape that the §0 round-1 first catch was meant to prevent). **Fix:** §3.7 example now includes `price_symbol=settlement_quote.symbol` in the dict and updates `_ledger_entry_matches` to include all three provenance fields in the equality check; §6 acceptance gains a criterion for `_build_expected_entry`'s symbol population and a criterion for idempotency-with-divergent-provenance raising 409. **Self-blame:** this is a cross-section sweep miss — round-1's fix added the column but skipped the §3.7 concrete code example. The 4-offense pattern from PR-5 strikes again; the 8-section sweep checklist must include "every concrete code example that constructs an instance of the affected schema" not just the schema declaration.

**Two Codex P1 absorbed against pre-merge dispatch (commit `0cbb20a87`):**

1. **Persist the settlement symbol with MTM provenance.** The first draft of §3.2 added `price_source + price_settlement_date + inputs_hash` (three columns) to `MTMSnapshot`. Codex caught: `cash_settlement_prices` is uniquely identified by `(source, symbol, settlement_date)`. When westmetall publishes LME_AL + LME_CU + LME_ZN on the same date, three rows share `(source, settlement_date)`; without `symbol` persisted, the snapshot cannot prove which row fed it. `inputs_hash` is a one-way verifier — not reverse-queryable. **Fix:** added `price_symbol: String(length=32)` as a fourth provenance column on `MTMSnapshot` and as a third provenance column on `cashflow_ledger_entries`; updated CHECK constraints, migration, snapshot creators, and §6/§7 references throughout. P&L stays JSON-list-shaped (per-entry `symbol` was already required in the example).

2. **Require the EXACT prior business-day price — no range fallback.** The first draft of §3.6 walked back 3 business days and queried `WHERE settlement_date <= price_date AND settlement_date >= lookback_limit ORDER BY settlement_date DESC`. Codex caught: a missing D-1 business-day row silently falls back to D-2/D-3/D-4 within the window. That is exactly the stale-price fallback OPUS-04 was meant to remove — re-created at a different layer. **Fix:** §3.6 now computes the SINGLE prior business day via `_prior_business_day(as_of_date, calendar)` and queries `WHERE settlement_date == prior_bd` (exact match). When the prior BD row is missing, `PriceReferenceUnprovable` raises; older business-day rows are NOT considered. The calendar's role is reduced to "skip weekends/holidays when computing the date" — never "define a fallback window".

This is the **first iteration** of the PR-A3-1 dispatch (now hardened against the two P1 catches above). Expect 2–7 more catches based on A1/A2 cycle history (the 4-offense cross-section sweep pattern from PR-5 round 4/5/9/10 will continue to apply unless the orchestrator + executor stay disciplined).

The Phase A3 jury verdict (`docs/audits/2026-05-09-phase-a3-jury-verdict.md`) is the institutional input. Findings are quoted as written there; do not re-adjudicate.

**Key infrastructure already in place (verified via Serena 2026-05-09 against `659e5ba9d`):**
- `PriceQuote` dataclass at `backend/app/services/price_lookup_service.py:42-56` carries `(value: Decimal, source: str, settlement_date: date, symbol: str)` — the canonical provenance quadruple. Note: `symbol` is part of the canonical key (per §0 absorbed Codex P1) — without it, multi-commodity-same-source-same-date publishings cannot be disambiguated.
- `get_cash_settlement_price_d1_with_provenance(db, symbol, as_of_date) -> PriceQuote` at `:137-183` returns the triplet and raises `PriceReferenceUnprovable` on no row in the lookback window.
- `get_cash_settlement_price_d1(db, symbol, as_of_date) -> Decimal` at `:186-211` is the legacy scalar wrapper. Its docstring already says "New code requiring the full provenance triplet MUST use `…_with_provenance` directly."

PR-A3-1 is **largely a downstream-consumer migration** — the contract is already defined; what's missing is (a) consumers persist the triplet, (b) snapshots carry `inputs_hash`, (c) the lookback uses a business calendar, (d) Float storage is corrected to Numeric, (e) Ledger amount is derived server-side.

---

## 1. Mission

Make every persisted valuation snapshot **reconstructible from its inputs** by storing the canonical price-provenance quadruple `(price_value, price_source, price_symbol, price_settlement_date)` and a `inputs_hash` covering the full input set; correct the canonical price column from `Float` to `Numeric` so that "the price" cannot drift by binary rounding; replace the 5-calendar-day price lookback with a business-calendar-aware D-1 lookback so weekend / holiday handling is auditable; and stop accepting the Ledger settlement amount from HTTP payload — derive it server-side from contract facts + price evidence.

This is the **foundational** wave of Phase A3: every later wave (commodity correctness, projection hardening, cashflow boundaries, P&L lifecycle) consumes the provenance triplet that this PR introduces. Without Wave 1, those waves cannot prove what price they used.

**Persona:** Senior software engineer building an institutional trading platform. Constitution `docs/governance.md` is supreme authority — **VALUATION/MTM/CASHFLOW** (governance.md:131-146, "no fallback pricing regimes" / "MTM uses D-1 settlement" / "cashflow always derived"), **GOVERNANCE HARD FAILS** (governance.md:159-174, "evidence missing" / "price reference unprovable"), **OUTPUT CONTRACT** (governance.md:208-217, "audit-friendly + free of speculation"). **Pricing-domain awareness obligatory** — hyphen `-`, plus `+`, period `.`, comma `,` are sign / decimal characters in trading bodies; any text-cleanup or character-class operation must be domain-aware.

> **Note on §-numbering:** `governance.md` does not use numbered subsections. The `§2.X` labels below are this dispatch's internal mnemonics:
> - `§2.1` → **VALUATION/MTM/CASHFLOW** (governance.md:131-146)
> - `§2.6` → **GOVERNANCE HARD FAILS** (governance.md:159-174)
> - `§2.7` → **OUTPUT CONTRACT** (governance.md:208-217)

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-09-phase-a3-jury-verdict.md`** §2 (J-A3-01, J-A3-03, J-A3-05) + §3 (J-A3-OPUS-03, J-A3-OPUS-04, J-A3-OPUS-05). Read all six in full.
- **`docs/governance.md`** — binding sections cited above.
- **`backend/app/services/price_lookup_service.py:42-56`** — `PriceQuote` dataclass shape.
- **`backend/app/services/price_lookup_service.py:137-183`** — `get_cash_settlement_price_d1_with_provenance` (the contract you migrate consumers to).
- **`backend/app/services/price_lookup_service.py:186-211`** — `get_cash_settlement_price_d1` (legacy scalar wrapper; deprecate per §3.1).
- **`backend/app/services/price_lookup_service.py`** entire — for the 5-calendar-day lookback at `:157-160` that needs to become business-day-aware.
- **`backend/app/models/mtm.py:18-35`** — `MTMSnapshot` model (current shape; columns to add per §3.2).
- **`backend/app/models/pl.py:12-32`** — `PLSnapshot` model (current shape; columns to add per §3.3).
- **`backend/app/models/cashflow.py:23-41`** — `CashFlowBaselineSnapshot` model (current shape; columns to add per §3.4).
- **`backend/app/models/market_data.py:12-23`** — `CashSettlementPrice` model. Note `price_usd: Mapped[float] = mapped_column(Float, nullable=False)` at `:23` — the OPUS-03 bug.
- **`backend/app/services/mtm_snapshot_service.py:20-62`** — `create_mtm_snapshot_for_contract` (consumer to migrate per §3.2).
- **`backend/app/services/mtm_snapshot_service.py:65-105`** — `create_mtm_snapshot_for_order` (consumer to migrate per §3.2).
- **`backend/app/services/pl_calculation_service.py`** — locate the snapshot-persistence function via Serena `find_symbol`; cite + migrate per §3.3.
- **`backend/app/services/cashflow_baseline_service.py:31-33`** — current `compute_cashflow_analytic` call (the J-A3-04 boundary collapse — out of scope here, addressed in Wave 4; PR-A3-1 only adds `inputs_hash` per §3.4 without redesigning the source).
- **`backend/app/services/cashflow_ledger_service.py:38-52`** — `_build_expected_entry`; line `:51` carries `"amount": leg.amount` (the J-A3-03 bug).
- **`backend/app/services/cashflow_ledger_service.py:76-...`** — `ingest_hedge_contract_settlement`; the entry point that currently accepts HTTP-payload amount.
- **`backend/alembic/versions/037_rfq_outbound_evidence.py`** — current alembic head; PR-A3-1's migration chains off this.

---

## 3. Scope IN — what PR-A3-1 ships

> **Line-number disclaimer:** all line numbers below are validated at `659e5ba9d` (2026-05-09). They will drift if any other PR merges before PR-A3-1. **Locate edits by symbol / identifier first** (function name, attribute name, literal string).

### 3.1 Migrate downstream consumers to `_with_provenance`

The **contract change is already done** (`PriceQuote` exists, `get_cash_settlement_price_d1_with_provenance` returns it). What's missing is consumer migration. After PR-A3-1, the only legitimate caller of `get_cash_settlement_price_d1` (scalar wrapper) is code that explicitly does NOT need provenance (e.g., a legacy public-facing /price endpoint that must preserve the old contract). Every snapshot-persisting consumer migrates to the provenance variant.

**Sites that must migrate (verify via Serena `find_symbol` / Grep):**
- `mtm_contract_service.py` — `compute_mtm_for_contract` calls `get_cash_settlement_price_d1`; replace with `_with_provenance`. Pass the returned `PriceQuote` up so `mtm_snapshot_service` can persist it (§3.2).
- `mtm_order_service.py` — same pattern (note: J-A3-02 commodity hard-coding is Wave 2; do NOT fix the commodity-default here, only the lookup-contract migration).
- `pl_calculation_service.py` — `compute_pl` likely calls the lookup; migrate and propagate (§3.3).
- `cashflow_baseline_service.py` — calls Analytic which calls lookup; migrates indirectly. Direct lookup calls (if any) migrate too.
- `cashflow_analytic_service.py` — **scope-local provenance plumbing IS in scope** for PR-A3-1 per the §3.4 round-4 expansion (extend `CashFlowItem` schema; `compute_cashflow_analytic` populates the three provenance fields from `_with_provenance` lookups). Other Wave 3 hardening (OPUS-02 swallowed hard-fails / OPUS-06 zero defaults / OPUS-07 5th-view declaration) remains out of scope.
- `scenario_whatif_service.py` — out of scope here (Wave 2 commodity correctness); leave.

**Helper for callers that need both value and triplet shape consistency**: do NOT add a third helper. Two helpers (`scalar` and `_with_provenance`) is sufficient; consumers that need the value alone call `.value` on the returned `PriceQuote`.

### 3.2 `MTMSnapshot` provenance fields + `inputs_hash`

Add to **`backend/app/models/mtm.py:MTMSnapshot`** (current body at `:18-35`) **four** new columns:

```python
# new fields after `quantity_mt`, before `correlation_id`:
price_source: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
price_symbol: Mapped[str | None] = mapped_column(String(length=32), nullable=True)
price_settlement_date: Mapped[date | None] = mapped_column(Date, nullable=True)
inputs_hash: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
```

**Why `price_symbol` is mandatory** (per Codex P1 absorbed in §0): `cash_settlement_prices` is uniquely identified by `(source, symbol, settlement_date)`. When the same source publishes multiple commodities on the same date (westmetall publishes LME_AL + LME_CU + LME_ZN per session), `price_source + price_settlement_date + price_d1` is NOT sufficient to prove which row was consumed — the same `price_source + settlement_date` matches three rows. Persisting `price_symbol` makes the provenance triplet a unique key into the source table; `inputs_hash` is a one-way verifier but cannot be reverse-queried, so the human-queryable provenance must carry the symbol as a structured column.

**Why nullable** (per `feedback_dispatch_self_consistency` "NOT NULL columns vs absent-value cases"): legacy rows pre-PR-A3-1 have no provenance recorded; `NULL` is the honest representation of "this row pre-dates the provenance regime; do not use for reconstrutibilidade verification". A CHECK constraint in `__table_args__` enforces the all-or-none invariant for **new** rows:

```python
CheckConstraint(
    "(price_source IS NULL AND price_symbol IS NULL AND price_settlement_date IS NULL AND inputs_hash IS NULL) "
    "OR (price_source IS NOT NULL AND price_symbol IS NOT NULL AND price_settlement_date IS NOT NULL AND inputs_hash IS NOT NULL)",
    name="ck_mtm_snapshots_provenance_all_or_none",
)
```

Pair with an application-layer `@validates` guard so SQLite tests enforce the same invariant (per `feedback_dispatch_self_consistency` "Every DDL construct touched by `create_all()` must be portable").

**Update `mtm_snapshot_service.create_mtm_snapshot_for_contract` (`:20-62`) and `create_mtm_snapshot_for_order` (`:65-105`)**: the existing `compute_mtm_for_contract` / `compute_mtm_for_order` produce a result that today carries `mtm_value, price_d1, entry_price, quantity_mt`. **Extend the result to also carry the `PriceQuote` consumed**, then `create_mtm_snapshot_for_*` constructs `MTMSnapshot` with the new fields:

```python
snapshot = MTMSnapshot(
    object_type=...,
    object_id=...,
    as_of_date=as_of_date,
    mtm_value=_as_decimal(computed.mtm_value),
    price_d1=_as_decimal(computed.price_d1),
    entry_price=_as_decimal(computed.entry_price),
    quantity_mt=_as_decimal(computed.quantity_mt),
    price_source=computed.price_quote.source,
    price_symbol=computed.price_quote.symbol,
    price_settlement_date=computed.price_quote.settlement_date,
    inputs_hash=_compute_inputs_hash(computed),
    correlation_id=correlation_id,
)
```

**`inputs_hash` construction** (a new helper in `mtm_snapshot_service` or a shared `app/utils/provenance.py`):

```python
import hashlib, json
def _compute_inputs_hash(computed) -> str:
    inputs = {
        "as_of_date": computed.as_of_date.isoformat(),
        "object_type": computed.object_type.value,
        "object_id": str(computed.object_id),
        "entry_price": str(computed.entry_price),
        "quantity_mt": str(computed.quantity_mt),
        "price_value": str(computed.price_quote.value),
        "price_source": computed.price_quote.source,
        "price_settlement_date": computed.price_quote.settlement_date.isoformat(),
        "symbol": computed.price_quote.symbol,
    }
    blob = json.dumps(inputs, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()
```

**Existence-check / conflict logic at `:33-46` and `:81-95`** must extend to compare the new fields too: a fresh recompute that diverges in `price_source`, `price_symbol`, or `price_settlement_date` (e.g., the canonical settlement table grew a row for a date previously unavailable, or a different symbol's row was now consumed) is a **legitimate conflict**, not a silent no-op. Match the existing conflict shape (raise `HTTPException(409, ...)`).

### 3.3 `PLSnapshot` price_references + `inputs_hash`

Add to **`backend/app/models/pl.py:PLSnapshot`** (current body at `:12-32`) two new columns:

```python
price_references: Mapped[dict | None] = mapped_column(
    JSON().with_variant(JSONB(), "postgresql"),
    nullable=True,
)
inputs_hash: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
```

**Why JSON not scalar columns** (per `feedback_dispatch_self_consistency` "Scalar columns cannot represent collection inputs"): `compute_pl` may consume **multiple** price lookups (e.g., one per leg in a spread; one per commodity in a multi-product portfolio). Three scalar columns `(price_value, price_source, price_date)` would silently store only one — a Tipo III layer-boundary regression.

`price_references` shape: a JSON list (order-preserving) of `{symbol, value, source, settlement_date}` dicts, one per lookup performed by `compute_pl` for this snapshot:

```json
[
  {"symbol": "LME_AL", "value": "2585.50", "source": "westmetall", "settlement_date": "2026-05-08"},
  {"symbol": "LME_CU", "value": "9320.00", "source": "westmetall", "settlement_date": "2026-05-08"}
]
```

**Use `JSON().with_variant(JSONB(), "postgresql")` for portability** (per `feedback_dispatch_self_consistency` "Every DDL construct touched by `create_all()` must be portable"). SQLite tests use `JSON`; production uses `JSONB`.

CHECK constraint pattern same as §3.2: `(price_references IS NULL AND inputs_hash IS NULL) OR (price_references IS NOT NULL AND inputs_hash IS NOT NULL)` (`pl_snapshots_provenance_all_or_none`). Application-layer guard for SQLite parity.

**Two-service propagation chain** (per Codex P1 absorbed in §0): in this repo, `compute_pl` lives in `backend/app/services/pl_calculation_service.py` and returns a `PLResultResponse`; `PLSnapshot` rows are created and conflict-checked in a SEPARATE service `backend/app/services/pl_snapshot_service.py:create_pl_snapshot`. The provenance contract MUST flow through both:

1. **Extend `PLResultResponse`** at `backend/app/schemas/pl.py:10-12` with a structured `price_references` field:
   ```python
   class PriceReferenceEntry(BaseModel):
       symbol: str
       source: str
       settlement_date: date
       value: Decimal

   class PLResultResponse(BaseModel):
       realized_pl: Decimal
       unrealized_mtm: Decimal
       price_references: list[PriceReferenceEntry] = Field(default_factory=list)
   ```
2. **Update `compute_pl`** (per Codex P1 absorbed in §0 round 5): collect provenance from BOTH paths, not just the unrealized-MTM lookup:
   - **Realized path (settled period)**: `compute_pl` reads `CashFlowLedgerEntry` rows for `(hedge_contract_id, period)`. After §3.7, each row carries the full quadruple `(price_source, price_symbol, price_settlement_date, price_value)`. For each ledger entry consumed in the realized_pl loop, construct a `PriceReferenceEntry` from the row's persisted provenance and append to `price_references`.
   - **Unrealized path**: when `compute_mtm_for_contract` is invoked at `period_end`, the migrated `_with_provenance` lookup returns a `PriceQuote`; that triplet (now quadruple with symbol) becomes a `PriceReferenceEntry` and is appended to `price_references` after the realized entries.
   - Order of references: deterministic — first all realized entries in cashflow_date order then settlement_date secondary sort, then the unrealized lookup last. Dedupe identical `(symbol, source, settlement_date, value)` rows so a settled period that consulted the same canonical price multiple times records ONE reference.
   
   Without ledger-side collection, a settled contract's P&L snapshot would have realized_pl populated but an empty (or unrealized-only) `price_references` list — the J-A3-05 finding remains open at the snapshot layer.
3. **Update `create_pl_snapshot`** in `pl_snapshot_service.py`: read `result.price_references` from the `PLResultResponse`; persist as `[entry.model_dump(mode="json") for entry in result.price_references]` on `PLSnapshot.price_references` (the `mode="json"` directive coerces `date` → ISO string and `Decimal` → JSON-string-compatible representation; without it Pydantic v2's plain `model_dump()` keeps Python objects that SQLAlchemy's JSON/JSONB serializer rejects at insert time); compute `inputs_hash` over the full input set using the SAME `mode="json"` shape (period_start ISO, period_end ISO, entity_type, str(entity_id), the JSON-mode-dumped sorted `price_references`, plus str(realized_pl) + str(unrealized_mtm)); persist on the row. **Hash and persisted shape MUST match by construction** — using `mode="json"` for one and plain `model_dump()` for the other guarantees a future-replay hash mismatch on the same logical inputs.
4. **Update `create_pl_snapshot` idempotency / conflict logic**: when an existing `PLSnapshot` matches `(entity_type, entity_id, period_start, period_end)`, the conflict check MUST compare the new fields too. A divergence in `price_references` (e.g., a new market-data row materialized that wasn't there in the prior snapshot) or in `inputs_hash` is a **legitimate conflict** (recompute happened against newer inputs); raise `HTTPException(409, ...)` matching the existing conflict shape, NOT a silent no-op return of the legacy row.

Without all four steps, the snapshot insertion path persists no provenance and the J-A3-05 finding remains open. The §6 acceptance + §7 tests below cover each step explicitly.

**Backward compat** (per `feedback_dispatch_self_consistency` "Hash/key signature changes — backfill only if you have all the inputs"): legacy `PLSnapshot` rows do NOT have the inputs that would be needed to backfill `price_references`. Legacy rows stay with `NULL` provenance. The idempotency contract for §3.7 ledger derivation applies to **post-deployment** rows only; legacy rows are forensic artifacts.

### 3.4 `CashFlowBaselineSnapshot` `inputs_hash`

Add to **`backend/app/models/cashflow.py:CashFlowBaselineSnapshot`** (current body at `:23-41`) one new column:

```python
inputs_hash: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
```

**Why only `inputs_hash` and not provenance triplet**: `snapshot_data: JSON` already carries the structured baseline payload; provenance for each constituent cashflow row should live INSIDE `snapshot_data` (e.g., per-row `{"price_source": ..., "price_settlement_date": ..., ...}`) rather than as snapshot-level scalar columns. The top-level `inputs_hash` covers the full assembled snapshot deterministically.

**Update `cashflow_baseline_service`**: locate the snapshot creation site (likely after `compute_cashflow_analytic` returns at `:31-33` — note this Analytic-reads-Baseline **boundary collapse is Wave 4**, NOT Wave 1; PR-A3-1 only adds `inputs_hash` and per-row provenance plumbing here and leaves the source-of-truth boundary fix to Wave 4). Compute hash over `(as_of_date, snapshot_data, total_net_cashflow)` using `mode="json"` shape consistently (per round-3 P1); persist on the row before `db.add(snapshot)`.

**Per-row provenance flow** (per Codex P1 absorbed in §0 round 4): the only existing path that builds the rows persisted into `CashFlowBaselineSnapshot.snapshot_data` is `compute_cashflow_analytic` returning `CashFlowAnalyticResponse[items: list[CashFlowItem]]`. The current `CashFlowItem` schema at `backend/app/schemas/cashflow.py:33-38` carries only `(object_type, object_id, settlement_date, amount_usd, mtm_value)` — **no price provenance**. Without extending this schema AND populating it from `compute_cashflow_analytic`, baseline `snapshot_data` rows cannot carry provenance and the J-A3-OPUS-05 finding remains open. PR-A3-1's scope therefore **expands narrowly** to include:

1. **Extend `CashFlowItem` schema** with FOUR optional provenance fields (full quadruple — per Codex P1 absorbed in §0 round 7, parity with the ledger row's quadruple is required so the same in-place-correction scenario surfaces in baseline as it does in the ledger):
   ```python
   class CashFlowItem(BaseModel):
       object_type: str = Field(..., max_length=64)
       object_id: str = Field(..., max_length=64)
       settlement_date: date
       amount_usd: Decimal
       mtm_value: Decimal
       # PR-A3-1: per-row price provenance (optional — items derived from
       # sources that do not consult price_lookup leave these as None,
       # which is honest absent-data, not silent fallback). Full quadruple
       # mirrors the ledger row shape so a canonical-price in-place
       # correction surfaces as snapshot drift on inputs_hash recompute.
       price_source: str | None = None
       price_symbol: str | None = None
       price_settlement_date: date | None = None
       price_value: Decimal | None = None
   ```
2. **Extend `compute_cashflow_analytic`** so every item that consumes a `_with_provenance` lookup (per §3.1 migration) populates ALL FOUR provenance fields (`price_source`, `price_symbol`, `price_settlement_date`, `price_value`) on the corresponding `CashFlowItem` directly from the returned `PriceQuote`.
3. **Update `cashflow_baseline_service` snapshot persistence**: serialize via `response.model_dump(mode="json")` so every item's `price_*` fields land as ISO-string / regular fields in `snapshot_data`. Compute `inputs_hash` over the SAME `mode="json"` shape (per round-3 P1).

This is **scope-local** to provenance plumbing inside `cashflow_analytic_service.py`. Wave 3 (cashflow projection hardening — OPUS-02/06/07) and Wave 4 (Baseline-reads-Analytic boundary fix — J-A3-04) remain out of scope; §10 codifies the boundary explicitly.

The resulting `snapshot_data` row shape (post-PR-A3-1):

```json
{
    "object_type": "hedge_contract",
    "object_id": "<uuid>",
    "settlement_date": "2026-05-08",
    "amount_usd": "1234.56",
    "mtm_value": "550.00",
    "price_source": "westmetall",
    "price_symbol": "LME_AL",
    "price_settlement_date": "2026-05-08",
    "price_value": "2585.50"
}
```

This is a **schema + content** change — `CashFlowItem` schema extension is the schema piece, populating it inside `compute_cashflow_analytic` is the content piece.

### 3.5 `CashSettlementPrice.price_usd` Float → Numeric

Current at **`backend/app/models/market_data.py:23`**: `price_usd: Mapped[float] = mapped_column(Float, nullable=False)`. Change to:

```python
price_usd: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
```

**Migration safety** (per `feedback_dispatch_self_consistency` "Beware silent data mutation in migrations described as 'type-only'"): Postgres `ALTER COLUMN ... TYPE numeric(18,6) USING price_usd::numeric` rounds to 6 decimal places. A preflight in the migration must FAIL-CLOSED if any existing row has more than 6 fractional digits:

```python
def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return  # SQLite: create_all builds the new shape directly
    # Preflight — fail closed on out-of-scale rows
    out_of_scale = bind.execute(
        sa.text("""
            SELECT COUNT(*)
              FROM cash_settlement_prices
             WHERE scale(price_usd::numeric) > 6
        """)
    ).scalar()
    if out_of_scale > 0:
        raise RuntimeError(
            f"Refusing to convert {out_of_scale} rows with > 6 fractional digits; "
            "manual review required before migration can proceed."
        )
    op.alter_column(
        "cash_settlement_prices",
        "price_usd",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 6),
        existing_nullable=False,
        postgresql_using="price_usd::numeric",
    )
```

**Update `get_cash_settlement_price_d1_with_provenance`** at `:179`: `value=Decimal(str(row.price_usd))` becomes `value=row.price_usd` (already Decimal post-migration). Verify no consumer of `CashSettlementPrice.price_usd` assumes `float` arithmetic.

### 3.6 Business-calendar D-1 lookup — **EXACT prior business day, no range fallback** (OPUS-04)

Current at **`backend/app/services/price_lookup_service.py:157-160`**: `lookback_limit = price_date - timedelta(days=5)` paired with `WHERE settlement_date <= price_date AND settlement_date >= lookback_limit` ordered desc — a **range query that silently accepts older rows**. This is the OPUS-04 violation: when the actual D-1 row is missing, the query happily returns D-2 or D-3 instead.

**Replacement**: compute the **EXACT prior business day** using the calendar, then query for that exact date. The calendar's only role is to skip weekends and holidays when computing the prior-business-day **date** — it does NOT define a fallback window of acceptable older dates.

**Per-commodity calendar — in-repo static map** (per Codex P2 absorbed in §0 round 11): LME aluminum / copper / etc. share the LME holiday calendar; other commodities may have different ones. The `holidays` / `python-holidays` library is NOT a current dependency in `backend/requirements.txt`; importing it without adding the dep would cause `ModuleNotFoundError` on every backend startup / test run. The institutional choice for PR-A3-1 is an **in-repo static map** of holiday dates — operator-auditable, no new dependency, year-by-year updates rolled in via small follow-up PRs. The trade-off (manual yearly maintenance) is acceptable because LME holidays are slow-changing, publicly published in advance, and reviewable in the same audit cycle as any other constitutional change.

```python
# backend/app/utils/market_calendar.py
from datetime import date

# LME official holidays (UK bank holidays + LME-specific). Source: lme.com/Trading/Holiday-calendar
# Calendar is YEAR-KEYED so coverage gaps surface as fail-closed errors
# rather than silently degrading to "weekends only" (per Codex P2 absorbed
# in §0 round 13). Operator extends with 2027+ as published.
_LME_HOLIDAYS_BY_YEAR: dict[int, frozenset[date]] = {
    2026: frozenset({
        date(2026, 1, 1),    # New Year's Day
        date(2026, 4, 3),    # Good Friday
        date(2026, 4, 6),    # Easter Monday
        date(2026, 5, 4),    # Early May Bank Holiday
        date(2026, 5, 25),   # Spring Bank Holiday
        date(2026, 8, 31),   # Summer Bank Holiday
        date(2026, 12, 25),  # Christmas Day
        date(2026, 12, 28),  # Boxing Day (substitute)
    }),
    # Add 2027+ as published — DO NOT delete past years.
}

def _market_calendar_for_symbol(symbol: str, year: int) -> frozenset[date]:
    """Return the holiday set for the symbol's market in `year` (frozenset[date]).

    Fail-closed in two cases:
      (a) Symbol has no registered market calendar (unknown commodity).
      (b) Year is outside the coverage of the year-keyed holiday map
          (operator hasn't published next year's dates yet). Without
          this guard, a 2027 prior-business-day calculation against a
          2026-only map silently treats 2027 holidays as ordinary
          business days, returning a missing-row 424 from the wrong
          date and recording the wrong proof on any persisted snapshot.
    """
    if not symbol.startswith("LME_"):
        raise PriceReferenceUnprovable(
            f"No market calendar registered for symbol {symbol!r}; "
            "operator must extend `_market_calendar_for_symbol` before "
            "MTM/P&L can be computed for this commodity.",
            symbol=symbol,
            as_of_date=None,
        )
    holidays = _LME_HOLIDAYS_BY_YEAR.get(year)
    if holidays is None:
        covered = sorted(_LME_HOLIDAYS_BY_YEAR.keys())
        raise PriceReferenceUnprovable(
            f"LME holiday calendar coverage does not include year {year}; "
            f"covered years: {covered}. Operator must extend "
            f"`_LME_HOLIDAYS_BY_YEAR` before lookups for this period.",
            symbol=symbol,
            as_of_date=date(year, 1, 1),
        )
    return holidays
```

Unknown commodities **MUST raise a structured error** at lookup time — do NOT silently fall through to a global default. That fall-through would be exactly the kind of fallback governance §2.6 forbids.

**Algorithm — exact prior business day**:

```python
def _prior_business_day(price_date: date, calendar_for_year) -> date:
    """Return the SINGLE most recent business day strictly before `price_date`.

    Walks back exactly one business day, skipping weekends and calendar
    holidays. Returns the unique date the caller MUST query for an exact
    match — there is no range fallback. If the row at that exact date
    is missing, the lookup raises PriceReferenceUnprovable; older
    business-day rows are NOT considered.

    `calendar_for_year` is a callable `(year: int) -> frozenset[date]`
    that fail-closes when the year is outside calendar coverage — so a
    cursor walking across a year boundary into uncovered territory
    surfaces as a structured `PriceReferenceUnprovable` rather than
    silently degrading to "weekends only" (per Codex P2 absorbed in §0
    round 13).
    """
    cursor = price_date - timedelta(days=1)
    while cursor.weekday() >= 5 or cursor in calendar_for_year(cursor.year):
        cursor -= timedelta(days=1)
    return cursor
```

**Canonical source per symbol** (per Codex P2 absorbed in §0 round 10): `cash_settlement_prices` unique constraint at `models/market_data.py:13` is `(source, symbol, settlement_date)` — multiple sources can publish for the same `(symbol, date)`. The lookup MUST filter by source to be deterministic; a `_canonical_source_for_symbol(symbol)` helper (in the new `app/utils/market_calendar.py` or a sibling module) returns the institutional canonical source. Unknown commodities **MUST raise a structured error** at lookup time — do NOT silently fall through to a global default. This mirrors the calendar selection rule (§3.6 paragraph above).

For the existing data: westmetall is the de-facto canonical source for all LME settlement symbols (per the existing helper docstring "PriceQuote.source is the row's source column verbatim, e.g. 'westmetall'"). The `_canonical_source_for_symbol` map is keyed by the **resolved settlement symbol** that `resolve_symbol(commodity)` returns (e.g., `LME_ALU_CASH_SETTLEMENT_DAILY`) — NOT by the short commodity code (`LME_AL`). Per Codex P1 absorbed in §0 round 12: keying by short codes makes every normal AL/CU/ZN/NI lookup raise `PriceReferenceUnprovable` because the lookup chain is `resolve_symbol(contract.commodity)` → long form → `_canonical_source_for_symbol(long_form)` map miss.

Verified against `backend/app/services/price_lookup_service.py:62-79` (`COMMODITY_SYMBOL_MAP`): the codebase supports six LME commodities (AL/CU/ZN/NI/PB/SN), all resolving to `LME_<X>_CASH_SETTLEMENT_DAILY`. The mapping below covers all six explicitly:

```python
_CANONICAL_SOURCE_BY_SYMBOL: dict[str, str] = {
    "LME_ALU_CASH_SETTLEMENT_DAILY": "westmetall",  # aluminum
    "LME_CU_CASH_SETTLEMENT_DAILY": "westmetall",   # copper
    "LME_ZN_CASH_SETTLEMENT_DAILY": "westmetall",   # zinc
    "LME_NI_CASH_SETTLEMENT_DAILY": "westmetall",   # nickel
    "LME_PB_CASH_SETTLEMENT_DAILY": "westmetall",   # lead
    "LME_SN_CASH_SETTLEMENT_DAILY": "westmetall",   # tin
    # Extend as new commodities / sources are onboarded — keyed by the
    # resolved settlement symbol, NOT the short code.
}

def _canonical_source_for_symbol(symbol: str) -> str:
    try:
        return _CANONICAL_SOURCE_BY_SYMBOL[symbol]
    except KeyError as exc:
        raise PriceReferenceUnprovable(
            f"No canonical source registered for resolved symbol {symbol!r}; "
            "operator must extend _CANONICAL_SOURCE_BY_SYMBOL (keyed by the "
            "long-form settlement symbol from resolve_symbol) before "
            "MTM/P&L can be computed for this commodity.",
            symbol=symbol,
            as_of_date=None,  # not yet relevant — no lookup attempted
        ) from exc
```

**Replacement lookup body** (replaces the range query at `:157-167`):

```python
canonical_source = _canonical_source_for_symbol(symbol)  # may raise PriceReferenceUnprovable
calendar_for_year = lambda yr: _market_calendar_for_symbol(symbol, yr)  # year-keyed; fail-closed on coverage gap
prior_bd = _prior_business_day(as_of_date, calendar_for_year)
row = (
    db.query(CashSettlementPrice)
    .filter(
        CashSettlementPrice.source == canonical_source,
        CashSettlementPrice.symbol == symbol,
        CashSettlementPrice.settlement_date == prior_bd,  # EXACT match — no range
    )
    .first()  # uniqueness guaranteed by uq_cash_settlement_prices_source_symbol_date
)
if not row:
    raise PriceReferenceUnprovable(
        f"No {canonical_source} {symbol} cash settlement for prior business day {prior_bd} "
        f"(as_of={as_of_date}); older settlements and other sources are NOT considered.",
        symbol=symbol,
        as_of_date=as_of_date,
    )
```

The `(source, symbol, settlement_date)` triplet matches the unique constraint at `uq_cash_settlement_prices_source_symbol_date`; `.first()` is now deterministic by construction (at most one row possible).

**Why no range fallback** (per Codex P1 absorbed in §0): the OPUS-04 finding cited "5-calendar-day lookback" as a regime that lets stale prices in. A 3-business-day range fallback has the same shape one layer down — Monday's missing row silently becomes Friday's. Constitution §2.1 ("no fallback pricing regimes") and §2.6 ("price reference unprovable") together require: if THE prior business day's row is missing, hard-fail. The operator must publish the missing row before MTM/P&L for that as_of_date can compute. There is no auto-fallback.

**Update `get_cash_settlement_price_d1_with_provenance`** to consume the new helper. The 5-calendar-day legacy AND any range scan are gone — replaced by exact-date query.

### 3.7 Ledger settlement amount server-side derivation (J-A3-03)

Current at **`backend/app/services/cashflow_ledger_service.py:51`**: `"amount": leg.amount` — comes from HTTP payload (`HedgeContractSettlementCreate.legs[].amount`). This is the cashflow-always-derived violation.

**Replacement**: `_build_expected_entry` derives `amount` from `(contract.quantity_per_leg, settlement_price.value, contract.fixed_price_value, leg.direction)`. The exact formula depends on the contract's economic semantics; consult `HedgeContract` model + the existing P&L/MTM math for the canonical settlement formula. A typical shape:

```python
def _build_expected_entry(
    db: Session,
    contract: HedgeContract,
    payload: HedgeContractSettlementCreate,
    leg: HedgeContractSettlementLeg,
) -> dict:
    # HedgeContract exposes `commodity` (not `commodity_symbol`); pricing
    # services resolve it via `resolve_symbol(...)` per the existing convention
    # at price_lookup_service.py.
    settlement_quote = get_cash_settlement_price_d1_with_provenance(
        db,
        symbol=resolve_symbol(contract.commodity),
        as_of_date=payload.cashflow_date,
    )
    # ── Settlement legs are PER-LEG, not net (per Codex P1 absorbed in §0
    # round 7). HedgeContractSettlementCreate validates exactly 2 legs
    # {FIXED, FLOAT}; _build_expected_entry is invoked ONCE PER LEG. Each
    # leg's amount is derived independently from its own price source:
    #   FIXED leg: amount = quantity × contract.fixed_price_value
    #              (no market lookup — provenance fields stay NULL)
    #   FLOAT leg: amount = quantity × settlement_quote.value
    #              (lookup made — provenance quadruple populated)
    #
    # Direction per leg from each leg's OWN stored side field
    # (per Codex P2 absorbed in §0 round 8):
    #   FIXED leg direction: from contract.fixed_leg_side
    #   FLOAT leg direction: from contract.variable_leg_side  (NOT "opposite
    #                        of fixed_leg_side" — there is no DB invariant
    #                        forcing the two sides to be opposite)
    # Side → direction mapping (matches the classification CHECK):
    #   side == buy  → direction = OUT (customer pays this leg)
    #   side == sell → direction = IN  (customer receives this leg)
    #
    # `compute_pl` (pl_calculation_service.py:16-83) iterates both rows
    # and applies sign by direction:
    #   realized_pl = (FIXED with sign) + (FLOAT with sign)
    # For fixed_leg_side=buy: realized = -qty*fixed + qty*settlement
    #                                  = qty*(settlement - fixed)  [long P&L]
    # For fixed_leg_side=sell: realized = +qty*fixed - qty*settlement
    #                                   = qty*(fixed - settlement) [short P&L]
    #
    # The institutional convention is therefore "amount is NON-NEGATIVE
    # MAGNITUDE; direction carries the sign." Copying a single net
    # formula across both legs (the round-4 sketch) would have produced
    # `realized = 2 × net` (catastrophic doubling).
    quantity = contract.quantity_mt
    if contract.fixed_price_value is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Cannot derive settlement: contract {contract.id} has no fixed_price_value",
        )

    # Each leg's direction is derived from the leg's OWN stored side field
    # (`fixed_leg_side` for FIXED, `variable_leg_side` for FLOAT) — NOT from
    # "opposite of the other leg" (per Codex P2 absorbed in §0 round 8).
    # The DB CHECK constraint at models/contracts.py:78-80 only ties
    # `classification` to `fixed_leg_side`; there is NO invariant that
    # `variable_leg_side != fixed_leg_side`. A contract with both sides
    # equal is degenerate but admissible at the schema layer; deriving
    # FLOAT direction as "opposite of fixed_leg_side" would silently
    # rewrite the stored variable side and let an inconsistent contract
    # generate realized P&L from a fabricated direction. Read each side
    # field independently from the contract row.
    #
    # Convention (matches the CHECK constraint):
    #   side == buy  → customer pays that leg   → direction = OUT
    #   side == sell → customer receives that leg → direction = IN
    #
    # For a well-formed long swap:
    #   fixed_leg_side=buy + variable_leg_side=sell → FIXED OUT + FLOAT IN
    # For a well-formed short swap:
    #   fixed_leg_side=sell + variable_leg_side=buy → FIXED IN + FLOAT OUT
    # A degenerate contract (both buy or both sell) will fail the
    # operator-supplied-vs-derived 422 check below if the payload reflects
    # the institutional intent rather than the broken stored state — that
    # surfaces the inconsistency rather than masking it.
    def _direction_from_side(side: HedgeLegSide) -> LedgerDirection:
        return LedgerDirection.out if side == HedgeLegSide.buy else LedgerDirection.in_

    # Quantize derived amount to the ledger column scale (Numeric(18, 6))
    # BEFORE both 422 comparison and persistence (per Codex P1 absorbed in
    # §0 round 11). `quantity_mt` and `price_value` each carry their own
    # decimal scales; their unrounded product can have > 6 fractional
    # digits, but `CashFlowLedgerEntry.amount` is `Numeric(18, 6)` and the
    # DB rounds on insert. An idempotent re-ingest then recomputes the
    # unrounded product and the comparator (`_ledger_entry_matches`)
    # compares exact Decimal values → false 409 conflict on legitimately
    # identical re-ingest. Quantize once, deterministically.
    LEDGER_AMOUNT_SCALE = Decimal("0.000001")  # 6 decimal places, matches Numeric(18, 6)

    if leg.leg_id == LedgerLegId.fixed:
        derived_amount = (quantity * contract.fixed_price_value).quantize(
            LEDGER_AMOUNT_SCALE, rounding=ROUND_HALF_EVEN
        )
        derived_direction = _direction_from_side(contract.fixed_leg_side)
        # FIXED leg has NO price lookup — provenance fields stay NULL
        # (admissible per the all-or-four-NULL CHECK constraint).
        provenance = {
            "price_source": None,
            "price_symbol": None,
            "price_settlement_date": None,
            "price_value": None,
        }
    elif leg.leg_id == LedgerLegId.float:
        derived_amount = (quantity * settlement_quote.value).quantize(
            LEDGER_AMOUNT_SCALE, rounding=ROUND_HALF_EVEN
        )
        derived_direction = _direction_from_side(contract.variable_leg_side)
        # FLOAT leg consumed _with_provenance — full quadruple populated.
        provenance = {
            "price_source": settlement_quote.source,
            "price_symbol": settlement_quote.symbol,
            "price_settlement_date": settlement_quote.settlement_date,
            "price_value": settlement_quote.value,
        }
    else:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Unexpected leg_id {leg.leg_id} after payload validation",
        )

    # Verify operator-supplied direction+amount match server-derived; 422 on
    # mismatch (same fail-closed shape as `_validate_currency`).
    if leg.direction != derived_direction:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Leg {leg.leg_id.value} direction mismatch: "
            f"derived={derived_direction.value}, payload={leg.direction.value}",
        )
    if leg.amount != derived_amount:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Leg {leg.leg_id.value} amount mismatch: "
            f"derived={derived_amount}, payload={leg.amount}",
        )

    return {
        "hedge_contract_id": contract.id,
        "source_event_type": SOURCE_EVENT_TYPE,
        "source_event_id": payload.source_event_id,
        "leg_id": leg.leg_id.value,
        "cashflow_date": payload.cashflow_date,
        "currency": "USD",
        "direction": derived_direction.value,
        "amount": derived_amount,  # always non-negative
        **provenance,  # FIXED → all NULL; FLOAT → full quadruple
    }
```

**Provenance shape per leg** (per Codex P1 absorbed in §0 round 7):
- **FIXED leg**: `(price_source, price_symbol, price_settlement_date, price_value)` are ALL NULL — the fixed leg's economics come from `contract.fixed_price_value` (contract attribute, not a market lookup). The all-four-or-none CHECK constraint is satisfied with all NULL.
- **FLOAT leg**: full quadruple populated from `settlement_quote`.

`compute_pl` (per §3.3 step 2) iterates ledger entries for the period; for entries where `price_source IS NOT NULL` (FLOAT legs), construct a `PriceReferenceEntry` and append. FIXED legs contribute amount but no provenance entry — that is honest representation, since FIXED amounts have no market-data dependency.

**Add `price_value` column to ledger entries** (per Codex P1 absorbed in §0 round 5 — P&L references must include ledger-row provenance for settled periods). With only `(price_source, price_symbol, price_settlement_date)` on the ledger row, `compute_pl` reading ledger entries can construct partial `PriceReferenceEntry` records but cannot populate `value` without a re-lookup. Adding `price_value: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)` makes the ledger row self-contained provenance evidence — full quadruple `(value, source, symbol, settlement_date)` per row, queryable without a join back to the canonical price table. CHECK constraint becomes all-four-or-none.

**Update `_ledger_entry_matches`** at `backend/app/services/cashflow_ledger_service.py:25-35` to include the new provenance fields in the idempotency comparison. A re-ingest of the same `source_event_id` whose derived `(price_source, price_symbol, price_settlement_date)` differs from the persisted row is a legitimate conflict (the canonical settlement table grew or a new symbol was published since the prior ingest); raise the existing 409 conflict shape, do NOT silently no-op:

```python
def _decimal_or_none_eq(a: Decimal | None, b: Decimal | None) -> bool:
    """Equality for nullable Decimal columns.

    `_normalize_decimal(None)` becomes `Decimal('None')` which raises;
    FIXED-leg ledger rows have `price_value=None` per §3.7's all-or-four-NULL
    design, so the idempotency comparator MUST handle nullables safely.
    """
    if a is None or b is None:
        return a is None and b is None
    return _normalize_decimal(a) == _normalize_decimal(b)


def _ledger_entry_matches(entry: CashFlowLedgerEntry, expected: dict) -> bool:
    return (
        entry.hedge_contract_id == expected["hedge_contract_id"]
        and entry.source_event_type == expected["source_event_type"]
        and entry.source_event_id == expected["source_event_id"]
        and entry.leg_id == expected["leg_id"]
        and entry.cashflow_date == expected["cashflow_date"]
        and entry.currency == expected["currency"]
        and entry.direction == expected["direction"]
        and _normalize_decimal(entry.amount) == _normalize_decimal(expected["amount"])
        # The four price_* fields are NULL-together for FIXED legs and
        # populated-together for FLOAT legs (per §3.7 + the all-four-or-NULL
        # CHECK constraint). String / date columns compare safely with `==`
        # (None == None is True in Python); the Decimal column needs the
        # NULL-aware helper above to avoid `_normalize_decimal(None)` raising.
        and entry.price_source == expected["price_source"]
        and entry.price_symbol == expected["price_symbol"]
        and entry.price_settlement_date == expected["price_settlement_date"]
        and _decimal_or_none_eq(entry.price_value, expected["price_value"])
    )
```

The `price_value` comparison closes a subtle silent-drift hole: when a canonical settlement row is corrected in-place (same `(source, symbol, settlement_date)` but a different `value` — e.g., a westmetall publication is republished with a corrected price), re-ingest of the same `source_event_id` would otherwise silently no-op, leaving realized P&L tied to the OLD value. With `price_value` in the equality, that scenario surfaces as a legitimate 409 conflict; the operator decides whether to retire the stale snapshot.

Without this idempotency extension, two ingests of the same `source_event_id` with different price provenance silently treat the second as a no-op and the audit trace cannot distinguish them.

**HTTP payload contract**: the `HedgeContractSettlementCreate.legs[].amount` field becomes **advisory / verification only** — server-side derivation is canonical; if the payload supplies a value, the service VERIFIES it matches the derived amount (within a tolerance) and rejects 422 on mismatch. This preserves any external-system idempotency keying that uses the amount, while making the derivation authoritative.

**Add Ledger provenance columns**: `cashflow_ledger_entries.price_source` (str nullable, length=64) + `price_symbol` (str nullable, length=32) + `price_settlement_date` (date nullable) + `price_value` (Decimal nullable, Numeric(18,6)) + a CHECK invariant that **all four** are NULL together OR all four are populated together. Migration in §3.8. The ledger row carries the full quadruple so `compute_pl` reading ledger entries for a settled period can populate `PriceReferenceEntry` records directly from the persisted row without a re-lookup against the canonical price table.

### 3.8 Migration `038_a3_price_provenance`

Single migration covering all of the above. Revision string: `"038_a3_price_provenance"` (24 chars, well within 32-char limit). `down_revision = "037_rfq_outbound_evidence"` (current single head verified via `alembic.script.get_heads()` on `659e5ba9d`).

```python
"""Phase A3 Wave 1: price provenance triplet + Float→Decimal + Ledger derivation evidence.

Revision ID: 038_a3_price_provenance
Revises: 037_rfq_outbound_evidence
Create Date: 2026-05-09 ...
"""

revision = "038_a3_price_provenance"
down_revision = "037_rfq_outbound_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. cash_settlement_prices.price_usd Float → Numeric(18,6) with preflight
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # Preflight: fail closed on out-of-scale rows (see §3.5)
        out_of_scale = bind.execute(sa.text(
            "SELECT COUNT(*) FROM cash_settlement_prices "
            "WHERE scale(price_usd::numeric) > 6"
        )).scalar()
        if out_of_scale > 0:
            raise RuntimeError(
                f"Refusing to convert {out_of_scale} rows with > 6 fractional digits"
            )
        op.alter_column(
            "cash_settlement_prices", "price_usd",
            existing_type=sa.Float(),
            type_=sa.Numeric(18, 6),
            existing_nullable=False,
            postgresql_using="price_usd::numeric",
        )

    # NOTE on op.batch_alter_table: SQLite cannot ALTER an existing TABLE to
    # add a CHECK constraint via plain ALTER TABLE (only via CREATE TABLE +
    # copy + rename). batch_alter_table emits the copy-and-move strategy on
    # SQLite and is a transparent passthrough on PostgreSQL, so wrapping the
    # add_column + create_check_constraint pair in batch mode is safe on
    # both dialects. This matches the pattern established by migration 035.

    # 2. mtm_snapshots: price_source + price_symbol + price_settlement_date + inputs_hash + CHECK
    with op.batch_alter_table("mtm_snapshots") as batch:
        batch.add_column(sa.Column("price_source", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("price_symbol", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("price_settlement_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("inputs_hash", sa.String(length=64), nullable=True))
        batch.create_check_constraint(
            "ck_mtm_snapshots_provenance_all_or_none",
            "(price_source IS NULL AND price_symbol IS NULL AND price_settlement_date IS NULL AND inputs_hash IS NULL) "
            "OR (price_source IS NOT NULL AND price_symbol IS NOT NULL AND price_settlement_date IS NOT NULL AND inputs_hash IS NOT NULL)",
        )

    # 3. pl_snapshots: price_references (JSONB on PG, JSON on SQLite) + inputs_hash + CHECK
    pl_json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    with op.batch_alter_table("pl_snapshots") as batch:
        batch.add_column(sa.Column("price_references", pl_json_type, nullable=True))
        batch.add_column(sa.Column("inputs_hash", sa.String(length=64), nullable=True))
        batch.create_check_constraint(
            "ck_pl_snapshots_provenance_all_or_none",
            "(price_references IS NULL AND inputs_hash IS NULL) "
            "OR (price_references IS NOT NULL AND inputs_hash IS NOT NULL)",
        )

    # 4. cashflow_baseline_snapshots: inputs_hash
    with op.batch_alter_table("cashflow_baseline_snapshots") as batch:
        batch.add_column(sa.Column("inputs_hash", sa.String(length=64), nullable=True))

    # 5. cashflow_ledger_entries: price_source + price_symbol + price_settlement_date + price_value + CHECK
    # Per round-5 P1: ledger row carries the full quadruple so compute_pl
    # reading ledger entries can populate PriceReferenceEntry without a
    # re-lookup against the canonical price table.
    with op.batch_alter_table("cashflow_ledger_entries") as batch:
        batch.add_column(sa.Column("price_source", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("price_symbol", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("price_settlement_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("price_value", sa.Numeric(18, 6), nullable=True))
        batch.create_check_constraint(
            "ck_cashflow_ledger_entries_provenance_all_or_none",
            "(price_source IS NULL AND price_symbol IS NULL AND price_settlement_date IS NULL AND price_value IS NULL) "
            "OR (price_source IS NOT NULL AND price_symbol IS NOT NULL AND price_settlement_date IS NOT NULL AND price_value IS NOT NULL)",
        )


def downgrade() -> None:
    # batch_alter_table also required for SQLite when dropping CHECK
    # constraints + columns; transparent on PostgreSQL.
    with op.batch_alter_table("cashflow_ledger_entries") as batch:
        batch.drop_constraint("ck_cashflow_ledger_entries_provenance_all_or_none", type_="check")
        batch.drop_column("price_value")
        batch.drop_column("price_settlement_date")
        batch.drop_column("price_symbol")
        batch.drop_column("price_source")
    with op.batch_alter_table("cashflow_baseline_snapshots") as batch:
        batch.drop_column("inputs_hash")
    with op.batch_alter_table("pl_snapshots") as batch:
        batch.drop_constraint("ck_pl_snapshots_provenance_all_or_none", type_="check")
        batch.drop_column("inputs_hash")
        batch.drop_column("price_references")
    with op.batch_alter_table("mtm_snapshots") as batch:
        batch.drop_constraint("ck_mtm_snapshots_provenance_all_or_none", type_="check")
        batch.drop_column("inputs_hash")
        batch.drop_column("price_settlement_date")
        batch.drop_column("price_symbol")
        batch.drop_column("price_source")
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # No backfill needed: Numeric → Float is lossless for our domain (settlement
        # prices have ≤ 6 fractional digits by §3.5 invariant).
        op.alter_column(
            "cash_settlement_prices", "price_usd",
            existing_type=sa.Numeric(18, 6),
            type_=sa.Float(),
            existing_nullable=False,
            postgresql_using="price_usd::double precision",
        )
```

**Test the migration roundtrip with §6 acceptance variants** including a row inserted post-upgrade with provenance populated, then downgraded and re-upgraded.

---

## 4. Scope OUT — explicitly NOT in PR-A3-1

- **Commodity correctness** (J-A3-02 Order MTM hard-codes LME_AL; J-A3-OPUS-01 scenario virtual hedges hard-code LME_AL) — Wave 2 (PR-A3-2). PR-A3-1 does NOT change `DEFAULT_COMMODITY` defaults; it preserves the legacy commodity-resolution path. Any consumer that today passes `commodity="LME_AL"` explicitly continues to do so post-PR-A3-1.
- **Cashflow projection hardening** (J-A3-OPUS-02 swallows hard-fails; J-A3-OPUS-06 zero defaults; J-A3-OPUS-07 5th-view declaration) — Wave 3 (PR-A3-3). PR-A3-1 does not touch `cashflow_projection_service.py`.
- **Cashflow boundary fix** (J-A3-04 Baseline reads Analytic; J-A3-OPUS-08 Ledger↔Baseline reconciliation) — Wave 4 (PR-A3-4). PR-A3-1's §3.4 only adds `inputs_hash` to `CashFlowBaselineSnapshot`; the source-of-truth Baseline computation (currently `compute_cashflow_analytic`) is NOT redesigned here.
- **P&L lifecycle** (J-A3-OPUS-09 partially-settled zeroes unrealized MTM) — Wave 5 (PR-A3-5).
- **Cross-A1 deferred** (X-A3-J-01 deal_engine repair path; X-A3-J-02 scenario duplicates A1 exposure) — future Phase A1 follow-up audit per `project_phase_a3_to_a1_followup` memory.
- **Frontend / OpenAPI regen** is REQUIRED but is a side-output, not a feature; see §11 step 14.
- **Removal of `get_cash_settlement_price_d1` legacy wrapper** — out of scope. Per its docstring, it remains for non-provenance-needing callers. Wave 5 or a future hygiene PR may remove it after every legitimate consumer is audited.

---

## 5. Constitutional rules (binding)

- **§2.1 — Valuation/MTM/Cashflow** (governance.md:131-146):
  - "Cashflow is always derived, never manually input" → §3.7 ledger derivation closes the J-A3-03 violation.
  - "MTM uses D-1 settlement" + "no fallback pricing regimes" → §3.6 business-calendar lookback closes the OPUS-04 violation; the 5-calendar-day silent-weekend-acceptance was a fallback regime.
  - "One methodology per endpoint" → §3.1 deprecates the scalar wrapper for snapshot-persisting consumers, ensuring one provenance methodology.
- **§2.6 — Hard Fails** (governance.md:159-174):
  - "Evidence missing" → §3.2/§3.3/§3.4 add `inputs_hash` + price provenance; legacy NULL rows are honest-absent, not silent-missing.
  - "Price reference unprovable" → `PriceReferenceUnprovable` already raises; §3.6 tightens the lookback to business-day-bounded so the failure mode is auditable.
- **§2.7 — Output Contract** (governance.md:208-217):
  - "Audit-friendly + free of speculation" → snapshots now carry inputs_hash + provenance; downstream consumers can VERIFY by recomputing the hash from the cited sources.

---

## 6. Acceptance criteria

- [ ] `MTMSnapshot.price_source`, `price_symbol`, `price_settlement_date`, `inputs_hash` columns exist (nullable) with CHECK constraint enforcing all-or-none across all four.
- [ ] `PLSnapshot.price_references` (JSON/JSONB) + `inputs_hash` columns exist with all-or-none CHECK.
- [ ] `CashFlowBaselineSnapshot.inputs_hash` column exists.
- [ ] `cashflow_ledger_entries.price_source` + `price_symbol` + `price_settlement_date` + `price_value` columns exist with all-or-none CHECK across all four.
- [ ] `cashflow_ledger_service._build_expected_entry` derives EACH LEG independently:
    - FIXED leg: amount = `quantity × contract.fixed_price_value`; provenance fields all NULL (no lookup made).
    - FLOAT leg: amount = `quantity × settlement_quote.value`; provenance quadruple populated from the lookup.
    - Direction per leg derived from EACH LEG'S OWN side field: FIXED from `contract.fixed_leg_side`; FLOAT from `contract.variable_leg_side`. Side → direction mapping: `buy → OUT (customer pays this leg)`, `sell → IN (customer receives this leg)`. Variable side is NOT inferred as "opposite of fixed" — the contract row's stored variable_leg_side is authoritative.
- [ ] `compute_pl` reading both ledger rows produces the correct net: `qty × (settlement − fixed)` for `fixed_leg_side=buy`; `qty × (fixed − settlement)` for `fixed_leg_side=sell`. Verified end-to-end in tests with both sides.
- [ ] All `amount` values persisted on `cashflow_ledger_entries` are NON-NEGATIVE (institutional magnitude convention). `compute_pl`'s direction-driven sign application reads correctly.
- [ ] Derived `amount` is `quantize`d to `Decimal("0.000001")` (matching `Numeric(18, 6)`) with `ROUND_HALF_EVEN` BEFORE both the 422 payload comparison and persistence. Idempotent re-ingest of the same payload + same canonical price returns the existing row (silent no-op) — NOT a 409 from precision drift.
- [ ] Market calendar is an in-repo YEAR-KEYED dict (`_LME_HOLIDAYS_BY_YEAR: dict[int, frozenset[date]]`), NOT an import from a missing `holidays` / `python-holidays` package. `_market_calendar_for_symbol(symbol, year)` raises `PriceReferenceUnprovable` when `year` is outside the covered keys (operator-extended coverage). `_prior_business_day(price_date, calendar_for_year)` consumes a year-aware callable; cursor walking into uncovered year fails-closed rather than silently treating year-N+1 holidays as business days.
- [ ] Per-leg derivation mismatch (`leg.direction != derived_direction` OR `leg.amount != derived_amount`) raises `HTTPException(422, "Leg <fixed|float> <direction|amount> mismatch: ...")`.
- [ ] `compute_pl` reads ledger-row provenance (post-§3.7) into `PriceReferenceEntry` records and appends them to `result.price_references` for the realized path; the unrealized lookup's quote is appended last; duplicates are deduped on `(symbol, source, settlement_date, value)`.
- [ ] A settled-period P&L snapshot has at least one `PriceReferenceEntry` per **priced** ledger entry consumed in `realized_pl` — i.e., per ledger row whose `price_*` provenance fields are non-NULL (FLOAT legs only). FIXED legs deliberately have NULL provenance per §3.7 (their economics come from `contract.fixed_price_value`, not a market lookup); requiring a reference for them would force fabricated provenance. A settled period that consumed only FLOAT priced rows MUST emit ≥1 reference; a hypothetical period consuming only FIXED legs (institutional edge case) emits zero realized references — the unrealized lookup still ensures `price_references` is non-empty for any compute_pl run that hits the active-contract path.
- [ ] `cash_settlement_prices.price_usd` is `Numeric(18, 6)` post-migration on Postgres; SQLite `create_all` produces the new shape.
- [ ] Migration `038_a3_price_provenance` ships; `alembic.script.get_heads()` returns single head `["038_a3_price_provenance"]`.
- [ ] `mtm_snapshot_service.create_mtm_snapshot_for_contract` and `_for_order` consume `_with_provenance` and persist `price_source` + `price_symbol` + `price_settlement_date` + `inputs_hash` on every NEW snapshot.
- [ ] `PLResultResponse` (`backend/app/schemas/pl.py`) carries `price_references: list[PriceReferenceEntry]` (default `[]`) — extends the response contract.
- [ ] `pl_calculation_service.compute_pl` populates `result.price_references` with every `PriceQuote` consumed during the period (one entry per distinct `(symbol, source, settlement_date, value)` — full quadruple dedupe so a corrected canonical price under same triple but new value is NOT collapsed against the original).
- [ ] `pl_snapshot_service.create_pl_snapshot` reads `result.price_references`, persists as JSON on `PLSnapshot.price_references` using `entry.model_dump(mode="json")` for each entry, computes `inputs_hash` over the SAME `mode="json"` shape, and persists both on the row. Hash is reproducible by re-running the same compute against the same inputs (no `mode` mismatch between persistence and hash).
- [ ] `pl_snapshot_service.create_pl_snapshot` idempotency / conflict logic compares `price_references` and `inputs_hash` on the existing row; divergence raises `HTTPException(409, ...)` matching the existing conflict shape — NOT a silent no-op return of the legacy row.
- [ ] `CashFlowItem` schema (`backend/app/schemas/cashflow.py:33-38`) carries FOUR new optional fields: `price_source`, `price_symbol`, `price_settlement_date`, `price_value`.
- [ ] `compute_cashflow_analytic` populates ALL FOUR fields on every item whose value derives from a `_with_provenance` price lookup (directly from the returned `PriceQuote`); items derived from non-lookup sources leave them None.
- [ ] `cashflow_baseline_service` serializes the analytic response via `response.model_dump(mode="json")` so each item's `price_*` fields land in `snapshot_data`; the hash is computed over the SAME `mode="json"` shape.
- [ ] `cashflow_baseline_service` computes `inputs_hash` over the assembled snapshot before persisting the baseline row.
- [ ] `cashflow_ledger_service.ingest_hedge_contract_settlement` derives `amount` server-side from contract facts + `_with_provenance` lookup; HTTP-payload `amount` (if present) is verified against the derived value and rejected 422 on mismatch.
- [ ] `cashflow_ledger_service._build_expected_entry` populates the four provenance fields ONLY on FLOAT legs (full quadruple from `settlement_quote`); FIXED legs construct dicts with all four `price_*` fields = NULL (no market lookup made — economics from `contract.fixed_price_value`). Per the all-four-or-NULL CHECK constraint, both shapes are admissible. Per §3.7.
- [ ] `cashflow_ledger_service._ledger_entry_matches` includes ALL FOUR provenance fields (`price_source`, `price_symbol`, `price_settlement_date`, `price_value`) in its equality check via `_decimal_or_none_eq` for the Decimal column; idempotency-with-divergent-provenance raises 409, not silent no-op. Specifically: a canonical settlement row corrected in-place with same `(source, symbol, date)` but new `value` triggers 409 on re-ingest of the same `source_event_id`. FIXED legs (all-four-NULL) are silently idempotent on re-ingest.
- [ ] `price_lookup_service` computes the EXACT prior business day via `_prior_business_day(as_of_date, calendar)` and queries `WHERE settlement_date == prior_bd` (no range). 5-calendar-day legacy AND any range fallback are gone.
- [ ] When the prior-business-day row is missing, `PriceReferenceUnprovable` raises — older business-day rows are NOT considered.
- [ ] `_market_calendar_for_symbol(symbol)` raises a structured error for unknown commodities — no silent fall-through to a global default calendar.
- [ ] `_canonical_source_for_symbol(symbol)` (new helper) returns the institutional canonical source per commodity (e.g., `LME_AL → "westmetall"`); raises `PriceReferenceUnprovable` for symbols not in `_CANONICAL_SOURCE_BY_SYMBOL`.
- [ ] Lookup query filters by `(source == canonical_source, symbol == symbol, settlement_date == prior_bd)` — three columns matching `uq_cash_settlement_prices_source_symbol_date`; `.first()` is deterministic by uniqueness construction (at most one row).
- [ ] `_decimal_or_none_eq(a, b)` helper handles nullable Decimal comparison without `_normalize_decimal(None)` raising; `_ledger_entry_matches` uses it for `price_value` so FIXED-leg idempotency comparison works (FIXED legs have all four price_* fields NULL).
- [ ] Float→Numeric migration preflight FAILS-CLOSED on any out-of-scale row.
- [ ] `test_alembic_chain.py` continues passing (single head invariant).
- [ ] Legacy MTMSnapshot / PLSnapshot / CashFlowBaselineSnapshot rows have `NULL` provenance fields (no backfill); a fresh-session readback test confirms.

---

## 7. Test coverage required

New / extended tests (locate existing test files via `Glob backend/tests/test_{mtm,pl,cashflow,price_lookup}*.py`):

- `backend/tests/test_mtm_snapshot_service.py`:
  - `test_mtm_snapshot_persists_price_provenance_quadruple` — asserts `price_source`, `price_symbol`, `price_settlement_date`, `inputs_hash` all populated on a fresh snapshot
  - `test_mtm_snapshot_persists_price_symbol_distinguishing_multi_commodity_same_source_same_date` — fixture with two `CashSettlementPrice` rows on the same date from the same source for different symbols (LME_AL + LME_CU); assert the snapshot's `price_symbol` correctly identifies which row was consumed
  - `test_mtm_snapshot_inputs_hash_is_deterministic_over_same_inputs`
  - `test_mtm_snapshot_inputs_hash_changes_when_price_settlement_date_changes`
  - `test_mtm_snapshot_inputs_hash_changes_when_price_symbol_changes`
  - `test_mtm_snapshot_legacy_null_provenance_does_not_violate_check`
  - `test_mtm_snapshot_partial_provenance_violates_check_constraint` — assert that constructing a row with three of four provenance fields populated and one NULL raises an `IntegrityError`

- `backend/tests/test_pl_calculation_service.py`:
  - `test_compute_pl_returns_price_references_in_result_response` — asserts `PLResultResponse.price_references` is populated by `compute_pl`
  - `test_compute_pl_emits_one_entry_per_distinct_symbol_source_date_lookup`

- `backend/tests/test_pl_snapshot_service.py` (new or extended):
  - `test_create_pl_snapshot_persists_price_references_from_result`
  - `test_create_pl_snapshot_inputs_hash_covers_full_input_set` — period_start/end + entity + price_references + realized_pl + unrealized_mtm
  - `test_create_pl_snapshot_persists_price_references_via_json_mode_dump` — fixture with one `PriceReferenceEntry` carrying a `Decimal` value and `date` settlement_date; assert the persisted JSON column carries ISO-string date and string-encoded Decimal (NOT a Python object that would fail SQLAlchemy serialization)
  - `test_create_pl_snapshot_inputs_hash_uses_json_mode_dump_consistently` — re-running compute_pl + create_pl_snapshot against the same DB state produces the same `inputs_hash` (regression for the hash-vs-persistence mode mismatch)
  - `test_create_pl_snapshot_multi_commodity_persists_one_reference_per_lookup` (regression for "scalar columns can't represent collection inputs")
  - `test_create_pl_snapshot_idempotency_no_op_on_identical_rerun`
  - `test_create_pl_snapshot_conflict_409_when_price_references_diverge` — second call with same `(entity, period)` but new market-data row materialized raises 409
  - `test_create_pl_snapshot_conflict_409_when_inputs_hash_diverges` — guard that hash drift surfaces as conflict, not silent no-op

- `backend/tests/test_cashflow_baseline_service.py`:
  - `test_cashflow_baseline_inputs_hash_is_deterministic`
  - `test_cashflow_baseline_per_row_provenance_quadruple_inside_snapshot_data` — fixture has Analytic emit a `CashFlowItem` with all four provenance fields populated; assert persisted `snapshot_data` row carries the full quadruple as ISO/string-decimal (mode="json").
  - `test_cashflow_baseline_inputs_hash_drifts_when_canonical_price_corrected_in_place` — fixture: persist baseline snapshot with `price_value="2585.50"`; in-place-correct the canonical settlement row to `2590.00` and recompute `compute_cashflow_analytic`; assert recomputed `inputs_hash` differs from persisted (snapshot drift surfaces — same shape as the ledger `_ledger_entry_matches` round-7 invariant).
  - `test_cashflow_baseline_items_without_price_lookup_have_null_provenance` — fixture has Analytic emit a fixed-cashflow item that never consulted `_with_provenance`; assert all four provenance fields are None in `snapshot_data` (honest absent-data, not silent fallback)

- `backend/tests/test_cashflow_analytic_service.py`:
  - `test_compute_cashflow_analytic_populates_provenance_on_priced_items`
  - `test_compute_cashflow_analytic_leaves_provenance_none_for_non_priced_items`

- `backend/tests/test_cashflow_ledger_service.py`:
  - `test_settlement_amount_derived_server_side_not_from_payload`
  - `test_settlement_payload_amount_mismatch_raises_422`
  - `test_settlement_per_leg_derivation_fixed_leg_uses_contract_fixed_price` — fixture: `quantity=10, fixed_price=100`; FIXED leg amount = 1000; provenance NULL.
  - `test_settlement_per_leg_derivation_float_leg_uses_settlement_quote` — fixture: `quantity=10, settlement_value=110`; FLOAT leg amount = 1100; provenance quadruple populated.
  - `test_settlement_compute_pl_realized_long_side` — fixture `fixed_leg_side=buy`, `qty=10, fixed=100, settlement=110`; both legs persisted; `compute_pl` returns `realized_pl = +100` (long P&L: `qty*(settlement - fixed) = 10*10`). Regression for the round-4 doubling bug (`+100` not `+200`).
  - `test_settlement_compute_pl_realized_short_side` — fixture `fixed_leg_side=sell`, `qty=10, fixed=100, settlement=110`; `compute_pl` returns `realized_pl = -100` (short P&L: `qty*(fixed - settlement) = 10*-10`).
  - `test_settlement_payload_leg_direction_mismatch_raises_422` — payload's FIXED leg direction differs from `fixed_leg_side`-derived direction → 422.
  - `test_settlement_payload_leg_amount_mismatch_raises_422` — payload's FLOAT leg amount differs from `qty × settlement_value` → 422.
  - `test_settlement_float_direction_derived_from_variable_leg_side_not_fixed_inverse` — fixture: contract with `fixed_leg_side=buy, variable_leg_side=buy` (degenerate but schema-admissible). Payload supplies FLOAT direction matching `variable_leg_side=buy` → OUT. Assert derivation reads `variable_leg_side` (produces OUT) and the row persists with FLOAT direction OUT — NOT the "opposite of fixed_leg_side" (which would have been IN). Regression for the round-8 P2 — proves the variable side is read independently.
  - `test_settlement_persists_price_source_and_symbol_and_settlement_date_and_value` — quadruple persistence
  - `test_settlement_partial_provenance_violates_check_constraint` — three of four populated, one NULL → `IntegrityError`
  - `test_ledger_entry_matches_includes_provenance_in_equality` — fixture persists row with `(source=A, symbol=LME_AL, date=D, value=2585)`; second `ingest` with derived `(source=A, symbol=LME_CU, date=D, value=9300)` raises 409, NOT silent no-op
  - `test_ledger_entry_matches_detects_price_value_only_divergence` — fixture persists row with `(source=A, symbol=LME_AL, date=D, value=2585)`; canonical price table is corrected in-place to `2590` for the same `(source, symbol, date)`; second `ingest` of the same `source_event_id` re-derives via `_with_provenance` and gets `value=2590`; assert 409, NOT silent no-op (the symbol/source/date triplet is identical but the `value` divergence MUST surface)
  - `test_ledger_idempotency_no_op_on_fixed_leg_with_null_provenance` — fixture: persist a settlement event whose FIXED leg has all four `price_*` fields NULL (per §3.7); re-ingest the SAME `source_event_id` with identical payload; assert no 500 / no AttributeError / no Decimal('None') raise — the comparator returns True via `_decimal_or_none_eq` and the call is silently idempotent. Regression for the round-10 P1 NULL-handling bug.
  - `test_ledger_idempotency_no_op_on_identical_rerun` — same payload + same derived provenance returns the existing row without conflict

- `backend/tests/test_pl_calculation_service.py` (extension for round-5 ledger-provenance collection):
  - `test_compute_pl_collects_provenance_from_ledger_entries_in_realized_path` — fixture has two `CashFlowLedgerEntry` rows in the period each carrying full quadruple; assert `result.price_references` includes a `PriceReferenceEntry` matching each ledger row's quadruple
  - `test_compute_pl_settled_period_with_priced_rows_does_not_emit_empty_price_references` — fixture: period contains at least one FLOAT (priced) ledger entry + FIXED entry; contract status not active → unrealized_mtm = 0; assert `len(result.price_references) >= 1` (FLOAT row contributes; FIXED row's NULL provenance correctly skipped). Pin the "priced rows surface, fixed rows do not" boundary explicitly.
  - `test_compute_pl_collects_only_priced_ledger_entries_into_price_references` — fixture: realized period has both FIXED and FLOAT ledger rows; assert `len(result.price_references) == 1` (only FLOAT contributes); FIXED leg's amount still feeds `realized_pl` correctly.
  - `test_compute_pl_dedupes_identical_provenance_across_realized_and_unrealized` — fixture: realized entry's quadruple matches the unrealized lookup's quote; assert ONE reference, not two

- `backend/tests/test_price_lookup_service.py`:
  - `test_lookup_queries_exact_prior_business_day_not_a_range` — assert the SQL/ORM query filters on `settlement_date == prior_bd` (not a `<=` range)
  - `test_lookup_skips_weekend_correctly_to_friday`
  - `test_lookup_skips_LME_holiday_correctly`
  - `test_missing_prior_business_day_raises_PriceReferenceUnprovable_even_when_older_business_day_exists` — fixture has Friday's row present but Monday's missing; lookup for Tuesday must raise (Monday is the exact prior BD; Friday is NOT considered)
  - `test_unknown_commodity_raises_structured_error_not_silent_default_calendar`
  - `test_canonical_source_for_symbol_returns_westmetall_for_resolved_LME_symbols` — fixture asserts mapping for ALL SIX commodities (`LME_ALU_CASH_SETTLEMENT_DAILY`, `LME_CU_CASH_SETTLEMENT_DAILY`, `LME_ZN_CASH_SETTLEMENT_DAILY`, `LME_NI_CASH_SETTLEMENT_DAILY`, `LME_PB_CASH_SETTLEMENT_DAILY`, `LME_SN_CASH_SETTLEMENT_DAILY`) — keys are the **resolved long-form symbols** that `resolve_symbol(commodity)` returns, not short codes
  - `test_canonical_source_for_symbol_raises_PriceReferenceUnprovable_for_unknown_symbol` — `XYZ_FAKE` not in `_CANONICAL_SOURCE_BY_SYMBOL` → exception with structured message
  - `test_canonical_source_lookup_chain_works_for_short_code_input` — fixture: `commodity="LME_AL"` → `resolve_symbol` returns `"LME_ALU_CASH_SETTLEMENT_DAILY"` → `_canonical_source_for_symbol` returns `"westmetall"` → lookup succeeds. Regression for the round-12 P1 mis-keying bug (short code AL keyed map silently raised on the long-form output).
  - `test_lookup_filters_by_canonical_source_excluding_other_sources` — fixture: insert two `CashSettlementPrice` rows with same `(symbol=LME_AL, settlement_date=D)` but different sources `westmetall` and `bloomberg`; lookup MUST return the westmetall row (canonical) regardless of insertion order. Without source filter, `.first()` is non-deterministic.
  - `test_market_calendar_is_in_repo_year_keyed_not_holidays_dependency` — assert no `import holidays` in `app/utils/market_calendar.py`; `_LME_HOLIDAYS_BY_YEAR` is a `dict[int, frozenset[date]]` literal in source. Regression for the round-11 P2 missing-dep risk.
  - `test_market_calendar_fails_closed_on_year_outside_coverage` — fixture: only 2026 in `_LME_HOLIDAYS_BY_YEAR`; call `_market_calendar_for_symbol("LME_ALU_CASH_SETTLEMENT_DAILY", 2027)` → raises `PriceReferenceUnprovable` with message naming covered years. Regression for the round-13 P2 silent-degradation bug.
  - `test_prior_business_day_fails_closed_when_walk_crosses_into_uncovered_year` — fixture: only 2026 in calendar; `_prior_business_day(date(2027, 1, 4), calendar_for_year)` → cursor enters 2027, callable raises. Verifies the year-aware lookup propagates correctly through the walk loop.
  - `test_settlement_amount_quantized_to_ledger_scale` — fixture: `quantity=Decimal("10.500000")` × `price=Decimal("2585.123457")` produces unrounded 8-digit-fractional result; assert persisted `amount.quantize(Decimal("0.000001"))` matches the persisted row exactly; idempotent re-ingest returns the existing row (no 409, no payload-comparison 422).
  - `test_settlement_idempotent_reingest_no_409_after_quantize` — fixture: persist a settlement; re-ingest same payload immediately; assert silent no-op (`_ledger_entry_matches` returns True via post-quantize values). Regression for the round-11 P1 quantize-precision-drift bug.
  - `test_price_usd_returned_as_decimal_not_float_post_migration`

- `backend/tests/test_038_migration_roundtrip.py` (new, manual or marked):
  - `test_038_upgrade_and_downgrade_clean`
  - `test_038_preflight_rejects_out_of_scale_float_rows`
  - `test_038_post_upgrade_insert_with_provenance_survives_downgrade_then_upgrade`

---

## 8. Critical sequencing

PR-A3-1 ships against **linear main** (`659e5ba9d` at authoring time). All A2 PRs and the A3 audit-cycle backfill (#39) are merged.

- **Branch base**: `origin/main` at `659e5ba9d` or later.
- **Migration chain**: `038_a3_price_provenance.down_revision = "037_rfq_outbound_evidence"`. After upgrade: single head `038_a3_price_provenance`.
- **Downstream dependency**: Waves 2-5 ALL depend on PR-A3-1's provenance triplet being persisted. Wave 2 (commodity correctness) needs `price_source` to verify post-fix that non-aluminum lookups actually consult the right calendar/source. Wave 3 (cashflow projection) needs `inputs_hash` to detect drift. Wave 4 (boundaries) needs the Baseline `inputs_hash` to assert reconciliation. Wave 5 (P&L lifecycle) needs `price_references` to scope partial-settlement semantics.
- **No rebase coordination required** — PR-A3-1 is the first remediation wave; no sibling PRs.

---

## 9. PR shape

**Title:** `fix(audit-a3): PR-A3-1 — foundational price/provenance (J-A3-01, 03, 05 + OPUS-03/04/05)`

**Body skeleton:**

```markdown
## Summary

Foundational Wave 1 of Phase A3 remediation. Persists the canonical
price-provenance quadruple `(price_value, price_source, price_symbol, price_settlement_date)`
on every new MTM/P&L/Baseline snapshot; adds `inputs_hash` for
reconstrutibilidade verification; corrects `cash_settlement_prices.price_usd`
from `Float` to `Numeric(18, 6)`; replaces 5-calendar-day price lookback
with a business-calendar-aware D-1 lookup (LME holidays per-commodity);
and stops accepting Ledger settlement `amount` from HTTP payload — derives
server-side from contract facts + price evidence.

Phase A3 jury verdict (FAIL-WITH-CRITICAL-CAVEATS @ commit `609924562`) —
addresses Tier 1 findings J-A3-01 + J-A3-03 + J-A3-05 + J-A3-OPUS-03 +
J-A3-OPUS-04 + J-A3-OPUS-05. Constitution §2.1 (cashflow always derived,
MTM D-1, no fallback pricing), §2.6 (evidence missing, price reference
unprovable), §2.7 (audit-friendly + free of speculation).

[BEHAVIOR_SHIFT] Ledger ingest now rejects 422 on payload-amount /
derived-amount mismatch (was: payload value persisted as-is). Operators
ingesting legacy mismatched payloads must update upstream.

## Files changed

- `backend/app/models/mtm.py` — provenance fields + CHECK
- `backend/app/models/pl.py` — price_references + inputs_hash + CHECK
- `backend/app/models/cashflow.py` — inputs_hash on Baseline + provenance fields on Ledger entry + CHECKs
- `backend/app/models/market_data.py` — price_usd Float → Numeric
- `backend/app/services/price_lookup_service.py` — business-calendar lookback
- `backend/app/services/mtm_snapshot_service.py` — consume `_with_provenance`, persist triplet + hash
- `backend/app/services/pl_calculation_service.py` — collect PriceQuotes; populate `PLResultResponse.price_references`
- `backend/app/services/pl_snapshot_service.py` — read response references; persist on `PLSnapshot`; compute + persist `inputs_hash`; extend idempotency / conflict logic
- `backend/app/schemas/pl.py` — extend `PLResultResponse` with `price_references: list[PriceReferenceEntry]`
- `backend/app/services/cashflow_baseline_service.py` — compute + persist inputs_hash
- `backend/app/services/cashflow_ledger_service.py` — server-side amount derivation
- `backend/app/services/mtm_contract_service.py` + `mtm_order_service.py` — propagate PriceQuote upward
- `backend/app/utils/market_calendar.py` (new) — per-commodity calendar resolution
- `backend/app/utils/provenance.py` (new) — `_compute_inputs_hash` shared helper
- `backend/alembic/versions/038_a3_price_provenance.py`
- Tests: per §7

## Acceptance evidence

- [ ] All criteria from dispatch §6 met
- [ ] Migration roundtrip clean on local Postgres (with out-of-scale preflight failing closed verified)
- [ ] `alembic heads` returns single `["038_a3_price_provenance"]`
- [ ] `test_alembic_chain.py` 2/2 pass
- [ ] Legacy snapshots have NULL provenance; new snapshots have full triplet + hash

## Constitutional impact

§2.1 (cashflow always derived, no fallback pricing, MTM D-1 with business
calendar), §2.6 (evidence missing — provenance closes the gap), §2.7
(audit-friendly + reconstrutibilidade via inputs_hash).

## Out of scope

- Wave 2-5 of Phase A3 (commodity correctness, projection hardening,
  cashflow boundaries, P&L lifecycle)
- Cross-A1 deferred (X-A3-J-01/02)
- Removal of legacy `get_cash_settlement_price_d1` scalar wrapper

## Closes

J-A3-01 + J-A3-03 + J-A3-05 + J-A3-OPUS-03 + J-A3-OPUS-04 + J-A3-OPUS-05.
```

---

## 10. Constraints — what NOT to do

- DO NOT remove `get_cash_settlement_price_d1` (the legacy scalar wrapper). It remains for non-provenance-needing callers per its docstring.
- DO NOT make new provenance columns `NOT NULL`. Legacy rows have no provenance to backfill (per `feedback_dispatch_self_consistency` "Hash/key signature changes — backfill only if you have all the inputs"). NULL is the honest representation.
- DO NOT backfill legacy `inputs_hash` values from current state. The hash inputs (e.g., the price the snapshot used at the time) are not historicized; backfilling from current settlement prices binds legacy snapshots to today's prices and breaks reconstrutibilidade. Legacy stays NULL.
- DO NOT use `strip(...)` with character classes that include hyphen `-`, plus `+`, period `.`, comma `,` anywhere in the migration or service code. These are sign / decimal characters in numeric contexts; pricing-domain awareness mandatory (per `feedback_dispatch_self_consistency` PR-5 round 7 P1 lesson).
- DO NOT change `DEFAULT_COMMODITY` defaults in `mtm_order_service` or `scenario_whatif_service`. Wave 2 owns commodity correctness; PR-A3-1 only migrates the lookup contract.
- DO NOT modify `cashflow_projection_service` or `scenario_whatif_service` beyond the lookup-contract migration (if they call `get_cash_settlement_price_d1` directly). Waves 3 and 2 own those surfaces.
- For `cashflow_analytic_service`: **scope-local provenance plumbing IS in scope** for PR-A3-1 (per §3.4 round-4 expansion) — extending `CashFlowItem` with three optional provenance fields and populating them from `_with_provenance` lookups is required so the Baseline path can carry per-row provenance through `snapshot_data`. **Other Wave 3 hardening of Analytic (OPUS-02 swallowed hard-fails / OPUS-06 zero defaults / OPUS-07 5th-view declaration) remains out of scope.** Distinguish "extend the data the function emits" (in scope) from "redesign the function's regimes" (out of scope).
- DO NOT use `Numeric` without a precision/scale (e.g., bare `Numeric()`). Always `Numeric(18, 6)` matching the existing repo convention.
- DO NOT use `JSONB` directly in `mapped_column(...)`; use `JSON().with_variant(JSONB(), "postgresql")` for portability (per `feedback_dispatch_self_consistency` "Every DDL construct touched by `create_all()` must be portable").
- DO NOT use a range query (`WHERE settlement_date <= price_date AND >= lookback_limit ORDER BY ... DESC`) for the D-1 settlement lookup, even with a business-calendar-bounded window. The query MUST be `WHERE settlement_date == _prior_business_day(as_of_date, calendar)` (exact match). A range query silently accepts older rows when the prior BD's row is missing — the OPUS-04 fallback regime that PR-A3-1 closes (per Codex P1 absorbed in §0).
- DO NOT omit `price_symbol` from any snapshot provenance contract (`MTMSnapshot`, `cashflow_ledger_entries`, per-row entries inside `CashFlowBaselineSnapshot.snapshot_data`, list entries inside `PLSnapshot.price_references`). `(source, settlement_date)` alone cannot disambiguate multi-commodity-same-source-same-date publishings (westmetall publishing LME_AL + LME_CU + LME_ZN on the same session); without the symbol, J-A3-01 / J-A3-05 reconstrutibilidade is not actually closed (per Codex P1 absorbed in §0).
- DO NOT omit `price_symbol` from `cashflow_ledger_service._build_expected_entry`'s constructed dict OR from `_ledger_entry_matches`'s equality check. Both must enumerate the three provenance fields explicitly. The all-or-none CHECK constraint makes a missing field a HARD failure at insert time, but a missing field in the comparator is a SILENT idempotency drift — equally bad institutionally (per Codex P1 absorbed in §0 round 2).
- DO NOT persist P&L provenance from `pl_calculation_service.compute_pl` alone. Snapshot creation lives in `pl_snapshot_service.create_pl_snapshot`; both services must change. Returning `price_references` on `PLResultResponse` is the propagation contract; persistence happens in the snapshot service.
- DO NOT use plain `entry.model_dump()` (Pydantic v2 default mode) when persisting `price_references` to JSON or constructing `inputs_hash`. ALWAYS `model_dump(mode="json")` so `date` becomes ISO string and `Decimal` becomes JSON-string-compatible. Plain mode keeps Python objects → SQLAlchemy serializer rejects on insert; mismatched modes between persistence and hash → non-replayable hash. The mode must match for hash+shape determinism (per Codex P1 absorbed in §0 round 3).
- DO NOT use plain `op.create_check_constraint(...)` for new CHECK constraints in this migration. Wrap every `add_column` + `create_check_constraint` pair in `op.batch_alter_table(...)` so the SQLite roundtrip succeeds (per Codex P2 absorbed in §0 round 3). Postgres passthrough is transparent.
- DO NOT reference `contract.commodity_symbol` in any service or migration code. `HedgeContract` exposes `commodity` (str) — pricing services resolve to a symbol via `resolve_symbol(contract.commodity)`. Copying `commodity_symbol` raises `AttributeError` at runtime (per Codex P2 absorbed in §0 round 3).
- DO NOT persist `CashFlowLedgerEntry.amount` as a SIGNED value. The existing `compute_pl` (`pl_calculation_service.py:16-83`) applies the sign from `direction` (IN adds, OUT subtracts) when reading ledger entries. The institutional convention is: `amount` is the NON-NEGATIVE MAGNITUDE; `direction` carries the sign (per Codex P1 absorbed in §0 round 5).
- DO NOT derive both ledger legs from a single net formula `(settlement − fixed) × qty`. The settlement payload carries TWO legs {FIXED, FLOAT}; `_build_expected_entry` is invoked ONCE PER LEG. Each leg's amount derives independently: FIXED uses `contract.fixed_price_value`, FLOAT uses `settlement_quote.value`. Copying one net formula across both legs produces `compute_pl` doubling — qty=10/fixed=100/settlement=110 yields `+200` instead of `+100`. Institutional P1 (per Codex P1 absorbed in §0 round 7).
- DO NOT derive the FLOAT leg's direction as "opposite of `contract.fixed_leg_side`". Read `contract.variable_leg_side` directly. The DB CHECK constraint at `models/contracts.py:78-80` only ties `classification` to `fixed_leg_side`; there is NO invariant forcing `variable_leg_side != fixed_leg_side`. A contract with both sides equal is degenerate but admissible at the schema layer; deriving FLOAT direction from "opposite of fixed" would silently rewrite the stored variable side and let an inconsistent contract generate realized P&L from a fabricated direction (per Codex P2 absorbed in §0 round 8).
- DO NOT call `_normalize_decimal(value)` directly on a nullable Decimal column without first checking for None. `_normalize_decimal(None) == Decimal(str(None))` raises `decimal.InvalidOperation`. FIXED-leg ledger rows have `price_value = None` per §3.7; a comparator that calls `_normalize_decimal(entry.price_value)` unconditionally will raise during idempotency re-ingest, returning a 500 instead of the existing settlement / a clean 409. Use the `_decimal_or_none_eq(a, b)` helper for nullable Decimal equality (per Codex P1 absorbed in §0 round 10).
- DO NOT query `cash_settlement_prices` filtering only by `(symbol, settlement_date)` and using `.first()`. The unique constraint is on `(source, symbol, settlement_date)` — multiple sources can publish for the same `(symbol, date)`. Without the source filter, `.first()` returns whichever row the DB happens to order first, making MTM / P&L provenance non-deterministic across environments. Lookup MUST filter on `(source == canonical_source, symbol, settlement_date)` where `canonical_source = _canonical_source_for_symbol(symbol)` (per Codex P2 absorbed in §0 round 10).
- DO NOT key `_CANONICAL_SOURCE_BY_SYMBOL` by SHORT commodity codes (`LME_AL`, `LME_CU`, etc.). The lookup chain is `resolve_symbol(contract.commodity)` → LONG-form settlement symbol (e.g., `LME_ALU_CASH_SETTLEMENT_DAILY`) → `_canonical_source_for_symbol(long_form)`. The map MUST be keyed by the long-form symbol that `resolve_symbol` actually returns. Verify against `backend/app/services/price_lookup_service.py:62-79` (`COMMODITY_SYMBOL_MAP`); cover all six supported commodities (AL/CU/ZN/NI/PB/SN). Keying by short codes would silently raise `PriceReferenceUnprovable` on every legitimate lookup (per Codex P1 absorbed in §0 round 12).
- DO NOT persist or compare unrounded `derived_amount` values. `quantity_mt × price` carries the sum of both factors' decimal scales (potentially > 6); `CashFlowLedgerEntry.amount` is `Numeric(18, 6)` and the DB rounds on insert. Quantize `derived_amount` to `Decimal("0.000001")` with `ROUND_HALF_EVEN` BEFORE both the 422 payload comparison and persistence. Skipping the quantize causes idempotent re-ingest to throw a false 409 (or to reject a payload that supplies the rounded value as a 422 mismatch) (per Codex P1 absorbed in §0 round 11).
- DO NOT `import holidays` (or `python_holidays`, or any other external calendar library) in the new `app/utils/market_calendar.py`. Those packages are NOT in `backend/requirements.txt`; the import would raise `ModuleNotFoundError` on every backend startup / test run. Use the in-repo `_LME_HOLIDAYS_BY_YEAR: dict[int, frozenset[date]]` static map prescribed in §3.6 (per Codex P2 absorbed in §0 round 11). If the operator decides to migrate to a package later, it lands as a separate dispatch with explicit dependency review.
- DO NOT use a single-year `frozenset[date]` for the holiday calendar (the round-11 first sketch). The map MUST be YEAR-KEYED (`dict[int, frozenset[date]]`) so a lookup whose prior-business-day calculation falls into an uncovered year fails-closed with a structured `PriceReferenceUnprovable` rather than silently treating year-N+1 holidays as business days. `_prior_business_day` consumes a `(year: int) -> frozenset[date]` callable that fail-closes on coverage gap. Operator extending the calendar yearly is institutional — coverage drift is operator's responsibility, but the system MUST surface the gap, not absorb it (per Codex P2 absorbed in §0 round 13).
- DO NOT trust the operator-supplied `payload.legs[*].direction` blindly. If the derived direction differs from the payload, raise `HTTPException(422, "Settlement direction does not match derived sign")` — same fail-closed shape as the existing `_validate_currency`. Operator intent verification stays; server-side derivation is authoritative.
- DO NOT limit `PLResultResponse.price_references` to the unrealized-MTM lookup. `compute_pl` reads `CashFlowLedgerEntry` rows for the realized path; after §3.7 those rows carry provenance. Settled-period P&L snapshots MUST collect ledger-row provenance into `price_references` — otherwise a fully-settled period emits an empty references list and J-A3-05 stays open at the snapshot layer (per Codex P1 absorbed in §0 round 5).
- DO NOT skip the Float→Numeric preflight. A row with `price_usd = 2585.501234567` would silently round; the preflight makes the failure visible.
- DO NOT skip the Ledger amount-mismatch 422 path. Returning 200 with derived amount silently overrides operator-supplied input — that's the kind of fallback governance §2.6 forbids.
- DO NOT skip `session.flush()` between provenance row insertion and any subsequent DB read that depends on the row being visible.
- DO NOT auto-merge — wait for Codex review.
- DO NOT use `--no-verify` to skip git hooks. If a hook fails, fix and create a new commit.
- DO NOT re-fork the alembic chain. The migration must declare `down_revision = "037_rfq_outbound_evidence"` (single string).

---

## 11. Workflow

1. `git fetch origin && git worktree add D:\Projetos\Hedge-Control-New-pr-a3-1 origin/main && cd D:\Projetos\Hedge-Control-New-pr-a3-1 && git checkout -b audit-a3/price-provenance`
2. Configure `.claude/settings.local.json` per A1/A2 worktree pattern (`defaultMode: bypassPermissions`, allow `git`/`gh`/`pytest`/`python`/`alembic`, deny `--force` raw / `--auto` / `--no-verify` / push to `main`).
3. Read jury §2 J-A3-01/03/05 + §3 J-A3-OPUS-03/04/05 in full (`docs/audits/2026-05-09-phase-a3-jury-verdict.md`).
4. Read `PriceQuote` + `_with_provenance` at `price_lookup_service.py:42-183` to confirm the contract you're migrating consumers TO.
5. Read all 4 model bodies (mtm.py, pl.py, cashflow.py, market_data.py) and the existing service consumers.
6. Implement model changes (§3.2/§3.3/§3.4 nullable columns + CHECK constraints + application-layer guards).
7. Implement migration `038_a3_price_provenance` per §3.8 including the Float→Numeric preflight.
8. Run migration roundtrip on local Postgres: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`. Verify single head via `alembic heads`. Run the §7 manual roundtrip test.
9. Implement `_compute_inputs_hash` shared helper (`app/utils/provenance.py`).
10. Implement business-calendar lookback (`app/utils/market_calendar.py` + `price_lookup_service` change per §3.6).
11. Migrate consumers (`mtm_snapshot_service`, `pl_calculation_service`, `cashflow_baseline_service`) to `_with_provenance` + persist triplet + hash.
12. Implement Ledger server-side derivation (§3.7) including the 422 mismatch path.
13. Run targeted pytest: `pytest backend/tests/test_mtm_snapshot_service.py backend/tests/test_pl_calculation_service.py backend/tests/test_cashflow_baseline_service.py backend/tests/test_cashflow_ledger_service.py backend/tests/test_price_lookup_service.py backend/tests/test_alembic_chain.py -v`
14. Full backend suite: `pytest backend/tests/ -v` — green except known failures (e.g., the 3 pre-existing `test_ws.py` Python 3.14 failures from A2 baseline).
15. **Frontend regen if any schema field changes touch surfaced read schemas** (likely yes — `MTMSnapshotRead`, `PLSnapshotRead`, `CashflowLedgerEntryRead` will gain new fields):
    - `cd backend && DATABASE_URL=sqlite:///:memory: SECRET_KEY=dummy JWT_SIGNING_SECRET=dummy AUDIT_HMAC_KEY=dummy AUDIT_SIGNING_KEY=test python -c "from app.main import app; import json; json.dump(app.openapi(), open('../docs/api/openapi_v1.json', 'w'), indent=2, sort_keys=True)"`
    - `cd ../frontend-svelte && OPENAPI_SOURCE=../docs/api/openapi_v1.json node scripts/regen-schema.mjs`
16. `git push -u origin audit-a3/price-provenance && gh pr create --base main --title "<§9 title>" --body-file <body>`
17. **STOP. Wait for Codex review.** Address each catch as a new commit. Expect 4-9 catches based on A2 PR-4 history (the largest dispatch-side surface is the migration + provenance schema + business-calendar; expect at least 1-2 P1 in those areas).
18. Report back to orchestrator with PR URL, final SHA, Codex review state, files-touched grouping, migration roundtrip evidence, test counts.

---

## 12. Final report shape

When complete, report to orchestrator:
- Branch + PR URL + final SHA.
- Files touched (grouped: services / models / migration / utils / schemas / tests / frontend).
- Migration roundtrip evidence (single head confirmed; out-of-scale preflight tested by inserting a synthetic out-of-scale row before upgrade).
- Test pass/fail counts vs main baseline.
- Codex review status + catches absorbed (Round / count / sticky-FP audit-trail entries if any, per `reference_codex_connector_calibration` protocol).
- Any unexpected rebase against main (none anticipated; flag if encountered).
- Frontend regen evidence (`schema.d.ts` + `openapi_v1.json` diff lines).

Keep report under 800 words.

Boa caça.
