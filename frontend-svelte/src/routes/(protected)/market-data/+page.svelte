<script lang="ts">
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	let { data } = $props();
	const commodities = $derived(data.commodities);

	const providers = [
		{ p: 'Refinitiv (LSEG)', sla: 99.97, status: 'pos' as const  },
		{ p: 'LME oficial',      sla: 99.91, status: 'pos' as const  },
		{ p: 'B3 (FX)',          sla: 99.99, status: 'pos' as const  },
		{ p: 'Bloomberg BBG',    sla: 98.40, status: 'warn' as const },
		{ p: 'CME Group',        sla: 99.85, status: 'pos' as const  },
	];

	const forward: [string, number, number, number, string, 'alta' | 'média' | 'baixa', number][] = [
		['jun/26', 2643, 2648, 2645.5, '+0,00 %', 'alta',  12],
		['jul/26', 2651, 2657, 2654.0, '+0,32 %', 'alta',   8],
		['ago/26', 2659, 2666, 2662.5, '+0,64 %', 'alta',   5],
		['set/26', 2667, 2675, 2671.0, '+0,96 %', 'média',  3],
		['out/26', 2675, 2684, 2679.5, '+1,29 %', 'média',  1],
		['nov/26', 2683, 2693, 2688.0, '+1,61 %', 'baixa',  0],
		['dez/26', 2691, 2702, 2696.5, '+1,93 %', 'baixa',  0],
	];

	function liquidityKind(l: 'alta' | 'média' | 'baixa'): 'pos' | 'warn' | 'neutral' {
		if (l === 'alta') return 'pos';
		if (l === 'média') return 'warn';
		return 'neutral';
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Dados de mercado</h1>
			<div class="page-sub">Cotações, curvas e provedores · atualizado 09:14</div>
		</div>
		<div class="page-actions">
			<Badge kind="pos" dot>Refinitiv ao vivo</Badge>
			<button type="button" class="btn btn-secondary"><Icon name="refresh"/>Atualizar</button>
		</div>
	</div>

	<div class="grid-7-5" style="margin-bottom: 16px;">
		<Card title="Spot" sub="Última cotação · USD" noPad>
			<table class="tbl">
				<thead>
					<tr>
						<th>Commodity</th>
						<th class="num">Última</th>
						<th class="num">Bid</th>
						<th class="num">Ask</th>
						<th class="num">Spread</th>
						<th class="num">Δ Dia</th>
						<th>Provedor</th>
						<th>Última atualização</th>
					</tr>
				</thead>
				<tbody>
					{#each commodities as c (c.code)}
						{@const hasLast = c.last != null}
						{@const hasPrev = c.prev != null && c.prev !== 0}
						{@const chg = hasLast && hasPrev ? ((c.last - c.prev) / c.prev) * 100 : null}
						{@const spread = c.code === 'USDBRL' ? 0.0005 : 1.5}
						{@const bid = hasLast ? c.last - spread / 2 : null}
						{@const ask = hasLast ? c.last + spread / 2 : null}
						{@const digits = c.code === 'USDBRL' ? 4 : 2}
						<tr>
							<td class="strong">
								<CommodityChip code={c.code}/>
								<div style="font-size: 11px; color: var(--muted); font-weight: 400; margin-top: 1px;">{c.name}</div>
							</td>
							<td class="num strong">{hasLast ? c.last.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : '—'}</td>
							<td class="num">{bid != null ? bid.toFixed(digits) : '—'}</td>
							<td class="num">{ask != null ? ask.toFixed(digits) : '—'}</td>
							<td class="num">{spread.toFixed(digits)}</td>
							<td class="num" style="color: {chg == null ? 'var(--muted)' : chg >= 0 ? 'var(--pos)' : 'var(--neg)'};">
								{chg == null ? '—' : `${chg >= 0 ? '+' : ''}${chg.toFixed(2)} %`}
							</td>
							<td><Badge kind="neutral">{c.code === 'USDBRL' ? 'B3' : 'Refinitiv'}</Badge></td>
							<td style="color: var(--muted); font-size: 12px;">27/05 09:14:08</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</Card>

		<Card title="Status dos provedores" sub="Disponibilidade · 24h">
			<div class="stack" style="gap: 8px;">
				{#each providers as p (p.p)}
					<div class="row gap-3" style="padding: 8px 0; border-bottom: 1px solid var(--line-soft);">
						<div style="flex: 1;">
							<div style="font-size: 12.5px; font-weight: 500;">{p.p}</div>
							<div style="font-size: 11px; color: var(--muted);">SLA {p.sla.toFixed(2)} %</div>
						</div>
						<Badge kind={p.status} dot>{p.status === 'pos' ? 'Operacional' : 'Atenção'}</Badge>
					</div>
				{/each}
			</div>
		</Card>
	</div>

	<Card title="Curva forward · AL-LME" sub="Preço por janela de entrega · USD/t">
		<table class="tbl tbl-tight">
			<thead>
				<tr>
					<th>Janela</th>
					<th class="num">Bid</th>
					<th class="num">Ask</th>
					<th class="num">Mid</th>
					<th class="num">Contango / Backwardation</th>
					<th>Liquidez</th>
					<th>Aberto na plataforma</th>
				</tr>
			</thead>
			<tbody>
				{#each forward as [w, b, a, m, contango, liquidity, n] (w)}
					<tr>
						<td class="strong">{w}</td>
						<td class="num">{b.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
						<td class="num">{a.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
						<td class="num strong">{m.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td>
						<td class="num" style="color: var(--info);">{contango}</td>
						<td><Badge kind={liquidityKind(liquidity)}>{liquidity}</Badge></td>
						<td class="num">{n}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</Card>
</div>
