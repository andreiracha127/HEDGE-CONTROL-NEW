/**
 * Design-port RFQ create regression guard.
 *
 * The promoted page no longer depends on prototype fixtures, but it must keep
 * the institutional controls, no-silent-submit behavior, actor-sub preflight,
 * and canonical POST /rfqs payload shape.
 */
// @vitest-environment node
// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const RFQ_NEW = resolve(
	process.cwd(),
	'src',
	'routes',
	'(protected)',
	'rfq',
	'new',
	'+page.svelte',
);

function readRfqNew(): string {
	return readFileSync(RFQ_NEW, 'utf8');
}

describe('RFQ create page — institutional controls', () => {
	const source = readRfqNew();

	it('exposes the institutional trade model controls and LME price-type names', () => {
		expect(source).toMatch(/tradeType\s*=\s*\$state<['"][^>]*Swap[^>]*Forward/);
		expect(source).toContain("tradeType === 'Swap'");
		expect(source).toContain("tradeType === 'Forward'");
		expect(source).toContain("priceType: 'AVG'");
		expect(source).toContain("priceType: 'Fix'");
	});

	it('keeps the create flow aluminum-only until backend preview support expands', () => {
		expect(source).toContain('<option value="ALUMINIUM">ALUMINIUM</option>');
		expect(source).not.toContain("'COPPER'");
		expect(source).not.toContain("'ZINC'");
		expect(source).not.toContain("'LEAD'");
		expect(source).not.toContain("'NICKEL'");
		expect(source).not.toContain("'TIN'");
	});

	it('offers expected hedge-intent templates', () => {
		expect(source).toMatch(/function\s+applyTemplate\s*\(/);
		expect(source).toContain("tpl: 'queda' | 'alta' | 'spread'");
		expect(source).toContain("applyTemplate('queda')");
		expect(source).toContain("applyTemplate('alta')");
		expect(source).toContain("applyTemplate('spread')");
	});
});

describe('RFQ create page — production submit contract', () => {
	const source = readRfqNew();

	it('posts to /rfqs through the typed client and never imports prototype mocks', () => {
		expect(source).toContain("client.POST('/rfqs'");
		expect(source).not.toContain('$lib/alcast/mock');
	});

	it('preflights authenticated actor sub without sending user_id', () => {
		expect(source).toContain('authStore.userSub');
		expect(source).toMatch(/if\s*\(\s*!\s*actorSub\s*\)/);
		expect(source).toMatch(/notifications\.error\(\s*['"`][^'"`]*sub[^'"`]*['"`]/i);
		expect(source).not.toMatch(/user_id\s*:/);
	});

	it('submits canonical create body fields and invitation mapping', () => {
		expect(source).toContain('commodity,');
		expect(source).toContain('direction,');
		expect(source).toContain('intent,');
		expect(source).toMatch(/quantity_mt:\s*quantityValidation\.canonical/);
		expect(source).toContain('delivery_window_start: deliveryStart');
		expect(source).toContain('delivery_window_end: deliveryEnd');
		expect(source).toMatch(/invitations:\s*selectedCounterparties\.map/);
		expect(source).toMatch(/counterparty_id:\s*cp\.id/);
		expect(source).not.toMatch(/counterparty_ids\s*:/);
	});

	it('validates MT quantity at three-decimal precision before preview or submit', () => {
		expect(source).toContain('step="0.001"');
		expect(source).toContain('validateMtQuantity');
		expect(source).toMatch(/quantityMtRaw\s*=\s*\$state<string>/);
		expect(source).toContain('data-testid="rfq-preview-button"');
		expect(source).toContain('data-testid="rfq-submit-button"');
		expect(source).toContain('data-testid="rfq-quantity-error"');
	});

	it('prevents silent omission of additional trades from submit', () => {
		expect(source).not.toMatch(/function\s+addTrade\s*\(/);
		expect(source).not.toContain('+ Novo Trade');
		expect(source).not.toContain('onclick={addTrade}');
	});
});
