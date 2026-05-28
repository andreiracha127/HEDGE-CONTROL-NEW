<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	import Pager from '$lib/components/alcast/Pager.svelte';
	import { canonicalCommodityCode, exposureBucketsFrom } from '$lib/alcast/route-data';
	import { authStore } from '$lib/stores/auth.svelte';
	let { data } = $props();
	const exposureRows = $derived(data.exposureRows ?? []);
	const hedgeTasks = $derived((data.tasks?.items ?? data.tasks ?? []) as Record<string, any>[]);
	const netRows = $derived((data.netExposure?.items ?? data.netExposure ?? []) as Record<string, any>[]);
	const exposureBuckets = $derived(data.exposureBuckets ?? []);
	const totalCommercial = $derived(exposureBuckets.reduce((sum, row) => sum + Math.abs(row.commercial_mt ?? 0), 0));
	const totalHedged = $derived(exposureBuckets.reduce((sum, row) => sum + Math.abs(row.hedged_mt ?? 0), 0));
	const totalResidual = $derived(exposureBuckets.reduce((sum, row) => sum + Math.abs(row.residual_mt ?? 0), 0));
	const policyAdherence = $derived(totalCommercial > 0 ? (totalHedged / totalCommercial) * 100 : null);
	const canCreateRfqs = $derived(authStore.hasRole('risk_manager'));

	let commodity = $state('ALUMINUM');
	const COMMODITIES = [
		{ label: 'AL-LME', value: 'ALUMINUM' },
		{ label: 'CU-LME', value: 'COPPER' },
		{ label: 'ZN-LME', value: 'ZINC' },
		{ label: 'NI-LME', value: 'NICKEL' },
		{ label: 'USDBRL', value: 'USDBRL' },
	];
	const filteredExposureBuckets = $derived.by(() =>
		exposureBucketsFrom({
			items: exposureRows.filter((bucket: Record<string, any>) => canonicalCommodityCode(bucket.commodity) === commodity),
		}),
	);

	function fmtMt(value: unknown): string {
		const parsed = Number(value);
		if (!Number.isFinite(parsed)) return '—';
		return parsed.toLocaleString('pt-BR', { maximumFractionDigits: 0 });
	}

	function fmtPct(value: number | null): string {
		if (value == null || !Number.isFinite(value)) return '—';
		return value.toLocaleString('pt-BR', { maximumFractionDigits: 1 });
	}

	function taskColor(status: unknown): string {
		if (status === 'pending') return 'var(--orange)';
		if (status === 'cancelled') return 'var(--muted)';
		return 'var(--info)';
	}
</script>

