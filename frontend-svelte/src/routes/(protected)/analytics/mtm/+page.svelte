<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	type Contract = Record<string, any>;
	let { data } = $props();
	const contracts = $derived(data.contracts);

	function midFor(commodity: string): number {
		if (commodity === 'AL-LME') return 2645.5;
		if (commodity === 'CU-LME') return 9412.0;
		if (commodity === 'ZN-LME') return 2812.5;
		if (commodity === 'USDBRL') return 5.124;
		return 0;
	}

	function priceDigits(c: Contract): number {
		return c.commodity === 'USDBRL' ? 4 : 2;
	}

	function fmtQty(c: Contract): string {
		if (c.commodity === 'USDBRL') return (c.qty / 1_000_000).toFixed(1) + ' M';
		return c.qty.toLocaleString('pt-BR');
	}

	function scenarioMtm(c: Contract): number {
		const mid = midFor(c.commodity);
		const scenarioMid = mid * 0.97;
		return c.fixed_leg === 'buy' ? (scenarioMid - c.price) * c.qty : (c.price - scenarioMid) * c.qty;
	}

	const sliders = [
		{ label: 'AL-LME', base: '2.645,50', delta: '−3,0 %', pct: -3 },
		{ label: 'CU-LME', base: '9.412,00', delta:  '0,0 %', pct:  0 },
		{ label: 'ZN-LME', base: '2.812,50', delta: '−2,0 %', pct: -2 },
		{ label: 'USDBRL', base: '5,1240',   delta: '+1,0 %', pct: +1 },
	];

	const historical = [
		{ name: 'LME −5 % (Lehman 2008)',     val: -412500, neg: true },
		{ name: 'LME +3 % (rally CN 2024)',   val:  246700, neg: false },
		{ name: 'USDBRL +8 % (eleição 2022)', val:  142800, neg: false },
		{ name: 'CU −10 % (Covid 03/2020)',   val:  -84300, neg: true },
	];
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Mark-to-market e cenário</h1>
			<div class="page-sub">Marcação a mercado oficial e simulação what-if</div>
		</div>
		<div class="page-actions">
			<span class="env-badge">Marcação 27/05/2026 11:30 BST</span>
			<button type="button" class="btn btn-secondary"><Icon name="refresh"/>Re-marcar</button>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="MTM oficial"               value="+US$ 204.165"   delta="+US$ 18.460 1d"                deltaKind="pos"/>
		<Kpi label="MTM cenário"               value="−US$ 122.840"   delta="vs base −US$ 327.005"          deltaKind="neg"/>
		<Kpi label="VaR 1d (95 %)"             value="US$ 84.200"     delta="histórico 2y · paramétrico"/>
		<Kpi label="Estresse (LME −5 %)"       value="−US$ 412.500"   delta="cenário Banxico 2008"          deltaKind="neg"/>
	</div>

	<div class="detail-grid">
		<Card title="Marcação por contrato" sub="MTM consolidado · marcação oficial 11:30 BST" noPad>
			<table class="tbl">
				<thead>
					<tr>
						<th>Contrato</th>
						<th>Commodity</th>
						<th class="num">Qtd</th>
						<th class="num">Preço fixo</th>
						<th class="num">Preço marcação</th>
						<th class="num">Δ Preço</th>
						<th class="num">MTM (USD)</th>
						<th class="num">MTM cenário</th>
					</tr>
				</thead>
				<tbody>
					{#each contracts as c (c.id)}
						{@const mid = midFor(c.commodity)}
						{@const scen = scenarioMtm(c)}
						<tr>
							<td class="strong mono">{c.id}</td>
							<td><CommodityChip code={c.commodity}/></td>
							<td class="num">{fmtQty(c)}</td>
							<td class="num">{c.price.toLocaleString('en-US', { minimumFractionDigits: priceDigits(c), maximumFractionDigits: priceDigits(c) })}</td>
							<td class="num">{mid.toLocaleString('en-US', { minimumFractionDigits: priceDigits(c), maximumFractionDigits: priceDigits(c) })}</td>
							<td class="num" style="color: {mid > c.price ? 'var(--pos)' : 'var(--neg)'};">
								{mid >= c.price ? '+' : ''}{(mid - c.price).toFixed(priceDigits(c))}
							</td>
							<td class="num strong" style="color: {c.mtm >= 0 ? 'var(--pos)' : 'var(--neg)'};">
								{c.mtm >= 0 ? '+' : ''}{c.mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}
							</td>
							<td class="num" style="color: {scen >= 0 ? 'var(--pos)' : 'var(--neg)'};">
								{scen >= 0 ? '+' : ''}{scen.toLocaleString('en-US', { maximumFractionDigits: 0 })}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</Card>

		<div class="stack gap-4" style="position: sticky; top: 72px; align-self: start;">
			<Card title="Simulador de cenário" sub="Ajuste preços e veja o impacto agregado">
				<div class="stack gap-4">
					{#each sliders as s (s.label)}
						{@const left = 50 + s.pct * 8}
						<div>
							<div class="row gap-2" style="font-size: 12px; margin-bottom: 4px;">
								<span style="font-weight: 500;">{s.label}</span>
								<span style="color: var(--muted);">· base {s.base}</span>
								<span class="tabular" style="margin-left: auto; color: {s.pct < 0 ? 'var(--neg)' : s.pct > 0 ? 'var(--pos)' : 'var(--muted)'}; font-weight: 500;">{s.delta}</span>
							</div>
							<div style="height: 6px; background: var(--surface-sunk); border-radius: 999px; position: relative;">
								<div style="position: absolute; left: 50%; top: -2px; bottom: -2px; width: 1px; background: var(--line-strong);"></div>
								<div style="position: absolute; left: {left}%; top: -4px; width: 14px; height: 14px; background: #fff; border: 2px solid var(--navy); border-radius: 50%; transform: translateX(-50%);"></div>
							</div>
						</div>
					{/each}
				</div>
				<div class="divider"></div>
				<dl class="kv">
					<dt>MTM base</dt><dd class="tabular">+US$ 204.165</dd>
					<dt>MTM cenário</dt><dd class="tabular strong" style="color: var(--neg);">−US$ 122.840</dd>
					<dt>Δ cenário</dt><dd class="tabular" style="color: var(--neg);">−US$ 327.005</dd>
				</dl>
				<button type="button" class="btn btn-secondary" style="width: 100%; margin-top: 10px;">Salvar cenário</button>
			</Card>

			<Card title="Cenários históricos">
				<div class="stack" style="gap: 0;">
					{#each historical as s (s.name)}
						<div class="row gap-3" style="padding: 9px 0; border-bottom: 1px solid var(--line-soft);">
							<span style="font-size: 12.5px; flex: 1;">{s.name}</span>
							<span class="tabular strong" style="color: {s.neg ? 'var(--neg)' : 'var(--pos)'};">
								{s.val >= 0 ? '+' : ''}{s.val.toLocaleString('en-US')}
							</span>
						</div>
					{/each}
				</div>
			</Card>
		</div>
	</div>
</div>
