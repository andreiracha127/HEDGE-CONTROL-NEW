<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import { page } from '$app/state';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import DecisionDossier from '$lib/components/alcast/DecisionDossier.svelte';
	import DirectionBadge from '$lib/components/alcast/DirectionBadge.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import ExecutionTimeline from '$lib/components/alcast/ExecutionTimeline.svelte';
	import StatePill from '$lib/components/alcast/StatePill.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	import { client } from '$lib/api/client';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { displayActor, safeBusinessText, stateBadge } from '$lib/alcast/presentation';
	let { data } = $props();
	const optionalData = $derived(data as Record<string, any>);
	const rfqs = $derived(data.rfqs);
	const loadedQuotes = $derived(data.quotes);
	const stateEvents = $derived(data.stateEvents ?? []);
	let actionBusy = $state<'cancel' | 'refresh' | 'award' | null>(null);

	const id = $derived(page.params.id ?? '');
	const rfq = $derived(rfqs.find((r) => r.id === id) ?? rfqs[0]);
	const quotes = $derived(loadedQuotes);
	const best = $derived(quotes.find((q) => q.status === 'best'));
	const canManageRfq = $derived(authStore.hasRole('risk_manager'));
	const canCancelRfq = $derived(canManageRfq && ['CREATED', 'SENT'].includes(rfq.state));
	const canRefreshRfq = $derived(canManageRfq && ['SENT', 'QUOTED'].includes(rfq.state));
	const canAwardRfq = $derived(canManageRfq && rfq.state === 'QUOTED' && Boolean(data.canAwardRfq));
	const actionableQuotes = $derived(quotes.filter((q) => q.status !== 'pending').length);
	const pendingQuotes = $derived(quotes.filter((q) => q.status === 'pending').length);
	const awardVerdict = $derived(canAwardRfq ? 'Pronta para adjudicação' : rfq.state === 'QUOTED' ? 'Cotação elegível pendente' : stateBadge(rfq.state).label);
	const awardVerdictKind = $derived(canAwardRfq ? 'pos' : rfq.state === 'QUOTED' ? 'warn' : 'neutral');
	const headerMeta = $derived([
		rfq.commodity,
		`${rfq.qty.toLocaleString('pt-BR')} t`,
		`Janela ${rfq.window}`,
		`${quotes.length} cotação${quotes.length === 1 ? '' : 'ões'}`,
	]);
	const timelineEvents = $derived(
		stateEvents.map((event) => ({
			label: eventWhat(event),
			time: eventWhen(event),
			actor: displayActor(event.user_id ?? event.triggering_counterparty_id ?? event.trigger, 'Sistema'),
			kind: eventKind(event),
		})),
	);
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
		if (event.reason) return safeBusinessText(event.reason, 'Evento registrado');
		if (event.from_state) return `${stateBadge(event.from_state).label} → ${stateBadge(event.to_state).label}`;
		return `RFQ ${stateBadge(event.to_state).label}`;
	}

	function errorDetail(detail: unknown): string {
		return typeof detail === 'string' ? safeBusinessText(detail, 'não foi possível concluir a ação') : 'não foi possível concluir a ação';
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

	const documents = $derived((optionalData.documents ?? []) as Record<string, any>[]);
</script>

<div class="page">
	<PageHeader
		eyebrow="Adjudicação de RFQ"
		title={rfq.rfq}
		subtitle={`${rfq.commodity} · ${rfq.intent === 'COMMERCIAL_HEDGE' ? 'Hedge comercial' : rfq.intent === 'SPREAD' ? 'Spread' : 'Posição global'}`}
		meta={headerMeta}
		actions={[
			{ label: 'Voltar', icon: 'arrowLeft', variant: 'secondary', href: '/rfq' },
			{ label: 'Cancelar RFQ', variant: 'secondary', disabled: actionBusy !== null || !canCancelRfq, onclick: cancelRfq },
			{ label: 'Reenviar', icon: 'refresh', variant: 'secondary', disabled: actionBusy !== null || !canRefreshRfq, onclick: refreshRfq },
			{ label: actionBusy === 'award' ? 'Fechando...' : 'Fechar com melhor cotação', icon: 'bolt', variant: 'accent', disabled: actionBusy !== null || !canAwardRfq, onclick: awardRfq },
		]}
	/>

	<div class="detail-grid">
		<div class="stack gap-4">
			<div class="rfq-command-strip">
				<StatePill state={rfq.state}/>
				<DirectionBadge dir={rfq.direction}/>
				<Badge kind={best ? 'pos' : 'warn'} dot>{best ? 'Melhor cotação carregada' : 'Sem melhor cotação'}</Badge>
				<Badge kind={pendingQuotes > 0 ? 'warn' : 'neutral'}>{pendingQuotes} pendente{pendingQuotes === 1 ? '' : 's'}</Badge>
			</div>

			<Card
				title="Ranking de cotações"
				sub="Ranking executável de preços, validade e elegibilidade"
				noPad
			>
				{#snippet actions()}
					<button type="button" class="btn-link">Reenviar pendentes</button>
				{/snippet}

				<table class="tbl quote-ladder">
					<thead>
						<tr>
							<th class="num">Rank</th>
							<th>Contraparte</th>
							<th class="num">Preço (USD/t)</th>
							<th class="num">Spread vs melhor</th>
							<th>Validade</th>
							<th>Recebida</th>
							<th>Status</th>
							<th></th>
						</tr>
					</thead>
					<tbody>
						{#each quotes as q, index (q.id)}
							{@const isBest = q.status === 'best'}
							{@const isPending = q.status === 'pending'}
							<tr class:selected={isBest}>
								<td class="num strong">{isPending ? '—' : index + 1}</td>
								<td class="strong">
									{q.cp}
									{#if isBest}
										<Badge kind="pos">Melhor executável</Badge>
									{/if}
								</td>
								<td class="num strong">{q.price != null ? q.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}</td>
								<td class="num" style="color: {q.spread === 0 ? 'var(--pos)' : 'var(--ink-2)'};">
									{q.spread != null ? (q.spread === 0 ? '—' : '+' + q.spread.toFixed(2)) : '—'}
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
						{#if quotes.length === 0}
							<tr>
								<td colspan="8">
									<EmptyState
										icon="rfq"
										title="Nenhuma cotação carregada"
										message="As cotações aparecerão quando as contrapartes retornarem preços executáveis."
									/>
								</td>
							</tr>
						{/if}
					</tbody>
				</table>
			</Card>

			<div class="grid-2">
				<Card title="Resumo da operação">
					<dl class="kv">
						<dt>RFQ</dt><dd>{rfq.rfq}</dd>
						<dt>Intenção</dt><dd>{rfq.intent === 'COMMERCIAL_HEDGE' ? 'Hedge comercial' : rfq.intent === 'SPREAD' ? 'Spread' : 'Posição global'}</dd>
						<dt>Tipo</dt><dd>{rfq.instrument_type ?? rfq.product_type ?? '—'}</dd>
						<dt>Lado</dt><dd><DirectionBadge dir={rfq.direction}/></dd>
						<dt>Quantidade</dt><dd class="tabular">{rfq.qty.toLocaleString('pt-BR')} t</dd>
						<dt>Janela</dt>
						<dd>
							{rfq.window} · {rfq.delivery_start.split('-').reverse().join('/')} → {rfq.delivery_end.split('-').reverse().join('/')}
						</dd>
						<dt>Solicitante</dt><dd>{rfq.requester ?? '—'}</dd>
					</dl>
				</Card>
				<Card title="Notional & impacto">
					{#if best && best.price != null}
						<dl class="kv">
							<dt>Notional (melhor)</dt>
							<dd class="tabular strong">
								US$ {(rfq.qty * best.price).toLocaleString('en-US', { maximumFractionDigits: 0 })}
							</dd>
						</dl>
					{:else}
						<EmptyState
							icon="rfq"
							title="Nenhuma melhor cotação carregada"
							message="O notional será calculado quando houver uma cotação elegível marcada como best."
						/>
					{/if}
				</Card>
			</div>
		</div>

		<div class="stack gap-4" style="position: sticky; top: 72px; align-self: start;">
			<Card noPad>
				<DecisionDossier
					title="Dossiê de adjudicação"
					verdict={awardVerdict}
					verdictKind={awardVerdictKind}
					items={[
						{ label: 'Melhor cotação', value: best?.price != null ? best.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—' },
						{ label: 'Cotações elegíveis', value: actionableQuotes },
						{ label: 'Alçada', value: canManageRfq ? 'Risk Manager' : 'Restrita' },
						{ label: 'Notional', value: best?.price != null ? `US$ ${(rfq.qty * best.price).toLocaleString('en-US', { maximumFractionDigits: 0 })}` : '—' },
					]}
				/>
			</Card>

			<Card title="Linha do tempo" sub="Trilha completa de auditoria">
				<ExecutionTimeline events={timelineEvents} emptyTitle="Sem eventos de estado registrados"/>
			</Card>

			<Card title="Documentos">
				<div class="stack gap-2">
					{#each documents as d, i (d.id ?? d.name ?? i)}
						<button type="button" class="row gap-2" style="width: 100%; padding: 6px 0; border: 0; background: transparent; text-align: left; font-size: 12.5px; color: var(--ink-2); cursor: pointer;">
							<Icon name="doc"/>
							<span style="flex: 1;">{d.name ?? d.title ?? 'Documento'}</span>
							<span style="color: var(--muted); font-size: 11px;">{d.size ?? d.file_size ?? '—'}</span>
							<Icon name="download"/>
						</button>
					{/each}
					{#if documents.length === 0}
						<EmptyState
							icon="doc"
							title="Nenhum documento carregado"
							message="Confirmações, anexos e evidências de contraparte aparecerão aqui."
						/>
					{/if}
				</div>
			</Card>
		</div>
	</div>
</div>
