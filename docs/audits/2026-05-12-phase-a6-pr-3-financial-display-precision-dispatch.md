# Phase A6 Remediation Dispatch - PR-A6-3 Financial Display and Numeric Precision

**Phase:** A6 - Frontend Svelte institutional control surface
**Wave:** PR-A6-3
**Authoring date:** 2026-05-12
**Repository:** `D:/Projetos/Hedge-Control-New`
**Base branch:** `main`
**Required branch:** `audit-a6/financial-display-numeric-precision`
**Source verdict:** `docs/audits/2026-05-12-phase-a6-jury-verdict.md`

## 1. Objective

Close:

- `J-A6-03` - Remove zero-default financial fallbacks from analytics displays.
- `J-A6-06` - Preserve six-decimal Westmetall price precision in market-data
  display.
- `J-A6-11` - Align RFQ quantity input precision with backend MT precision.

This wave removes silent financial display defaults and aligns frontend numeric
entry/formatting with backend Decimal semantics.

## 2. Non-Negotiable Constraints

- Do not edit `docs/governance.md`.
- Do not implement PR-A6-1 endpoint path cleanup except as needed to integrate
  with already-merged path fixes.
- Do not use `?? 0` to mask missing required economic values.
- Do not coerce persisted decimal strings through `Number()` when the display
  requires precision beyond plain two-decimal formatting.
- Do not broaden RFQ quantity changes into RFQ lifecycle or actor identity
  fixes. Those belong to PR-A6-2.
- Do not invent new rounding rules. MT quantities are three-decimal precision
  per backend schema; any subsystem that requires a different MT precision must
  be escalated instead of patched locally.

Financial zeros, quantities, and settlement prices are institutional data, not
decorative display values.

## 3. Findings and Evidence

### J-A6-03 - Zero-default analytics values

Accepted evidence:

- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:49`
  maps realized P&L with `e.realized_pnl ?? e.realized ?? 0`.
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:56`
  maps unrealized P&L with `e.unrealized_pnl ?? e.unrealized ?? 0`.
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:41`
  maps response entries with `(e: any)`.
- `frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte:83`
  totals missing realized/unrealized values as zero.
- `frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte:46`
  maps MTM values with `e.mtm_value ?? e.value ?? 0`.
- `frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte:39`
  maps response entries with `(e: any)`.

### J-A6-06 - Westmetall price precision

Accepted evidence:

- `frontend-svelte/src/routes/(protected)/market-data/+page.svelte:112`
  renders settlement prices through `formatNumber`.
- `frontend-svelte/src/lib/utils/format.ts:61` says decimal economic columns
  serialize as strings.
- `frontend-svelte/src/lib/utils/format.ts:63` says `formatNumber` is for
  plain two-decimal numbers.
- `frontend-svelte/src/lib/utils/format.ts:79` exports the existing
  `formatPrice(value, unit?)` helper with six-decimal preservation.
- `frontend-svelte/src/lib/utils/format.ts:84` shows `formatPrice` uses
  `formatDecimalString(value, 6)`.
- `frontend-svelte/src/lib/utils/format.test.ts:72` already has a
  `formatPrice` test block proving six-decimal behavior.

### J-A6-11 - RFQ quantity precision

Accepted evidence:

- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:10` stores
  `quantityMt` as a JavaScript `number`.
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:105` submits that
  numeric value.
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:177` uses
  `type="number"`.
- `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:178` uses
  `step="0.01"`.
- `frontend-svelte/src/lib/api/schema.d.ts:3291` defines
  `RFQCreate.quantity_mt: number | string`.
- `backend/app/schemas/_types.py:13` defines `MTQuantity` as a Decimal.
- `backend/app/core/precision.py:7` defines `MT_NUMERIC_SCALE = 3`.
- `frontend-svelte/src/lib/utils/format.ts:74-76` exports `formatQuantityMT`,
  which treats MT quantities as
  three-decimal precision.
- This makes the current `step="0.01"` input a two-decimal frontend boundary
  mismatch against the backend three-decimal MT schema and existing
  three-decimal display helper.

## 4. Required Implementation Boundary

### P&L and MTM Required Fields

For P&L and MTM analytics:

- replace `any` response parsing with typed or runtime-validated response
  objects;
- use canonical fields from `frontend-svelte/src/lib/api/schema.d.ts`:
  - `PLSnapshotResponse.realized_pl: string` in generated frontend types
    (backend schema: `Decimal`; required);
  - `PLSnapshotResponse.unrealized_mtm: string` in generated frontend types
    (backend schema: `Decimal`; required);
  - `PLSnapshotResponse.period_start: string` (required date);
  - `PLSnapshotResponse.period_end: string` (required date);
  - `MTMSnapshotResponse.mtm_value: string` in generated frontend types
    (backend schema: `Decimal`; required);
  - `MTMSnapshotResponse.as_of_date: string` (required date);
  - `MTMSnapshotResponse.object_id: string` (required);
  - `MTMSnapshotResponse.object_type: MTMObjectType` (required);
