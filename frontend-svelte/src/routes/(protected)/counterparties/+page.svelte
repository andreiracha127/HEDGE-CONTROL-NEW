<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	let { data } = $props();
	const counterparties = $derived(data.counterparties);
	const activeCount = $derived(counterparties.filter((cp) => cp.status === 'active').length);
	const reviewCount = $derived(counterparties.filter((cp) => cp.status === 'review').length);
	const totalLimit = $derived(counterparties.reduce((sum, cp) => sum + cp.limit, 0));
	const totalUsed = $derived(counterparties.reduce((sum, cp) => sum + cp.used, 0));
	const usagePct = $derived(totalLimit > 0 ? (totalUsed / totalLimit) * 100 : 0);
	const topConcentration = $derived(totalLimit > 0 ? (Math.max(0, ...counterparties.map((cp) => cp.used)) / totalLimit) * 100 : 0);
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
		<Kpi label="Contrapartes ativas"     value={String(activeCount)} delta={`${reviewCount} em análise`} deltaKind="flat"/>
		<Kpi label="Limite agregado"         value={`US$ ${(totalLimit / 1_000_000).toFixed(1)} M`} delta={`utilizado ${usagePct.toFixed(0)} %`} deltaKind="flat"/>
		<Kpi label="Concentração top-1"      value={topConcentration.toFixed(1)} unit="%" delta="maior utilização / limite agregado" deltaKind={topConcentration <= 30 ? 'pos' : 'flat'}/>
		<Kpi label="Utilização média"        value={usagePct.toFixed(1)} unit="%" delta="credit_used_usd / credit_limit_usd"/>
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
					<th>Status</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each counterparties as cp (cp.id)}
					{@const pct = cp.limit > 0 ? (cp.used / cp.limit) * 100 : 0}
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
						<td><StatePill state={cp.status}/></td>
						<td><button type="button" class="btn btn-ghost btn-sm"><Icon name="chevronRight"/></button></td>
					</tr>
				{/each}
				{#if counterparties.length === 0}
					<tr><td colspan="7" class="tbl-empty">Nenhuma contraparte carregada</td></tr>
				{/if}
			</tbody>
		</table>
	</Card>
</div>
