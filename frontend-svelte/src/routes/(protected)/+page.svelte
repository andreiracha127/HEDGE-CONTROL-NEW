<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import DecisionDossier, { type DossierKind } from '$lib/components/alcast/DecisionDossier.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	let { data } = $props();
	const commodities = $derived(data.commodities);
	const exposureBuckets = $derived(data.exposureBuckets);
	const exposureRows = $derived(data.exposureRows ?? []);
	const totalCommercial = $derived(exposureRows.reduce((sum, row) => sum + Math.abs(row.commercial_mt ?? 0), 0));
	const totalHedged = $derived(exposureRows.reduce((sum, row) => sum + Math.abs(row.hedged_mt ?? 0), 0));
	const totalResidual = $derived(exposureRows.reduce((sum, row) => sum + Math.abs(row.residual_mt ?? 0), 0));
	const totalCoverage = $derived(totalCommercial > 0 ? (totalHedged / totalCommercial) * 100 : 0);
	const openRfqs = $derived(data.rfqs ?? []);
	const riskVerdict = $derived.by(() => {
		if (exposureRows.length === 0) return 'Data load pending';
		if (totalCoverage >= 70) return 'Policy aligned';
		if (totalCoverage >= 40) return 'Coverage watch';
		return 'Residual risk';
	});
	const riskVerdictKind = $derived.by((): DossierKind => {
		if (exposureRows.length === 0 || totalCoverage >= 40 && totalCoverage < 70) return 'warn';
		return totalCoverage >= 70 ? 'pos' : 'neg';
	});

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

	function marketKey(c: Record<string, any>): string {
		return [c.code, c.settlement_date, c.date, c.source, c.last].filter(Boolean).join(':');
	}

	function refreshPage() {
		window.location.reload();
	}
</script>

<div class="page">
	<PageHeader
		eyebrow="Visão executiva"
		title="Risk command center"
		subtitle="Cobertura, residual, RFQs abertas e mercado em uma leitura única da mesa."
		meta={[
			`${exposureRows.length} commodity(s) live`,
			`${openRfqs.length} RFQ(s) enviadas`,
			`Cobertura ${totalCoverage.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}%`,
		]}
		actions={[
			{ label: 'Atualizar', icon: 'refresh', variant: 'secondary', onclick: refreshPage },
			{ label: 'Exportar', icon: 'download', variant: 'secondary' },
			{ label: 'Nova RFQ', icon: 'plus', variant: 'primary', href: '/rfq/new' },
		]}
	/>

	<div class="rfq-command-strip risk-command-center">
		<Badge kind={riskVerdictKind} dot>{riskVerdict}</Badge>
		<Badge kind="neutral">Residual {fmtMt(totalResidual)} t</Badge>
		<Badge kind={openRfqs.length > 0 ? 'warn' : 'neutral'}>{openRfqs.length} RFQ(s) em curso</Badge>
	</div>

	<div class="kpi-row" style="margin-bottom: 16px;">
		<Kpi
			label="Exposição comercial"
			value={fmtMt(totalCommercial)}
			unit="t"
			delta={`${exposureRows.length} commodity(s) live`}
			deltaKind="flat"
		/>
		<Kpi
			label="Hedge ratio"
			value={totalCoverage.toLocaleString('pt-BR', { maximumFractionDigits: 1 })}
			unit="%"
			delta="live exposure list"
			deltaKind={totalCoverage >= 70 ? 'pos' : totalCoverage >= 40 ? 'flat' : 'neg'}
		/>
		<Kpi
			label="Residual"
			value={fmtMt(totalResidual)}
			unit="t"
			delta="derivado de exposures/list"
			deltaKind={totalResidual === 0 ? 'flat' : 'neg'}
		/>
		<Kpi
			label="RFQs enviadas"
			value={String(openRfqs.length)}
			delta="state=SENT"
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

			{#if exposureBuckets.length}
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
			{:else}
				<EmptyState
					icon="chart"
					title="Nenhuma janela de cobertura carregada"
					message="A matriz será preenchida quando a exposição comercial e os hedges chegarem de exposures/list."
				/>
			{/if}

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

		<Card noPad>
			<DecisionDossier
				title="Mesa de risco"
				verdict={riskVerdict}
				verdictKind={riskVerdictKind}
				items={[
					{ label: 'Exposição comercial', value: `${fmtMt(totalCommercial)} t` },
					{ label: 'Hedgeado', value: `${fmtMt(totalHedged)} t`, kind: totalHedged > 0 ? 'pos' : 'neutral' },
					{ label: 'Residual', value: `${fmtMt(totalResidual)} t`, kind: totalResidual > 0 ? 'warn' : 'neutral' },
					{ label: 'RFQs abertas', value: openRfqs.length, kind: openRfqs.length > 0 ? 'warn' : 'neutral' },
				]}
			/>
		</Card>

		<Card title="Atividade operacional" sub="Eventos auditáveis recentes">
			{#snippet actions()}
				<button type="button" class="btn-link">Ver tudo</button>
			{/snippet}

			<EmptyState
				icon="shieldCheck"
				title="Nenhum evento operacional carregado"
				message="Quando a trilha de auditoria estiver disponível para a visão geral, ela aparecerá aqui."
				actionLabel="Abrir auditoria"
				actionHref="/audit"
			/>
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
						<tr>
							<td colspan="6">
								<EmptyState
									icon="chart"
									title="Nenhuma exposição live carregada"
									message="A tabela permanece vazia até o backend retornar linhas de exposures/list."
								/>
							</td>
						</tr>
					{/if}
				</tbody>
			</table>
		</Card>

		<Card title="Cotações de mercado" sub="Westmetall cash settlement">
			{#snippet actions()}
				<Badge kind="pos" dot>ao vivo</Badge>
			{/snippet}

			<div class="stack" style="gap: 0;">
				{#each commodities as c (marketKey(c))}
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
