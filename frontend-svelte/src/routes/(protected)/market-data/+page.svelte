<script lang="ts">
	import Card from '$lib/components/alcast/Card.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	let { data } = $props();
	const commodities = $derived(data.commodities);

	function marketKey(c: Record<string, any>): string {
		return `${c.code}:${c.settlement_date ?? c.date ?? c.ts ?? 'latest'}:${c.provider ?? ''}`;
	}

	function fmtPrice(c: Record<string, any>): string {
		if (c.last == null) return '—';
		const digits = c.code === 'USDBRL' ? 4 : 2;
		return c.last.toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
	}

	function fmtDate(value: unknown): string {
		if (typeof value !== 'string' || !value) return '—';
		const date = value.slice(0, 10);
		const parts = date.split('-');
		return parts.length === 3 ? `${parts[2]}/${parts[1]}/${parts[0]}` : value;
	}
</script>

<div class="page">
	<PageHeader
		eyebrow="Controle de mercado"
		title="Dados de mercado"
		subtitle="Cotações oficiais para marcação, execução e conciliação."
		meta={[`${commodities.length} cotação(ões)`, 'Liquidação oficial', 'Fonte: Market Data']}
		actions={[
			{ label: 'Atualizar', icon: 'refresh', variant: 'secondary' },
		]}
	/>

	<div class="institutional-monitoring">
	<div style="margin-bottom: 16px;">
		<Card title="Preços de liquidação" sub="Cotações oficiais para marcação" noPad>
			<table class="tbl">
				<thead>
					<tr>
						<th>Commodity</th>
						<th>Data de liquidação</th>
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
						<tr>
							<td colspan="5">
								<EmptyState
									icon="globe"
									title="Nenhuma cotação disponível"
									message="Nenhuma cotação disponível para os filtros selecionados."
								/>
							</td>
						</tr>
					{/if}
				</tbody>
			</table>
		</Card>
	</div>
	</div>
</div>