<div class="page">
	<PageHeader
		eyebrow="Controle de exposição"
		title="Exposições"
		subtitle="Saldo comercial líquido, aderência à política e pendências de hedge."
		meta={[`Comercial ${fmtMt(totalCommercial)} t`, `Residual ${fmtMt(totalResidual)} t`, `Política ${fmtPct(policyAdherence)}%`]}
		actions={[
			{ label: 'Recalcular', icon: 'refresh', variant: 'secondary' },
			{ label: 'Exportar', icon: 'download', variant: 'secondary' },
		]}
	/>

	<div class="institutional-monitoring">
	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Comercial total"        value={fmtMt(totalCommercial)} unit="t" delta="posições comerciais" deltaKind="flat"/>
		<Kpi label="Hedgeado"               value={fmtMt(totalHedged)} unit="t" delta="cobertura vigente" deltaKind="flat"/>
		<Kpi label="Residual"               value={fmtMt(totalResidual)} unit="t" delta="exposição aberta" deltaKind={totalResidual === 0 ? 'flat' : 'neg'}/>
		<Kpi label="Aderência à política"   value={fmtPct(policyAdherence)} unit={policyAdherence == null ? undefined : '%'} delta="cobertura sobre comercial" deltaKind={policyAdherence == null ? 'flat' : policyAdherence >= 70 ? 'pos' : policyAdherence >= 40 ? 'flat' : 'neg'}/>
	</div>

	<Card title="Exposição por commodity e janela" sub="Detalhamento por mês de entrega" noPad>
		{#snippet actions()}
			<div class="row gap-2">
				<div class="radio-group">
					{#each COMMODITIES as c (c.value)}
						<button type="button" class:active={commodity === c.value} onclick={() => (commodity = c.value)}>{c.label}</button>
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
				{#each filteredExposureBuckets as b (b.month)}
					{@const ok = b.ratio >= 70}
					{@const warn = b.ratio >= 40 && b.ratio < 70}
					<tr>
						<td class="strong">{b.month}</td>
						<td class="num">{b.commercial_active_mt.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</td>
						<td class="num">{b.commercial_passive_mt.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}</td>
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
								{#if canCreateRfqs}
									<a href="/rfq/new" class="btn btn-ghost btn-sm">Cobrir →</a>
								{/if}
							</div>
						</td>
					</tr>
				{/each}
				{#if filteredExposureBuckets.length === 0}
					<tr>
						<td colspan="9">
							<EmptyState
								icon="scale"
								title="Nenhuma exposição para o filtro selecionado"
								message={canCreateRfqs ? 'Selecione outra commodity ou atualize a base de posições.' : 'Selecione outra commodity ou consulte a mesa de risco para originar cobertura.'}
								actionLabel={canCreateRfqs ? 'Criar RFQ de cobertura' : undefined}
								actionHref={canCreateRfqs ? '/rfq/new' : undefined}
							/>
						</td>
					</tr>
				{/if}
			</tbody>
		</table>
		<Pager from={filteredExposureBuckets.length > 0 ? 1 : 0} to={filteredExposureBuckets.length} total={filteredExposureBuckets.length}/>
	</Card>

	<div class="grid-7-5" style="margin-top: 16px;">
		<Card title="Exposição líquida" sub="Saldo líquido por commodity">
			<table class="tbl tbl-tight">
				<thead>
					<tr>
						<th>Commodity</th>
						<th class="num">Long</th>
						<th class="num">Short</th>
						<th class="num">Net</th>
						<th class="num">Hedge long</th>
						<th class="num">Hedge short</th>
					</tr>
				</thead>
				<tbody>
					{#each netRows as row, i (row.commodity ?? i)}
						<tr>
							<td class="strong">{row.commodity ?? '—'}</td>
							<td class="num">{fmtMt(row.long_tons)}</td>
							<td class="num">{fmtMt(row.short_tons)}</td>
							<td class="num strong">{fmtMt(row.net_tons)}</td>
							<td class="num">{fmtMt(row.long_hedged)}</td>
							<td class="num">{fmtMt(row.short_hedged)}</td>
						</tr>
					{/each}
					{#if netRows.length === 0}
						<tr>
							<td colspan="6">
								<EmptyState
								icon="chart"
									title="Nenhuma exposição líquida carregada"
									message="Atualize a base de posições para visualizar a exposição líquida consolidada."
								/>
							</td>
						</tr>
					{/if}
				</tbody>
			</table>
		</Card>

		<Card title="Pendências" sub="Itens que precisam de ação">
			<div class="stack" style="gap: 0;">
				{#each hedgeTasks as task (task.id)}
					<div class="row gap-3" style="padding: 10px 0; border-bottom: 1px solid var(--line-soft);">
						<div style="width: 4px; align-self: stretch; background: {taskColor(task.status)}; border-radius: 2px;"></div>
						<div style="flex: 1;">
							<div style="font-size: 12.5px; font-weight: 500;">{task.recommended_action ?? 'Ação de hedge'}</div>
							<div style="font-size: 11.5px; color: var(--muted);">{fmtMt(task.recommended_tons)} t · exposição {task.exposure_id ?? '—'}</div>
						</div>
						<div style="font-size: 11px; color: var(--muted);">{task.status ?? '—'}</div>
						<button type="button" class="btn btn-ghost btn-sm">Ver →</button>
					</div>
				{/each}
				{#if hedgeTasks.length === 0}
					<EmptyState
						icon="shieldCheck"
						title="Nenhuma pendência carregada"
						message="Não há desvios de cobertura ou recomendações de hedge para revisão."
					/>
				{/if}
			</div>
		</Card>
	</div>
	</div>
</div>
