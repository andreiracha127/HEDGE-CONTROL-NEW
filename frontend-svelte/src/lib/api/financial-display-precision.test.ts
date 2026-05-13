/**
 * J-A6-03 / J-A6-06 / J-A6-11 — static invariants for the analytics,
 * market-data, and RFQ create pages.
 *
 * These tests source-scan the page files to assert that:
 *
 *   - P&L and MTM pages never reintroduce `?? 0` zero-defaults or
 *     alternate-field fallbacks for required Decimal/identifier fields,
 *     and that they actually invoke the runtime validators
 *     (`validatePnlSnapshot` / `validateMtmSnapshot`) before rendering.
 *   - Market-data renders settlement prices through `formatPrice` with
 *     the `USD/MT` unit, reads canonical `CashSettlementPriceRead`
 *     fields (`price_usd`, `settlement_date`), and no longer accesses
 *     non-existent legacy fields (`price`, `value`, `date`, `change`)
 *     via `?? 0` chains.
 *   - RFQ create input declares `step="0.001"`, validates quantity via
 *     `validateMtQuantity`, gates the preview/submit buttons on the
 *     validation result, and sends the canonical decimal string in the
 *     payload (never a JS number).
 *
 * Pattern follows the source-scan style already used by
 * `page-contracts.test.ts` and `rfq-evidence-integrity.test.ts`.
 */
// @vitest-environment node
// @ts-nocheck — Node-only source-scan; matches the existing convention.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROUTES = resolve(process.cwd(), 'src', 'routes');
const SRC = resolve(process.cwd(), 'src');

function read(rel: string): string {
	return readFileSync(resolve(ROUTES, rel), 'utf8');
}

describe('P&L snapshot page — J-A6-03 financial display precision', () => {
	const source = read('(protected)/analytics/pnl/+page.svelte');

	it('imports the validatePnlSnapshot runtime validator', () => {
		expect(source).toContain('validatePnlSnapshot');
		expect(source).toContain(
			"import { validatePnlSnapshot } from '$lib/api/analytics-response-shape'",
		);
	});

	it('renders an explicit malformed state when validation fails', () => {
		expect(source).toMatch(/validation\.ok/);
		expect(source).toMatch(/viewState\s*=\s*'malformed'/);
		expect(source).toMatch(/validation\.missing/);
	});

	it('does not reintroduce ?? 0 zero-defaults on financial fields', () => {
		expect(source).not.toMatch(/realized_p?n?l[^\n]*\?\?\s*0\b/);
		expect(source).not.toMatch(/unrealized[^\n]*\?\?\s*0\b/);
		expect(source).not.toMatch(/\(e:\s*any\)/);
	});

	it('does not reintroduce the legacy realized_pnl / realized / unrealized alternate-field chains', () => {
		expect(source).not.toMatch(/realized_pnl\s*\?\?\s*e\.realized/);
		expect(source).not.toMatch(/unrealized_pnl\s*\?\?\s*e\.unrealized/);
	});
});

describe('MTM snapshot page — J-A6-03 financial display precision', () => {
	const source = read('(protected)/analytics/mtm/+page.svelte');

	it('imports the validateMtmSnapshot runtime validator', () => {
		expect(source).toContain('validateMtmSnapshot');
		expect(source).toContain(
			"import { validateMtmSnapshot } from '$lib/api/analytics-response-shape'",
		);
	});

	it('renders an explicit malformed state when validation fails', () => {
		expect(source).toMatch(/validation\.ok/);
		expect(source).toMatch(/viewState\s*=\s*'malformed'/);
		expect(source).toMatch(/validation\.missing/);
	});

	it('does not reintroduce ?? 0 zero-defaults on financial fields', () => {
		expect(source).not.toMatch(/mtm_value[^\n]*\?\?\s*0\b/);
		expect(source).not.toMatch(/entry_price[^\n]*\?\?\s*0\b/);
		expect(source).not.toMatch(/price_d1[^\n]*\?\?\s*0\b/);
		expect(source).not.toMatch(/\(e:\s*any\)/);
	});

	it('does not reintroduce the legacy mtm_value / value alternate-field chain', () => {
		expect(source).not.toMatch(/mtm_value\s*\?\?\s*e\.value/);
	});
});

