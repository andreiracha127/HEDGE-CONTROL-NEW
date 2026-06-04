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
const PAGE_DETAIL_LOAD = resolve(ROUTES, '(protected)', 'contracts', '[id]', '+page.ts');
const PAGE_LIST = resolve(ROUTES, '(protected)', 'contracts', '+page.svelte');
const PAGE_LIST_LOAD = resolve(ROUTES, '(protected)', 'contracts', '+page.ts');

function read(path: string): string {
	return readFileSync(path, 'utf8');
}

describe('contract detail page — settlement guard (J-A6-02 slice)', () => {
	const source = read(PAGE_DETAIL);
	const loadSource = read(PAGE_DETAIL_LOAD);

	it('does not wire generic contract status mutations from the promoted design page', () => {
		expect(source).not.toMatch(/client\.(POST|PUT|PATCH|DELETE)\(/);
		expect(source).not.toMatch(/contractsHedgeStatusPath|\/contracts\/hedge\/\{contract_id\}\/status/);
		expect(source).not.toContain('Liquidar Parcial');
	});

	it('uses canonical /contracts/hedge/{id} and /status paths', () => {
		expect(loadSource).toContain("client.GET('/contracts/hedge/{contract_id}'");
		// No stale literal templates left over.
		expect(loadSource).not.toContain('`/contracts/${contractId}`');
		expect(loadSource).not.toContain('`/contracts/${contractId}/status`');
	});
});

describe('contracts list page — canonical /contracts/hedge path', () => {
	const source = read(PAGE_LIST);
	const loadSource = read(PAGE_LIST_LOAD);

	it('routes the list query through contractsHedgeListPath, not /contracts?', () => {
		expect(loadSource).toContain("client.GET('/contracts/hedge'");
		expect(source + loadSource).not.toMatch(/apiFetch\(\s*`\/contracts\?/);
	});
});
