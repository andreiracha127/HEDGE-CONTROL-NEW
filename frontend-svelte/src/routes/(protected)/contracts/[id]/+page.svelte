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

	const id = $derived(page.params.id ?? '');
	const c = $derived(contracts.find((x) => x.id === id) ?? contracts[0]);
	let tab = $state<'resumo' | 'legs' | 'cashflow' | 'mtm' | 'docs'>('resumo');

	const mid = $derived.by(() => {
		if (c.commodity === 'AL-LME') return 2645.5;
		if (c.commodity === 'CU-LME') return 9412.0;
		if (c.commodity === 'ZN-LME') return 2812.5;
		if (c.commodity === 'USDBRL') return 5.124;
		return c.price;
	});

	const today = new Date(2026, 4, 27);
	const daysToSettle = $derived(
		Math.round((new Date(c.settle).getTime() - today.getTime()) / 86_400_000),
	);
	const notional = $derived(c.qty * c.price);
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
		if (contract.commodity === 'USDBRL') return contract.qty.toLocaleString('pt-BR') + ' USD';
		return contract.qty.toLocaleString('pt-BR') + ' MT';
	}

	function fmtPriceUnit(contract: Contract): string {
		return contract.commodity === 'USDBRL' ? 'USD/BRL' : 'USD/MT';
	}

	function priceDigits(contract: Contract): number {
		return contract.commodity === 'USDBRL' ? 4 : 2;
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
				{#if daysToSettle <= 7 && daysToSettle >= 0}
					<Badge kind="warn" dot>Vence em {daysToSettle}d</Badge>
				{/if}
			</div>
			<div class="page-sub" style="margin-top: 6px;">
				{c.fixed_leg === 'buy' ? 'Compra' : 'Venda'} fixa × {c.var_leg === 'buy' ? 'Compra' : 'Venda'} variável · {c.qty.toLocaleString('pt-BR')} {c.commodity === 'USDBRL' ? 'USD' : 'MT'} · {c.cp} · liquidação {c.settle.split('-').reverse().join('/')}
			</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary"><Icon name="download"/>Confirmação</button>
			<button type="button" class="btn btn-secondary">Histórico MTM</button>
			{#if c.status === 'active'}
				<button type="button" class="btn btn-danger">Unwinding</button>
			{:else if c.status === 'maturing'}
				<button type="button" class="btn btn-accent">Iniciar liquidação</button>
			{/if}
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi
			label="Notional"
			value={`US$ ${(notional / 1_000_000).toFixed(2)}`}
			unit="M"
			delta={`${c.qty.toLocaleString('pt-BR')} ${c.commodity === 'USDBRL' ? 'USD' : 'MT'} @ ${c.price}`}
		/>
		<Kpi
			label="MTM atual"
			value={(c.mtm >= 0 ? '+US$ ' : '−US$ ') + Math.abs(c.mtm).toLocaleString('en-US', { maximumFractionDigits: 0 })}
			delta="+US$ 1.420 1d"
			deltaKind={c.mtm >= 0 ? 'pos' : 'neg'}
		/>
		<Kpi
			label="P&L desde a contratação"
			value={(c.mtm >= 0 ? '+' : '') + ((c.mtm / notional) * 100).toFixed(2) + ' %'}
			delta={'preço mid ' + mid.toFixed(2)}
			deltaKind={c.mtm >= 0 ? 'pos' : 'neg'}
		/>
		<Kpi
			label="Dias até liquidação"
			value={String(daysToSettle)}
			unit="d"
			delta={c.settle.split('-').reverse().join('/')}
			deltaKind={daysToSettle <= 7 ? 'neg' : 'flat'}
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
						<dt>Notional</dt><dd class="tabular">US$ {notional.toLocaleString('en-US', { maximumFractionDigits: 0 })}</dd>
						<dt>Preço fixo</dt>
						<dd class="tabular strong">
							{c.price.toLocaleString('en-US', { minimumFractionDigits: priceDigits(c) })} {fmtPriceUnit(c)}
						</dd>
						<dt>Preço variável</dt><dd>LME Average · mês de liquidação</dd>
						<dt>Contratação</dt><dd>26/05/2026 09:02</dd>
						<dt>Liquidação</dt><dd>{c.settle.split('-').reverse().join('/')} ({daysToSettle}d)</dd>
						<dt>Contraparte</dt><dd><a href={`/counterparties/${c.cp}`}>{cpName}</a></dd>
						<dt>RFQ origem</dt><dd class="mono"><a href="/rfq/RFQ-2026-0177">RFQ-2026-0177</a></dd>
						<dt>Política contábil</dt><dd>Hedge accounting (IFRS 9)</dd>
						<dt>Margem inicial</dt>
						<dd class="tabular">US$ {(notional * 0.1).toLocaleString('en-US', { maximumFractionDigits: 0 })} (10%)</dd>
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
								{c.price.toLocaleString('en-US', { minimumFractionDigits: priceDigits(c) })}
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
								{mid.toLocaleString('en-US', { minimumFractionDigits: priceDigits(c) })}
							</div>
							<div style="font-size: 11.5px; color: var(--muted); margin-top: 6px;">{fmtPriceUnit(c)} · LME 11:30 BST</div>
						</div>
					</div>
					<div class="divider"></div>
					<div class="row gap-3" style="align-items: baseline;">
						<span style="font-size: 12px; color: var(--muted);">Δ Preço:</span>
						<span class="tabular" style="font-size: 14px; font-weight: 500; color: {mid > c.price ? 'var(--pos)' : 'var(--neg)'};">
							{mid >= c.price ? '+' : ''}{(mid - c.price).toFixed(priceDigits(c))}
						</span>
						<span style="font-size: 12px; color: var(--muted);">·</span>
						<span style="font-size: 12px; color: var(--muted);">MTM:</span>
						<span class="tabular strong" style="font-size: 14px; color: {c.mtm >= 0 ? 'var(--pos)' : 'var(--neg)'};">
							{c.mtm >= 0 ? '+' : ''}US$ {c.mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}
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
						<div class="feed-item info"><div class="icon"></div><div><div class="what">Liquidação financeira · {c.cp}</div><div class="row gap-2"><span class="when">{c.settle.split('-').reverse().join('/')}</span><span class="who">· Agendado</span></div></div></div>
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
						<td class="num strong">{c.price.toLocaleString('en-US', { minimumFractionDigits: 2 })}</td>
						<td>{c.settle.split('-').reverse().join('/')} · fixing</td>
						<td>LME Official Settlement</td>
					</tr>
					<tr>
						<td class="strong">Leg 2</td>
						<td><DirectionBadge dir={c.var_leg}/></td>
						<td><Badge kind="neutral">AVG</Badge></td>
						<td class="num">{c.qty.toLocaleString('pt-BR')} MT</td>
						<td class="num">média {c.settle.slice(5, 7)}/{c.settle.slice(2, 4)}</td>
						<td>{c.settle.split('-')[0]}-{c.settle.slice(5, 7)} · mês completo</td>
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
					<tr>
						<td>{c.settle.split('-').reverse().join('/')}</td>
						<td>Liquidação principal · {c.id}</td>
						<td class="num strong" style="color: {c.mtm >= 0 ? 'var(--pos)' : 'var(--neg)'};">
							{c.mtm >= 0 ? '+' : ''}{c.mtm.toLocaleString('en-US', { maximumFractionDigits: 0 })}
						</td>
						<td>
							{#if c.mtm >= 0}
								<Badge kind="pos" dot>Entrada</Badge>
							{:else}
								<Badge kind="neg" dot>Saída</Badge>
							{/if}
						</td>
						<td><StatePill state="projected"/></td>
					</tr>
					<tr>
						<td>15/06/2026</td>
						<td>Margin call (estimado · 30 % do MTM)</td>
						<td class="num">US$ {(Math.abs(c.mtm) * 0.3).toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
						<td><Badge kind="info" dot>Garantia</Badge></td>
						<td><StatePill state="projected"/></td>
					</tr>
					<tr>
						<td>27/05/2026</td>
						<td>Pagamento de margem inicial</td>
						<td class="num">US$ {(notional * 0.1).toLocaleString('en-US', { maximumFractionDigits: 0 })}</td>
						<td><Badge kind="info" dot>Garantia</Badge></td>
						<td><StatePill state="confirmed"/></td>
					</tr>
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
