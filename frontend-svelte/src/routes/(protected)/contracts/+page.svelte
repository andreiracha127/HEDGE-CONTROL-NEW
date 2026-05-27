<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import Pager from '$lib/components/alcast/Pager.svelte';
	type Contract = Record<string, any>;
	let { data } = $props();
	const contracts = $derived(data.contracts);

	let tab = $state<'active' | 'maturing' | 'settled'>('active');
	const OPEN_CONTRACT_STATUSES = new Set(['active', 'partially_settled']);
	const maturingContracts = $derived(
		contracts.filter((contract) => {
			if (contract.status === 'partially_settled') return true;
			const settleMs = contract.settle ? Date.parse(contract.settle) : Number.NaN;
			if (!Number.isFinite(settleMs) || contract.status !== 'active') return false;
			const now = Date.now();
			const thirtyDays = 30 * 24 * 60 * 60 * 1000;
			return settleMs >= now && settleMs <= now + thirtyDays;
		}),
	);
	const activeContracts = $derived(contracts.filter((contract) => OPEN_CONTRACT_STATUSES.has(contract.status)));
	const settledContracts = $derived(contracts.filter((contract) => contract.status === 'settled'));
	const TABS = $derived<[typeof tab, string, number][]>([
		['active',   'Ativos',     activeContracts.length],
		['maturing', 'Vencendo',   maturingContracts.length],
		['settled',  'Liquidados', settledContracts.length],
	]);
	const filteredContracts = $derived(
		contracts.filter((contract) => {
			const status = contract.status;
			if (tab === 'active') return OPEN_CONTRACT_STATUSES.has(status);
			if (tab === 'settled') return status === 'settled';
			return maturingContracts.includes(contract);
		}),
	);
	const totalNotional = $derived(
		contracts.reduce((sum, contract) => {
			const qty = Number(contract.qty);
			const price = Number(contract.price);
			return Number.isFinite(qty) && Number.isFinite(price) ? sum + Math.abs(qty * price) : sum;
		}, 0),
	);
	const aggregateMtm = $derived(
		contracts.reduce((sum, contract) => {
			const mtm = Number(contract.mtm);
			return Number.isFinite(mtm) ? sum + mtm : sum;
		}, 0),
	);
	const maturingNotional = $derived(
		maturingContracts.reduce((sum, contract) => {
			const qty = Number(contract.qty);
			const price = Number(contract.price);
			return Number.isFinite(qty) && Number.isFinite(price) ? sum + Math.abs(qty * price) : sum;
		}, 0),
	);

	function fmtQty(c: Contract): string {
		if (c.qty == null) return '—';
		if (c.commodity === 'USDBRL') return 'US$ ' + (c.qty / 1_000_000).toFixed(1) + ' M';
		return c.qty.toLocaleString('pt-BR') + ' t';
	}

	function fmtPrice(c: Contract): string {
		if (c.price == null) return '—';
		const digits = c.commodity === 'USDBRL' ? 4 : 2;
		return c.price.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
	}

	function fmtDate(value: string | null | undefined): string {
		return value ? value.split('-').reverse().join('/') : '—';
	}

	function fmtMtm(value: number | null | undefined): string {
		if (value == null) return '—';
		return `${value >= 0 ? '+' : ''}${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
	}

	function fmtUsdMillions(value: number): string {
		return `US$ ${(value / 1_000_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} M`;
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Contratos</h1>
			<div class="page-sub">Posições derivativas ativas e vencendo</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Exportar</button>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Contratos ativos"                  value={String(activeContracts.length)} delta={`${maturingContracts.length} vencendo em 30d`} deltaKind="flat"/>
		<Kpi label="Notional total"                    value={fmtUsdMillions(totalNotional)}  delta={`${contracts.length} contrato(s)`}             deltaKind="flat"/>
		<Kpi label="MTM agregado"                      value={`${aggregateMtm >= 0 ? '+US$ ' : '-US$ '}${Math.abs(aggregateMtm).toLocaleString('en-US', { maximumFractionDigits: 0 })}`} delta="carteira carregada" deltaKind={aggregateMtm >= 0 ? 'pos' : 'neg'}/>
		<Kpi label="Contratos no vencimento (30d)"     value={String(maturingContracts.length)} delta={`Notional ${fmtUsdMillions(maturingNotional)}`} deltaKind="flat"/>
	</div>

	<Card noPad>
		<div class="tbl-tools">
			<div class="tabs-pill">
				{#each TABS as [k, l, c] (k)}
					<button type="button" class="tab" class:active={tab === k} onclick={() => (tab = k)}>
						{l} <span style="color: var(--muted-2); margin-left: 4px;">{c}</span>
					</button>
				{/each}
			</div>
			<div class="sp"></div>
			<button type="button" class="chip"><Icon name="filter"/>Commodity</button>
			<button type="button" class="chip"><Icon name="filter"/>Contraparte</button>
			<button type="button" class="chip"><Icon name="filter"/>Vencimento</button>
		</div>

		<table class="tbl">
			<thead>
				<tr>
					<th>Contrato</th>
					<th>Commodity</th>
					<th>Tipo</th>
					<th>Pernas</th>
					<th class="num">Qtd</th>
					<th class="num">Preço fixo</th>
					<th>Contraparte</th>
					<th>Vencimento</th>
					<th class="num">MTM (USD)</th>
					<th>Status</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each filteredContracts as c (c.id)}
					<tr>
						<td class="strong mono"><a href={`/contracts/${c.id}`}>{c.id}</a></td>
						<td><CommodityChip code={c.commodity}/></td>
						<td>{c.type}</td>
						<td>
							<span class="row gap-2" style="font-size: 11px;">
								<Badge kind={c.fixed_leg === 'buy' ? 'pos' : 'neg'}>{c.fixed_leg === 'buy' ? 'Compra' : 'Venda'} fixa</Badge>
								<span style="color: var(--muted);">×</span>
								<Badge kind="neutral">{c.var_leg === 'buy' ? 'Compra' : 'Venda'} var.</Badge>
							</span>
						</td>
						<td class="num">{fmtQty(c)}</td>
						<td class="num strong">{fmtPrice(c)}</td>
						<td>{c.cp}</td>
						<td>{fmtDate(c.settle)}</td>
						<td class="num strong" style="color: {c.mtm == null ? 'var(--muted)' : c.mtm >= 0 ? 'var(--pos)' : 'var(--neg)'};">
							{fmtMtm(c.mtm)}
						</td>
						<td><StatePill state={c.status}/></td>
						<td><button type="button" class="btn btn-ghost btn-sm"><Icon name="chevronRight"/></button></td>
					</tr>
				{/each}
				{#if filteredContracts.length === 0}
					<tr><td colspan="11" class="tbl-empty">Nenhum contrato para o filtro selecionado</td></tr>
				{/if}
			</tbody>
		</table>
		<Pager from={filteredContracts.length > 0 ? 1 : 0} to={filteredContracts.length} total={filteredContracts.length}/>
	</Card>
</div>
