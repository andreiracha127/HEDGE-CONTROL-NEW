<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import Pager from '$lib/components/alcast/Pager.svelte';
	type Contract = Record<string, any>;
	let { data } = $props();
	const contracts = $derived(data.contracts);

	let tab = $state<'active' | 'maturing' | 'settled'>('active');

	const TABS: [typeof tab, string, number][] = [
		['active',   'Ativos',     84],
		['maturing', 'Vencendo',    9],
		['settled',  'Liquidados', 412],
	];

	function fmtQty(c: Contract): string {
		if (c.qty == null) return '—';
		if (c.commodity === 'USDBRL') return 'US$ ' + (c.qty / 1_000_000).toFixed(1) + ' M';
		return c.qty.toLocaleString('pt-BR') + ' t';
	}

	function fmtPrice(c: Contract): string {
		if (c.price == null) return '—';
		const digits = c.commodity === 'USDBRL' ? 4 : 2;
		return c.price.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
	}

	function fmtDate(value: string | null | undefined): string {
		return value ? value.split('-').reverse().join('/') : '—';
	}

	function fmtMtm(value: number | null | undefined): string {
		if (value == null) return '—';
		return `${value >= 0 ? '+' : ''}${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Contratos</h1>
			<div class="page-sub">Posições derivativas ativas e vencendo</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Exportar</button>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Contratos ativos"                  value="84"           delta="9 vencendo em 30d"        deltaKind="flat"/>
		<Kpi label="Notional total"                    value="US$ 192,4 M"  delta="+US$ 24,1 M MTD"          deltaKind="pos"/>
		<Kpi label="MTM agregado"                      value="+US$ 204.165" delta="+US$ 18.460 1d"           deltaKind="pos"/>
		<Kpi label="Contratos no vencimento (30d)"     value="9"            delta="Notional US$ 14,2 M"      deltaKind="flat"/>
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
			<button type="button" class="chip"><Icon name="filter"/>Contraparte</button>
			<button type="button" class="chip"><Icon name="filter"/>Vencimento</button>
		</div>

		<table class="tbl">
			<thead>
				<tr>
					<th>Contrato</th>
					<th>Commodity</th>
					<th>Tipo</th>
					<th>Pernas</th>
					<th class="num">Qtd</th>
					<th class="num">Preço fixo</th>
					<th>Contraparte</th>
					<th>Vencimento</th>
					<th class="num">MTM (USD)</th>
					<th>Status</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each contracts as c (c.id)}
					<tr>
						<td class="strong mono"><a href={`/contracts/${c.id}`}>{c.id}</a></td>
						<td><CommodityChip code={c.commodity}/></td>
						<td>{c.type}</td>
						<td>
							<span class="row gap-2" style="font-size: 11px;">
								<Badge kind={c.fixed_leg === 'buy' ? 'pos' : 'neg'}>{c.fixed_leg === 'buy' ? 'Compra' : 'Venda'} fixa</Badge>
								<span style="color: var(--muted);">×</span>
								<Badge kind="neutral">{c.var_leg === 'buy' ? 'Compra' : 'Venda'} var.</Badge>
							</span>
						</td>
						<td class="num">{fmtQty(c)}</td>
						<td class="num strong">{fmtPrice(c)}</td>
						<td>{c.cp}</td>
						<td>{fmtDate(c.settle)}</td>
						<td class="num strong" style="color: {c.mtm == null ? 'var(--muted)' : c.mtm >= 0 ? 'var(--pos)' : 'var(--neg)'};">
							{fmtMtm(c.mtm)}
						</td>
						<td><StatePill state={c.status}/></td>
						<td><button type="button" class="btn btn-ghost btn-sm"><Icon name="chevronRight"/></button></td>
					</tr>
				{/each}
			</tbody>
		</table>
		<Pager from={1} to={9} total={84}/>
	</Card>
</div>
