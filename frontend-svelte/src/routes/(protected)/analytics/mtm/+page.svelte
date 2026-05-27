<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	type Contract = Record<string, any>;
	let { data } = $props();
	const contracts = $derived(data.contracts);
	const mtmValues = $derived(contracts.map((contract) => Number(contract.mtm)).filter(Number.isFinite));
	const aggregateMtm = $derived(mtmValues.length ? mtmValues.reduce((sum, value) => sum + value, 0) : null);
	const contractsWithMtm = $derived(mtmValues.length);

	function priceDigits(c: Contract): number {
		return c.commodity === 'USDBRL' ? 4 : 2;
	}

	function fmtPrice(c: Contract): string {
		if (c.price == null) return '—';
		return c.price.toLocaleString('en-US', { minimumFractionDigits: priceDigits(c), maximumFractionDigits: priceDigits(c) });
	}

	function fmtQty(c: Contract): string {
		if (c.qty == null) return '—';
		if (c.commodity === 'USDBRL') return (c.qty / 1_000_000).toFixed(1) + ' M';
		return c.qty.toLocaleString('pt-BR');
	}

	function fmtMtm(value: number | null | undefined): string {
		if (value == null) return '—';
		return `${value >= 0 ? '+' : ''}${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Mark-to-market e cenário</h1>
			<div class="page-sub">Marcação a mercado oficial e simulação what-if</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="refresh"/>Re-marcar</button>
		</div>
	</div>

	<div class="kpi-row cols-3" style="margin-bottom: 16px;">
		<Kpi label="Contratos carregados" value={String(contracts.length)} delta="/contracts/hedge" deltaKind="flat"/>
		<Kpi label="Contratos com MTM" value={String(contractsWithMtm)} delta="mtm_value presente" deltaKind="flat"/>
		<Kpi label="MTM agregado" value={aggregateMtm == null ? '—' : fmtMtm(aggregateMtm)} delta="somente payload backend" deltaKind={aggregateMtm == null || aggregateMtm >= 0 ? 'pos' : 'neg'}/>
	</div>

	<div>
		<Card title="Marcação por contrato" sub="MTM carregado do backend" noPad>
			<table class="tbl">
				<thead>
					<tr>
						<th>Contrato</th>
						<th>Commodity</th>
						<th class="num">Qtd</th>
						<th class="num">Preço fixo</th>
						<th class="num">MTM (USD)</th>
					</tr>
				</thead>
				<tbody>
					{#each contracts as c (c.id)}
						<tr>
							<td class="strong mono">{c.id}</td>
							<td><CommodityChip code={c.commodity}/></td>
							<td class="num">{fmtQty(c)}</td>
							<td class="num">{fmtPrice(c)}</td>
							<td class="num strong" style="color: {c.mtm == null ? 'var(--muted)' : c.mtm >= 0 ? 'var(--pos)' : 'var(--neg)'};">
								{fmtMtm(c.mtm)}
							</td>
						</tr>
					{/each}
					{#if contracts.length === 0}
						<tr><td colspan="5" class="tbl-empty">Nenhum contrato carregado para marcação</td></tr>
					{/if}
				</tbody>
			</table>
		</Card>
	</div>
</div>
