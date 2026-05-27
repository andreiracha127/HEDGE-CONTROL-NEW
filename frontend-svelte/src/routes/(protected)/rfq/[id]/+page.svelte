<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import DirectionBadge from '$lib/components/alcast/DirectionBadge.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import { client } from '$lib/api/client';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	let { data } = $props();
	const rfqs = $derived(data.rfqs);
	const sampleQuotes = $derived(data.quotes);
	const stateEvents = $derived(data.stateEvents ?? []);
	let actionBusy = $state<'cancel' | 'refresh' | 'award' | null>(null);

	const id = $derived(page.params.id ?? '');
	const rfq = $derived(rfqs.find((r) => r.id === id) ?? rfqs[0]);
	const quotes = $derived(sampleQuotes);
	const best = $derived(quotes.find((q) => q.status === 'best'));
	const canManageRfq = $derived(authStore.hasRole('risk_manager'));
	const canCancelRfq = $derived(canManageRfq && ['CREATED', 'SENT'].includes(rfq.state));
	const canRefreshRfq = $derived(canManageRfq && ['SENT', 'QUOTED'].includes(rfq.state));
	const canAwardRfq = $derived(canManageRfq && rfq.state === 'QUOTED' && !!best);
	const mid = 2645.5;

	function vsMid(price: number | null): number | null {
		if (price == null) return null;
		return ((price - mid) / mid) * 100;
	}

	function pnlVsMid(price: number | null): number | null {
		if (price == null || !rfq) return null;
		const impact = rfq.direction === 'SELL' ? (price - mid) * rfq.qty : (mid - price) * rfq.qty;
		return Number.isFinite(impact) ? impact : null;
	}

	function eventKind(event: Record<string, any>): 'pos' | 'warn' | 'info' {
		if (event.to_state === 'AWARDED' || event.to_state === 'CLOSED') return 'pos';
		if (event.trigger === 'cancel' || event.to_state === 'CANCELLED') return 'warn';
		return 'info';
	}

	function eventWhen(event: Record<string, any>): string {
		const raw = event.event_timestamp ?? event.created_at;
		if (!raw) return '—';
		const date = new Date(raw);
		if (Number.isNaN(date.getTime())) return String(raw);
		return date.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
	}

	function eventWhat(event: Record<string, any>): string {
		if (event.reason) return event.reason;
		if (event.from_state) return `${event.from_state} → ${event.to_state}`;
		return `RFQ ${event.to_state}`;
	}

	function errorDetail(detail: unknown): string {
		return typeof detail === 'string' ? detail : 'erro desconhecido';
	}

	async function handleActionResult(apiError: { detail?: unknown } | undefined, success: string) {
		actionBusy = null;
		if (apiError) {
			notifications.error(`Falha na ação da RFQ: ${errorDetail(apiError.detail)}`);
			return;
		}
		notifications.success(success);
		await invalidateAll();
	}

	async function cancelRfq() {
		if (!rfq?.id || actionBusy || !canCancelRfq) return;
		actionBusy = 'cancel';
		const { error: apiError } = await client.POST('/rfqs/{rfq_id}/actions/cancel', {
			params: { path: { rfq_id: rfq.id } },
			body: {},
		});
		await handleActionResult(apiError, 'RFQ cancelada');
	}

	async function refreshRfq() {
		if (!rfq?.id || actionBusy || !canRefreshRfq) return;
		actionBusy = 'refresh';
		const { error: apiError } = await client.POST('/rfqs/{rfq_id}/actions/refresh', {
			params: { path: { rfq_id: rfq.id } },
			body: {},
		});
		await handleActionResult(apiError, 'RFQ reenviada');
	}

	async function awardRfq() {
		if (!rfq?.id || actionBusy || !canAwardRfq) return;
		actionBusy = 'award';
		const { error: apiError } = await client.POST('/rfqs/{rfq_id}/actions/award', {
			params: { path: { rfq_id: rfq.id } },
			body: {},
		});
		await handleActionResult(apiError, 'RFQ fechada com a melhor cotação elegível');
	}

	const docs = [
		{ name: 'Confirmação de RFQ',                size: '48 KB' },
		{ name: 'Snapshot de exposição #EXP-091200', size: '172 KB' },
		{ name: 'Política de hedge · v3.2',          size: '2,1 MB' },
	];
