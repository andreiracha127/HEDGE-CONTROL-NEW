<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	let { data } = $props();
	const counterparties = $derived(data.counterparties);

	// Deterministic per-row pseudo-data so the table doesn't change across renders.
	function spread(seed: number): string {
		const v = 1.4 + ((seed * 9301 + 49297) % 1800) / 1000;
		return v.toFixed(1) + ' bps';
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Contrapartes</h1>
			<div class="page-sub">Limites de crédito, rating e exposição corrente</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Exportar</button>
			<a href="/counterparties/new" class="btn btn-primary"><Icon name="plus"/>Nova contraparte</a>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Contrapartes ativas"     value="6"          delta="1 em análise"                        deltaKind="flat"/>
		<Kpi label="Limite agregado"         value="US$ 62,0 M" delta="utilizado 53 %"                       deltaKind="flat"/>
		<Kpi label="Concentração top-1"      value="24,1" unit="%" delta="JPMorgan · dentro do limite (≤ 30 %)" deltaKind="pos"/>
		<Kpi label="Spread médio"            value="2,1"  unit="bps" delta="−0,4 bps vs mês"/>
	</div>

	<Card noPad>
		<table class="tbl">
			<thead>
				<tr>
					<th>Contraparte</th>
					<th>Rating</th>
					<th class="num">Limite</th>
					<th class="num">Utilizado</th>
					<th style="width: 200px;">Utilização</th>
					<th class="num">Contratos</th>
					<th class="num">MTM (USD)</th>
					<th class="num">Spread médio</th>
					<th>Status</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each counterparties as cp, idx (cp.id)}
					{@const pct = (cp.used / cp.limit) * 100}
					<tr>
						<td class="strong">
							<a href={`/counterparties/${cp.id}`}>
								<div>{cp.name}</div>
								<div style="font-size: 11px; color: var(--muted); font-weight: 400;">{cp.short} · {cp.id}</div>
							</a>
						</td>
						<td><Badge kind={cp.rating.startsWith('AA') ? 'pos' : 'neutral'}>{cp.rating}</Badge></td>
						<td class="num">US$ {(cp.limit / 1_000_000).toFixed(1)} M</td>
						<td class="num strong">US$ {(cp.used / 1_000_000).toFixed(1)} M</td>
						<td>
							<div class="row gap-3">
								<Bar pct={pct} kind={pct > 80 ? 'neg' : pct > 60 ? 'warn' : 'pos'}/>
								<span class="tabular" style="width: 42px; text-align: right;">{pct.toFixed(0)}%</span>
							</div>
						</td>
						<td class="num">{Math.floor(cp.used / 600_000)}</td>
						<td class="num strong" style="color: var(--pos);">+{Math.floor(cp.used * 0.004).toLocaleString('en-US')}</td>
						<td class="num">{spread(idx + 1)}</td>
						<td><StatePill state={cp.status}/></td>
						<td><button type="button" class="btn btn-ghost btn-sm"><Icon name="chevronRight"/></button></td>
					</tr>
				{/each}
			</tbody>
		</table>
	</Card>
</div>
