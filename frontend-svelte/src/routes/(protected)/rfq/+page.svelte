<script lang="ts">
	import { goto } from '$app/navigation';
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import DirectionBadge from '$lib/components/alcast/DirectionBadge.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	import Pager from '$lib/components/alcast/Pager.svelte';
	let { data } = $props();
	const rfqs = $derived(data.rfqs);
	type TabKey = 'all' | 'CREATED' | 'SENT' | 'QUOTED';
	const tab = $derived((data.tab ?? 'all') as TabKey);
	const totalLoaded = $derived(data.total ?? rfqs.length);
	const stateCount = (state: string) => rfqs.filter((rfq) => rfq.state === state).length;

	const TABS = $derived<[TabKey, string, number][]>([
		['all',     'Todas',    totalLoaded],
		['CREATED', 'Criadas',  stateCount('CREATED')],
		['SENT',    'Enviadas', stateCount('SENT')],
		['QUOTED',  'Cotadas',  stateCount('QUOTED')],
	]);

	function setTab(next: TabKey) {
		const query = next === 'all' ? '' : `?tab=${next}`;
		goto(`/rfq${query}`, { noScroll: true });
	}

	function fmtQty(qty: number, commodity: string): string {
		if (commodity === 'USDBRL') return 'US$ ' + (qty / 1_000_000).toFixed(1) + ' M';
		return qty.toLocaleString('pt-BR') + ' t';
	}

</script>

<div class="page">
	<PageHeader
		eyebrow="RFQ blotter"
		title="Solicitações de cotação"
		subtitle="Originar, monitorar e converter cotações com contrapartes aprovadas."
		meta={[`${totalLoaded} RFQ(s)`, `${stateCount('SENT')} enviadas`, `${stateCount('QUOTED')} cotadas`]}
		actions={[
			{ label: 'Exportar', icon: 'download', variant: 'secondary' },
			{ label: 'Nova RFQ', icon: 'plus', variant: 'primary', href: '/rfq/new' },
		]}
	/>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="RFQs carregadas" value={String(totalLoaded)} delta="/rfqs" deltaKind="flat"/>
		<Kpi label="Criadas" value={String(stateCount('CREATED'))} delta="state=CREATED" deltaKind="flat"/>
		<Kpi label="Enviadas" value={String(stateCount('SENT'))} delta="state=SENT" deltaKind="flat"/>
		<Kpi label="Cotadas" value={String(stateCount('QUOTED'))} delta="state=QUOTED" deltaKind="flat"/>
	</div>

	<div class="institutional-blotter">
	<Card noPad>
		<div class="tbl-tools">
			<div class="tabs-pill">
				{#each TABS as [k, l, c] (k)}
					<button type="button" class="tab" class:active={tab === k} onclick={() => setTab(k)}>
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
					<th>Status</th>
					<th>Criada</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each rfqs as r (r.id)}
					<tr>
						<td class="strong mono"><a href={`/rfq/${r.id}`}>{r.rfq}</a></td>
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
						<td><StatePill state={r.state}/></td>
						<td style="color: var(--muted); font-size: 12px;">{r.created}</td>
						<td><button type="button" class="btn btn-ghost btn-sm"><Icon name="chevronRight"/></button></td>
					</tr>
				{/each}
				{#if rfqs.length === 0}
					<tr>
							<td colspan="10">
							<EmptyState
								icon="rfq"
								title="Nenhuma RFQ para o filtro selecionado"
								message="Ajuste os filtros ou origine uma nova solicitação para a mesa."
								actionLabel="Nova RFQ"
								actionHref="/rfq/new"
							/>
						</td>
					</tr>
				{/if}
			</tbody>
		</table>
		<Pager from={rfqs.length > 0 ? 1 : 0} to={rfqs.length} total={totalLoaded}/>
	</Card>
	</div>
</div>
