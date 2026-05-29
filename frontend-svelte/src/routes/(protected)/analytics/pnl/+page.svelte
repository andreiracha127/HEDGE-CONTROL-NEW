<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';

	let { data } = $props();
	const pnl = $derived(data.pnl);
	const totals = $derived(pnl.totals);
	const deals = $derived(pnl.deals ?? []);

	const money = (value: unknown): number => {
		const parsed = Number(value);
		return Number.isFinite(parsed) ? parsed : 0;
	};

	function fmtUsd(value: unknown): string {
		const amount = money(value);
		const sign = amount > 0 ? '+' : amount < 0 ? '-' : '';
		return `${sign}US$ ${Math.abs(amount).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`;
	}

	function fmtNumber(value: unknown, digits = 2): string {
		return money(value).toLocaleString('pt-BR', { minimumFractionDigits: digits, maximumFractionDigits: digits });
	}

	const dailyBars = $derived.by(() => {
		const rows = deals.map((deal, idx) => [idx + 1, money(deal.total_pnl)] as [number, number]);
		return rows.length > 0 ? rows : [[1, 0] as [number, number]];
	});
	const maxAbs = $derived(Math.max(1, ...dailyBars.map((d) => Math.abs(d[1]))));

	const attribution = $derived.by(() => {
		const byCommodity = new Map<string, { code: string; realized: number; mtm: number; total: number; kind: 'pos' | 'neg' }>();
		for (const deal of deals) {
			const code = deal.commodity ?? '—';
			const current = byCommodity.get(code) ?? { code, realized: 0, mtm: 0, total: 0, kind: 'pos' as const };
			current.realized += money(deal.hedge_pnl_realized);
			current.mtm += money(deal.hedge_pnl_mtm);
			current.total += money(deal.total_pnl);
			current.kind = current.total < 0 ? 'neg' : 'pos';
			byCommodity.set(code, current);
		}
		return Array.from(byCommodity.values()).sort((a, b) => Math.abs(b.total) - Math.abs(a.total));
	});

	const topContrib = $derived.by(() => {
		const max = Math.max(1, ...deals.flatMap((deal) => deal.financial_items.map((item) => Math.abs(money(item.pnl)))));
		return deals
			.flatMap((deal) =>
				deal.financial_items.map((item) => {
					const pnlValue = money(item.pnl);
					const quantity = money(item.quantity_mt);
					const price = money(item.entry_price);
					return {
						id: item.reference ?? String(item.id).slice(0, 8),
						commodity: deal.commodity,
						cp: item.classification,
						notional: fmtNumber(quantity * price, 0),
						fixed: fmtNumber(item.entry_price),
						current: item.market_price == null ? '—' : fmtNumber(item.market_price),
						pnl: fmtUsd(item.pnl),
						kind: pnlValue < 0 ? 'neg' as const : 'pos' as const,
						contrib: Math.max(4, Math.round((Math.abs(pnlValue) / max) * 100)),
					};
				}),
			)
			.sort((a, b) => b.contrib - a.contrib)
			.slice(0, 8);
	});
</script>

