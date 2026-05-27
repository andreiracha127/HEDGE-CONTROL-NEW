<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';

	let period = $state<'MTD' | 'QTD' | 'YTD' | 'Custom'>('MTD');

	const data: [number, number][] = [
		[ 1,  12], [ 2,  18], [ 3,  -4], [ 4,  22], [ 5,  14], [ 6,   8], [ 7, -12],
		[ 8,  24], [ 9,  31], [10,  16], [11,  22], [12,  35], [13,  18], [14,  -8],
		[15,  28], [16,  32], [17,  18], [18,  26], [19,  14], [20,  38], [21,  28],
		[22,  16], [23,  -6], [24,  42], [25,  38], [26,  21], [27,  18],
	];
	const maxAbs = Math.max(...data.map((d) => Math.abs(d[1])));

	const attribution = [
		{ code: 'AL-LME', realized: '+248.120', mtm: '+128.025', total: '+376.145', kind: 'pos' as const },
		{ code: 'USDBRL', realized:  '+58.420', mtm:  '+85.500', total: '+143.920', kind: 'pos' as const },
		{ code: 'CU-LME', realized:   '+6.340', mtm:   '+3.200', total:   '+9.540', kind: 'pos' as const },
		{ code: 'ZN-LME', realized:        '0', mtm:   '−1.260', total:   '−1.260', kind: 'neg' as const },
		{ code: 'NI-LME', realized:        '0', mtm:  '−11.300', total:  '−11.300', kind: 'neg' as const },
	];

	const topContrib: { id: string; commodity: string; cp: string; notional: string; fixed: string; current: string; pnl: string; kind: 'pos' | 'neg'; contrib: number }[] = [
		{ id: 'CT-2026-0111', commodity: 'AL-LME', cp: 'JPM',  notional:  '5.204.000', fixed: '2.602,00', current: '2.645,50', pnl: '+87.000', kind: 'pos', contrib: 100 },
		{ id: 'CT-2026-0112', commodity: 'USDBRL', cp: 'BRAD', notional:  '7.638.000', fixed: '5,0920',   current: '5,1240',   pnl: '+48.000', kind: 'pos', contrib:  55 },
		{ id: 'CT-2026-0117', commodity: 'USDBRL', cp: 'JPM',  notional: '15.334.500', fixed: '5,1115',   current: '5,1240',   pnl: '+37.500', kind: 'pos', contrib:  43 },
		{ id: 'CT-2026-0118', commodity: 'AL-LME', cp: 'ITAU', notional:  '3.946.500', fixed: '2.631,00', current: '2.645,30', pnl: '+21.450', kind: 'pos', contrib:  25 },
		{ id: 'CT-2026-0116', commodity: 'AL-LME', cp: 'SANT', notional:  '2.365.650', fixed: '2.628,50', current: '2.645,50', pnl: '+15.300', kind: 'pos', contrib:  18 },
		{ id: 'CT-2026-0110', commodity: 'AL-LME', cp: 'BTG',  notional:  '3.186.000', fixed: '2.655,00', current: '2.645,50', pnl: '−11.400', kind: 'neg', contrib:  13 },
	];
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">P&amp;L</h1>
			<div class="page-sub">Resultado realizado, não-realizado e atribuição</div>
		</div>
		<div class="page-actions">
			<div class="radio-group">
				<button type="button" class:active={period === 'MTD'} onclick={() => (period = 'MTD')}>MTD</button>
				<button type="button" class:active={period === 'QTD'} onclick={() => (period = 'QTD')}>QTD</button>
				<button type="button" class:active={period === 'YTD'} onclick={() => (period = 'YTD')}>YTD</button>
				<button type="button" class:active={period === 'Custom'} onclick={() => (period = 'Custom')}>Custom</button>
			</div>
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Exportar</button>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi
			label="P&L total MTD"        value="+US$ 517.045"  delta="+2,4 % vs mês anterior" deltaKind="pos"
			spark={[100, 120, 160, 180, 210, 260, 300, 420, 517]} sparkColor="var(--pos)"
		/>
		<Kpi label="Realizado"            value="+US$ 312.880"  delta="20 contratos liquidados" deltaKind="pos"/>
		<Kpi label="Não-realizado (MTM)"  value="+US$ 204.165"  delta="+US$ 18.460 1d"          deltaKind="pos"/>
		<Kpi label="Sharpe (anualizado)"  value="2,18"          delta="+0,21 vs trimestre"      deltaKind="pos"/>
	</div>

	<div class="grid-7-5" style="margin-bottom: 16px;">
		<Card title="P&L diário · maio/2026" sub="Realizado + variação MTM · USD">
			<div style="height: 200px; position: relative; display: flex; align-items: center;">
				<div class="row gap-1" style="align-items: stretch; height: 100%; flex: 1; padding: 0 4px;">
					{#each data as [d, v] (d)}
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

		<Card title="Atribuição" sub="MTD">
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
							<td class="num">{a.realized}</td>
							<td class="num">{a.mtm}</td>
							<td class="num strong" style="color: {a.kind === 'pos' ? 'var(--pos)' : 'var(--neg)'};">{a.total}</td>
						</tr>
					{/each}
				</tbody>
				<tfoot>
					<tr style="border-top: 2px solid var(--line-strong);">
						<td class="strong">Total</td>
						<td class="num strong">+312.880</td>
						<td class="num strong">+204.165</td>
						<td class="num strong" style="color: var(--pos);">+517.045</td>
					</tr>
				</tfoot>
			</table>
		</Card>
	</div>

	<Card title="Top contribuintes" sub="Contratos com maior impacto MTD" noPad>
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
			</tbody>
		</table>
	</Card>
</div>
