/**
 * J-A6-04 + J-A6-12 — static invariants for the RFQ create and detail
 * pages.
 *
 * These tests enforce the dispatch acceptance criteria as source-scan
 * invariants, mirroring the pattern used by `contracts-settlement-guard`:
 *
 * J-A6-04 (actor identity)
 *   - No frontend RFQ create/award/reject/cancel/refresh body contains
 *     `authStore.userName || 'trader'` or any literal actor fallback.
 *   - RFQ mutation bodies never send `user_id`; backend evidence derives
 *     actor identity from the authenticated JWT sub.
 *   - Missing `sub` short-circuits the mutation with an explicit
 *     notification before any apiFetch is dispatched.
 *
 * J-A6-12 (single response-body parse + non-2xx evidence preservation)
 *   - Quote and state-event response bodies are parsed exactly once.
 *   - Non-2xx quote / state-event reload surfaces an explicit error and
 *     does NOT replace existing evidence with `[]`.
 */
// @vitest-environment node
// @ts-nocheck — Node-only source-scan; matches the existing
//                contracts-settlement-guard.test.ts convention.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROUTES = resolve(process.cwd(), 'src', 'routes');
const RFQ_NEW = resolve(ROUTES, '(protected)', 'rfq', 'new', '+page.svelte');
const RFQ_DETAIL = resolve(ROUTES, '(protected)', 'rfq', '[id]', '+page.svelte');
const RFQ_DETAIL_LOAD = resolve(ROUTES, '(protected)', 'rfq', '[id]', '+page.ts');
const ROUTE_DATA = resolve(process.cwd(), 'src', 'lib', 'alcast', 'route-data.ts');

function read(path: string): string {
	return readFileSync(path, 'utf8');
}

describe('RFQ create page — actor identity (J-A6-04 slice)', () => {
	const source = read(RFQ_NEW);

	it("does not contain the literal 'trader' actor fallback", () => {
		expect(source).not.toMatch(/\|\|\s*['"]trader['"]/);
	});

	it("does not send display name (userName) as actor evidence", () => {
		expect(source).not.toMatch(/user_id\s*:\s*authStore\.userName/);
	});

	it('uses authStore.userSub as a local UX preflight only', () => {
		expect(source).toMatch(/authStore\.userSub/);
		expect(source).not.toMatch(/user_id\s*:/);
	});

	it('blocks submit when sub is missing with an explicit auth-error notification', () => {
		// Pattern: `if (!actorSub) { notifications.error(...); return; }`
		expect(source).toMatch(/if\s*\(\s*!\s*actorSub\s*\)/);
		expect(source).toMatch(/notifications\.error\(\s*['"`][^'"`]*sub[^'"`]*['"`]/i);
	});

	it('POST /rfqs body uses canonical invitations mapping and not legacy counterparty_ids', () => {
		expect(source).not.toMatch(/counterparty_ids\s*:/);
		expect(source).toMatch(/invitations\s*:/);
		expect(source).toMatch(/selectedCounterparties\.map\(\(cp\)\s*=>\s*\(\{\s*counterparty_id:\s*cp\.id/);
	});
});

describe('RFQ detail page — actor identity (J-A6-04 slice)', () => {
	const source = read(RFQ_DETAIL);

	it("does not contain the literal 'trader' actor fallback in any mutation", () => {
		expect(source).not.toMatch(/\|\|\s*['"]trader['"]/);
	});

	it('does not send authStore.userName as actor evidence in any mutation body', () => {
		expect(source).not.toMatch(/user_id\s*:\s*authStore\.userName/);
	});

	it('does not wire frontend actor evidence into detail mutations', () => {
		expect(source).not.toMatch(/client\.(POST|PUT|PATCH|DELETE)\(/);
		expect(source).not.toMatch(/apiFetch\([^)]*method\s*:\s*['"](POST|PUT|DELETE|PATCH)['"]/);
	});

	it('does not send user_id from the detail page', () => {
		expect(source).not.toMatch(/user_id\s*:/);
	});
});

describe('RFQ mutation bodies — backend-derived actor identity (Cluster 2)', () => {
	const createSource = read(RFQ_NEW);
	const detailSource = read(RFQ_DETAIL);

	it('does not send user_id in create or detail mutation body literals', () => {
		expect(createSource).not.toMatch(/user_id\s*:/);
		expect(detailSource).not.toMatch(/user_id\s*:/);
	});

	it('keeps the local actor-sub preflight on create and existing detail mutations', () => {
		expect(createSource).toMatch(/authStore\.userSub/);
		expect(detailSource).not.toMatch(/client\.(POST|PUT|PATCH|DELETE)\(/);
	});
});

describe('RFQ detail page — single-parse + evidence preservation (J-A6-12 slice)', () => {
	const source = read(RFQ_DETAIL);
	const loadSource = read(RFQ_DETAIL_LOAD);
	const routeDataSource = read(ROUTE_DATA);

	it('does not call quotesRes.json() twice in the same expression', () => {
		// The previous bug pattern was:
		//   ((await quotesRes.json()).items ?? await quotesRes.json())
		// Reading a Response body twice throws. Forbid back-to-back json()
		// calls on the same identifier.
		expect(source).not.toMatch(/quotesRes\.json\(\)[\s\S]{0,200}quotesRes\.json\(\)/);
		expect(source).not.toMatch(/eventsRes\.json\(\)[\s\S]{0,200}eventsRes\.json\(\)/);
	});

	it('routes evidence list loading through SvelteKit load and the shared items helper', () => {
		expect(loadSource).toContain("client.GET('/rfqs/{rfq_id}/quotes'");
		expect(loadSource).toContain("client.GET('/rfqs/{rfq_id}/state-events'");
		expect(loadSource).toMatch(/items<.*>\(requireData\(quotesResult/);
		expect(loadSource).toMatch(/items\(requireData\(eventsResult/);
	});

	it('does NOT replace quotes with [] on non-2xx reload', () => {
		// The previous code did `quotes = quotesRes.ok ? ... : []`.
		// Forbid that exact replacement pattern.
		expect(source).not.toMatch(/quotes\s*=\s*quotesRes\.ok\s*\?[\s\S]*?:\s*\[\s*\]/);
		expect(source).not.toMatch(/stateEvents\s*=\s*eventsRes\.ok\s*\?[\s\S]*?:\s*\[\s*\]/);
	});

	it('surfaces non-2xx quote/state-event errors through the route error boundary', () => {
		expect(loadSource).toContain('Failed to load RFQ quotes');
		expect(loadSource).toContain('Failed to load RFQ state events');
	});

	it('resets evidence on cross-RFQ navigation so previous RFQ data does not leak under a new RFQ header', () => {
		expect(loadSource).toContain('params.id');
		expect(source).toContain("const id = $derived(page.params.id ?? '')");
		expect(source).toMatch(/rfqs\.find\(\(r\) => r\.id === id\)/);
	});

	it('parseListBodyOnce coerces both bare-array and {items:[]} backend shapes', () => {
		expect(routeDataSource).toMatch(/Array\.isArray\(\s*data\s*\)/);
		expect(routeDataSource).toMatch(/record\.items/);
	});
});