<div class="page">
	<PageHeader
		eyebrow="Performance analytics"
		title="P&L"
		subtitle="Resultado realizado, não-realizado, atribuição e contribuintes financeiros."
		meta={[`Snapshot ${data.snapshotDate}`, `${deals.length} deal(s)`, `Total ${fmtUsd(totals.total_pnl)}`]}
		actions={[
			{ label: 'Exportar', icon: 'download', variant: 'secondary' },
		]}
	/>

	<div class="institutional-analytics">
	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi
			label="P&L total"        value={fmtUsd(totals.total_pnl)}  delta={`snapshot ${data.snapshotDate}`} deltaKind={money(totals.total_pnl) < 0 ? 'neg' : 'pos'}
			spark={dailyBars.map(([, v]) => v)} sparkColor={money(totals.total_pnl) < 0 ? 'var(--neg)' : 'var(--pos)'}
		/>
		<Kpi label="Realizado"            value={fmtUsd(totals.hedge_pnl_realized)}  delta={`${deals.length} deal(s)`} deltaKind={money(totals.hedge_pnl_realized) < 0 ? 'neg' : 'pos'}/>
		<Kpi label="Não-realizado (MTM)"  value={fmtUsd(totals.hedge_pnl_mtm)}       delta="hedges abertos" deltaKind={money(totals.hedge_pnl_mtm) < 0 ? 'neg' : 'pos'}/>
		<Kpi label="Resultado físico"     value={fmtUsd(money(totals.physical_revenue) - money(totals.physical_cost))} delta="receita menos custo" deltaKind={money(totals.physical_revenue) - money(totals.physical_cost) < 0 ? 'neg' : 'pos'}/>
	</div>

	<div class="grid-7-5" style="margin-bottom: 16px;">
		<Card title="P&L por deal" sub={`Snapshot ${data.snapshotDate} · USD`}>
			<div style="height: 200px; position: relative; display: flex; align-items: center;">
				<div class="row gap-1" style="align-items: stretch; height: 100%; flex: 1; padding: 0 4px;">
					{#each dailyBars as [d, v] (d)}
						{@const h = (Math.abs(v) / maxAbs) * 80}
						<div style="flex: 1; display: flex; flex-direction: column; justify-content: center; position: relative; min-width: 0;">
							{#if v >= 0}
								<div style="margin-top: auto; margin-bottom: 50%; height: {h}%; background: var(--pos); border-radius: 1px 1px 0 0;"></div>
							{:else}
								<div style="margin-top: 50%; margin-bottom: auto; height: {h}%; background: var(--neg); border-radius: 0 0 1px 1px;"></div>
							{/if}
						</div>
					{/each}
					<div style="position: absolute; left: 4px; right: 4px; top: 50%; height: 1px; background: var(--line);"></div>
				</div>
			</div>
		</Card>

		<Card title="Atribuição" sub={`Snapshot ${data.snapshotDate}`}>
			<table class="tbl tbl-tight">
				<thead>
					<tr>
						<th>Commodity</th>
						<th class="num">Realizado</th>
						<th class="num">MTM</th>
						<th class="num">Total</th>
					</tr>
				</thead>
				<tbody>
					{#each attribution as a (a.code)}
						<tr>
							<td class="strong"><CommodityChip code={a.code}/></td>
							<td class="num">{fmtUsd(a.realized)}</td>
							<td class="num">{fmtUsd(a.mtm)}</td>
							<td class="num strong" style="color: {a.kind === 'pos' ? 'var(--pos)' : 'var(--neg)'};">{fmtUsd(a.total)}</td>
						</tr>
					{/each}
					{#if attribution.length === 0}
						<tr>
							<td colspan="4">
								<EmptyState
									icon="chart"
									title="Nenhuma atribuição no snapshot"
									message="A tabela será preenchida quando houver deals com P&L retornados pelo backend."
								/>
							</td>
						</tr>
					{/if}
				</tbody>
				<tfoot>
					<tr style="border-top: 2px solid var(--line-strong);">
						<td class="strong">Total</td>
						<td class="num strong">{fmtUsd(totals.hedge_pnl_realized)}</td>
						<td class="num strong">{fmtUsd(totals.hedge_pnl_mtm)}</td>
						<td class="num strong" style="color: {money(totals.total_pnl) < 0 ? 'var(--neg)' : 'var(--pos)'};">{fmtUsd(totals.total_pnl)}</td>
					</tr>
				</tfoot>
			</table>
		</Card>
	</div>

	<Card title="Top contribuintes" sub={`Contratos com maior impacto no snapshot ${data.snapshotDate}`} noPad>
		<table class="tbl">
			<thead>
				<tr>
					<th>Contrato</th>
					<th>Commodity</th>
					<th>Contraparte</th>
					<th class="num">Notional (USD)</th>
					<th class="num">Preço fixo</th>
					<th class="num">Preço atual</th>
					<th class="num">P&amp;L (USD)</th>
					<th style="width: 160px;">Contribuição</th>
				</tr>
			</thead>
			<tbody>
				{#each topContrib as t (t.id)}
					<tr>
						<td class="mono strong">{t.id}</td>
						<td><CommodityChip code={t.commodity}/></td>
						<td>{t.cp}</td>
						<td class="num">{t.notional}</td>
						<td class="num">{t.fixed}</td>
						<td class="num">{t.current}</td>
						<td class="num strong" style="color: {t.kind === 'pos' ? 'var(--pos)' : 'var(--neg)'};">{t.pnl}</td>
						<td><Bar pct={t.contrib} kind={t.kind}/></td>
					</tr>
				{/each}
				{#if topContrib.length === 0}
					<tr>
						<td colspan="8">
							<EmptyState
								icon="coins"
								title="Nenhum contribuinte financeiro no snapshot"
								message="Os maiores impactos aparecerão aqui quando houver itens financeiros com P&L."
							/>
						</td>
					</tr>
				{/if}
			</tbody>
		</table>
	</Card>
	</div>
</div>
