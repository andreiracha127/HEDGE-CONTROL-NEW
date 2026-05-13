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
		expect(source).toMatch(/selectedCounterpartyIds\.map\(\(id\)\s*=>\s*\(\{\s*counterparty_id:\s*id\s*\}\)\)/);
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
		expect(source).not.toMatch(/user_id\s*:/);
	});

	it('requireActorSub raises an explicit auth-error notification on missing sub', () => {
		expect(source).toMatch(/notifications\.error\(\s*['"`][^'"`]*sub[^'"`]*['"`]/i);
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
		const requireOccurrences = detailSource.match(/requireActorSub\s*\(\s*\)/g) ?? [];
		expect(requireOccurrences.length).toBeGreaterThanOrEqual(4);
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

	it('resets evidence on cross-RFQ navigation so previous RFQ data does not leak under a new RFQ header', () => {
		// Codex P2: SvelteKit reuses this component when navigating from
		// /rfq/A to /rfq/B. The preservation branch above is correct for
		// SAME-RFQ reloads but would otherwise display A's quotes /
		// timeline under B's header if B's /quotes or /state-events
		// returns non-2xx. loadAll() must therefore detect a fresh RFQ
		// via a non-reactive route-id marker and clear stale evidence at
		// the top without reading `rfq` in the $effect-triggered sync path.
		expect(source).toMatch(/loadedEvidenceRfqId\s*!==\s*targetRfqId/);
		expect(source).not.toMatch(/rfq\?\.id\s*!==\s*rfqId|rfq\.id\s*!==\s*rfqId/);
		expect(source).toMatch(/isFreshRfq/);
		// And on a fresh RFQ load, all evidence collections must be
		// reset to their initial empty values BEFORE the await.
		const freshBlock = source.match(/if\s*\(\s*isFreshRfq\s*\)\s*\{([\s\S]*?)\}/);
		expect(freshBlock, 'isFreshRfq reset block must exist').toBeTruthy();
		const block = freshBlock![1];
		expect(block).toMatch(/loadedEvidenceRfqId\s*=\s*targetRfqId/);
		expect(block).toMatch(/rfq\s*=\s*null/);
		expect(block).toMatch(/invitations\s*=\s*\[\s*\]/);
		expect(block).toMatch(/quotes\s*=\s*\[\s*\]/);
		expect(block).toMatch(/stateEvents\s*=\s*\[\s*\]/);
		expect(block).toMatch(/ranking\s*=\s*null/);
	});

	it('parseListBodyOnce coerces both bare-array and {items:[]} backend shapes', () => {
		// The backend canonical /quotes and /state-events return bare lists;
		// older paginated envelopes use { items: [...] }. Helper must accept
		// both without re-reading the body.
		expect(source).toMatch(/Array\.isArray\(\s*body\s*\)/);
		expect(source).toMatch(/\(body as \{ items\??\:[\s\S]*?\}\)\.items/);
	});
});
