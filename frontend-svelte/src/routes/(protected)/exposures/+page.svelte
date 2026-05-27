<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import Pager from '$lib/components/alcast/Pager.svelte';
	let { data } = $props();
	const exposureBuckets = $derived(data.exposureBuckets);

	let commodity = $state('AL-LME');
	const COMMODITIES = ['AL-LME', 'CU-LME', 'ZN-LME', 'NI-LME', 'USDBRL'];

	const pending = [
		{ when: 'hoje', sev: 'neg' as const,  title: 'ago/26 abaixo da política', desc: 'Cobertura em 39 % · meta ≥ 70 %' },
		{ when: 'hoje', sev: 'neg' as const,  title: 'set/26 abaixo da política', desc: 'Cobertura em 22,9 % · meta ≥ 70 %' },
		{ when: 'hoje', sev: 'warn' as const, title: 'Diferença jun/26 ↔ SAP',    desc: '15 t de divergência detectadas' },
		{ when: 'd-1',  sev: 'warn' as const, title: '3 ajustes de exposição',    desc: 'Pendentes de aprovação no workflow' },
		{ when: 'd-2',  sev: 'info' as const, title: 'Rebalanceamento sugerido',  desc: 'Reduzir 200 t em ZN-LME para abrir limite' },
	];

	function sevColor(sev: 'neg' | 'warn' | 'info'): string {
		if (sev === 'neg') return 'var(--neg)';
		if (sev === 'warn') return 'var(--orange)';
		return 'var(--info)';
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Exposições</h1>
			<div class="page-sub">Saldo comercial líquido por janela de entrega · snapshot 27/05/2026 09:12</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="refresh"/>Recalcular</button>
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Exportar</button>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Comercial total"        value="36.300" unit="t" delta="+1.420 t · 24h" deltaKind="pos"/>
		<Kpi label="Hedgeado"               value="17.900" unit="t" delta="+700 t · 24h"   deltaKind="pos"/>
		<Kpi label="Residual"               value="18.400" unit="t" delta="+720 t · 24h"   deltaKind="neg"/>
		<Kpi label="Aderência à política"   value="49,3"   unit="%" delta="meta ≥ 70 %"    deltaKind="neg"/>
	</div>

	<Card title="Exposição por commodity e janela" sub="Drill-down por mês de entrega" noPad>
		{#snippet actions()}
			<div class="row gap-2">
				<div class="radio-group">
					{#each COMMODITIES as c (c)}
						<button type="button" class:active={commodity === c} onclick={() => (commodity = c)}>{c}</button>
					{/each}
				</div>
				<button type="button" class="btn btn-secondary btn-sm"><Icon name="filter"/>Filtros</button>
			</div>
		{/snippet}

		<table class="tbl">
			<thead>
				<tr>
					<th>Janela</th>
					<th class="num">Comercial ativa</th>
					<th class="num">Comercial passiva</th>
					<th class="num">Saldo líquido</th>
					<th class="num">Hedgeado</th>
					<th class="num">Residual</th>
					<th style="width: 220px;">Cobertura</th>
					<th>Política</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each exposureBuckets as b (b.month)}
					{@const ok = b.ratio >= 70}
					{@const warn = b.ratio >= 40 && b.ratio < 70}
					<tr>
						<td class="strong">{b.month}</td>
						<td class="num">{(b.commercial_mt * 0.62).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</td>
						<td class="num">{(b.commercial_mt * 0.38).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</td>
						<td class="num strong">{b.commercial_mt.toLocaleString('pt-BR')}</td>
						<td class="num">{b.hedged_mt.toLocaleString('pt-BR')}</td>
						<td class="num" style="color: {b.residual_mt > 2000 ? 'var(--neg)' : 'var(--ink-2)'};">{b.residual_mt.toLocaleString('pt-BR')}</td>
						<td>
							<div class="row gap-3">
								<Bar pct={b.ratio} kind={ok ? 'pos' : warn ? 'warn' : 'neg'}/>
								<span class="tabular" style="width: 42px; text-align: right;">{b.ratio.toFixed(1)}%</span>
							</div>
						</td>
						<td>
							{#if ok}
								<Badge kind="pos" dot>OK</Badge>
							{:else if warn}
								<Badge kind="warn" dot>Atenção</Badge>
							{:else}
								<Badge kind="neg" dot>Abaixo</Badge>
							{/if}
						</td>
						<td>
							<div class="tbl-actions">
								<a href="/rfq/new" class="btn btn-ghost btn-sm">Cobrir →</a>
							</div>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<Pager from={1} to={8} total={8}/>
	</Card>

	<div class="grid-7-5" style="margin-top: 16px;">
		<Card title="Reconciliação contábil" sub="Comparativo SAP × Plataforma de Hedge · D-1">
			<table class="tbl tbl-tight">
				<thead>
					<tr>
						<th>Janela</th>
						<th class="num">SAP (ECC)</th>
						<th class="num">Plataforma</th>
						<th class="num">Δ</th>
						<th>Status</th>
					</tr>
				</thead>
				<tbody>
					<tr><td>jun/26</td><td class="num">4.215</td><td class="num">4.200</td><td class="num" style="color: var(--warn);">−15</td><td><Badge kind="warn" dot>Diferença</Badge></td></tr>
					<tr><td>jul/26</td><td class="num">3.800</td><td class="num">3.800</td><td class="num">0</td><td><Badge kind="pos" dot>OK</Badge></td></tr>
					<tr><td>ago/26</td><td class="num">4.100</td><td class="num">4.100</td><td class="num">0</td><td><Badge kind="pos" dot>OK</Badge></td></tr>
					<tr><td>set/26</td><td class="num">3.495</td><td class="num">3.500</td><td class="num" style="color: var(--warn);">+5</td><td><Badge kind="warn" dot>Diferença</Badge></td></tr>
					<tr><td>out/26</td><td class="num">3.900</td><td class="num">3.900</td><td class="num">0</td><td><Badge kind="pos" dot>OK</Badge></td></tr>
				</tbody>
			</table>
		</Card>

		<Card title="Pendências" sub="Itens que precisam de ação">
			<div class="stack" style="gap: 0;">
				{#each pending as p, i (i)}
					<div class="row gap-3" style="padding: 10px 0; border-bottom: 1px solid var(--line-soft);">
						<div style="width: 4px; align-self: stretch; background: {sevColor(p.sev)}; border-radius: 2px;"></div>
						<div style="flex: 1;">
							<div style="font-size: 12.5px; font-weight: 500;">{p.title}</div>
							<div style="font-size: 11.5px; color: var(--muted);">{p.desc}</div>
						</div>
						<div style="font-size: 11px; color: var(--muted);">{p.when}</div>
						<button type="button" class="btn btn-ghost btn-sm">Ver →</button>
					</div>
				{/each}
			</div>
		</Card>
	</div>
</div>