</script>

<div class="page">
	<div class="page-head">
		<div>
			<div class="row gap-2" style="margin-bottom: 4px;">
				<a href="/rfq" class="btn btn-link"><Icon name="arrowLeft"/> RFQ</a>
				<span style="color: var(--muted);">/</span>
				<span class="mono" style="font-size: 12px; color: var(--muted);">{rfq.id}</span>
			</div>
			<h1 class="page-title">{rfq.id}</h1>
			<div class="page-sub">
				{rfq.commodity} · <DirectionBadge dir={rfq.direction}/> · {rfq.qty.toLocaleString('pt-BR')} t · janela {rfq.window}
			</div>
		</div>
		<div class="page-actions">
			<StatePill state={rfq.state}/>
			<button type="button" class="btn btn-secondary" onclick={cancelRfq} disabled={actionBusy !== null || !canCancelRfq}>Cancelar RFQ</button>
			<button type="button" class="btn btn-secondary" onclick={refreshRfq} disabled={actionBusy !== null || !canRefreshRfq}>Reenviar</button>
			<button type="button" class="btn btn-accent" onclick={awardRfq} disabled={actionBusy !== null || !canAwardRfq}>
				<Icon name="bolt"/>Fechar com melhor cotação
			</button>
		</div>
	</div>

	<div class="card" style="margin-bottom: 16px; padding: 12px 18px;">
		<div class="steps">
			<div class="step done"><span class="dot"></span>Criada · 09:14</div>
			<div class="step done"><span class="dot"></span>Enviada · 09:18</div>
			<div class="step current"><span class="dot"></span>Cotada · 09:19 — 4/5</div>
			<div class="step"><span class="dot"></span>Aprovada</div>
			<div class="step"><span class="dot"></span>Executada</div>
		</div>
	</div>

	<div class="detail-grid">
		<div class="stack gap-4">
			<Card
				title="Cotações recebidas"
				sub="Janela de cotação válida até 09:34 · 16 min restantes"
				noPad
			>
				{#snippet actions()}
					<button type="button" class="btn-link">Reenviar pendentes</button>
				{/snippet}

				<table class="tbl">
					<thead>
						<tr>
							<th>Contraparte</th>
							<th class="num">Preço (USD/t)</th>
							<th class="num">Spread vs melhor</th>
							<th class="num">vs Mid LME</th>
							<th>Validade</th>
							<th>Recebida</th>
							<th>Status</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each quotes as q (q.id)}
							{@const isBest = q.status === 'best'}
							{@const isPending = q.status === 'pending'}
							{@const mid_pct = vsMid(q.price)}
							<tr class:selected={isBest}>
								<td class="strong">
									{q.cp}
									{#if isBest}
										<span style="margin-left: 6px; color: var(--orange); font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">Melhor</span>
									{/if}
								</td>
								<td class="num strong">{q.price ? q.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</td>
								<td class="num" style="color: {q.spread === 0 ? 'var(--pos)' : 'var(--ink-2)'};">
									{q.spread != null ? (q.spread === 0 ? '—' : '+' + q.spread.toFixed(2)) : '—'}
								</td>
								<td class="num" style="color: {mid_pct != null ? (mid_pct < 0 ? 'var(--pos)' : 'var(--neg)') : 'var(--muted)'};">
									{mid_pct != null ? (mid_pct >= 0 ? '+' : '') + mid_pct.toFixed(2) + ' %' : '—'}
								</td>
								<td style="font-size: 12px; color: var(--muted);">{q.valid ?? '—'}</td>
								<td style="font-size: 12px; color: var(--muted);">{q.received ?? '—'}</td>
								<td><StatePill state={q.status}/></td>
								<td>
									{#if isBest}
										<button type="button" class="btn btn-accent btn-sm" onclick={awardRfq} disabled={actionBusy !== null || !canAwardRfq}>Fechar →</button>
									{:else if isPending}
										<button type="button" class="btn btn-ghost btn-sm" onclick={refreshRfq} disabled={actionBusy !== null || !canRefreshRfq}>Lembrar</button>
									{:else}
										<span style="color: var(--muted);">—</span>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</Card>

			<div class="grid-2">
				<Card title="Resumo da operação">
					<dl class="kv">
						<dt>RFQ</dt><dd class="mono">{rfq.id}</dd>
						<dt>Intenção</dt><dd>{rfq.intent === 'COMMERCIAL_HEDGE' ? 'Hedge comercial' : rfq.intent === 'SPREAD' ? 'Spread' : 'Posição global'}</dd>
						<dt>Tipo</dt><dd>Forward (futuro a termo)</dd>
						<dt>Lado</dt><dd><DirectionBadge dir={rfq.direction}/></dd>
						<dt>Quantidade</dt><dd class="tabular">{rfq.qty.toLocaleString('pt-BR')} t</dd>
						<dt>Janela</dt>
						<dd>
							{rfq.window} · {rfq.delivery_start.split('-').reverse().join('/')} → {rfq.delivery_end.split('-').reverse().join('/')}
						</dd>
						<dt>Mid LME (ref.)</dt><dd class="tabular">2.645,50</dd>
						<dt>Solicitante</dt><dd>{rfq.requester} · Mesa Metais</dd>
					</dl>
				</Card>
				<Card title="Notional & impacto">
					{#if best && best.price != null}
						{@const impact = pnlVsMid(best.price)}
						<dl class="kv">
							<dt>Notional (melhor)</dt>
							<dd class="tabular strong">
								US$ {(rfq.qty * best.price).toLocaleString('en-US', { maximumFractionDigits: 0 })}
							</dd>
							<dt>Notional em BRL</dt>
							<dd class="tabular">
								R$ {(rfq.qty * best.price * 5.124).toLocaleString('pt-BR', { maximumFractionDigits: 0 })}
							</dd>
							<dt>P&amp;L vs mid</dt>
							<dd class="tabular" style="color: {impact == null ? 'var(--muted)' : impact >= 0 ? 'var(--pos)' : 'var(--neg)'};">
								{impact == null ? '—' : `${impact >= 0 ? '+' : '-'}US$ ${Math.abs(impact).toLocaleString('en-US', { maximumFractionDigits: 0 })}`}
							</dd>
							<dt>Δ cobertura jun/26</dt><dd class="tabular" style="color: var(--pos);">+28,6 pp → 116,7 %</dd>
							<dt>Margem inicial</dt><dd class="tabular">US$ 158.310 (10 %)</dd>
						</dl>
					{/if}
				</Card>
			</div>
		</div>

		<div class="stack gap-4" style="position: sticky; top: 72px; align-self: start;">
			<Card title="Histórico" sub="Trilha completa de auditoria">
				<div class="feed">
					{#each stateEvents as event (event.id)}
						<div class="feed-item {eventKind(event)}">
							<div class="icon"></div>
							<div>
								<div class="what">{eventWhat(event)}</div>
								<div class="row gap-2">
									<span class="when">{eventWhen(event)}</span>
									<span class="who">· {event.user_id ?? event.triggering_counterparty_id ?? event.trigger ?? 'Sistema'}</span>
								</div>
							</div>
						</div>
					{/each}
					{#if stateEvents.length === 0}
						<div style="font-size: 12px; color: var(--muted);">Sem eventos de estado registrados.</div>
					{/if}
				</div>
			</Card>

			<Card title="Documentos">
				<div class="stack gap-2">
					{#each docs as d (d.name)}
						<button type="button" class="row gap-2" style="width: 100%; padding: 6px 0; border: 0; background: transparent; text-align: left; font-size: 12.5px; color: var(--ink-2); cursor: pointer;">
							<Icon name="doc"/>
							<span style="flex: 1;">{d.name}</span>
							<span style="color: var(--muted); font-size: 11px;">{d.size}</span>
							<Icon name="download"/>
						</button>
					{/each}
				</div>
			</Card>
		</div>
	</div>
</div>
