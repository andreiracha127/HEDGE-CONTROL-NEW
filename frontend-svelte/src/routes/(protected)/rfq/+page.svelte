<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import DirectionBadge from '$lib/components/alcast/DirectionBadge.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import Pager from '$lib/components/alcast/Pager.svelte';
	let { data } = $props();
	const rfqs = $derived(data.rfqs);

	let tab = $state<'all' | 'CREATED' | 'SENT' | 'QUOTED'>('all');

	const TABS: [typeof tab, string, number][] = [
		['all',     'Todas',    184],
		['CREATED', 'Criadas',    1],
		['SENT',    'Enviadas',   2],
		['QUOTED',  'Cotadas',    4],
	];

	function fmtQty(qty: number, commodity: string): string {
		if (commodity === 'USDBRL') return 'US$ ' + (qty / 1_000_000).toFixed(1) + ' M';
		return qty.toLocaleString('pt-BR') + ' t';
	}

	function fmtBest(best: number | null, commodity: string): string {
		if (best == null) return '—';
		const digits = commodity === 'USDBRL' ? 4 : 2;
		return best.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">RFQ · Solicitações de cotação</h1>
			<div class="page-sub">Originar cotações com contrapartes e converter em ordens</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Exportar</button>
			<a href="/rfq/new" class="btn btn-primary"><Icon name="plus"/>Nova RFQ</a>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="RFQ abertas"             value="3"          delta="2 aguardando cotação"  deltaKind="flat"/>
		<Kpi label="Tempo médio à cotação"   value="00:18"      unit="min" delta="−00:02 vs semana" deltaKind="pos"/>
		<Kpi label="Hit ratio (mês)"         value="68,4"       unit="%" delta="+3,2 pp" deltaKind="pos"/>
		<Kpi label="Volume em cotação"       value="US$ 4,9 M"  delta="3 commodities"/>
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
			<button type="button" class="chip"><Icon name="filter"/>Commodity</button>
			<button type="button" class="chip"><Icon name="filter"/>Intenção</button>
			<button type="button" class="chip"><Icon name="filter"/>Período</button>
		</div>

		<table class="tbl">
			<thead>
				<tr>
					<th>RFQ</th>
					<th>Intenção</th>
					<th>Commodity</th>
					<th>Lado</th>
					<th class="num">Quantidade</th>
					<th>Janela</th>
					<th class="num">Cotações</th>
					<th class="num">Melhor</th>
					<th>Status</th>
					<th>Criada</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each rfqs as r (r.id)}
					<tr>
						<td class="strong mono"><a href={`/rfq/${r.id}`}>{r.id}</a></td>
						<td>
							<Badge kind={r.intent === 'COMMERCIAL_HEDGE' ? 'info' : 'neutral'}>
								{r.intent === 'COMMERCIAL_HEDGE' ? 'Hedge comercial' : r.intent === 'SPREAD' ? 'Spread' : 'Posição global'}
							</Badge>
						</td>
						<td><CommodityChip code={r.commodity}/></td>
						<td><DirectionBadge dir={r.direction}/></td>
						<td class="num">{fmtQty(r.qty, r.commodity)}</td>
						<td>{r.window}</td>
						<td class="num">{r.quotes}</td>
						<td class="num strong">{fmtBest(r.best, r.commodity)}</td>
						<td><StatePill state={r.state}/></td>
						<td style="color: var(--muted); font-size: 12px;">{r.created}</td>
						<td><button type="button" class="btn btn-ghost btn-sm"><Icon name="chevronRight"/></button></td>
					</tr>
				{/each}
			</tbody>
		</table>
		<Pager from={1} to={7} total={184}/>
	</Card>
</div>
