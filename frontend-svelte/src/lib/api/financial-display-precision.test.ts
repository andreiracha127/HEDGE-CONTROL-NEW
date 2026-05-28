// @vitest-environment node
// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROUTES = resolve(process.cwd(), 'src', 'routes');
const SRC = resolve(process.cwd(), 'src');

function read(rel: string): string {
	return readFileSync(resolve(ROUTES, rel), 'utf8');
}

describe('design-port financial endpoint wiring', () => {
	it('loads P&L from the backend and does not call retired P&L snapshot literals', () => {
		const loadSource = read('(protected)/analytics/pnl/+page.ts');
		expect(loadSource).toContain("client.POST('/deals/pnl-breakdown'");
		expect(loadSource).toContain('snapshot_date');
		expect(loadSource).not.toContain('/pl/snapshot/latest');
		expect(loadSource).not.toContain('/pl/snapshots/latest');
	});

	it('loads MTM from backend MTM/contract endpoints and does not call retired latest literals', () => {
		const loadSource = read('(protected)/analytics/mtm/+page.ts');
		expect(loadSource).toContain("client.GET('/contracts/hedge'");
		expect(loadSource).not.toContain('/mtm/snapshots/latest');
	});

	it('loads market-data settlement prices from canonical Westmetall endpoint', () => {
		const loadSource = read('(protected)/market-data/+page.ts');
		const routeData = readFileSync(resolve(SRC, 'lib', 'alcast', 'route-data.ts'), 'utf8');
		expect(loadSource).toContain("client.GET('/market-data/westmetall/aluminum/cash-settlement/prices'");
		expect(routeData).toContain('price_usd');
		expect(routeData).not.toMatch(/price\.price\s*\?\?\s*price\.value/);
	});
});

describe('RFQ create page — MT quantity precision', () => {
	const source = read('(protected)/rfq/new/+page.svelte');

	it('keeps quantity as a decimal text value and validates before submit', () => {
		expect(source).toContain('type="text"');
		expect(source).toContain('inputmode="decimal"');
		expect(source).not.toContain('step="0.001"');
		expect(source).toContain('validateMtQuantity');
		expect(source).toContain("import { validateMtQuantity } from '$lib/rfq/quantity'");
		expect(source).toMatch(/quantityMtRaw\s*=\s*\$state<string>/);
		expect(source).not.toMatch(/quantityMt\s*=\s*\$state<number>/);
	});

	it('submits the canonical decimal string and gates preview/submit buttons', () => {
		expect(source).toMatch(/quantity_mt:\s*quantityValidation\.canonical/);
		expect(source).toContain("testId: 'rfq-preview-button'");
		expect(source).toContain("testId: 'rfq-submit-button'");
		expect(source).toMatch(/disabled:\s*!quantityValidation\.ok \|\| !legsReady \|\| !datesReady/);
		expect(source).toMatch(/disabled:\s*submitting \|\| !quantityValidation\.ok \|\| selectedCounterparties\.length === 0 \|\| !legsReady \|\| !datesReady \|\| !intentReady \|\| !recipientsReady \|\| !rfqRoleReady/);
		const pageHeader = readFileSync(resolve(SRC, 'lib', 'components', 'alcast', 'PageHeader.svelte'), 'utf8');
		expect(pageHeader).toContain('data-testid={action.testId}');
	});

	it('renders the validation error inline when quantity is invalid', () => {
		expect(source).toContain('data-testid="rfq-quantity-error"');
		expect(source).toContain('aria-invalid={quantityError != null}');
	});
});
