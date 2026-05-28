<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import DirectionBadge from '$lib/components/alcast/DirectionBadge.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	import Pager from '$lib/components/alcast/Pager.svelte';
	import { formatPrice, formatQuantityMT } from '$lib/utils/format';
	let { data } = $props();
	const orders = $derived(data.orders);

	let tab = $state<'all' | 'buy' | 'sell'>('all');

	const directionCount = (direction: string) =>
		orders.filter((order) => String(order.direction ?? '').toLowerCase() === direction).length;
	const totalVolume = $derived(
		orders.reduce((sum, order) => {
			const qty = Number(order.quantity_mt ?? order.qty);
			const price = Number(order.avg_entry_price ?? order.price);
			return Number.isFinite(qty) && Number.isFinite(price) ? sum + Math.abs(qty * price) : sum;
		}, 0),
	);
	const TABS = $derived<[typeof tab, string, number][]>([
		['all',  'Todas',   orders.length],
		['buy',  'Compras', directionCount('buy')],
		['sell', 'Vendas',  directionCount('sell')],
	]);
	const filteredOrders = $derived(
		orders.filter((order) => {
			const direction = String(order.direction ?? '').toLowerCase();
			return tab === 'all' || direction === tab;
		}),
	);

	function fmtQty(order: Record<string, any>): string {
		if (order.commodity === 'USDBRL') return formatPrice(order.quantity_mt ?? order.qty, 'USD');
		return `${formatQuantityMT(order.quantity_mt ?? order.qty)} MT`;
	}

	function fmtOrderPrice(order: Record<string, any>): string {
		return formatPrice(order.avg_entry_price ?? order.price, order.commodity === 'USDBRL' ? 'USD/BRL' : 'USD/MT');
	}

	function fmtUsd(value: number): string {
		return `US$ ${(value / 1_000_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} M`;
	}
</script>

<div class="page">
	<PageHeader
		eyebrow="Execution blotter"
		title="Ordens"
		subtitle="Execução de hedges, status de liquidação e vínculo com RFQs."
		meta={[`${orders.length} ordem(ns)`, `Volume ${fmtUsd(totalVolume)}`, `${filteredOrders.length} no filtro`]}
		actions={[
			{ label: 'Exportar', icon: 'download', variant: 'secondary' },
			{ label: 'Nova ordem', icon: 'plus', variant: 'primary', href: '/orders/new' },
		]}
	/>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Ordens carregadas" value={String(orders.length)} delta="/orders" deltaKind="flat"/>
		<Kpi label="Volume carregado" value={fmtUsd(totalVolume)} delta="quantidade × preço" deltaKind="flat"/>
		<Kpi label="Compras" value={String(directionCount('buy'))} delta="direção buy" deltaKind="flat"/>
		<Kpi label="Vendas" value={String(directionCount('sell'))} delta="direção sell" deltaKind="flat"/>
	</div>

	<div class="institutional-blotter">
	<Card noPad>
		<div class="tbl-tools">
			<div class="tabs-pill">
				{#each TABS as [k, l, c] (k)}
					<button type="button" class="tab" class:active={tab === k} onclick={() => (tab = k)}>
						{l} <span style="color: var(--muted-2); margin-left: 4px;">{c}</span>
					</button>
				{/each}
			</div>
			<div class="sp"></div>
			<button type="button" class="chip"><Icon name="filter"/>Commodity</button>
			<button type="button" class="chip"><Icon name="filter"/>Contraparte</button>
			<button type="button" class="chip"><Icon name="filter"/>Período</button>
		</div>

		<table class="tbl">
			<thead>
				<tr>
					<th>Ordem</th>
					<th>RFQ</th>
					<th>Commodity</th>
					<th>Lado</th>
					<th class="num">Quantidade</th>
					<th class="num">Preço (USD)</th>
					<th>Contraparte</th>
					<th>Liquidação</th>
					<th>Status</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each filteredOrders as o (o.id)}
					<tr style="cursor: default;">
						<td class="strong mono">{o.id}</td>
						<td class="mono">
							{#if o.rfq_id}
								<a href={`/rfq/${o.rfq_id}`}>{o.rfq}</a>
							{:else}
								<span style="color: var(--muted);">—</span>
							{/if}
						</td>
						<td><CommodityChip code={o.commodity}/></td>
						<td><DirectionBadge dir={o.direction}/></td>
						<td class="num">{fmtQty(o)}</td>
						<td class="num strong">{fmtOrderPrice(o)}</td>
						<td>{o.cp}</td>
						<td>{o.settlement ? o.settlement.split('-').reverse().join('/') : '—'}</td>
						<td><StatePill state={o.status}/></td>
						<td>
							<a href={`/orders/${o.id}`} data-testid="orders-detail-link" class="btn btn-ghost btn-sm">
								<Icon name="chevronRight"/>
							</a>
						</td>
					</tr>
				{/each}
				{#if filteredOrders.length === 0}
					<tr>
						<td colspan="10">
							<EmptyState
								icon="clipboard"
								title="Nenhuma ordem para o filtro selecionado"
								message="Ajuste direção ou filtros de mercado para reabrir o blotter."
								actionLabel="Nova ordem"
								actionHref="/orders/new"
							/>
						</td>
					</tr>
				{/if}
			</tbody>
		</table>
		<Pager from={filteredOrders.length > 0 ? 1 : 0} to={filteredOrders.length} total={filteredOrders.length}/>
	</Card>
	</div>
</div>
