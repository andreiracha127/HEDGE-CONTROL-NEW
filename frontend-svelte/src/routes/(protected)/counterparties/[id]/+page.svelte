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
	const contracts = $derived(data.contracts);

	const id = $derived(page.params.id ?? '');
	const cp = $derived(counterparties.find((c) => c.id === id || c.short === id) ?? counterparties[0]);
	let tab = $state<'resumo' | 'contratos' | 'limites' | 'atividade'>('resumo');

	const usePct = $derived((cp.used / cp.limit) * 100);
	const cpContracts = $derived<Contract[]>(contracts.filter((c) => c.counterparty_id === cp.id || c.cp_id === cp.id || c.cp === cp.short));
	const mtm = $derived(cpContracts.reduce((s, c) => s + (Number(c.mtm) || 0), 0));

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
		<Kpi label="Limite de crédito" value={`US$ ${(cp.limit / 1_000_000).toFixed(1)}`} unit="M" delta="aprovado 18/03/2026"/>
		<Kpi
			label="Utilização"
			value={`${usePct.toFixed(0)}`}
			unit="%"
			delta={`US$ ${(cp.used / 1_000_000).toFixed(1)} M em uso`}
			deltaKind={usePct > 80 ? 'neg' : usePct > 60 ? 'flat' : 'pos'}
		/>
		<Kpi label="Contratos ativos" value={String(cpContracts.length)} delta={`Notional US$ ${(cp.used / 1_000_000).toFixed(1)} M`}/>
		<Kpi
			label="MTM (USD)"
			value={(mtm >= 0 ? '+' : '') + mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}
			delta="marcação 11:30 BST"
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
						<dt>Última operação</dt><dd>27/05/2026 09:14</dd>
					</dl>
				</Card>

				<Card title="Contato">
					<dl class="kv">
						<dt>Mesa</dt><dd>Mesa de Commodities</dd>
						<dt>Contato principal</dt><dd>Maria Santos · trader@{cp.short.toLowerCase()}.com.br</dd>
						<dt>Telefone</dt><dd>+55 11 3000-0000</dd>
						<dt>WhatsApp</dt><dd>+55 11 99999-0000</dd>
						<dt>Canal RFQ</dt><dd><Badge kind="pos" dot>Email + WhatsApp</Badge></dd>
					</dl>
				</Card>

				<Card title="Operações recentes" noPad>
					<table class="tbl tbl-tight">
						<thead>
							<tr><th>Quando</th><th>Tipo</th><th>Entidade</th><th class="num">Volume</th><th>Status</th></tr>
						</thead>
						<tbody>
							<tr><td>27/05 09:14</td><td>RFQ</td><td class="mono">RFQ-2026-0184</td><td class="num">1.200 MT</td><td><StatePill state="QUOTED"/></td></tr>
							<tr><td>27/05 09:04</td><td>Ordem</td><td class="mono">ORD-2026-0419</td><td class="num">1.500 MT</td><td><StatePill state="filled"/></td></tr>
							<tr><td>26/05 13:02</td><td>Ordem</td><td class="mono">ORD-2026-0415</td><td class="num">700 MT</td><td><StatePill state="filled"/></td></tr>
							<tr><td>25/05 11:18</td><td>RFQ</td><td class="mono">RFQ-2026-0167</td><td class="num">2.000 MT</td><td><StatePill state="QUOTED"/></td></tr>
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
								<dt>Limite</dt><dd class="tabular">US$ {(cp.limit / 1_000_000).toFixed(1)} M</dd>
								<dt>Em uso</dt><dd class="tabular strong">US$ {(cp.used / 1_000_000).toFixed(1)} M</dd>
								<dt>Disponível</dt><dd class="tabular" style="color: var(--pos);">US$ {((cp.limit - cp.used) / 1_000_000).toFixed(1)} M</dd>
							</dl>
						</div>
					</div>
					<div class="divider" style="margin: 6px 0 12px;"></div>
					<div class="section-title" style="margin-bottom: 8px;">Concentração por commodity</div>
					<div class="stack gap-2">
						<div class="row gap-3">
							<span style="width: 80px; font-size: 12px;">AL-LME</span>
							<Bar pct={72} kind="pos"/>
							<span class="tabular" style="width: 40px; text-align: right; font-size: 11px;">72%</span>
						</div>
						<div class="row gap-3">
							<span style="width: 80px; font-size: 12px;">USDBRL</span>
							<Bar pct={21} kind="pos"/>
							<span class="tabular" style="width: 40px; text-align: right; font-size: 11px;">21%</span>
						</div>
						<div class="row gap-3">
							<span style="width: 80px; font-size: 12px;">CU-LME</span>
							<Bar pct={7} kind="pos"/>
							<span class="tabular" style="width: 40px; text-align: right; font-size: 11px;">7%</span>
						</div>
					</div>
				</Card>

				<Card title="Compliance">
					<dl class="kv">
						<dt>KYC</dt><dd><Badge kind="pos" dot>Aprovado</Badge> <span style="color: var(--muted); font-size: 11px;">· renova em 12/09/2026</span></dd>
						<dt>Sanctions</dt><dd><Badge kind="pos" dot>Clear</Badge> <span style="color: var(--muted); font-size: 11px;">· última varredura 25/05</span></dd>
						<dt>Rating externo</dt><dd>S&amp;P {cp.rating} · Moody's Aa3</dd>
						<dt>Política IFRS</dt><dd>Aprovado para hedge accounting</dd>
					</dl>
				</Card>
			</div>
		</div>
	{:else if tab === 'contratos'}
		<Card title="Contratos ativos" sub={`${cpContracts.length} contratos · notional total US$ ${(cp.used / 1_000_000).toFixed(1)} M`} noPad>
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
						<tr><td>18/03/2026</td><td class="num tabular strong">{(cp.limit / 1_000_000).toFixed(1)} M</td><td class="num" style="color: var(--pos);">+2,0 M</td><td>Comitê de Risco</td></tr>
						<tr><td>15/09/2025</td><td class="num tabular">{((cp.limit - 2_000_000) / 1_000_000).toFixed(1)} M</td><td class="num">—</td><td>Comitê de Risco</td></tr>
						<tr><td>22/03/2025</td><td class="num tabular">{((cp.limit - 4_000_000) / 1_000_000).toFixed(1)} M</td><td class="num" style="color: var(--pos);">+1,5 M</td><td>Comitê de Risco</td></tr>
						<tr><td>10/09/2024</td><td class="num tabular">{((cp.limit - 5_500_000) / 1_000_000).toFixed(1)} M</td><td class="num">Inicial</td><td>Comitê de Risco</td></tr>
					</tbody>
				</table>
			</Card>

			<Card title="Trilha KYC">
				<div class="feed">
					<div class="feed-item pos"><div class="icon"></div><div><div class="what">KYC renovado · documentação atualizada</div><div class="row gap-2"><span class="when">12/03/2026</span><span class="who">· L. Ferreira</span></div></div></div>
					<div class="feed-item pos"><div class="icon"></div><div><div class="what">Sanctions screening · clear (OFAC, Bacen, EU)</div><div class="row gap-2"><span class="when">25/05/2026</span><span class="who">· Sistema</span></div></div></div>
					<div class="feed-item info"><div class="icon"></div><div><div class="what">Limite ampliado de US$ 10 M → US$ 12 M</div><div class="row gap-2"><span class="when">18/03/2026</span><span class="who">· Comitê de Risco</span></div></div></div>
					<div class="feed-item info"><div class="icon"></div><div><div class="what">Revisão semestral concluída · sem restrições</div><div class="row gap-2"><span class="when">15/09/2025</span><span class="who">· A. Costa</span></div></div></div>
					<div class="feed-item pos"><div class="icon"></div><div><div class="what">Habilitação inicial para operar RFQs</div><div class="row gap-2"><span class="when">10/09/2024</span><span class="who">· Comitê de Risco</span></div></div></div>
				</div>
			</Card>
		</div>
	{:else if tab === 'atividade'}
		<Card title="Linha do tempo">
			<div class="feed">
				<div class="feed-item pos"><div class="icon"></div><div><div class="what">RFQ <strong>RFQ-2026-0184</strong> enviada · AL-LME 1.200t buy</div><div class="row gap-2"><span class="when">hoje 09:14</span><span class="who">· M. Santos</span></div></div></div>
				<div class="feed-item pos"><div class="icon"></div><div><div class="what">Ordem <strong>ORD-2026-0419</strong> liquidada · 1.500t @ 2.631,00</div><div class="row gap-2"><span class="when">hoje 09:04</span><span class="who">· R. Almeida</span></div></div></div>
				<div class="feed-item info"><div class="icon"></div><div><div class="what">Contrato CT-2026-0118 aprovado</div><div class="row gap-2"><span class="when">ontem 17:55</span><span class="who">· A. Costa</span></div></div></div>
				<div class="feed-item pos"><div class="icon"></div><div><div class="what">Ordem ORD-2026-0415 liquidada · 700t</div><div class="row gap-2"><span class="when">ontem 13:02</span><span class="who">· R. Almeida</span></div></div></div>
				<div class="feed-item info"><div class="icon"></div><div><div class="what">Sanctions screening · clear</div><div class="row gap-2"><span class="when">25/05</span><span class="who">· Sistema</span></div></div></div>
				<div class="feed-item warn"><div class="icon"></div><div><div class="what">Limite revisado preventivamente · sem alteração</div><div class="row gap-2"><span class="when">22/05</span><span class="who">· L. Ferreira</span></div></div></div>
				<div class="feed-item info"><div class="icon"></div><div><div class="what">RFQ RFQ-2026-0145 cancelada</div><div class="row gap-2"><span class="when">20/05</span><span class="who">· M. Santos</span></div></div></div>
			</div>
		</Card>
	{/if}
</div>