- validate the complete required response shape:
  - `PLSnapshotResponse`: `id`, `entity_type`, `entity_id`, `period_start`,
    `period_end`, `realized_pl`, `unrealized_mtm`, `created_at`,
    `correlation_id`;
  - `MTMSnapshotResponse`: `id`, `object_type`, `object_id`, `as_of_date`,
    `quantity_mt`, `entry_price`, `price_d1`, `mtm_value`, `created_at`,
    `correlation_id`;
- treat absent values, or `null` values for non-nullable required fields above,
  as malformed response data. For P&L, missing `period_start` or `period_end`
  must render a date-boundary error; do not substitute the current date or an
  empty label.
- remove alternate-field chains such as `realized_pnl ?? realized` and
  `mtm_value ?? value` unless the generated schema explicitly documents both
  names;
- render explicit error states when required fields are absent;
- do not render missing financial values as zero;
- keep true numeric zero display intact when the backend explicitly returns
  zero.

### Market-Data Price Formatting

For Westmetall/cash settlement prices:

- use the existing `formatPrice(value, unit?)` helper exported from
  `frontend-svelte/src/lib/utils/format.ts:79`; pass the unit argument, such as
  `USD/MT`, when the market-data row has a unit;
- do not create a new formatter unless the existing helper provably fails on a
  concrete settlement-price value; justify any new formatter in the PR body;
- keep change/delta formatting separate if it has a different precision rule;
- add tests that prove decimal strings are not rounded to two decimals.

### RFQ Quantity Input

For RFQ quantity:

- update `frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte:178`
  from `step="0.01"` to `step="0.001"` unless a backend/product rule proves a
  different precision;
- support three-decimal MT entry end to end;
- reject quantities with more than three decimal places at the frontend with a
  visible validation error before preview generation, submit-button enablement,
  and submission payload construction;
- preserve submitted quantity as a decimal string at the form boundary;
- update preview and submit payloads consistently.

## 5. Acceptance Criteria

- P&L/MTM required values missing from the response produce explicit error
  states, not zeros.
- All fields listed in the required response-shape enumeration are present and
  non-null, except `correlation_id` may be `null` only if the generated schema
  permits it; missing any non-null required field renders an error state.
- True backend zero values still display as zero.
- Westmetall settlement price strings preserve six-decimal display precision.
- RFQ quantity input accepts and submits valid three-decimal MT quantities.
- RFQ preview and create payloads use the same quantity representation.
- No new use of `any` or `?? 0` is introduced in the touched financial display
  code.
- `docs/governance.md` has no diff.

## 6. Required Tests

Add or update focused frontend tests.

Minimum coverage:

- existing `formatPrice` usage preserves a six-decimal string such as
  `2380.123456`;
- market-data page renders settlement prices with six decimals;
- P&L analytics rejects or errors on missing realized/unrealized required
  fields;
- P&L snapshot response includes valid `period_start` and `period_end`
  boundaries, verifies `period_start <= period_end`, and raises an error state
  if either boundary is missing;
- MTM analytics rejects or errors on missing `mtm_value` or `as_of_date`;
- true zero realized/unrealized/MTM values render as zero;
- RFQ quantity accepts `123.456` MT and submits `"123.456"` as a decimal
  string;
- RFQ quantity input renders `step="0.001"` unless the PR documents and tests a
  stricter product rule;
- RFQ quantity with four or more decimal places, such as `123.4567`, is
  rejected with a visible error before preview generation or submission;
- RFQ preview and create use identical quantity precision behavior.

## 7. Required Verification

Run, at minimum:

```bash
cd frontend-svelte
npm run check
npm test
npm run build
```

Also run and report:

```bash
rg -n "\\?\\? 0|: any|formatNumber\\(price\\.price|formatNumber\\(price\\.value" "frontend-svelte/src/routes/(protected)/analytics/pnl/+page.svelte" "frontend-svelte/src/routes/(protected)/analytics/mtm/+page.svelte" "frontend-svelte/src/routes/(protected)/market-data/+page.svelte"
rg -n "step=\"0\\.01\"|quantityMt = \\$state<number" "frontend-svelte/src/routes/(protected)/rfq/new/+page.svelte"
git diff --check
```

Report every remaining match in those in-scope files and adjudicate it in the
PR body. Matches outside those files belong to later scope unless they are
introduced by this PR.

## 8. Out of Scope

- Endpoint path repair and non-2xx route discipline. That is PR-A6-1.
- Settlement/RFQ actor evidence. That is PR-A6-2.
- Orders/audit pages and login gating. That is PR-A6-4.
- Backend Decimal type redesign.
- Broad charting or ECharts refactor.

## 9. PR Requirements

- Use branch `audit-a6/financial-display-numeric-precision`.
- Push normally; do not use `--no-verify`.
- Open a PR against `main`.
- Include in the PR body:
  - findings closed;
  - files changed;
  - tests run and results;
  - numeric precision decisions;
  - remaining grep matches and adjudication;
  - hook artifact path;
  - statement that `docs/governance.md` has no diff.
