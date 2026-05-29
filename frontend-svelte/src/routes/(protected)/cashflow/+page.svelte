<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
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
			const k = c.date?.slice(0, 7);
			if (!k) continue;
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

	function startOfLocalDay(value: Date): Date {
		return new Date(value.getFullYear(), value.getMonth(), value.getDate());
	}

	const cashflow90d = $derived.by(() => {
		const start = startOfLocalDay(new Date()).getTime();
		const horizon = start + 90 * 24 * 60 * 60 * 1000;
		return cashflow.filter((c) => {
			const timestamp = Date.parse(c.date);
			return Number.isFinite(timestamp) && timestamp >= start && timestamp <= horizon;
		});
	});
	const projectedInflow90d = $derived(cashflow90d.reduce((sum, c) => sum + Math.max(c.amount_usd, 0), 0));
	const projectedOutflow90d = $derived(cashflow90d.reduce((sum, c) => sum + Math.min(c.amount_usd, 0), 0));
	const projectedNet90d = $derived(projectedInflow90d + projectedOutflow90d);
	const nextSettlement = $derived.by(() =>
		[...cashflow]
			.filter((c) => Number.isFinite(Date.parse(c.date)))
			.sort((a, b) => Date.parse(a.date) - Date.parse(b.date))[0] ?? null,
	);

	const cpConcentration = $derived.by(() => {
		const totals = new Map<string, number>();
		for (const c of cashflow90d) {
			const cp = c.cp || '—';
			totals.set(cp, (totals.get(cp) ?? 0) + Math.max(c.amount_usd, 0));
		}
		const total = [...totals.values()].reduce((sum, value) => sum + value, 0);
		return [...totals.entries()]
			.map(([cp, v]) => ({ cp, v, pct: total > 0 ? (v / total) * 100 : 0 }))
			.sort((a, b) => b.v - a.v)
			.slice(0, 5);
	});

	function fmtUsd(value: number): string {
		const prefix = value >= 0 ? '+US$ ' : '-US$ ';
		return prefix + Math.abs(value).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
	}

	function fmtShortDate(value: string | null | undefined): string {
		if (!value) return '—';
		const date = value.slice(0, 10);
		const parts = date.split('-');
		return parts.length === 3 ? `${parts[2]}/${parts[1]}` : '—';
	}

	function fmtBrl(c: Record<string, any>): string {
		if (c.amount_brl == null) return '—';
		return `R$ ${Number(c.amount_brl).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`;
	}
</script>

<div class="page">
	<PageHeader
		eyebrow="Controle de caixa"
		title="Fluxo de caixa projetado"
		subtitle="Liquidações financeiras de derivativos, concentração e integração operacional."
		meta={[`${cashflow.length} evento(s)`, `Saldo 90d ${fmtUsd(projectedNet90d)}`, nextSettlement ? `Próxima ${fmtShortDate(nextSettlement.date)}` : 'Sem liquidação futura']}
		actions={[
			{ label: 'Exportar', icon: 'download', variant: 'secondary' },
			{ label: 'Sincronizar SAP', icon: 'refresh', variant: 'primary' },
		]}
	/>

	<div class="institutional-monitoring">
	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Entradas projetadas (90d)"  value={fmtUsd(projectedInflow90d)}  delta={`${cashflow90d.filter((c) => c.amount_usd > 0).length} liquidação(ões)`} deltaKind="pos"/>
		<Kpi label="Saídas projetadas (90d)" value={fmtUsd(projectedOutflow90d)} delta={`${cashflow90d.filter((c) => c.amount_usd < 0).length} liquidação(ões)`} deltaKind="neg"/>
		<Kpi label="Saldo projetado (90d)"               value={fmtUsd(projectedNet90d)}     delta={`${cashflow90d.length} evento(s)`}                    deltaKind={projectedNet90d >= 0 ? 'pos' : 'neg'}/>
		<Kpi label="Próxima liquidação"      value={fmtShortDate(nextSettlement?.date)} delta={nextSettlement ? `${nextSettlement.desc} · ${nextSettlement.cp}` : 'sem eventos'} deltaKind="flat"/>
	</div>

	<div class="grid-7-5" style="margin-bottom: 16px;">
		<Card title="Linha do tempo" sub="Líquido por mês · USD">
			{#if months.length}
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
			{:else}
				<EmptyState
					icon="coins"
					title="Nenhuma liquidação mensal carregada"
					message="Nenhuma liquidação foi encontrada no horizonte selecionado."
				/>
			{/if}
		</Card>

		<Card title="Concentração por contraparte" sub="Entradas projetadas · 90 dias">
			{#if cpConcentration.length}
				<div class="stack" style="gap: 8px;">
					{#each cpConcentration as r (r.cp)}
						<div>
							<div class="row gap-3" style="font-size: 12.5px; margin-bottom: 4px;">
								<span style="width: 60px; font-weight: 500;">{r.cp}</span>
								<Bar pct={r.pct} kind={r.pct > 40 ? 'warn' : 'pos'}/>
								<span class="tabular" style="width: 90px; text-align: right;">US$ {(r.v / 1000).toFixed(1)}k</span>
								<span class="tabular" style="width: 36px; text-align: right; color: var(--muted);">{r.pct.toFixed(1)}%</span>
							</div>
						</div>
					{/each}
				</div>
				<div class="divider"></div>
				<div class="row gap-2" style="font-size: 11.5px;">
					<Badge kind={cpConcentration[0]?.pct > 50 ? 'warn' : 'pos'} dot>Concentração</Badge>
					<span style="color: var(--muted);">{cpConcentration[0] ? `${cpConcentration[0].pct.toFixed(1)} % do fluxo · ${cpConcentration[0].cp}` : 'sem entradas no horizonte'}</span>
				</div>
			{:else}
				<EmptyState
					icon="users"
					title="Sem concentração no horizonte"
					message="Nenhuma entrada projetada em 90 dias foi encontrada para análise por contraparte."
				/>
			{/if}
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
						<td class="strong">{fmtShortDate(c.date)}</td>
						<td>{c.desc}</td>
						<td><CommodityChip code={c.commodity}/></td>
						<td>{c.cp}</td>
						<td class="num strong" style="color: {c.amount_usd >= 0 ? 'var(--pos)' : 'var(--neg)'};">
							{c.amount_usd >= 0 ? '+' : ''}{c.amount_usd.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}
						</td>
						<td class="num">{fmtBrl(c)}</td>
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
				{#if cashflow.length === 0}
					<tr>
						<td colspan="8">
							<EmptyState
								icon="coins"
								title="Nenhuma liquidação carregada"
								message="Nenhum evento de caixa foi encontrado para os filtros atuais."
							/>
						</td>
					</tr>
				{/if}
			</tbody>
		</table>
	</Card>
	</div>
</div>
