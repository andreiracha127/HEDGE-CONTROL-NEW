/**
 * J-A6-02 settlement-guard slice — static invariants for the
 * contracts/[id] page.
 *
 * After PR-A6-1 the generic status endpoint must not expose settlement
 * transitions. The source must therefore satisfy:
 *
 *   1. `VALID_TRANSITIONS` does not list `settled` or `partially_settled`
 *      as targets from any status. Only `cancelled` is reachable through
 *      the generic status patch.
 *   2. `TRANSITION_CONFIG` does not contain `settled` or `partially_settled`
 *      keys, and does not contain a `'Liquidar'` / `'Liquidar Parcial'`
 *      button label.
 *   3. The defence-in-depth check inside `transitionStatus` rejects
 *      `settled` / `partially_settled`.
 *
 * We also verify the contracts list/detail/status calls reach
 * `/contracts/hedge...` only (covered by the drift guard but reaffirmed
 * here for the specific page).
 */
// @vitest-environment node
// @ts-nocheck — Node-only source-scan test; @types/node is not a project
//                dep, so svelte-check cannot resolve node:fs / node:path.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROUTES = resolve(process.cwd(), 'src', 'routes');
const PAGE_DETAIL = resolve(ROUTES, '(protected)', 'contracts', '[id]', '+page.svelte');
const PAGE_LIST = resolve(ROUTES, '(protected)', 'contracts', '+page.svelte');

function read(path: string): string {
	return readFileSync(path, 'utf8');
}

describe('contract detail page — settlement guard (J-A6-02 slice)', () => {
	const source = read(PAGE_DETAIL);

	it('does not enumerate settled or partially_settled as transition targets in VALID_TRANSITIONS', () => {
		// Capture the VALID_TRANSITIONS block (between `VALID_TRANSITIONS: ...` and `};`).
		const blockMatch = source.match(/VALID_TRANSITIONS[\s\S]*?\{([\s\S]*?)\n\t\};/);
		expect(blockMatch, 'VALID_TRANSITIONS block must be present').toBeTruthy();
		const block = blockMatch![1];
		expect(block).toMatch(/'cancelled'/);
		expect(block).not.toMatch(/'settled'/);
		expect(block).not.toMatch(/'partially_settled'/);
	});

	it('does not expose Liquidar / Liquidar Parcial transition buttons in TRANSITION_CONFIG', () => {
		const blockMatch = source.match(/TRANSITION_CONFIG[\s\S]*?\{([\s\S]*?)\n\t\};/);
		expect(blockMatch, 'TRANSITION_CONFIG block must be present').toBeTruthy();
		const block = blockMatch![1];
		expect(block).not.toContain('Liquidar');
		expect(block).not.toContain('Liquidar Parcial');
		expect(block).not.toMatch(/^\s*settled\s*:/m);
		expect(block).not.toMatch(/^\s*partially_settled\s*:/m);
		expect(block).toMatch(/cancelled\s*:/);
	});

	it('has a defence-in-depth check rejecting settled / partially_settled in transitionStatus', () => {
		// transitionStatus must refuse to dispatch these targets even if a
		// caller (test, stale UI, console) somehow tries.
		expect(source).toMatch(/targetStatus === 'settled'/);
		expect(source).toMatch(/targetStatus === 'partially_settled'/);
	});

	it('uses canonical /contracts/hedge/{id} and /status paths', () => {
		expect(source).toContain('contractsHedgeDetailPath');
		expect(source).toContain('contractsHedgeStatusPath');
		// No stale literal templates left over.
		expect(source).not.toContain('`/contracts/${contractId}`');
		expect(source).not.toContain('`/contracts/${contractId}/status`');
	});
});

describe('contracts list page — canonical /contracts/hedge path', () => {
	const source = read(PAGE_LIST);

	it('routes the list query through contractsHedgeListPath, not /contracts?', () => {
		expect(source).toContain('contractsHedgeListPath');
		expect(source).not.toMatch(/apiFetch\(\s*`\/contracts\?/);
	});
});
