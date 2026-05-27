<script lang="ts">
	import Card from '$lib/components/alcast/Card.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	let { data } = $props();
	const commodities = $derived(data.commodities);

	function marketKey(c: Record<string, any>): string {
		return `${c.code}:${c.settlement_date ?? c.date ?? c.ts ?? 'latest'}:${c.provider ?? ''}`;
	}

	function fmtPrice(c: Record<string, any>): string {
		if (c.last == null) return '—';
		const digits = c.code === 'USDBRL' ? 4 : 2;
		return c.last.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
	}

	function fmtDate(value: unknown): string {
		if (typeof value !== 'string' || !value) return '—';
		const date = value.slice(0, 10);
		const parts = date.split('-');
		return parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : value;
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Dados de mercado</h1>
			<div class="page-sub">Cash settlement prices carregados do backend</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="refresh"/>Atualizar</button>
		</div>
	</div>

	<div style="margin-bottom: 16px;">
		<Card title="Cash settlement" sub="Dados retornados por /market-data/westmetall/aluminum/cash-settlement/prices" noPad>
			<table class="tbl">
				<thead>
					<tr>
						<th>Commodity</th>
						<th>Data de settlement</th>
						<th class="num">Preço</th>
						<th>Unidade</th>
						<th>Provedor</th>
					</tr>
				</thead>
				<tbody>
					{#each commodities as c (marketKey(c))}
						<tr>
							<td class="strong">
								<CommodityChip code={c.code}/>
								<div style="font-size: 11px; color: var(--muted); font-weight: 400; margin-top: 1px;">{c.name}</div>
							</td>
							<td>{fmtDate(c.settlement_date ?? c.date)}</td>
							<td class="num strong">{fmtPrice(c)}</td>
							<td>{c.unit ?? '—'}</td>
							<td>{c.provider ?? '—'}</td>
						</tr>
					{/each}
					{#if commodities.length === 0}
						<tr><td colspan="5" class="tbl-empty">Nenhuma cotação carregada</td></tr>
					{/if}
				</tbody>
			</table>
		</Card>
	</div>
</div>
