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
	const exposureRows = $derived(data.exposureRows ?? []);
	const totalCommercial = $derived(exposureRows.reduce((sum, row) => sum + Math.abs(row.commercial_mt ?? 0), 0));
	const totalHedged = $derived(exposureRows.reduce((sum, row) => sum + Math.abs(row.hedged_mt ?? 0), 0));
	const totalResidual = $derived(exposureRows.reduce((sum, row) => sum + Math.abs(row.residual_mt ?? 0), 0));
	const totalCoverage = $derived(totalCommercial > 0 ? (totalHedged / totalCommercial) * 100 : 0);

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

	function fmtMt(value: unknown): string {
		const parsed = Number(value);
		if (!Number.isFinite(parsed)) return '—';
		return parsed.toLocaleString('pt-BR', { maximumFractionDigits: 0 });
	}

	function fmtMtmDelta(value: unknown): string {
		const parsed = Number(value);
		if (!Number.isFinite(parsed)) return '—';
		return `${parsed >= 0 ? '+' : '-'}US$ ${Math.abs(parsed).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
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
			value={fmtMt(totalCommercial)}
			unit="t"
			delta={`${exposureRows.length} commodity(s) live`}
			deltaKind="flat"
			spark={[24, 26, 28, 27, 29, 32, 34, 36, 36.3]}
			sparkColor="var(--navy-2)"
		/>
		<Kpi
			label="Hedge ratio"
			value={totalCoverage.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}
			unit="%"
			delta="live exposure list"
			deltaKind={totalCoverage >= 70 ? 'pos' : totalCoverage >= 40 ? 'flat' : 'neg'}
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
			label="P&L realizado"
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
							<td class="num">{fmtMt(r.commercial_mt)}</td>
							<td class="num">{fmtMt(r.hedged_mt)}</td>
							<td class="num">{fmtMt(r.residual_mt)}</td>
							<td>
								<div class="row gap-3">
									<Bar pct={r.pct} kind={r.pct >= 70 ? 'pos' : r.pct >= 40 ? 'warn' : 'neg'}/>
									<span class="tabular" style="width: 36px; text-align: right; font-size: 12px;">{r.pct}%</span>
								</div>
							</td>
							<td
								class="num"
								style="color: {r.mtm_delta_usd == null ? 'var(--muted)' : r.mtm_delta_usd >= 0 ? 'var(--pos)' : 'var(--neg)'};"
							>{fmtMtmDelta(r.mtm_delta_usd)}</td>
						</tr>
					{/each}
					{#if exposureRows.length === 0}
						<tr><td colspan="6" style="color: var(--muted);">Sem exposição live carregada</td></tr>
					{/if}
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
