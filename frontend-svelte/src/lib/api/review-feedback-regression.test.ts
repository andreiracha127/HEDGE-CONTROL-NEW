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
		expect(source).toContain("optionalData(exposureListResult.status === 'fulfilled' ? exposureListResult.value : null)");
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
		expect(source).toContain("const rfqRoleReady = $derived(authStore.hasRole('risk_manager'))");
		expect(source).toContain('const datesReady = $derived(deliveryWindow != null)');
		expect(source).toContain('function legFieldsReady');
		expect(source).toContain("client.POST('/rfqs/preview-text'");
		expect(source).toContain('text_en: preview.text_en');
		expect(source).toContain('text_pt: preview.text_pt');
		expect(source).not.toMatch(/preview\.text(?!_)/);
		expect(source).toMatch(/disabled=\{submitting \|\| !quantityValidation\.ok \|\| selectedCounterparties\.length === 0 \|\| !legsReady \|\| !datesReady \|\| !intentReady \|\| !recipientsReady \|\| !rfqRoleReady\}/);
		expect(source).not.toContain("new Date().toISOString().slice(0, 10)");
	});

	it('keeps live market rows keyed by a unique quote identity', () => {
		const source = readRoute('(protected)/market-data/+page.svelte');

		expect(source).toContain('function marketKey');
		expect(source).toContain('{#each commodities as c (marketKey(c))}');
		expect(source).not.toContain('{#each commodities as c (c.code)}');
	});

	it('filters exposure buckets by the selected commodity tab', () => {
		const source = readRoute('(protected)/exposures/+page.svelte');
		const routeData = readFileSync(resolve(process.cwd(), 'src', 'lib', 'alcast', 'route-data.ts'), 'utf8');

		expect(source).toContain('const filteredExposureBuckets = $derived');
		expect(source).toContain('canonicalCommodityCode(bucket.commodity) === commodity');
		expect(source).toContain('{#each filteredExposureBuckets as b');
		expect(source).toContain('b.commercial_active_mt.toLocaleString');
		expect(source).toContain('b.commercial_passive_mt.toLocaleString');
		expect(routeData).toContain('export function canonicalCommodityCode');
		expect(routeData).toContain("return 'ALUMINUM'");
		expect(source).not.toContain('commercial_mt * 0.62');
		expect(source).not.toContain('commercial_mt * 0.38');
	});

	it('renders dashboard commodity exposure from live exposure aggregates', () => {
		const source = readRoute('(protected)/+page.svelte');
		const loader = readRoute('(protected)/+page.ts');
		const routeData = readFileSync(resolve(process.cwd(), 'src', 'lib', 'alcast', 'route-data.ts'), 'utf8');

		expect(loader).toContain('exposureRows: exposureCommodityRowsFrom(exposureList)');
		expect(routeData).toContain('export function exposureCommodityRowsFrom');
		expect(source).toContain('const exposureRows = $derived(data.exposureRows ?? [])');
		expect(source).not.toContain('const exposureRows = [');
		expect(source).not.toContain("comm: '22.400'");
	});

	it('keeps RFQ detail ranking, impact, and history tied to backend evidence', () => {
		const source = readRoute('(protected)/rfq/[id]/+page.svelte');
		const loader = readRoute('(protected)/rfq/[id]/+page.ts');

		expect(loader).toContain("rfq.intent === 'SPREAD'");
		expect(loader).toContain('spreadBest.buy_quote?.id');
		expect(source).toContain("rfq.direction === 'SELL' ? (price - mid) * rfq.qty : (mid - price) * rfq.qty");
		expect(source).toContain("const canManageRfq = $derived(authStore.hasRole('risk_manager'))");
		expect(source).toContain("rfq.state === 'QUOTED' && !!best");
		expect(source).toContain('const stateEvents = $derived(data.stateEvents ?? [])');
		expect(source).toContain('{#each stateEvents as event');
		expect(source).not.toContain('Cotou 2.638,50');
	});

	it('does not expose inert P&L period tabs', () => {
		const source = readRoute('(protected)/analytics/pnl/+page.svelte');

		expect(source).not.toContain("period = $state");
		expect(source).not.toContain("period === 'QTD'");
		expect(source).not.toContain('P&L total MTD');
	});

	it('omits fabricated counterparty contract, MTM, and spread metrics', () => {
		const source = readRoute('(protected)/counterparties/+page.svelte');

		expect(source).not.toContain('Math.floor(cp.used / 600_000)');
		expect(source).not.toContain('Math.floor(cp.used * 0.004)');
		expect(source).not.toContain('function spread');
		expect(source).toContain('const totalLimit = $derived');
	});

	it('persists commercial order references through the submitted notes field', () => {
		const source = readRoute('(protected)/orders/new/+page.svelte');

		expect(source).toContain('const submittedNotes = $derived.by');
		expect(source).toContain('Referencia ERP/SAP');
		expect(source).toContain('notes: submittedNotes');
	});

	it('resolves contract counterparties through stable ids', () => {
		const source = readRoute('(protected)/contracts/[id]/+page.svelte');

		expect(source).toContain('x.id === c.counterparty_id');
		expect(source).toContain('const cpId = $derived');
		expect(source).toContain('href={`/counterparties/${cpId}`}');
		expect(source).not.toContain('href={`/counterparties/${c.cp}`}');
	});

	it('does not load hedge contracts from trader counterparty detail', () => {
		const loader = readRoute('(protected)/counterparties/[id]/+page.ts');

		expect(loader).toContain("client.GET('/counterparties/{counterparty_id}'");
		expect(loader).not.toContain("client.GET('/contracts/hedge'");
		expect(loader).toContain('contracts: []');
	});

	it('filters risk-only analysis links by role in the sidebar', () => {
		const source = readFileSync(resolve(process.cwd(), 'src', 'lib', 'components', 'alcast', 'Sidebar.svelte'), 'utf8');

		expect(source).toContain("const canUseAnalysis = $derived(userRoles.includes('risk_manager') || userRoles.includes('auditor'))");
		expect(source).toContain('items: canUseAnalysis');
		expect(source).toContain('{#if section.items.length > 0}');
	});

	it('preserves variable-order entry prices in order creation payloads', () => {
		const source = readRoute('(protected)/orders/new/+page.svelte');

		expect(source).toContain("priceType === 'fixed'");
		expect(source).toContain('avg_entry_price: price');
		expect(source).toContain('pricing_convention');
		expect(source).toMatch(/priceType === 'fixed'[\s\S]+:\s*\{[\s\S]*avg_entry_price: price[\s\S]*pricing_convention/);
	});

	it('keeps partially settled contracts visible in list filters', () => {
		const source = readRoute('(protected)/contracts/+page.svelte');

		expect(source).toContain('OPEN_CONTRACT_STATUSES');
		expect(source).toContain("'partially_settled'");
		expect(source).toContain("status === 'partially_settled'");
	});

	it('clamps non-finite bar percentages before writing CSS width', () => {
		const source = readRoute('../lib/components/alcast/Bar.svelte');

		expect(source).toContain('Number.isFinite(pct) ? pct : 0');
		expect(source).not.toMatch(/Math\.max\(0,\s*pct\)/);
	});

	it('guards MTM analytics fixed prices before formatting or scenario math', () => {
		const source = readRoute('(protected)/analytics/mtm/+page.svelte');

		expect(source).toContain('function fmtPrice');
		expect(source).toContain('if (c.price == null) return');
		expect(source).toContain('function scenarioMtm(c: Contract): number | null');
		expect(source).not.toMatch(/<td class="num">\{c\.price\.toLocaleString/);
	});

	it('keeps latest review cleanup free of static finance residues', () => {
		const cashflow = readRoute('(protected)/cashflow/+page.svelte');
		const contractDetail = readRoute('(protected)/contracts/[id]/+page.svelte');
		const rfqCreate = readRoute('(protected)/rfq/new/+page.svelte');

		expect(cashflow).toContain('function fmtBrl');
		expect(cashflow).toContain('const cpConcentration = $derived');
		expect(cashflow).toContain('<Bar pct={r.pct}');
		expect(cashflow).not.toContain('amount_usd * 5.124');
		expect(cashflow).not.toContain("'JPM'");
		expect(contractDetail).toContain('let now = $state(Date.now())');
		expect(contractDetail).not.toContain('const today = new Date()');
		expect(contractDetail).toContain("c.status === 'partially_settled'");
		expect(contractDetail).toContain('href={`/rfq/${c.rfq_id}`}');
		expect(contractDetail).not.toContain("c.status === 'maturing'");
		expect(contractDetail).not.toContain('RFQ-2026-0177');
		expect(contractDetail).not.toContain('ORD-2026-0419');
		expect(contractDetail).not.toContain('APR-2026-0096');
		expect(contractDetail).not.toContain('A. Costa · Risco');
		expect(contractDetail).not.toContain("['27/05'");
		expect(contractDetail).not.toContain('2645.5');
		expect(contractDetail).not.toContain('9412.0');
		expect(contractDetail).not.toContain('2812.5');
		expect(contractDetail).not.toContain('26/05/2026 09:02');
		expect(contractDetail).not.toContain('notional * 0.1');
		expect(contractDetail).toContain('c.market_mid');
		expect(contractDetail).toContain('initialMarginRate');
		expect(contractDetail).toContain('Nenhum histórico de MTM carregado para este contrato');
		expect(rfqCreate).toContain('<dt>Alçada</dt><dd>Risk Manager</dd>');
		expect(rfqCreate).not.toContain('Trader · até US$ 5 M');
	});

	it('preflights RFQ recipients for WhatsApp channel availability', () => {
		const source = readRoute('(protected)/rfq/new/+page.svelte');

		expect(source).toContain('function canReceiveRfq');
		expect(source).toContain('cp.is_active !== false');
		expect(source).toContain('!!cp.whatsapp_phone');
		expect(source).toContain("cp.kyc_status === 'approved'");
		expect(source).not.toContain("cp.status === 'active'");
		expect(source).toContain('selectedCounterparties.every(canReceiveRfq)');
		expect(source).toContain('!canReceiveRfq(cp)');
	});

	it('defaults new counterparties to a trader-allowed type', () => {
		const source = readRoute('(protected)/counterparties/new/+page.svelte');

		expect(source).toContain("$state<'broker' | 'bank_br' | 'customer' | 'supplier'>('supplier')");
		expect(source).not.toContain('kyc_status:');
	});
});
