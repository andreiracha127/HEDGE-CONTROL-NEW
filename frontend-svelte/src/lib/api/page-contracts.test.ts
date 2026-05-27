// @vitest-environment node
// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROUTES = resolve(process.cwd(), 'src', 'routes');

function read(rel: string): string {
	return readFileSync(resolve(ROUTES, rel), 'utf8');
}

describe('design-port route load contracts', () => {
	it('loads cashflow analytic and projection through typed openapi-fetch calls', () => {
		const source = read('(protected)/cashflow/+page.ts');
		expect(source).toContain("client.GET('/cashflow/analytic'");
		expect(source).toContain("client.GET('/cashflow/projection'");
		expect(source).toContain('as_of_date');
		expect(source).toContain('Failed to load cashflow analytic');
		expect(source).toContain('Failed to load cashflow projection');
	});

	it('loads MTM and P&L from existing backend endpoints without stale latest paths', () => {
		const mtm = read('(protected)/analytics/mtm/+page.ts');
		const pnl = read('(protected)/analytics/pnl/+page.ts');
		expect(mtm).toContain("client.GET('/contracts/hedge'");
		expect(pnl).toContain("client.POST('/deals/pnl-breakdown'");
		expect(mtm + pnl).not.toContain('/mtm/snapshots/latest');
		expect(mtm + pnl).not.toContain('/pl/snapshot/latest');
		expect(mtm + pnl).not.toContain('/pl/snapshots/latest');
	});

	it('loads RFQ detail evidence through GET-only route loads', () => {
		const source = read('(protected)/rfq/[id]/+page.ts');
		expect(source).toContain("client.GET('/rfqs/{rfq_id}'");
		expect(source).toContain("client.GET('/rfqs/{rfq_id}/quotes'");
		expect(source).toContain("client.GET('/rfqs/{rfq_id}/ranking'");
		expect(source).toContain("client.GET('/rfqs/{rfq_id}/trade-ranking'");
		expect(source).toContain("client.GET('/rfqs/{rfq_id}/state-events'");
		expect(source).toContain('normalizeRfqQuote');
		expect(source).not.toContain('backendGap');
	});

	it('wires RFQ detail visible actions to live RFQ mutations', () => {
		const source = read('(protected)/rfq/[id]/+page.svelte');
		expect(source).toContain("client.POST('/rfqs/{rfq_id}/actions/cancel'");
		expect(source).toContain("client.POST('/rfqs/{rfq_id}/actions/refresh'");
		expect(source).toContain("client.POST('/rfqs/{rfq_id}/actions/award'");
		expect(source).toMatch(/onclick=\{cancelRfq\}/);
		expect(source).toMatch(/onclick=\{refreshRfq\}/);
		expect(source).toMatch(/onclick=\{awardRfq\}/);
	});

	it('loads market data through the Westmetall settlement-price endpoint', () => {
		const source = read('(protected)/market-data/+page.ts');
		expect(source).toContain("client.GET('/market-data/westmetall/aluminum/cash-settlement/prices'");
		expect(source).toContain('Failed to load market data');
	});

	it('loads exposures from the list, net, and task contracts', () => {
		const source = read('(protected)/exposures/+page.ts');
		expect(source).toContain("client.GET('/exposures/list'");
		expect(source).toContain("client.GET('/exposures/net'");
		expect(source).toContain("client.GET('/exposures/tasks'");
	});

	it('loads workflow approvals from the canonical backend endpoint', () => {
		const source = read('(protected)/workflow-approvals/+page.ts');
		expect(source).toContain("client.GET('/workflow-approvals'");
		expect(source).toContain('Failed to load workflow approvals');
		expect(source).not.toContain('backendGap');
	});

	it('keeps workflow approval grant and reject wired to live backend mutations', () => {
		const source = read('(protected)/workflow-approvals/+page.svelte');
		expect(source).toContain("client.POST('/workflow-approvals/{approval_id}/grant'");
		expect(source).toContain("client.POST('/workflow-approvals/{approval_id}/reject'");
		expect(source).toContain('data.approvals');
		expect(source).not.toContain('APR-2026-0098');
	});
});

