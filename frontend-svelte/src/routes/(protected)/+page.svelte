<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	let { data } = $props();
	const commodities = $derived(data.commodities);
	const exposureBuckets = $derived(data.exposureBuckets);

	const exposureRows = [
		{ code: 'AL-LME', comm: '22.400',         hed: '12.300',        res: '10.100',        pct: 55, delta: '+US$ 14.820', kind: 'pos' as const },
		{ code: 'CU-LME', comm: '3.200',          hed: '1.250',         res: '1.950',         pct: 39, delta: '+US$ 2.140',  kind: 'pos' as const },
		{ code: 'ZN-LME', comm: '2.450',          hed: '180',           res: '2.270',         pct: 7,  delta: '−US$ 410',    kind: 'neg' as const },
		{ code: 'NI-LME', comm: '420',            hed: '0',             res: '420',           pct: 0,  delta: '+US$ 0',      kind: 'flat' as const },
		{ code: 'USDBRL', comm: 'US$ 38,2 M',     hed: 'US$ 18,0 M',    res: 'US$ 20,2 M',    pct: 47, delta: '+US$ 1.910',  kind: 'pos' as const },
	];

	const feed = [
		{ kind: 'pos',  when: '09:14', who: 'M. Santos',    whatHtml: 'Nova RFQ <strong>RFQ-2026-0184</strong> · AL-LME 1.200t buy' },
		{ kind: 'info', when: '09:08', who: 'Sistema',      whatHtml: 'Snapshot diário de exposições · 4 ajustes detectados' },
		{ kind: 'pos',  when: '09:04', who: 'R. Almeida',   whatHtml: 'Ordem <strong>ORD-2026-0419</strong> liquidada · AL-LME 1.500t @ 2.631,00 · ITAU' },
		{ kind: 'warn', when: '08:55', who: 'L. Ferreira',  whatHtml: 'Limite de contraparte <strong>Citi</strong> sob análise · uso 0/6,5M' },
		{ kind: 'pos',  when: '08:21', who: 'R. Almeida',   whatHtml: 'Ordem <strong>ORD-2026-0418</strong> liquidada · USDBRL 3M @ 5,1115 · JPM' },
		{ kind: 'info', when: '08:14', who: 'Sistema',      whatHtml: 'Cotações LME atualizadas (open)' },
		{ kind: 'pos',  when: '17:55', who: 'A. Costa',     whatHtml: 'Aprovação <strong>APR-2026-0096</strong> concedida · CT-2026-0118' },
	];

	function coverageKind(ratio: number): 'pos' | 'warn' | 'neg' {
		if (ratio >= 70) return 'pos';
		if (ratio >= 40) return 'warn';
		return 'neg';
	}

	function coverageColor(kind: 'pos' | 'warn' | 'neg'): string {
		if (kind === 'pos') return 'var(--pos)';
		if (kind === 'warn') return 'var(--orange-strong)';
		return 'var(--neg)';
	}

	function fmt(v: number | null, code: string): string {
		if (v == null || !Number.isFinite(v)) return '—';
		const opts =
			code === 'USDBRL'
				? { minimumFractionDigits: 4, maximumFractionDigits: 4 }
				: { minimumFractionDigits: 2, maximumFractionDigits: 2 };
		return v.toLocaleString('en-US', opts);
	}

	function marketChangePct(c: Record<string, any>): number | null {
		if (c.last == null || c.prev == null || c.prev === 0) return null;
		const chg = ((c.last - c.prev) / c.prev) * 100;
		return Number.isFinite(chg) ? chg : null;
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Visão geral</h1>
			<div class="page-sub">Posições, cobertura de hedge e atividade · atualizado às 09:14</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary">
				<Icon name="refresh"/>Atualizar
			</button>
			<button type="button" class="btn btn-secondary">
				<Icon name="download"/>Exportar
			</button>
			<a href="/rfq" class="btn btn-primary">
				<Icon name="plus"/>Nova RFQ
			</a>
		</div>
	</div>

	<div class="kpi-row" style="margin-bottom: 16px;">
		<Kpi
			label="Exposição comercial"
			value="36.300"
			unit="t"
			delta="+1.420 t vs ontem"
			deltaKind="pos"
			spark={[24, 26, 28, 27, 29, 32, 34, 36, 36.3]}
			sparkColor="var(--navy-2)"
		/>
		<Kpi
			label="Hedge ratio"
			value="49,3"
			unit="%"
			delta="+2,1 pp vs ontem"
			deltaKind="pos"
			spark={[41, 42, 44, 43, 45, 46, 47, 48, 49.3]}
			sparkColor="var(--pos)"
		/>
		<Kpi
			label="MTM agregado"
			value="+US$ 204.165"
			delta="+US$ 18.460 1d"
			deltaKind="pos"
			spark={[100, 110, 140, 160, 150, 170, 180, 190, 204]}
			sparkColor="var(--pos)"
		/>
		<Kpi
			label="P&L MTD realizado"
			value="+US$ 312.880"
			delta="+1,8 % vs mês anterior"
			deltaKind="pos"
		/>
		<Kpi
			label="RFQ abertas"
			value="3"
			delta="2 aguardando cotação"
			deltaKind="flat"
		/>
	</div>

	<div class="grid-7-5" style="margin-bottom: 16px;">
		<Card title="Cobertura por janela" sub="Hedge vs exposição comercial · próximos 8 meses">
			{#snippet actions()}
				<div class="tabs-pill">
					<button type="button" class="tab active">t</button>
					<button type="button" class="tab">US$</button>
				</div>
			{/snippet}

			<div style="display: grid; grid-template-columns: 1fr 1fr; gap: 4px 24px;">
				{#each exposureBuckets as b (b.month)}
					{@const k = coverageKind(b.ratio)}
					<div
						class="row gap-3"
						style="padding: 5px 0; border-bottom: 1px solid var(--line-soft);"
					>
						<span style="width: 56px; font-size: 12.5px; font-weight: 500; color: var(--ink-2);">{b.month}</span>
						<div style="flex: 1;"><Bar pct={b.ratio} kind={k}/></div>
						<span
							class="tabular"
							style="width: 46px; text-align: right; font-size: 12px; font-weight: 500; color: {coverageColor(k)};"
						>{b.ratio.toFixed(0)}%</span>
						<span
							class="tabular"
							style="width: 60px; text-align: right; font-size: 11px; color: var(--muted);"
						>
							{b.hedged_mt > 0 ? (b.hedged_mt / 1000).toFixed(1) + 'k/' : '0/'}{(b.commercial_mt / 1000).toFixed(1)}k t
						</span>
					</div>
				{/each}
			</div>

			<div
				class="row gap-4"
				style="margin-top: 10px; font-size: 11.5px; color: var(--muted);"
			>
				<span class="row gap-2">
					<span style="width: 8px; height: 8px; background: var(--pos);"></span>≥ 70% (política)
				</span>
				<span class="row gap-2">
					<span style="width: 8px; height: 8px; background: var(--orange);"></span>40–70%
				</span>
				<span class="row gap-2">
					<span style="width: 8px; height: 8px; background: var(--neg);"></span>&lt; 40%
				</span>
			</div>
		</Card>

		<Card title="Atividade recente" sub="Operações dos últimos 24 h">
			{#snippet actions()}
				<button type="button" class="btn-link">Ver tudo</button>
			{/snippet}

			<div class="feed">
				{#each feed as item, i (i)}
					<div class="feed-item {item.kind}">
						<div class="icon"></div>
						<div>
							<div class="what">{@html item.whatHtml}</div>
							<div class="row gap-2">
								<span class="when">{item.when}</span>
								<span class="who">· {item.who}</span>
							</div>
						</div>
					</div>
				{/each}
			</div>
		</Card>
	</div>

	<div class="grid-8-4">
		<Card title="Exposição por commodity" sub="Saldo comercial líquido por mês · em toneladas">
			<table class="tbl tbl-tight">
				<thead>
					<tr>
						<th>Commodity</th>
						<th class="num">Comercial</th>
						<th class="num">Hedgeado</th>
						<th class="num">Residual</th>
						<th style="width: 220px;">Cobertura</th>
						<th class="num">Δ 1d (MTM)</th>
					</tr>
				</thead>
				<tbody>
					{#each exposureRows as r (r.code)}
						<tr>
							<td class="strong"><CommodityChip code={r.code}/></td>
							<td class="num">{r.comm}</td>
							<td class="num">{r.hed}</td>
							<td class="num">{r.res}</td>
							<td>
								<div class="row gap-3">
									<Bar pct={r.pct} kind={r.pct >= 70 ? 'pos' : r.pct >= 40 ? 'warn' : 'neg'}/>
									<span class="tabular" style="width: 36px; text-align: right; font-size: 12px;">{r.pct}%</span>
								</div>
							</td>
							<td
								class="num"
								style="color: {r.kind === 'pos' ? 'var(--pos)' : r.kind === 'neg' ? 'var(--neg)' : 'var(--muted)'};"
							>{r.delta}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</Card>

		<Card title="Cotações de mercado" sub="LME · Bovespa · 09:14">
			{#snippet actions()}
				<Badge kind="pos" dot>ao vivo</Badge>
			{/snippet}

			<div class="stack" style="gap: 0;">
				{#each commodities as c (c.code)}
					{@const chg = marketChangePct(c)}
					<div
						class="row gap-3"
						style="padding: 11px 0; border-bottom: 1px solid var(--line-soft);"
					>
						<div style="flex: 1;">
							<div style="font-size: 12.5px; font-weight: 500;">{c.code}</div>
							<div style="font-size: 11px; color: var(--muted);">{c.name}</div>
						</div>
						<div style="text-align: right;">
							<div class="tabular" style="font-weight: 500;">{fmt(c.last, c.code)}</div>
							{#if chg == null}
								<div class="tabular" style="font-size: 11px; color: var(--muted);">—</div>
							{:else}
								<div
									class="tabular"
									style="font-size: 11px; color: {chg >= 0 ? 'var(--pos)' : 'var(--neg)'};"
								>
									{chg >= 0 ? '▲' : '▼'} {Math.abs(chg).toFixed(2)}%
								</div>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</Card>
	</div>
</div>
