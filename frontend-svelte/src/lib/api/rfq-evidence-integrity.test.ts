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
 *   - RFQ actor payloads use the immutable JWT `sub` exposed by
 *     `authStore.userSub`.
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

function read(path: string): string {
	return readFileSync(path, 'utf8');
}

describe('RFQ create page — actor identity (J-A6-04 slice)', () => {
	const source = read(RFQ_NEW);

	it("does not contain the literal 'trader' actor fallback", () => {
		expect(source).not.toMatch(/\|\|\s*['"]trader['"]/);
	});

	it("does not send display name (userName) as user_id evidence", () => {
		expect(source).not.toMatch(/user_id\s*:\s*authStore\.userName/);
	});

	it('uses authStore.userSub for the user_id evidence field', () => {
		// We bind sub to a local actorSub variable, then send it as user_id.
		expect(source).toMatch(/authStore\.userSub/);
		expect(source).toMatch(/user_id\s*:\s*actorSub/);
	});

	it('blocks submit when sub is missing with an explicit auth-error notification', () => {
		// Pattern: `if (!actorSub) { notifications.error(...); return; }`
		expect(source).toMatch(/if\s*\(\s*!\s*actorSub\s*\)/);
		expect(source).toMatch(/notifications\.error\(\s*['"`][^'"`]*sub[^'"`]*['"`]/i);
	});
});

describe('RFQ detail page — actor identity (J-A6-04 slice)', () => {
	const source = read(RFQ_DETAIL);

	it("does not contain the literal 'trader' actor fallback in any mutation", () => {
		expect(source).not.toMatch(/\|\|\s*['"]trader['"]/);
	});

	it('does not send authStore.userName as user_id in any mutation body', () => {
		expect(source).not.toMatch(/user_id\s*:\s*authStore\.userName/);
	});

	it('exposes a requireActorSub helper that pulls sub from authStore', () => {
		expect(source).toMatch(/function\s+requireActorSub\s*\(/);
		expect(source).toMatch(/authStore\.userSub/);
	});

	it('award, reject, cancel, refresh all gate on requireActorSub before apiFetch', () => {
		// Each mutation function must call requireActorSub() and early-return
		// when null, BEFORE apiFetch is dispatched. We assert the helper
		// appears at least four times — once per gated mutation.
		const requireOccurrences = source.match(/requireActorSub\s*\(\s*\)/g) ?? [];
		expect(requireOccurrences.length).toBeGreaterThanOrEqual(4);
		// And every gated mutation sends user_id: actorSub, not a fallback.
		const actorSubBodies = source.match(/user_id\s*:\s*actorSub/g) ?? [];
		expect(actorSubBodies.length).toBeGreaterThanOrEqual(4);
	});

	it('requireActorSub raises an explicit auth-error notification on missing sub', () => {
		expect(source).toMatch(/notifications\.error\(\s*['"`][^'"`]*sub[^'"`]*['"`]/i);
	});
});

describe('RFQ detail page — single-parse + evidence preservation (J-A6-12 slice)', () => {
	const source = read(RFQ_DETAIL);

	it('does not call quotesRes.json() twice in the same expression', () => {
		// The previous bug pattern was:
		//   ((await quotesRes.json()).items ?? await quotesRes.json())
		// Reading a Response body twice throws. Forbid back-to-back json()
		// calls on the same identifier.
		expect(source).not.toMatch(/quotesRes\.json\(\)[\s\S]{0,200}quotesRes\.json\(\)/);
		expect(source).not.toMatch(/eventsRes\.json\(\)[\s\S]{0,200}eventsRes\.json\(\)/);
	});

	it('routes list-body parsing through the single-parse helper', () => {
		expect(source).toMatch(/parseListBodyOnce\s*\(\s*quotesRes\s*\)/);
		expect(source).toMatch(/parseListBodyOnce\s*\(\s*eventsRes\s*\)/);
	});

	it('does NOT replace quotes with [] on non-2xx reload', () => {
		// The previous code did `quotes = quotesRes.ok ? ... : []`.
		// Forbid that exact replacement pattern.
		expect(source).not.toMatch(/quotes\s*=\s*quotesRes\.ok\s*\?[\s\S]*?:\s*\[\s*\]/);
		expect(source).not.toMatch(/stateEvents\s*=\s*eventsRes\.ok\s*\?[\s\S]*?:\s*\[\s*\]/);
	});

	it('surfaces an explicit error notification on non-2xx quote/state-event reload', () => {
		// Both list-load failures must call notifications.error with a
		// "Falha ao recarregar ..." message, so the user knows the
		// preserved evidence is stale.
		expect(source).toMatch(/Falha ao recarregar cotações/);
		expect(source).toMatch(/Falha ao recarregar timeline/);
	});

	it('parseListBodyOnce coerces both bare-array and {items:[]} backend shapes', () => {
		// The backend canonical /quotes and /state-events return bare lists;
		// older paginated envelopes use { items: [...] }. Helper must accept
		// both without re-reading the body.
		expect(source).toMatch(/Array\.isArray\(\s*body\s*\)/);
		expect(source).toMatch(/\(body as \{ items\??\:[\s\S]*?\}\)\.items/);
	});
});
