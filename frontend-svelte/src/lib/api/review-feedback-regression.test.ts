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
		expect(source).toMatch(/disabled:\s*submitting \|\| !quantityValidation\.ok \|\| selectedCounterparties\.length === 0 \|\| !legsReady \|\| !datesReady \|\| !intentReady \|\| !recipientsReady \|\| !rfqRoleReady/);
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

	it('keeps RFQ detail ranking, notional, and history tied to backend evidence', () => {
		const source = readRoute('(protected)/rfq/[id]/+page.svelte');
		const loader = readRoute('(protected)/rfq/[id]/+page.ts');

		expect(loader).toContain("rfq.intent === 'SPREAD'");
		expect(loader).toContain('spreadBest.buy_quote?.id');
		expect(source).toContain('US$ {(rfq.qty * best.price).toLocaleString');
		expect(source).not.toContain('const mid =');
		expect(source).not.toContain('pnlVsMid');
		expect(source).toContain("const canManageRfq = $derived(authStore.hasRole('risk_manager'))");
		expect(source).toContain("rfq.state === 'QUOTED' && Boolean(data.canAwardRfq)");
		expect(source).toContain('const stateEvents = $derived(data.stateEvents ?? [])');
		expect(source).toContain('const timelineEvents = $derived');
		expect(source).toContain('stateEvents.map((event)');
		expect(source).toContain('<ExecutionTimeline events={timelineEvents}');
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
		const schema = readFileSync(resolve(process.cwd(), '..', 'backend', 'app', 'schemas', 'orders.py'), 'utf8');

		expect(source).toContain('const submittedNotes = $derived.by');
		expect(source).toContain('Referencia ERP/SAP');
		expect(source).toContain('notes: submittedNotes');
		expect(source).toContain('external_reference: reference');
		expect(schema).toContain('external_reference: str | None');
	});

	it('resolves contract counterparties through stable ids', () => {
		const source = readRoute('(protected)/contracts/[id]/+page.svelte');

		expect(source).toContain('x.id === c.counterparty_id');
		expect(source).toContain('const cpId = $derived');
		expect(source).toContain('href={`/counterparties/${cpId}`}');
		expect(source).not.toContain('href={`/counterparties/${c.cp}`}');
	});

	it('loads counterparty detail contracts from the backend instead of keeping prototype operations', () => {
		const loader = readRoute('(protected)/counterparties/[id]/+page.ts');
		const source = readRoute('(protected)/counterparties/[id]/+page.svelte');

		expect(loader).toContain("client.GET('/counterparties/{counterparty_id}'");
		expect(loader).toContain("client.GET('/contracts/hedge'");
		expect(loader).toContain('items<Record<string, any>>(optionalData(contractsResult)).map(normalizeContract)');
		expect(source).toContain('{#each cpContracts as contract');
		expect(source).not.toContain('RFQ-2026-0184');
	});

	it('filters risk-only analysis links by role in the sidebar', () => {
		const source = readFileSync(resolve(process.cwd(), 'src', 'lib', 'components', 'alcast', 'Sidebar.svelte'), 'utf8');

		expect(source).toContain("const canUseAnalysis = $derived(userRoles.includes('risk_manager') || userRoles.includes('auditor'))");
		expect(source).toContain('const canUseRiskWorkflows = $derived');
		expect(source).toContain('items: canUseAnalysis');
		expect(source).toContain('{#if section.items.length > 0}');
		expect(source).toContain("...(canUseRiskWorkflows ? [");
	});

	it('preserves variable-order entry prices in order creation payloads', () => {
		const source = readRoute('(protected)/orders/new/+page.svelte');

		expect(source).toContain("priceType === 'fixed'");
		expect(source).toContain('avg_entry_price: price');
		expect(source).toContain('pricing_convention');
		expect(source).toContain('variablePricingPayload');
		expect(source).toContain('reference_month: avgReferenceMonth');
		expect(source).toContain('observation_date_start: observationStart');
		expect(source).toContain('fixing_date: fixingDate');
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

	it('guards MTM analytics fixed prices and removes scenario math without backend contract', () => {
		const source = readRoute('(protected)/analytics/mtm/+page.svelte');

		expect(source).toContain('function fmtPrice');
		expect(source).toContain('if (c.price == null) return');
		expect(source).toContain('const mtmValues = $derived');
		expect(source).not.toContain('function scenarioMtm');
		expect(source).not.toContain('midFor');
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
		expect(contractDetail).toContain('Nenhum histórico de MTM carregado');
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

	it('keeps commercial order pricing conventions aligned to backend enum values', () => {
		const source = readRoute('(protected)/orders/new/+page.svelte');

		expect(source).toContain("let pricingConv = $state<'AVG' | 'AVGInter' | 'C2R'>('AVG')");
		expect(source).toContain('pricing_convention: pricingConv');
		expect(source).toContain('const formReady = $derived');
		expect(source).toContain('hasPrice && pricingWindowReady');
		expect(source).toContain('disabled: submitting || !formReady');
		expect(source).toContain('<option value="AVG">');
		expect(source).toContain('<option value="AVGInter">');
		expect(source).toContain('<option value="C2R">');
		expect(source).not.toContain("pricingConv === 'LME-AVG-M' ? 'AVG' : 'C2R'");
		expect(source).not.toContain('LME-OFFICIAL');
	});

	it('allows fixed RFQ legs without fixing dates when another leg supplies the delivery window', () => {
		const source = readRoute('(protected)/rfq/new/+page.svelte');

		expect(source).toContain('const deliveryWindow = $derived(legDeliveryWindow(leg1) ?? (showLeg2 ? legDeliveryWindow(leg2) : null))');
		expect(source).toContain("if (leg.orderType === 'Limit' && !leg.limitPrice) return false");
		expect(source).toContain("if (leg.priceType === 'Fix') return true");
		expect(source).not.toContain("if (leg.priceType === 'Fix') return !!leg.fixingDate");
	});

	it('submits commercial order counterparties by UUID instead of short name', () => {
		const source = readRoute('(protected)/orders/new/+page.svelte');

		expect(source).toContain('const selectedCounterparty = counterparties.find((item) => item.id === cp)');
		expect(source).toContain('<option value={c.id}>{c.name} ({c.short})</option>');
		expect(source).toContain('const selectedCounterpartyLabel = $derived');
		expect(source).not.toContain('item.short === cp || item.id === cp');
		expect(source).not.toContain('<option value={c.short}>');
	});

	it('includes date-only cashflows from today in the 90-day KPI window', () => {
		const source = readRoute('(protected)/cashflow/+page.svelte');

		expect(source).toContain('function startOfLocalDay');
		expect(source).toContain('const start = startOfLocalDay(new Date()).getTime()');
		expect(source).toContain('timestamp >= start');
		expect(source).not.toContain('timestamp >= now');
	});

	it('keys dashboard market quotes by quote identity rather than display code only', () => {
		const source = readRoute('(protected)/+page.svelte');

		expect(source).toContain('function marketKey');
		expect(source).toContain('{#each commodities as c (marketKey(c))}');
		expect(source).not.toContain('{#each commodities as c (c.code)}');
	});

	it('hides risk-only exposure navigation for trader-only users', () => {
		const source = readFileSync(resolve(process.cwd(), 'src', 'lib', 'components', 'alcast', 'Sidebar.svelte'), 'utf8');

		expect(source).toContain("...(canUseAnalysis ? [{ key: 'exposures'");
		expect(source).not.toContain("\t\t\t\t{ key: 'exposures', label: 'Exposições', icon: 'layers', badge: null, href: '/exposures' },");
	});

	it('defaults new counterparties to a trader-allowed type', () => {
		const source = readRoute('(protected)/counterparties/new/+page.svelte');

		expect(source).toContain("type CounterpartyType = 'broker' | 'bank_br' | 'customer' | 'supplier'");
		expect(source).toContain("let type = $state<CounterpartyType>('supplier')");
		expect(source).toContain("canCreateFinancialCounterparties ? ['broker', 'bank_br', 'customer', 'supplier'] : ['customer', 'supplier']");
		expect(source).toContain('{#each allowedTypes as option (option)}');
		expect(source).not.toContain('kyc_status:');
	});

	it('keeps route-data derived values tied to backend semantics', () => {
		const source = readFileSync(resolve(process.cwd(), 'src', 'lib', 'alcast', 'route-data.ts'), 'utf8');

		expect(source).toContain('response?: { status?: number }');
		expect(source).toContain('result.response?.status ?? result.error.status ?? result.error.statusCode ?? 502');
		expect(source).toContain('quotes: row.quote_count ?? row.quotes ?? row.submitted_quote_count ?? 0');
		expect(source).not.toContain('quotes: row.invitations?.length');
		expect(source).not.toContain('best: row.notional_usd_at_best');
		expect(source).toContain('function signedExposureAmount');
		expect(source).toContain("['long', 'buy', 'purchase', 'po']");
		expect(source).toContain('const monthPart =');
		expect(source).toContain('monthPart(row.delivery_date_start ?? row.delivery_window_start ?? row.as_of_date ?? row.exposure_date)');
	});

	it('gates header CTAs by the backend roles that can execute the mutation', () => {
		const whatIf = readRoute('(protected)/analytics/what-if/+page.svelte');
		const orders = readRoute('(protected)/orders/+page.svelte');
		const counterparties = readRoute('(protected)/counterparties/+page.svelte');
		const appShell = readFileSync(resolve(process.cwd(), 'src', 'lib', 'components', 'alcast', 'AppShell.svelte'), 'utf8');
		const topbar = readFileSync(resolve(process.cwd(), 'src', 'lib', 'components', 'alcast', 'Topbar.svelte'), 'utf8');
		const layout = readRoute('+layout.ts');

		expect(whatIf).toContain('const scenarioActions = $derived.by');
		expect(whatIf).toContain('allowed');
		expect(whatIf).toContain('actions={scenarioActions}');
		expect(orders).toContain("const canCreateOrders = $derived(authStore.hasRole('trader'))");
		expect(orders).toContain('actions={headerActions}');
		expect(counterparties).toContain("const canCreateCounterparties = $derived(authStore.hasAnyRole('trader', 'risk_manager'))");
		expect(counterparties).toContain('actions={headerActions}');
		expect(appShell).toContain('<Topbar {crumbs} {userRoles}/>');
		expect(topbar).toContain('userRoles = [] as string[]');
		expect(topbar).toContain("const canCreateOrders = $derived(userRoles.includes('trader'))");
		expect(topbar).toContain('const commands = $derived.by');
		expect(layout).toContain('const countList = async');
		expect(layout).toContain('limit: 200, cursor');
	});

	it('omits unavailable RFQ best-price metrics from the list blotter', () => {
		const source = readRoute('(protected)/rfq/+page.svelte');

		expect(source).toContain("`${stateCount('QUOTED')} cotadas`");
		expect(source).toContain('<Kpi label="Cotadas"');
		expect(source).not.toContain('quotedNotional');
		expect(source).not.toContain('fmtBest');
		expect(source).not.toContain('r.best');
	});

	it('does not synthesize RFQ winners outside backend ranking', () => {
		const loader = readRoute('(protected)/rfq/[id]/+page.ts');

		expect(loader).toContain('const tradeRankingRows = Array.isArray(tradeRanking?.ranking) ? tradeRanking.ranking : []');
		expect(loader).toContain('const rankedQuoteIds = tradeRankingRows');
		expect(loader).toContain('const canAwardRfq = Boolean(spreadBest?.buy_quote?.id && spreadBest?.sell_quote?.id) || bestQuoteIds.length > 0');
		expect(loader).toContain('const rankedQuotes = activeQuotes');
		expect(loader).not.toContain("rfq.direction === 'SELL' ? right - left : left - right");
	});

	it('does not reset the shared full-stack E2E database from backend pytest fixtures', () => {
		const source = readFileSync(resolve(process.cwd(), '..', 'backend', 'tests', 'conftest.py'), 'utf8');

		expect(source).toContain('if os.environ.get("E2E_FULL_STACK") == "1":');
		expect(source).toContain('yield');
		expect(source).toContain('Base.metadata.drop_all(bind=engine)');
	});
});
