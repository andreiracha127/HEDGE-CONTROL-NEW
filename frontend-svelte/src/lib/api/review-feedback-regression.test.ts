// @vitest-environment node
// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROUTES = resolve(process.cwd(), 'src', 'routes');

function readRoute(rel: string): string {
	return readFileSync(resolve(ROUTES, rel), 'utf8');
}

describe('latest review feedback regressions', () => {
	it('guards dashboard market-change rendering when previous price is absent', () => {
		const source = readRoute('(protected)/+page.svelte');

		expect(source).toContain('function marketChangePct');
		expect(source).toContain('c.prev == null || c.prev === 0');
		expect(source).toContain('{#if chg == null}');
		expect(source).not.toContain('{@const chg = ((c.last - c.prev) / c.prev) * 100}');
	});

	it('loads dashboard coverage buckets from exposure-list data instead of global exposure rows', () => {
		const source = readRoute('(protected)/+page.ts');

		expect(source).toContain("client.GET('/exposures/list'");
		expect(source).toContain("requireData(exposureListResult, 'Failed to load exposure buckets')");
		expect(source).toContain('exposureBuckets: exposureBucketsFrom(exposureList)');
		expect(source).not.toContain('exposureBuckets: exposureBucketsFrom(globalExposure)');
	});

	it('renders real audit checksums instead of fabricated hashes', () => {
		const source = readRoute('(protected)/audit/+page.svelte');

		expect(source).toContain('function fmtChecksum');
		expect(source).toContain('fmtChecksum(e.checksum)');
		expect(source).not.toContain('function hashStub');
	});

	it('uses loaded contract cashflow rows and guards nullable settlement dates', () => {
		const source = readRoute('(protected)/contracts/[id]/+page.svelte');

		expect(source).toContain('const cashflows = $derived(data.cashflow ?? [])');
		expect(source).toContain('{#each cashflows as flow');
		expect(source).not.toContain('Margin call (estimado');
		expect(source).not.toContain('Pagamento de margem inicial');
		expect(source).not.toMatch(/c\.settle\.(split|slice)\(/);
	});

	it('renders loaded counterparty profile fields instead of hard-coded identity data', () => {
		const source = readRoute('(protected)/counterparties/[id]/+page.svelte');

		expect(source).toContain('fmtText(cp.tax_id)');
		expect(source).toContain('fmtText(cp.address)');
		expect(source).not.toContain('17.298.092/0001-30');
		expect(source).not.toContain('Av. Brigadeiro Faria Lima, 3500');
	});

	it('only exposes RFQ close action on the backend-selected best quote', () => {
		const source = readRoute('(protected)/rfq/[id]/+page.svelte');

		expect(source).not.toContain('{#if !isPending && !isBest}');
		expect(source).toContain('{#if isBest}');
		expect(source).toContain('Fechar →');
	});

	it('requires intent references and preview-generated text before RFQ creation', () => {
		const source = readRoute('(protected)/rfq/new/+page.svelte');

		expect(source).toContain('const intentReady = $derived');
		expect(source).toContain("client.POST('/rfqs/preview-text'");
		expect(source).toContain('text_en: preview.text_en ?? preview.text');
		expect(source).toContain('text_pt: preview.text_pt ?? preview.text');
		expect(source).toMatch(/disabled=\{submitting \|\| !quantityValidation\.ok \|\| selectedCounterparties\.length === 0 \|\| !legsReady \|\| !intentReady\}/);
	});
});
