/**
 * PR-A6-1 page-level invariants.
 *
 * These tests scan routed-page source files to assert that:
 *
 *   - cashflow analytic/projection requests use the singular contract
 *     paths via `cashflowAnalyticPath` / `cashflowProjectionPath` and that
 *     the cashflow page no longer issues a date-range ledger request;
 *   - MTM and P&L pages never call `/mtm/snapshots` or `/pl/snapshots`
 *     without their singleton query parameters and never call the
 *     non-existent `/latest` paths;
 *   - RFQ reject/cancel/refresh and market-data ingest surface non-2xx
 *     bodies through `describeApiError` rather than silently clearing
 *     state.
 *
 * The drift guard test (`paths.drift.test.ts`) covers the negative side
 * (stale literals must not reappear anywhere under `src/`); this file
 * covers the positive contract for each repaired call site.
 */
// @vitest-environment node
// @ts-nocheck — Node-only source-scan test; @types/node is not a project
//                dep, so svelte-check cannot resolve node:fs / node:path.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROUTES = resolve(process.cwd(), 'src', 'routes');

function read(rel: string): string {
	return readFileSync(resolve(ROUTES, rel), 'utf8');
}

describe('cashflow page', () => {
	const source = read('(protected)/cashflow/+page.svelte');

	it('uses singular cashflowAnalyticPath / cashflowProjectionPath helpers', () => {
		expect(source).toContain('cashflowAnalyticPath');
		expect(source).toContain('cashflowProjectionPath');
	});

	it('passes as_of_date to analytic and projection helpers', () => {
		expect(source).toMatch(/cashflowAnalyticPath\(\{\s*as_of_date:/);
		expect(source).toMatch(/cashflowProjectionPath\(\{\s*as_of_date:/);
	});

	it('does not issue ledger requests with date-range query params', () => {
		// No `apiFetch(...)` call points at `/cashflow/ledger` — the ledger
		// tab is now a missing-parameter state. A comment that mentions the
		// path string is fine; an actual call site is not.
		expect(source).not.toMatch(/apiFetch\(\s*[`'"][^`'"]*\/cashflow\/ledger/);
		expect(source).not.toContain('date_from=');
		expect(source).not.toContain('date_to=');
		expect(source).not.toContain('cashflowLedgerPath');
	});

	it('renders explicit non-2xx error states via describeApiError', () => {
		expect(source).toContain('describeApiError');
		expect(source).toMatch(/analyticsState\s*=\s*'error'/);
		expect(source).toMatch(/projectionsState\s*=\s*'error'/);
		expect(source).toMatch(/'missing-param'/);
	});
});

describe('MTM snapshot page', () => {
	const source = read('(protected)/analytics/mtm/+page.svelte');

	it('uses mtmSnapshotsPath with object_type, object_id, as_of_date', () => {
		expect(source).toContain('mtmSnapshotsPath');
		expect(source).toMatch(/object_type:/);
		expect(source).toMatch(/object_id:/);
		expect(source).toMatch(/as_of_date:/);
	});

	it('does not call /mtm/snapshots/latest or fire a request without required params', () => {
		expect(source).not.toContain('/mtm/snapshots/latest');
		// Guard: viewState starts as missing-param on mount until operator supplies inputs.
		expect(source).toMatch(/viewState\s*=\s*'missing-param'/);
		expect(source).toMatch(/paramsReady\(\)/);
	});
});

describe('P&L snapshot page', () => {
	const source = read('(protected)/analytics/pnl/+page.svelte');

	it('uses pnlSnapshotsPath with entity_type, entity_id, period_start, period_end', () => {
		expect(source).toContain('pnlSnapshotsPath');
		expect(source).toMatch(/entity_type:/);
		expect(source).toMatch(/entity_id:/);
		expect(source).toMatch(/period_start:/);
		expect(source).toMatch(/period_end:/);
	});

	it('does not call /pl/snapshot/latest and does not call /pl/snapshots without required params', () => {
		expect(source).not.toContain('/pl/snapshot/latest');
		expect(source).not.toContain('/pl/snapshots/latest');
		expect(source).toMatch(/viewState\s*=\s*'missing-param'/);
		expect(source).toMatch(/paramsReady\(\)/);
	});
});

describe('RFQ detail mutations', () => {
	const source = read('(protected)/rfq/[id]/+page.svelte');

	it('imports describeApiError', () => {
		expect(source).toContain("import { describeApiError } from '$lib/api/errors';");
	});

	it('reject / cancel / refresh handlers call describeApiError on non-2xx', () => {
		// Each function block has an else-branch that invokes describeApiError(res)
		for (const fn of ['rejectRfq', 'cancelRfq', 'refreshInvitations']) {
			const re = new RegExp(`async function ${fn}\\([\\s\\S]*?\\n\\t\\}`);
			const block = source.match(re);
			expect(block, `${fn} function block must be present`).toBeTruthy();
			expect(block![0]).toContain('describeApiError(res)');
		}
	});
});

describe('market-data ingest mutation', () => {
	const source = read('(protected)/market-data/+page.svelte');

	it('imports describeApiError', () => {
		expect(source).toContain("import { describeApiError } from '$lib/api/errors';");
	});

	it('ingest handler surfaces non-2xx detail through describeApiError', () => {
		const block = source.match(/async function triggerIngest\([\s\S]*?\n\t\}/);
		expect(block, 'triggerIngest function block must be present').toBeTruthy();
		expect(block![0]).toContain('describeApiError(res)');
	});
});