describe('design-port create affordances', () => {
	it('shows the new RFQ entry point and posts through client.POST /rfqs', () => {
		const loadSource = read('(protected)/rfq/new/+page.ts');
		const listSource = read('(protected)/rfq/+page.svelte');
		const createSource = read('(protected)/rfq/new/+page.svelte');
		expect(loadSource).toContain("client.GET('/orders'");
		expect(listSource).toContain('href="/rfq/new"');
		expect(listSource).toContain("goto(`/rfq${query}`");
		expect(createSource).toContain("client.POST('/rfqs'");
		expect(createSource).toContain('authStore.userSub');
		expect(createSource).toContain('invitations:');
		expect(createSource).toContain('value={order.id}');
		expect(createSource).not.toContain('PO-2026-1184');
	});

	it('shows the new counterparty entry point and posts the current CounterpartyCreate shape', () => {
		const listSource = read('(protected)/counterparties/+page.svelte');
		const createSource = read('(protected)/counterparties/new/+page.svelte');
		expect(listSource).toContain('href="/counterparties/new"');
		expect(listSource).toContain('Nova contraparte');
		expect(createSource).toContain("client.POST('/counterparties'");
		expect(createSource).toContain('type,');
		expect(createSource).toContain('name,');
		expect(createSource).toContain('country,');
		expect(createSource).not.toContain('kyc_status:');
	});

	it('posts order create through the purchase/sales endpoints', () => {
		const source = read('(protected)/orders/new/+page.svelte');
		expect(source).toContain("const endpoint = orderType === 'PO' ? '/orders/purchase' : '/orders/sales'");
		expect(source).toContain('client.POST(endpoint');
		expect(source).toContain("goto(`/orders/${created?.id}`)");
		expect(source).not.toContain('reference_month: reference');
	});

	it('uses UUID hrefs for live RFQ and counterparty detail routes', () => {
		const rfq = read('(protected)/rfq/+page.svelte');
		const counterparties = read('(protected)/counterparties/+page.svelte');
		expect(rfq).toContain('<a href={`/rfq/${r.id}`}>{r.rfq}</a>');
		expect(counterparties).toContain('<a href={`/counterparties/${cp.id}`}>');
		expect(counterparties).not.toContain('/counterparties/${cp.short}');
	});

	it('renders the loaded P&L breakdown instead of static prototype series', () => {
		const source = read('(protected)/analytics/pnl/+page.svelte');
		expect(source).toContain('let { data } = $props();');
		expect(source).toContain('data.pnl');
		expect(source).toContain('data.snapshotDate');
		expect(source).not.toContain('CT-2026-0111');
		expect(source).not.toContain('+US$ 517.045');
	});

	it('joins counterparty detail contracts by counterparty UUID', () => {
		const source = read('(protected)/counterparties/[id]/+page.svelte');
		expect(source).toContain('c.counterparty_id === cp.id');
		expect(source).not.toContain('contracts.filter((c) => c.cp === cp.short)');
	});

	it('renders MTM analytics rows with null-safe MTM placeholders', () => {
		const source = read('(protected)/analytics/mtm/+page.svelte');
		expect(source).toContain('function fmtMtm');
		expect(source).not.toContain('c.mtm.toLocaleString');
		expect(source).not.toContain('midFor');
		expect(source).not.toContain('const sliders');
		expect(source).not.toContain('const historical');
	});

	it('does not link normal orders to placeholder RFQs', () => {
		const source = read('(protected)/orders/+page.svelte');
		expect(source).toContain('{#if o.rfq_id}');
		expect(source).not.toContain('href={`/rfq/${o.rfq}`}');
	});

	it('requires the second swap leg before RFQ submit', () => {
		const source = read('(protected)/rfq/new/+page.svelte');
		expect(source).toContain('const legsReady = $derived(legFieldsReady(leg1) && (!showLeg2 || legFieldsReady(leg2)))');
		expect(source).toContain('!legsReady');
	});

	it('filters order and contract tabs against displayed rows', () => {
		const orders = read('(protected)/orders/+page.svelte');
		const contracts = read('(protected)/contracts/+page.svelte');
		expect(orders).toContain('const filteredOrders = $derived');
		expect(orders).toContain('{#each filteredOrders as o (o.id)}');
		expect(contracts).toContain('const filteredContracts = $derived');
		expect(contracts).toContain('{#each filteredContracts as c (c.id)}');
	});

	it('keeps RFQ list counters and pagination derived from loaded data', () => {
		const source = read('(protected)/rfq/+page.svelte');
		expect(source).toContain('value={String(totalLoaded)}');
		expect(source).toContain('stateCount(');
		expect(source).toContain('total={totalLoaded}');
		expect(source).not.toContain('value="3"');
		expect(source).not.toContain('total={184}');
	});
});
