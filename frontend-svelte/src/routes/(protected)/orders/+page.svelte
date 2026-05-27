<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import DirectionBadge from '$lib/components/alcast/DirectionBadge.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import Pager from '$lib/components/alcast/Pager.svelte';
	import { formatPrice, formatQuantityMT } from '$lib/utils/format';
	let { data } = $props();
	const orders = $derived(data.orders);

	let tab = $state<'all' | 'filled' | 'partial' | 'pending' | 'cancelled'>('all');
	let dir = $state<'all' | 'buy' | 'sell'>('all');

	const TABS: [typeof tab, string, number][] = [
		['all',       'Todas',      47],
		['filled',    'Liquidadas', 38],
		['partial',   'Parciais',    3],
		['pending',   'Pendentes',   4],
		['cancelled', 'Canceladas',  2],
	];

	function fmtQty(order: Record<string, any>): string {
		if (order.commodity === 'USDBRL') return formatPrice(order.quantity_mt ?? order.qty, 'USD');
		return `${formatQuantityMT(order.quantity_mt ?? order.qty)} MT`;
	}

	function fmtOrderPrice(order: Record<string, any>): string {
		return formatPrice(order.avg_entry_price ?? order.price, order.commodity === 'USDBRL' ? 'USD/BRL' : 'USD/MT');
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Ordens</h1>
			<div class="page-sub">Execução de hedges e fechamento com contrapartes</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Exportar</button>
			<a href="/orders/new" class="btn btn-primary"><Icon name="plus"/>Nova ordem</a>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Ordens hoje"     value="24"        delta="+4 vs ontem"           deltaKind="pos"/>
		<Kpi label="Volume D"        value="US$ 24,1 M" delta="+US$ 3,2 M vs ontem"   deltaKind="pos"/>
		<Kpi label="Preço médio AL"  value="2.632,15"  unit="USD/t" delta="vs mid 2.635,00 LME" deltaKind="pos"/>
		<Kpi label="Slippage médio"  value="−0,11"     unit="%" delta="dentro do limite −0,25%" deltaKind="pos"/>
	</div>

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
			<div class="radio-group">
				<button type="button" class:active={dir === 'all'} onclick={() => (dir = 'all')}>Todas</button>
				<button type="button" class:active={dir === 'buy'} class:buy={dir === 'buy'} onclick={() => (dir = 'buy')}>Compra</button>
				<button type="button" class:active={dir === 'sell'} class:sell={dir === 'sell'} onclick={() => (dir = 'sell')}>Venda</button>
			</div>
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
				{#each orders as o (o.id)}
					<tr style="cursor: default;">
						<td class="strong mono">{o.id}</td>
						<td class="mono"><a href={`/rfq/${o.rfq}`}>{o.rfq}</a></td>
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
			</tbody>
		</table>
		<Pager from={1} to={8} total={47}/>
	</Card>
</div>
