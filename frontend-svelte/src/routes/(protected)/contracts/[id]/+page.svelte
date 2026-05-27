<script lang="ts">
	import { page } from '$app/state';
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import CommodityChip from '$lib/components/alcast/CommodityChip.svelte';
	import DirectionBadge from '$lib/components/alcast/DirectionBadge.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import MtmSparkline from '$lib/components/alcast/MtmSparkline.svelte';
	type Contract = Record<string, any>;
	let { data } = $props();
	const contracts = $derived(data.contracts);
	const counterparties = $derived(data.counterparties);
	const cashflows = $derived(data.cashflow ?? []);

	const id = $derived(page.params.id ?? '');
	const c = $derived(contracts.find((x) => x.id === id) ?? contracts[0]);
	let tab = $state<'resumo' | 'legs' | 'cashflow' | 'mtm' | 'docs'>('resumo');

	const mid = $derived.by(() => {
		if (c.commodity === 'AL-LME') return 2645.5;
		if (c.commodity === 'CU-LME') return 9412.0;
		if (c.commodity === 'ZN-LME') return 2812.5;
		return c.price ?? null;
	});

	const today = new Date();
	const settleDate = $derived(c?.settle ?? null);
	const daysToSettle = $derived.by(() => {
		if (!settleDate) return null;
		const timestamp = new Date(settleDate).getTime();
		return Number.isFinite(timestamp) ? Math.round((timestamp - today.getTime()) / 86_400_000) : null;
	});
	const notional = $derived(c.qty == null || c.price == null ? null : c.qty * c.price);
	const cpName = $derived(
		counterparties.find((x) => x.short === c.cp)?.name ?? c.cp,
	);

	const TABS: [typeof tab, string][] = [
		['resumo',   'Resumo'],
		['legs',     'Pernas'],
		['cashflow', 'Cash flows'],
		['mtm',      'Histórico MTM'],
		['docs',     'Documentos'],
	];

	function fmtQty(contract: Contract): string {
		if (contract.qty == null) return '—';
		if (contract.commodity === 'USDBRL') return contract.qty.toLocaleString('pt-BR') + ' USD';
		return contract.qty.toLocaleString('pt-BR') + ' MT';
	}

	function fmtPrice(contract: Contract): string {
		if (contract.price == null) return '—';
		return contract.price.toLocaleString('en-US', { minimumFractionDigits: priceDigits(contract) });
	}

	function fmtNumber(value: number | null | undefined, digits = 0): string {
		if (value == null || !Number.isFinite(value)) return '—';
		return value.toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits });
	}

	function fmtUsd(value: number | null | undefined): string {
		if (value == null || !Number.isFinite(value)) return '—';
		return `${value >= 0 ? '+' : ''}US$ ${Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
	}

	function priceDelta(): number | null {
		if (mid == null || c.price == null) return null;
		return mid - c.price;
	}

	function fmtPriceUnit(contract: Contract): string {
		return contract.commodity === 'USDBRL' ? 'USD/BRL' : 'USD/MT';
	}

	function priceDigits(contract: Contract): number {
		return contract.commodity === 'USDBRL' ? 4 : 2;
	}

	function fmtDate(value: string | null | undefined): string {
		if (!value) return '—';
		const date = value.slice(0, 10);
		const parts = date.split('-');
		if (parts.length !== 3) return value;
		return `${parts[2]}/${parts[1]}/${parts[0]}`;
	}

	function fmtSettleWithDays(): string {
		const date = fmtDate(settleDate);
		return daysToSettle == null ? date : `${date} (${daysToSettle}d)`;
	}

	function settleMonth(value: string | null | undefined): string {
		if (!value) return '—';
		const date = value.slice(0, 10);
		return date.length >= 7 ? `${date.slice(5, 7)}/${date.slice(2, 4)}` : '—';
	}

	function settleYearMonth(value: string | null | undefined): string {
		if (!value) return '—';
		const date = value.slice(0, 10);
		return date.length >= 7 ? date.slice(0, 7) : '—';
	}
</script>

<div class="page">
	<div class="page-head">
		<div style="flex: 1;">
			<div class="row gap-2" style="margin-bottom: 4px;">
				<a href="/contracts" class="btn btn-link"><Icon name="arrowLeft"/> Contratos</a>
				<span style="color: var(--muted);">/</span>
				<span class="mono" style="font-size: 12px; color: var(--muted);">{c.id}</span>
			</div>
			<div class="row gap-3" style="align-items: baseline;">
				<h1 class="page-title" style="margin: 0;">{c.id}</h1>
				<Badge kind="neutral">{c.type}</Badge>
				<CommodityChip code={c.commodity}/>
				<StatePill state={c.status}/>
				{#if daysToSettle != null && daysToSettle <= 7 && daysToSettle >= 0}
					<Badge kind="warn" dot>Vence em {daysToSettle}d</Badge>
				{/if}
			</div>
			<div class="page-sub" style="margin-top: 6px;">
				{c.fixed_leg === 'buy' ? 'Compra' : 'Venda'} fixa × {c.var_leg === 'buy' ? 'Compra' : 'Venda'} variável · {fmtQty(c)} · {c.cp} · liquidação {fmtDate(settleDate)}
			</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Confirmação</button>
			<button type="button" class="btn btn-secondary">Histórico MTM</button>
			{#if c.status === 'active'}
				<button type="button" class="btn btn-danger">Unwinding</button>
			{:else if c.status === 'partially_settled'}
				<button type="button" class="btn btn-accent">Iniciar liquidação</button>
			{/if}
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi
			label="Notional"
			value={notional == null ? '—' : `US$ ${(notional / 1_000_000).toFixed(2)}`}
			unit="M"
			delta={`${fmtQty(c)} @ ${fmtPrice(c)}`}
		/>
		<Kpi
			label="MTM atual"
			value={fmtUsd(c.mtm)}
			delta="+US$ 1.420 1d"
			deltaKind={c.mtm == null || c.mtm >= 0 ? 'pos' : 'neg'}
		/>
		<Kpi
			label="P&L desde a contratação"
			value={notional == null || c.mtm == null ? '—' : (c.mtm >= 0 ? '+' : '') + ((c.mtm / notional) * 100).toFixed(2) + ' %'}
			delta={'preço mid ' + fmtNumber(mid, priceDigits(c))}
			deltaKind={c.mtm == null || c.mtm >= 0 ? 'pos' : 'neg'}
		/>
		<Kpi
			label="Dias até liquidação"
			value={daysToSettle == null ? '—' : String(daysToSettle)}
			unit={daysToSettle == null ? '' : 'd'}
			delta={fmtDate(settleDate)}
			deltaKind={daysToSettle != null && daysToSettle <= 7 ? 'neg' : 'flat'}
		/>
	</div>

	<div class="tabs">
		{#each TABS as [k, l] (k)}
			<button type="button" class="tab" class:active={tab === k} onclick={() => (tab = k)}>{l}</button>
		{/each}
	</div>

	{#if tab === 'resumo'}
		<div class="detail-grid">
			<div class="stack gap-4">
				<Card title="Termos do contrato">
					<dl class="kv" style="grid-template-columns: 180px 1fr 180px 1fr;">
						<dt>Tipo</dt><dd>{c.type}</dd>
						<dt>Commodity</dt><dd>{c.commodity}</dd>
						<dt>Quantidade</dt><dd class="tabular">{fmtQty(c)}</dd>
						<dt>Notional</dt><dd class="tabular">{notional == null ? '—' : `US$ ${notional.toLocaleString('en-US', { maximumFractionDigits: 0 })}`}</dd>
						<dt>Preço fixo</dt>
						<dd class="tabular strong">
							{fmtPrice(c)} {c.price == null ? '' : fmtPriceUnit(c)}
						</dd>
						<dt>Preço variável</dt><dd>LME Average · mês de liquidação</dd>
						<dt>Contratação</dt><dd>26/05/2026 09:02</dd>
						<dt>Liquidação</dt><dd>{fmtSettleWithDays()}</dd>
						<dt>Contraparte</dt><dd><a href={`/counterparties/${c.cp}`}>{cpName}</a></dd>
						<dt>RFQ origem</dt>
						<dd class="mono">
							{#if c.rfq_id}
								<a href={`/rfq/${c.rfq_id}`}>{c.rfq_number ?? c.rfq_id}</a>
							{:else}
								—
							{/if}
						</dd>
						<dt>Política contábil</dt><dd>Hedge accounting (IFRS 9)</dd>
						<dt>Margem inicial</dt>
						<dd class="tabular">{notional == null ? '—' : `US$ ${(notional * 0.1).toLocaleString('en-US', { maximumFractionDigits: 0 })} (10%)`}</dd>
					</dl>
				</Card>

				<Card title="Pernas do swap" sub="Visualização do payoff">
					<div class="grid-2">
						<div class="card" style="padding: 16px; background: {c.fixed_leg === 'buy' ? 'var(--pos-soft)' : 'var(--neg-soft)'};">
							<div class="row gap-2" style="margin-bottom: 10px;">
								<Badge kind={c.fixed_leg === 'buy' ? 'pos' : 'neg'}>
									{c.fixed_leg === 'buy' ? 'COMPRA' : 'VENDA'} FIXA
								</Badge>
								<span style="margin-left: auto; font-size: 11px; color: var(--muted);">Leg 1</span>
							</div>
							<div style="font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;">Preço fixo</div>
							<div style="font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums;">
								{fmtPrice(c)}
							</div>
							<div style="font-size: 11.5px; color: var(--muted); margin-top: 6px;">{fmtPriceUnit(c)} · contratual</div>
						</div>
						<div class="card" style="padding: 16px; background: {c.var_leg === 'buy' ? 'var(--pos-soft)' : 'var(--neg-soft)'};">
							<div class="row gap-2" style="margin-bottom: 10px;">
								<Badge kind={c.var_leg === 'buy' ? 'pos' : 'neg'}>
									{c.var_leg === 'buy' ? 'COMPRA' : 'VENDA'} VARIÁVEL
								</Badge>
								<span style="margin-left: auto; font-size: 11px; color: var(--muted);">Leg 2</span>
							</div>
							<div style="font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 4px;">Preço mid de mercado</div>
							<div style="font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums;">
								{fmtNumber(mid, priceDigits(c))}
							</div>
							<div style="font-size: 11.5px; color: var(--muted); margin-top: 6px;">{fmtPriceUnit(c)} · LME 11:30 BST</div>
						</div>
					</div>
					<div class="divider"></div>
					<div class="row gap-3" style="align-items: baseline;">
						<span style="font-size: 12px; color: var(--muted);">Δ Preço:</span>
						<span class="tabular" style="font-size: 14px; font-weight: 500; color: {priceDelta() == null ? 'var(--muted)' : priceDelta()! >= 0 ? 'var(--pos)' : 'var(--neg)'};">
							{priceDelta() == null ? '—' : `${priceDelta()! >= 0 ? '+' : ''}${priceDelta()!.toFixed(priceDigits(c))}`}
						</span>
						<span style="font-size: 12px; color: var(--muted);">·</span>
						<span style="font-size: 12px; color: var(--muted);">MTM:</span>
						<span class="tabular strong" style="font-size: 14px; color: {c.mtm == null ? 'var(--muted)' : c.mtm >= 0 ? 'var(--pos)' : 'var(--neg)'};">
							{fmtUsd(c.mtm)}
						</span>
					</div>
				</Card>
			</div>

			<div class="stack gap-4">
				<Card title="Cronograma">
					<div class="feed">
						<div class="feed-item pos"><div class="icon"></div><div><div class="what">Contrato assinado · ORD-2026-0419 ↘ <strong>{c.id}</strong></div><div class="row gap-2"><span class="when">26/05 09:02</span><span class="who">· R. Almeida</span></div></div></div>
						<div class="feed-item pos"><div class="icon"></div><div><div class="what">Aprovação concedida · APR-2026-0096</div><div class="row gap-2"><span class="when">26/05 13:45</span><span class="who">· A. Costa</span></div></div></div>
						<div class="feed-item info"><div class="icon"></div><div><div class="what">MTM atualizado · +US$ 1.420</div><div class="row gap-2"><span class="when">27/05 09:14</span><span class="who">· Sistema</span></div></div></div>
						<div class="feed-item info"><div class="icon"></div><div><div class="what">Liquidação financeira · {c.cp}</div><div class="row gap-2"><span class="when">{fmtDate(settleDate)}</span><span class="who">· Agendado</span></div></div></div>
					</div>
				</Card>

				<Card title="Documentação">
					<div class="stack gap-2">
						{#each [
							{ name: 'Confirmação ISDA',     size: '142 KB' },
							{ name: 'Term sheet',           size: '86 KB' },
							{ name: 'Anexo de garantia',    size: '48 KB' },
							{ name: 'Marcação MTM diária',  size: '2,1 MB' },
						] as d (d.name)}
							<button type="button" class="row gap-2" style="width: 100%; padding: 6px 0; border: 0; background: transparent; text-align: left; font-size: 12.5px; color: var(--ink-2); cursor: pointer;">
								<Icon name="doc"/>
								<span style="flex: 1;">{d.name}</span>
								<span style="color: var(--muted); font-size: 11px;">{d.size}</span>
								<Icon name="download"/>
							</button>
						{/each}
					</div>
				</Card>

				<Card title="Aprovação">
					<dl class="kv">
						<dt>Status</dt><dd><Badge kind="pos" dot>Concedida</Badge></dd>
						<dt>ID</dt><dd class="mono">APR-2026-0096</dd>
						<dt>Aprovador</dt><dd>A. Costa · Risco</dd>
						<dt>Em</dt><dd>26/05 13:45</dd>
						<dt>Política</dt><dd>Hedge §4.1 · Notional ≤ US$ 5 M</dd>
					</dl>
				</Card>
			</div>
		</div>
	{:else if tab === 'legs'}
		<Card title="Detalhes das pernas">
			<table class="tbl">
				<thead>
					<tr>
						<th>Leg</th>
						<th>Side</th>
						<th>Price type</th>
						<th class="num">Quantidade</th>
						<th class="num">Preço</th>
						<th>Janela / Fixing</th>
						<th>Convenção</th>
					</tr>
				</thead>
				<tbody>
					<tr>
						<td class="strong">Leg 1</td>
						<td><DirectionBadge dir={c.fixed_leg}/></td>
						<td><Badge kind="info">Fix</Badge></td>
						<td class="num">{c.qty.toLocaleString('pt-BR')} MT</td>
						<td class="num strong">{fmtPrice(c)}</td>
						<td>{fmtDate(settleDate)} · fixing</td>
						<td>LME Official Settlement</td>
					</tr>
					<tr>
						<td class="strong">Leg 2</td>
						<td><DirectionBadge dir={c.var_leg}/></td>
						<td><Badge kind="neutral">AVG</Badge></td>
						<td class="num">{c.qty.toLocaleString('pt-BR')} MT</td>
						<td class="num">média {settleMonth(settleDate)}</td>
						<td>{settleYearMonth(settleDate)} · mês completo</td>
						<td>LME Average Month</td>
					</tr>
				</tbody>
			</table>
		</Card>
	{:else if tab === 'cashflow'}
		<Card title="Cash flows projetados" noPad>
			<table class="tbl">
				<thead>
					<tr>
						<th>Data</th>
						<th>Descrição</th>
						<th class="num">Valor (USD)</th>
						<th>Direção</th>
						<th>Status</th>
					</tr>
				</thead>
				<tbody>
					{#if cashflows.length}
						{#each cashflows as flow, i (flow.id ?? i)}
							{@const amount = Number(flow.amount_usd ?? 0)}
							<tr>
								<td>{fmtDate(flow.date)}</td>
								<td>{flow.desc ?? flow.description ?? 'Cash flow'}</td>
								<td class="num strong" style="color: {amount >= 0 ? 'var(--pos)' : 'var(--neg)'};">
									{amount >= 0 ? '+' : ''}{amount.toLocaleString('en-US', { maximumFractionDigits: 0 })}
								</td>
								<td>
									{#if flow.direction === 'in'}
										<Badge kind="pos" dot>Entrada</Badge>
									{:else}
										<Badge kind="neg" dot>Saída</Badge>
									{/if}
								</td>
								<td><StatePill state={flow.status ?? 'projected'}/></td>
							</tr>
						{/each}
					{:else}
						<tr><td colspan="5" class="tbl-empty">Nenhum cash flow carregado para este contrato</td></tr>
					{/if}
				</tbody>
			</table>
		</Card>
	{:else if tab === 'mtm'}
		<Card title="Histórico de marcação" sub="Últimos 30 dias">
			<MtmSparkline mtm={c.mtm}/>
			<table class="tbl tbl-tight" style="margin-top: 16px;">
				<thead>
					<tr>
						<th>Data</th>
						<th class="num">Preço mid</th>
						<th class="num">MTM (USD)</th>
						<th class="num">Δ Dia</th>
					</tr>
				</thead>
				<tbody>
					{#each [
						['27/05', mid,       c.mtm,         1420 ],
						['26/05', mid - 0.5, c.mtm - 1420, -240  ],
						['25/05', mid - 0.3, c.mtm - 1180,  820  ],
						['22/05', mid - 1.8, c.mtm - 2000,  1100 ],
						['21/05', mid - 2.5, c.mtm - 3100, -560  ],
					] as [d, p, m, dDay], i (i)}
						<tr>
							<td>{d}</td>
							<td class="num tabular">{(p as number).toFixed(priceDigits(c))}</td>
							<td class="num tabular strong" style="color: {(m as number) >= 0 ? 'var(--pos)' : 'var(--neg)'};">
								{(m as number) >= 0 ? '+' : ''}{(m as number).toLocaleString('en-US', { maximumFractionDigits: 0 })}
							</td>
							<td class="num tabular" style="color: {(dDay as number) >= 0 ? 'var(--pos)' : 'var(--neg)'};">
								{(dDay as number) >= 0 ? '+' : ''}{(dDay as number).toLocaleString('en-US')}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</Card>
	{:else if tab === 'docs'}
		<div class="grid-2">
			<Card title="Documentos do contrato">
				<div class="stack gap-2">
					{#each [
						{ name: 'Confirmação ISDA · assinada',         size: '142 KB' },
						{ name: 'Term sheet',                          size: '86 KB' },
						{ name: 'Anexo de garantia',                   size: '48 KB' },
						{ name: 'Documentação hedge accounting',       size: '218 KB' },
						{ name: 'Trilha de aprovação',                 size: '32 KB' },
					] as d (d.name)}
						<button type="button" class="row gap-2" style="width: 100%; padding: 6px 0; border: 0; background: transparent; text-align: left; font-size: 12.5px; color: var(--ink-2); cursor: pointer;">
							<Icon name="doc"/>
							<span style="flex: 1;">{d.name}</span>
							<span style="color: var(--muted); font-size: 11px;">{d.size}</span>
							<Icon name="download"/>
						</button>
					{/each}
				</div>
			</Card>
			<Card title="Histórico de versões">
				<div class="feed">
					<div class="feed-item pos"><div class="icon"></div><div><div class="what">Versão final aprovada · v3</div><div class="row gap-2"><span class="when">26/05 13:45</span><span class="who">· A. Costa</span></div></div></div>
					<div class="feed-item info"><div class="icon"></div><div><div class="what">Ajuste no anexo de garantia · v2</div><div class="row gap-2"><span class="when">26/05 11:20</span><span class="who">· R. Almeida</span></div></div></div>
					<div class="feed-item info"><div class="icon"></div><div><div class="what">Confirmação inicial gerada · v1</div><div class="row gap-2"><span class="when">26/05 09:02</span><span class="who">· R. Almeida</span></div></div></div>
				</div>
			</Card>
		</div>
	{/if}
</div>
