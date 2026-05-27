<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	let { data } = $props();
	const cashflow = $derived(data.cashflow);

	interface MonthAgg {
		inflow: number;
		outflow: number;
		count: number;
	}

	const byMonth = $derived.by(() => {
		const map: Record<string, MonthAgg> = {};
		for (const c of cashflow) {
			const k = c.date.slice(0, 7);
			if (!map[k]) map[k] = { inflow: 0, outflow: 0, count: 0 };
			if (c.amount_usd > 0) map[k].inflow += c.amount_usd;
			else map[k].outflow += c.amount_usd;
			map[k].count++;
		}
		return map;
	});

	const months = $derived(Object.keys(byMonth).sort());
	const maxAbs = $derived(
		Math.max(1, ...months.map((m) => Math.max(byMonth[m].inflow, -byMonth[m].outflow))),
	);

	const cpConcentration = [
		{ cp: 'ITAU', v:  40425, pct: 19 },
		{ cp: 'JPM',  v: 123250, pct: 57 },
		{ cp: 'BTG',  v:  17000, pct:  8 },
		{ cp: 'SANT', v:  15300, pct:  7 },
		{ cp: 'BRAD', v:  21148, pct: 10 },
	];
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Fluxo de caixa projetado</h1>
			<div class="page-sub">Liquidações financeiras de derivativos · próximos 12 meses</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Exportar</button>
			<button type="button" class="btn btn-primary">Sincronizar com SAP</button>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Inflow projetado (90d)"  value="+US$ 216.865"         delta="9 liquidações"             deltaKind="pos"/>
		<Kpi label="Outflow projetado (90d)" value="−US$ 1.260"           delta="1 liquidação"              deltaKind="neg"/>
		<Kpi label="Net (90d)"               value="+US$ 215.605"         delta="vs mês anterior +18 %"     deltaKind="pos"/>
		<Kpi label="Próxima liquidação"      value="29/05"                delta="CT-2026-0110 · BTG"        deltaKind="flat"/>
	</div>

	<div class="grid-7-5" style="margin-bottom: 16px;">
		<Card title="Linha do tempo" sub="Líquido por mês · USD">
			<div style="position: relative; padding: 12px 0;">
				<div class="row gap-3" style="align-items: flex-end; height: 160px;">
					{#each months as m (m)}
						{@const b = byMonth[m]}
						{@const inH = (b.inflow / maxAbs) * 130}
						{@const outH = (-b.outflow / maxAbs) * 130}
						{@const net = b.inflow + b.outflow}
						<div style="flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px;">
							<div class="tabular" style="font-size: 11px; color: {net >= 0 ? 'var(--pos)' : 'var(--neg)'}; font-weight: 500;">
								{net >= 0 ? '+' : ''}{(net / 1000).toFixed(1)}k
							</div>
							<div style="width: 70%; display: flex; flex-direction: column; align-items: stretch; gap: 1px;">
								<div style="height: {inH}px; background: var(--pos); border-radius: 2px 2px 0 0;"></div>
								{#if outH > 0}
									<div style="height: {outH}px; background: var(--neg); border-radius: 0 0 2px 2px;"></div>
								{/if}
							</div>
							<div style="border-top: 1px solid var(--line-strong); align-self: stretch;"></div>
							<div style="font-size: 11px; color: var(--muted);">{m.slice(5) + '/' + m.slice(2, 4)}</div>
						</div>
					{/each}
				</div>
			</div>
		</Card>

		<Card title="Concentração por contraparte" sub="Inflow projetado · 90 dias">
			<div class="stack" style="gap: 8px;">
				{#each cpConcentration as r (r.cp)}
					<div>
						<div class="row gap-3" style="font-size: 12.5px; margin-bottom: 4px;">
							<span style="width: 60px; font-weight: 500;">{r.cp}</span>
							<Bar pct={r.pct * 1.5} kind={r.pct > 40 ? 'warn' : 'pos'}/>
							<span class="tabular" style="width: 90px; text-align: right;">US$ {(r.v / 1000).toFixed(1)}k</span>
							<span class="tabular" style="width: 36px; text-align: right; color: var(--muted);">{r.pct}%</span>
						</div>
					</div>
				{/each}
			</div>
			<div class="divider"></div>
			<div class="row gap-2" style="font-size: 11.5px;">
				<Badge kind="warn" dot>Concentração JPM</Badge>
				<span style="color: var(--muted);">57 % do fluxo · acima do alerta (≥ 50 %)</span>
			</div>
		</Card>
	</div>

	<Card title="Liquidações detalhadas" sub="Eventos de caixa de derivativos · ordenado por data" noPad>
		{#snippet actions()}
			<button type="button" class="btn btn-secondary btn-sm"><Icon name="filter"/>Filtros</button>
		{/snippet}

		<table class="tbl">
			<thead>
				<tr>
					<th>Data</th>
					<th>Descrição</th>
					<th>Commodity</th>
					<th>Contraparte</th>
					<th class="num">Valor (USD)</th>
					<th class="num">Valor (BRL)</th>
					<th>Direção</th>
					<th>Status</th>
				</tr>
			</thead>
			<tbody>
				{#each cashflow as c, i (i)}
					<tr>
						<td class="strong">{c.date.split('-').reverse().join('/')}</td>
						<td>{c.desc}</td>
						<td><CommodityChip code={c.commodity}/></td>
						<td>{c.cp}</td>
						<td class="num strong" style="color: {c.amount_usd >= 0 ? 'var(--pos)' : 'var(--neg)'};">
							{c.amount_usd >= 0 ? '+' : ''}{c.amount_usd.toLocaleString('en-US', { maximumFractionDigits: 0 })}
						</td>
						<td class="num">R$ {(c.amount_usd * 5.124).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</td>
						<td>
							{#if c.amount_usd >= 0}
								<Badge kind="pos" dot>Entrada</Badge>
							{:else}
								<Badge kind="neg" dot>Saída</Badge>
							{/if}
						</td>
						<td><StatePill state={c.status}/></td>
					</tr>
				{/each}
			</tbody>
		</table>
	</Card>
</div>