describe('market-data page — J-A6-06 Westmetall settlement-price precision', () => {
	const source = read('(protected)/market-data/+page.svelte');

	it('renders settlement prices via formatPrice with the USD/MT unit', () => {
		expect(source).toContain('formatPrice');
		expect(source).toMatch(/formatPrice\(\s*price\.price_usd\s*,\s*['"]USD\/MT['"]\s*\)/);
	});

	it('reads the canonical CashSettlementPriceRead fields', () => {
		expect(source).toContain('price.settlement_date');
		expect(source).toContain('price.price_usd');
	});

	it('does not reintroduce ?? 0 chains on the price column', () => {
		expect(source).not.toMatch(/price\.price\s*\?\?\s*price\.value/);
		expect(source).not.toMatch(/price\.price\s*\?\?\s*price\.value\s*\?\?\s*0/);
		// `formatNumber` is still permitted for the row-to-row delta which is
		// a derived two-decimal change column, but never for the settlement
		// price itself.
		expect(source).not.toMatch(/formatNumber\(\s*price\.price\b/);
		expect(source).not.toMatch(/formatNumber\(\s*price\.value\b/);
	});

	it('does not access legacy `date` field on market prices', () => {
		expect(source).not.toMatch(/price\.date\b/);
	});

	it('still surfaces non-2xx ingest errors via describeApiError (regression guard)', () => {
		expect(source).toContain("import { describeApiError } from '$lib/api/errors';");
		const block = source.match(/async function triggerIngest\([\s\S]*?\n\t\}/);
		expect(block, 'triggerIngest function block must be present').toBeTruthy();
		expect(block![0]).toContain('describeApiError(res)');
	});
});

describe('MarketPrice type — J-A6-06 canonical shape', () => {
	const entities = readFileSync(
		resolve(SRC, 'lib', 'api', 'types', 'entities.ts'),
		'utf8',
	);

	function marketPriceBlock(): string {
		const match = entities.match(/export interface MarketPrice \{[\s\S]*?\n\}/);
		if (!match) throw new Error('MarketPrice interface block not found');
		return match[0];
	}

	it('declares price_usd and settlement_date as required Decimal/date strings', () => {
		// The interface field is required and typed string — six-decimal
		// precision is preserved by `formatPrice` only when the input is
		// the raw decimal string, not a coerced number.
		const block = marketPriceBlock();
		expect(block).toMatch(/price_usd:\s*string\b/);
		expect(block).toMatch(/settlement_date:\s*string\b/);
	});

	it('does not retain the legacy number-typed price / value / change / date fields', () => {
		// The legacy shape (`price?: number`, `value?: number`, `change?:
		// number`, `date?: string`) was never produced by the
		// CashSettlementPriceRead endpoint and was the root cause of
		// `?? 0` defaults on the market-data page. Scope this check to
		// the MarketPrice block — `value?: number` is a substring of
		// other unrelated fields elsewhere in `entities.ts`.
		const block = marketPriceBlock();
		expect(block).not.toMatch(/\bprice\?:\s*number/);
		expect(block).not.toMatch(/\bvalue\?:\s*number/);
		expect(block).not.toMatch(/\bchange\?:\s*number/);
		expect(block).not.toMatch(/\bdate\?:\s*string/);
	});
});

describe('RFQ create page — J-A6-11 MT quantity precision', () => {
	const source = read('(protected)/rfq/new/+page.svelte');

	it('declares step="0.001" on the quantity input (three-decimal MT scale)', () => {
		expect(source).toContain('step="0.001"');
		expect(source).not.toContain('step="0.01"');
	});

	it('imports and uses validateMtQuantity for precision gating', () => {
		expect(source).toContain('validateMtQuantity');
		expect(source).toContain("import { validateMtQuantity } from '$lib/rfq/quantity'");
	});

	it('keeps the user-typed quantity as a string at the form boundary', () => {
		// The form binds a string state, not a number-typed binding that
		// would coerce through JS Number and lose trailing zeros.
		expect(source).toMatch(/quantityMtRaw\s*=\s*\$state<string>/);
		expect(source).not.toMatch(/quantityMt\s*=\s*\$state<number>/);
	});

	it('submits the canonical decimal string in both preview and create payloads', () => {
		// Both fetch bodies must read from `quantityValidation.canonical`
		// — the raw user-typed decimal string — never a numeric variable.
		const previewBlock = source.match(/loadPreview\(\)[\s\S]*?body:\s*JSON\.stringify\([\s\S]*?\}\)/);
		const submitBlock = source.match(/handleSubmit\([\s\S]*?body:\s*JSON\.stringify\(body\)/);
		expect(previewBlock, 'loadPreview body must be present').toBeTruthy();
		expect(submitBlock, 'handleSubmit body must be present').toBeTruthy();
		expect(previewBlock![0]).toMatch(/quantity_mt:\s*quantityValidation\.canonical/);
		expect(submitBlock![0]).toMatch(/quantity_mt:\s*quantityValidation\.canonical/);
	});

	it('gates preview and submit buttons on the validation result', () => {
		// Both buttons must be disabled when the quantity fails MT-scale
		// validation — preview and submit share precision behaviour.
		// Attribute order is irrelevant; assert the pairing inside each
		// element opening tag.
		const previewBtn = source.match(/<button\b[^>]*data-testid="rfq-preview-button"[^>]*>/);
		const submitBtn = source.match(/<button\b[^>]*data-testid="rfq-submit-button"[^>]*>/);
		expect(previewBtn, 'preview button element must be present').toBeTruthy();
		expect(submitBtn, 'submit button element must be present').toBeTruthy();
		expect(previewBtn![0]).toMatch(/disabled=\{!quantityValidation\.ok\}/);
		expect(submitBtn![0]).toMatch(/disabled=\{submitting \|\| !quantityValidation\.ok\}/);
	});

	it('renders the validation error inline when quantity is invalid', () => {
		expect(source).toContain('data-testid="rfq-quantity-error"');
		expect(source).toContain('aria-invalid={quantityError != null}');
	});
});
