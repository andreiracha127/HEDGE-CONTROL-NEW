<script lang="ts">
	import { page } from '$app/state';
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	type Contract = Record<string, any>;
	let { data } = $props();
	const counterparties = $derived(data.counterparties);
	const contracts = $derived((data.contracts ?? []) as Contract[]);

	const id = $derived(page.params.id ?? '');
	const cp = $derived(counterparties.find((c) => c.id === id || c.short === id) ?? counterparties[0]);
	let tab = $state<'resumo' | 'contratos' | 'limites' | 'atividade'>('resumo');

	const usePct = $derived(cp.limit > 0 ? (cp.used / cp.limit) * 100 : 0);
	const cpContracts = $derived<Contract[]>(contracts.filter((c) => c.counterparty_id === cp.id || c.cp_id === cp.id || c.cp === cp.short));
	const mtm = $derived(cpContracts.reduce((s, c) => s + (Number(c.mtm) || 0), 0));
	const latestContractDate = $derived(
		cpContracts
			.map((contract) => contract.created_at ?? contract.traded ?? contract.settle)
			.filter(Boolean)
			.sort()
			.at(-1) ?? null,
	);
	const concentrationRows = $derived.by(() => {
		const byCommodity = new Map<string, number>();
		for (const contract of cpContracts) {
			const qty = Number(contract.qty);
			const price = Number(contract.price);
			const notional = Number.isFinite(qty) && Number.isFinite(price) ? Math.abs(qty * price) : 0;
			if (notional === 0) continue;
			byCommodity.set(contract.commodity ?? '—', (byCommodity.get(contract.commodity ?? '—') ?? 0) + notional);
		}
		const total = Array.from(byCommodity.values()).reduce((sum, value) => sum + value, 0);
		return Array.from(byCommodity.entries()).map(([commodity, notional]) => ({
			commodity,
			pct: total > 0 ? (notional / total) * 100 : 0,
		}));
	});

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

	function fmtText(value: unknown): string {
		return typeof value === 'string' && value.trim() ? value : '—';
	}

	function fmtMtm(value: number | null | undefined): string {
		if (value == null) return '—';
		return `${value >= 0 ? '+' : ''}${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
	}

	function fmtUsdMillions(value: number | null | undefined): string {
		if (value == null || !Number.isFinite(value)) return '—';
		return `US$ ${(value / 1_000_000).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} M`;
	}
</script>

<div class="page">
	<div class="page-head">
		<div style="flex: 1;">
			<div class="row gap-2" style="margin-bottom: 4px;">
				<a href="/counterparties" class="btn btn-link"><Icon name="arrowLeft"/> Contrapartes</a>
				<span style="color: var(--muted);">/</span>
				<span class="mono" style="font-size: 12px; color: var(--muted);">{cp.id}</span>
			</div>
			<div class="row gap-3" style="align-items: center;">
				<div style="width: 44px; height: 44px; border-radius: 8px; background: var(--navy); color: #fff; display: grid; place-items: center; font-size: 14px; font-weight: 600;">{cp.short.slice(0, 3)}</div>
				<div>
					<h1 class="page-title" style="margin: 0;">{cp.name}</h1>
					<div class="row gap-2" style="margin-top: 4px;">
						<Badge kind={cp.rating.startsWith('AA') ? 'pos' : 'neutral'}>{cp.rating}</Badge>
						<StatePill state={cp.status}/>
						<Badge kind="neutral">{cp.short}</Badge>
						<span style="font-size: 11.5px; color: var(--muted);">· {fmtText(cp.type)} · {fmtText(cp.city)} · {fmtText(cp.country)}</span>
					</div>
				</div>
			</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary">Editar</button>
			<button type="button" class="btn btn-secondary">Histórico KYC</button>
			<a href="/rfq/new" class="btn btn-primary"><Icon name="plus"/>Nova RFQ</a>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Limite de crédito" value={fmtUsdMillions(cp.limit)} delta="credit_limit_usd"/>
		<Kpi
			label="Utilização"
			value={`${usePct.toFixed(0)}`}
			unit="%"
			delta={`${fmtUsdMillions(cp.used)} em uso`}
			deltaKind={usePct > 80 ? 'neg' : usePct > 60 ? 'flat' : 'pos'}
		/>
		<Kpi label="Contratos carregados" value={String(cpContracts.length)} delta="/contracts/hedge"/>
		<Kpi
			label="MTM (USD)"
			value={(mtm >= 0 ? '+' : '') + mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}
			delta="mtm_value carregado"
			deltaKind={mtm >= 0 ? 'pos' : 'neg'}
		/>
	</div>

	<div class="tabs">
		<button type="button" class="tab" class:active={tab === 'resumo'} onclick={() => (tab = 'resumo')}>Resumo</button>
		<button type="button" class="tab" class:active={tab === 'contratos'} onclick={() => (tab = 'contratos')}>Contratos ({cpContracts.length})</button>
		<button type="button" class="tab" class:active={tab === 'limites'} onclick={() => (tab = 'limites')}>Limites &amp; KYC</button>
		<button type="button" class="tab" class:active={tab === 'atividade'} onclick={() => (tab = 'atividade')}>Atividade</button>
	</div>

	{#if tab === 'resumo'}
		<div class="detail-grid">
			<div class="stack gap-4">
				<Card title="Identificação">
					<dl class="kv" style="grid-template-columns: 160px 1fr 160px 1fr;">
						<dt>Razão social</dt><dd>{fmtText(cp.legal_name ?? cp.name)}</dd>
						<dt>Tax ID (CNPJ)</dt><dd class="mono">{fmtText(cp.tax_id)}</dd>
						<dt>Tipo</dt><dd>{fmtText(cp.type)}</dd>
						<dt>País</dt><dd>{fmtText(cp.country)}</dd>
						<dt>Cidade</dt><dd>{fmtText(cp.city)}</dd>
						<dt>Endereço</dt><dd>{fmtText(cp.address)}</dd>
						<dt>Cadastro</dt><dd>{fmtDate(cp.created_at ?? cp.created)}</dd>
						<dt>Última operação</dt><dd>{fmtDate(latestContractDate)}</dd>
					</dl>
				</Card>

				<Card title="Contato">
					<dl class="kv">
						<dt>Contato principal</dt><dd>{fmtText(cp.contact_name)}</dd>
						<dt>Email</dt><dd>{fmtText(cp.contact_email)}</dd>
						<dt>Telefone</dt><dd>{fmtText(cp.contact_phone)}</dd>
						<dt>WhatsApp</dt><dd>{fmtText(cp.whatsapp_phone)}</dd>
					</dl>
				</Card>

				<Card title="Operações recentes" noPad>
					<table class="tbl tbl-tight">
						<thead>
							<tr><th>Quando</th><th>Tipo</th><th>Entidade</th><th class="num">Volume</th><th>Status</th></tr>
						</thead>
						<tbody>
							{#each cpContracts as contract (contract.id)}
								<tr>
									<td>{fmtDate(contract.created_at ?? contract.traded)}</td>
									<td>Contrato</td>
									<td class="mono">{contract.id}</td>
									<td class="num">{fmtQty(contract)}</td>
									<td><StatePill state={contract.status}/></td>
								</tr>
							{/each}
							{#if cpContracts.length === 0}
								<tr><td colspan="5" class="tbl-empty">Nenhuma operação carregada para esta contraparte</td></tr>
							{/if}
						</tbody>
					</table>
				</Card>
			</div>

			<div class="stack gap-4">
				<Card title="Utilização do limite">
					<div class="row gap-3" style="align-items: center; margin-bottom: 14px;">
						<div class="donut" style="background: conic-gradient(var(--navy) 0% {usePct}%, var(--surface-sunk) {usePct}% 100%);">
							<div class="donut-label">
								<div>
									<div class="v">{usePct.toFixed(0)}%</div>
									<div class="l">utilizado</div>
								</div>
							</div>
						</div>
						<div style="flex: 1;">
							<dl class="kv">
								<dt>Limite</dt><dd class="tabular">{fmtUsdMillions(cp.limit)}</dd>
								<dt>Em uso</dt><dd class="tabular strong">{fmtUsdMillions(cp.used)}</dd>
								<dt>Disponível</dt><dd class="tabular" style="color: var(--pos);">{fmtUsdMillions(cp.limit - cp.used)}</dd>
							</dl>
						</div>
					</div>
					<div class="divider" style="margin: 6px 0 12px;"></div>
					<div class="section-title" style="margin-bottom: 8px;">Concentração por commodity</div>
					<div class="stack gap-2">
						{#each concentrationRows as row (row.commodity)}
							<div class="row gap-3">
								<span style="width: 80px; font-size: 12px;">{row.commodity}</span>
								<Bar pct={row.pct} kind={row.pct > 80 ? 'neg' : row.pct > 60 ? 'warn' : 'pos'}/>
								<span class="tabular" style="width: 40px; text-align: right; font-size: 11px;">{row.pct.toFixed(0)}%</span>
							</div>
						{/each}
						{#if concentrationRows.length === 0}
							<div class="tbl-empty">Nenhuma concentração carregada</div>
						{/if}
					</div>
				</Card>

				<Card title="Compliance">
					<dl class="kv">
						<dt>KYC</dt><dd>{fmtText(cp.kyc_status)}</dd>
						<dt>Sanctions</dt><dd>{fmtText(cp.sanctions_status)}</dd>
						<dt>Rating</dt><dd>{fmtText(cp.rating)}</dd>
						<dt>Ativa</dt><dd>{cp.is_active === true ? 'Sim' : cp.is_active === false ? 'Não' : '—'}</dd>
					</dl>
				</Card>
			</div>
		</div>
	{:else if tab === 'contratos'}
		<Card title="Contratos ativos" sub={`${cpContracts.length} contratos carregados`} noPad>
			<table class="tbl">
				<thead>
					<tr>
						<th>Contrato</th><th>Commodity</th><th>Tipo</th><th class="num">Qtd</th>
						<th class="num">Preço</th><th>Vencimento</th><th class="num">MTM (USD)</th><th>Status</th>
					</tr>
				</thead>
				<tbody>
					{#if cpContracts.length}
						{#each cpContracts as c (c.id)}
							<tr>
								<td class="mono strong"><a href={`/contracts/${c.id}`}>{c.id}</a></td>
								<td><CommodityChip code={c.commodity}/></td>
								<td>{c.type}</td>
								<td class="num">{fmtQty(c)}</td>
								<td class="num">{fmtPrice(c)}</td>
								<td>{fmtDate(c.settle)}</td>
								<td class="num strong" style="color: {c.mtm == null ? 'var(--muted)' : c.mtm >= 0 ? 'var(--pos)' : 'var(--neg)'};">
									{fmtMtm(c.mtm)}
								</td>
								<td><StatePill state={c.status}/></td>
							</tr>
						{/each}
					{:else}
						<tr><td colspan="8" class="tbl-empty">Nenhum contrato ativo com esta contraparte</td></tr>
					{/if}
				</tbody>
			</table>
		</Card>
	{:else if tab === 'limites'}
		<div class="grid-2">
			<Card title="Histórico de limites" noPad>
				<table class="tbl tbl-tight">
					<thead><tr><th>Data</th><th class="num">Limite</th><th class="num">Δ</th><th>Aprovador</th></tr></thead>
					<tbody>
						<tr><td colspan="4" class="tbl-empty">Nenhum histórico de limite carregado</td></tr>
					</tbody>
				</table>
			</Card>

			<Card title="Trilha KYC">
				<div class="feed">
					<div class="tbl-empty">Nenhuma trilha KYC carregada</div>
				</div>
			</Card>
		</div>
	{:else if tab === 'atividade'}
		<Card title="Linha do tempo">
			<div class="feed">
				<div class="tbl-empty">Nenhuma atividade carregada para esta contraparte</div>
			</div>
		</Card>
	{/if}
</div>
