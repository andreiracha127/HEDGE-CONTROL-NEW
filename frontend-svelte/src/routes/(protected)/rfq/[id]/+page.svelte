<script lang="ts">
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth.svelte';
	import { wsStore } from '$lib/stores/ws.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { apiFetch } from '$lib/api/fetch';
	import { formatQuantityMT,
		formatDate,
		formatPrice,
		stateLabel,
		stateColor,
		intentLabel,
		directionLabel,
		directionColor,
	} from '$lib/utils/format';
	import type { QuoteReceivedEvent, StatusChangedEvent, InvitationDeliveredEvent, InvitationFailedEvent } from '$lib/api/types/ws-events';
	import type { Rfq, RfqQuote, RfqInvitation, RfqRanking, RfqStateEvent } from '$lib/api/types/entities';

	const rfqId = $derived(page.params.id ?? '');
	const isTrader = $derived(authStore.hasRole('trader'));

	// ─── Board State ────────────────────────────────────────────────────
	type BoardMode = 'IDLE' | 'AWARDING' | 'REJECTING' | 'RANKING_STALE' | 'DISCONNECTED';

	let rfq = $state<Rfq | null>(null);
	let quotes = $state<RfqQuote[]>([]);
	let invitations = $state<RfqInvitation[]>([]);
	let ranking = $state<RfqRanking | null>(null);
	let stateEvents = $state<RfqStateEvent[]>([]);
	let boardMode = $state<BoardMode>('IDLE');
	let isLoading = $state(true);
	let operationInFlight = $state(false);

	// Ranking debounce
	let rankingDebounce: ReturnType<typeof setTimeout> | null = null;
	let rankingController: AbortController | null = null;
	let isRankingStale = $state(false);

	// ─── Helpers ────────────────────────────────────────────────────────
	function parseContractIds(raw: string | null | undefined): string[] {
		if (!raw) return [];
		try { return JSON.parse(raw); } catch { return []; }
	}

	// ─── Data Fetching ──────────────────────────────────────────────────
	let loadGeneration = 0;

	async function loadAll() {
		const gen = ++loadGeneration;
		isLoading = true;
		try {
			const [rfqRes, quotesRes, eventsRes] = await Promise.all([
				apiFetch(`/rfqs/${rfqId}`),
				apiFetch(`/rfqs/${rfqId}/quotes`),
				apiFetch(`/rfqs/${rfqId}/state-events`),
			]);

			if (gen !== loadGeneration) return; // Superseded by newer call

			if (!rfqRes.ok) {
				if (rfqRes.status === 404) { goto('/rfq'); return; }
				throw new Error('Erro ao carregar RFQ');
			}

			rfq = await rfqRes.json();
			invitations = rfq?.invitations ?? [];
			quotes = quotesRes.ok ? ((await quotesRes.json()).items ?? await quotesRes.json()) : [];
			stateEvents = eventsRes.ok ? ((await eventsRes.json()).items ?? await eventsRes.json()) : [];

			// Load ranking if in quotable state
			if (rfq?.state === 'QUOTED') {
				await fetchRanking();
			}
		} catch (e) {
			if (gen !== loadGeneration) return;
			notifications.error('Erro ao carregar dados da RFQ');
		} finally {
			if (gen === loadGeneration) isLoading = false;
		}
	}

	async function fetchRanking() {
		rankingController?.abort();
		rankingController = new AbortController();
		try {
			const res = await apiFetch(`/rfqs/${rfqId}/trade-ranking`, {
				signal: rankingController.signal,
			});
			if (res.ok) {
				ranking = await res.json();
				isRankingStale = false;
				boardMode = 'IDLE';
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			// Non-fatal — ranking may not be available yet
		}
	}

	function debouncedRankingFetch() {
		isRankingStale = true;
		boardMode = 'RANKING_STALE';
		if (rankingDebounce) clearTimeout(rankingDebounce);
		rankingDebounce = setTimeout(() => fetchRanking(), 300);
	}

	// ─── WebSocket Handlers ─────────────────────────────────────────────

	// ─── Actions ────────────────────────────────────────────────────────
	async function awardRfq() {
		if (!confirm('Confirma award automático (melhor ranking)?')) return;
		operationInFlight = true;
		boardMode = 'AWARDING';
		try {
			const res = await apiFetch(`/rfqs/${rfqId}/actions/award`, {
				method: 'POST',
				body: JSON.stringify({ user_id: authStore.userName || 'trader' }),
			});
			if (!res.ok) {
				const err = await res.json().catch(() => ({ detail: 'Erro' }));
				if (res.status === 409) {
					notifications.warning('RFQ já foi premiada por outro usuário');
				} else {
					notifications.error(typeof err.detail === 'string' ? err.detail : 'Erro ao premiar');
				}
				return;
			}
			notifications.success('RFQ premiada com sucesso');
			await loadAll();
		} finally {
			operationInFlight = false;
			boardMode = 'IDLE';
		}
	}

	async function rejectRfq() {
		if (!confirm('Rejeitar esta RFQ?')) return;
		operationInFlight = true;
		boardMode = 'REJECTING';
		try {
			const res = await apiFetch(`/rfqs/${rfqId}/actions/reject`, {
				method: 'POST',
				body: JSON.stringify({ user_id: authStore.userName || 'trader' }),
			});
			if (res.ok) {
				notifications.success('RFQ rejeitada');
				await loadAll();
			}
		} finally {
			operationInFlight = false;
			boardMode = 'IDLE';
		}
	}

	async function cancelRfq() {
		if (!confirm('Cancelar esta RFQ?')) return;
		operationInFlight = true;
		try {
			const res = await apiFetch(`/rfqs/${rfqId}/actions/cancel`, {
				method: 'POST',
				body: JSON.stringify({ user_id: authStore.userName || 'trader' }),
			});
			if (res.ok) {
				notifications.success('RFQ cancelada');
				await loadAll();
			}
		} finally {
			operationInFlight = false;
		}
	}

	async function refreshInvitations() {
		try {
			const res = await apiFetch(`/rfqs/${rfqId}/actions/refresh`, {
				method: 'POST',
				body: JSON.stringify({ user_id: authStore.userName || 'trader' }),
			});
			if (res.ok) {
				notifications.success('Convites reenviados');
				await loadAll();
			}
		} catch {
			notifications.error('Erro ao reenviar convites');
		}
	}

	// ─── Derived state ──────────────────────────────────────────────────
	let isTerminal = $derived(rfq && ['AWARDED', 'CLOSED'].includes(rfq.state));
	let canAward = $derived(
		isTrader && rfq?.state === 'QUOTED' && boardMode === 'IDLE' && !isRankingStale
	);
	let canReject = $derived(isTrader && rfq?.state === 'QUOTED' && boardMode === 'IDLE');
	let canCancel = $derived(
		isTrader && rfq && ['CREATED', 'SENT'].includes(rfq.state) && boardMode === 'IDLE'
	);
	let canRefresh = $derived(
		isTrader && rfq && ['SENT', 'QUOTED'].includes(rfq.state) && boardMode === 'IDLE'
	);

	// ─── Lifecycle ──────────────────────────────────────────────────────
	$effect(() => {
		const id = rfqId; // track dependency
		if (!id) return;

		loadAll();

		const unsubWs = wsStore.subscribe('rfq', id);

		const unsubQuote = wsStore.on('quote_received', (event: QuoteReceivedEvent) => {
			if (operationInFlight) return;
			if (event.rfq_id !== id) return;
			// Add new quote to list
			quotes = [...quotes, {
				id: event.data.quote_id,
				counterparty_id: event.data.counterparty_id,
				fixed_price_value: event.data.fixed_price_value,
				fixed_price_unit: event.data.fixed_price_unit,
				float_pricing_convention: event.data.float_pricing_convention,
				received_at: event.data.received_at,
				_isNew: true,
			}];
			debouncedRankingFetch();
		});

		const unsubStatus = wsStore.on('status_changed', (event: StatusChangedEvent) => {
			if (operationInFlight) return; // HTTP response is authority
			if (event.rfq_id !== id) return;
			if (rfq) rfq = { ...rfq, state: event.data.to_state };
			if (['AWARDED', 'CLOSED'].includes(event.data.to_state)) {
				boardMode = 'IDLE';
				notifications.info('RFQ atualizada por outro usuário');
				loadAll(); // Full refresh
			}
		});

		const unsubInvDelivered = wsStore.on('invitation_delivered', (event: InvitationDeliveredEvent) => {
			if (event.rfq_id !== id) return;
			invitations = invitations.map((inv) =>
				inv.id === event.data.invitation_id
					? { ...inv, send_status: 'sent' }
					: inv
			);
		});

		const unsubInvFailed = wsStore.on('invitation_failed', (event: InvitationFailedEvent) => {
			if (event.rfq_id !== id) return;
			invitations = invitations.map((inv) =>
				inv.id === event.data.invitation_id
					? { ...inv, send_status: 'failed' }
					: inv
			);
		});

		// Register polling fallback
		wsStore.registerPollingCallback('rfq', id, () => loadAll());

		return () => {
			unsubWs();
			unsubQuote();
			unsubStatus();
			unsubInvDelivered();
			unsubInvFailed();
			wsStore.unregisterPollingCallback('rfq', id);
			if (rankingDebounce) clearTimeout(rankingDebounce);
			rankingController?.abort();
		};
	});
</script>

{#if isLoading}
	<div class="flex h-full items-center justify-center">
		<div class="text-surface-500">Carregando RFQ...</div>
	</div>
{:else if rfq}
	<div class="flex h-full flex-col overflow-hidden">
		<!-- Header -->
		<div class="flex items-center gap-4 border-b border-surface-800 bg-surface-900 px-4 py-3">
			<a href="/rfq" class="text-surface-500 hover:text-surface-300">←</a>
			<div>
				<span class="font-mono text-sm text-surface-400">{rfq.rfq_number}</span>
				<span class="ml-2 inline-block rounded px-1.5 py-0.5 text-xs font-medium {stateColor(rfq.state)}">
					{stateLabel(rfq.state)}
				</span>
			</div>
			<div class="text-sm text-surface-400">
				<span class="font-medium {directionColor(rfq.direction)}">{directionLabel(rfq.direction)}</span>
				<span class="ml-1">{rfq.commodity}</span>
				<span class="ml-1 tabular-nums">{formatQuantityMT(rfq.quantity_mt)} MT</span>
			</div>
			<div class="text-xs text-surface-500">{intentLabel(rfq.intent)}</div>
			<div class="ml-auto text-xs text-surface-500">{formatDate(rfq.created_at)}</div>

			{#if wsStore.isPollingFallback}
				<span class="rounded bg-warning/20 px-2 py-0.5 text-xs text-warning">polling</span>
			{/if}
		</div>

		<!-- 3-column grid -->
		<div class="grid flex-1 grid-cols-[1fr_2fr_1fr] overflow-hidden">

			<!-- Column 1: Invitations -->
			<div class="overflow-y-auto border-r border-surface-800 p-4">
				<h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">
					Convites ({invitations.length})
				</h2>
				<div class="mt-3 space-y-2">
					{#each invitations as inv (inv.id)}
						<div class="rounded border border-surface-800 bg-surface-900 px-3 py-2">
							<div class="text-sm text-surface-300">{inv.recipient_name}</div>
							<div class="text-xs text-surface-500">{inv.recipient_phone}</div>
							<div class="mt-1">
								{#if inv.send_status === 'sent'}
									<span class="text-xs text-success">Enviado</span>
								{:else if inv.send_status === 'failed'}
									<span class="text-xs text-danger">Falhou</span>
								{:else}
									<span class="text-xs text-surface-500">Na fila</span>
								{/if}
							</div>
						</div>
					{:else}
						<div class="text-sm text-surface-500">Nenhum convite</div>
					{/each}
				</div>

				{#if canRefresh}
					<button
						onclick={refreshInvitations}
						class="mt-3 w-full rounded border border-surface-700 py-1.5 text-xs text-surface-400 hover:bg-surface-800"
					>
						Reenviar convites
					</button>
				{/if}
			</div>

			<!-- Column 2: Quotes + Ranking -->
			<div class="overflow-y-auto border-r border-surface-800 p-4">
				<h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">
					Cotações ({quotes.length})
					{#if isRankingStale}
						<span class="ml-2 text-warning">Ranking atualizando...</span>
					{/if}
				</h2>

				{#if quotes.length > 0}
					<div class="mt-3 overflow-x-auto">
						<table class="w-full text-sm">
							<thead>
								<tr class="text-left text-xs text-surface-500">
									<th class="pb-2 pr-4">Contraparte</th>
									<th class="pb-2 pr-4">Preço Fixo</th>
									<th class="pb-2 pr-4">Convenção</th>
									<th class="pb-2 pr-4">Recebido</th>
								</tr>
							</thead>
							<tbody>
								{#each quotes as quote (quote.id)}
									<tr class="border-t border-surface-800/50 {quote._isNew ? 'bg-accent/5' : ''}">
										<td class="py-2 pr-4 text-surface-300">{quote.counterparty_id}</td>
										<td class="py-2 pr-4 tabular-nums font-medium text-surface-200">
											{formatPrice(quote.fixed_price_value, quote.fixed_price_unit)}
										</td>
										<td class="py-2 pr-4 text-xs text-surface-400">{quote.float_pricing_convention ?? '—'}</td>
										<td class="py-2 pr-4 text-xs text-surface-500">{formatDate(quote.received_at || quote.created_at)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div class="mt-4 text-sm text-surface-500">
						{#if rfq.state === 'CREATED'}
							Aguardando envio dos convites...
						{:else if rfq.state === 'SENT'}
							Aguardando cotações das contrapartes...
						{:else}
							Nenhuma cotação recebida.
						{/if}
					</div>
				{/if}

				<!-- Ranking -->
				{#if ranking?.ranking && ranking.ranking.length > 0}
					<h3 class="mt-6 text-xs font-semibold uppercase tracking-wide text-surface-500">
						Ranking
					</h3>
					<div class="mt-2 space-y-1">
						{#each ranking.ranking as entry, idx}
							<div class="flex items-center gap-3 rounded border border-surface-800 bg-surface-900 px-3 py-2">
								<span class="text-lg font-bold {idx === 0 ? 'text-success' : 'text-surface-500'}">{idx + 1}</span>
								<div class="flex-1">
									<div class="text-sm text-surface-300">{entry.counterparty_id ?? entry.counterparty_name ?? 'N/A'}</div>
									<div class="text-xs text-surface-500">Score: {entry.score?.toFixed(2) ?? '—'}</div>
								</div>
								<div class="text-sm font-medium tabular-nums text-surface-200">
									{formatPrice(entry.fixed_price_value, entry.fixed_price_unit)}
								</div>
							</div>
						{/each}
					</div>
				{/if}
			</div>

			<!-- Column 3: Actions + Timeline -->
			<div class="overflow-y-auto p-4">
				<!-- Actions -->
				{#if isTrader && !isTerminal}
					<h2 class="text-xs font-semibold uppercase tracking-wide text-surface-500">Ações</h2>
					<div class="mt-3 space-y-2">
						{#if canAward}
							<button
								onclick={awardRfq}
								disabled={boardMode !== 'IDLE'}
								class="w-full rounded bg-success py-2 text-sm font-medium text-white hover:bg-success-hover disabled:opacity-50"
							>
								{boardMode === 'AWARDING' ? 'Premiando...' : 'Award (Melhor Ranking)'}
							</button>
						{/if}

						{#if canReject}
							<button
								onclick={rejectRfq}
								disabled={boardMode !== 'IDLE'}
								class="w-full rounded border border-danger/50 py-2 text-sm text-danger hover:bg-danger/10 disabled:opacity-50"
							>
								{boardMode === 'REJECTING' ? 'Rejeitando...' : 'Rejeitar RFQ'}
							</button>
						{/if}

						{#if canCancel}
							<button
								onclick={cancelRfq}
								class="w-full rounded border border-surface-700 py-2 text-sm text-surface-400 hover:bg-surface-800"
							>
								Cancelar RFQ
							</button>
						{/if}
					</div>
				{/if}

				{#if isTerminal}
					<div class="rounded border border-surface-700 bg-surface-900 p-3">
						<div class="text-sm font-medium text-surface-300">
							{rfq.state === 'AWARDED' ? 'RFQ Premiada' : 'RFQ Fechada'}
						</div>
						<!-- Show created contract link if available from state events -->
						{#each stateEvents as evt}
							{#if evt.created_contract_ids}
								<div class="mt-2">
									{#each parseContractIds(evt.created_contract_ids) as contractId}
										<a
											href="/contracts/{contractId}"
											class="text-sm text-accent hover:underline"
										>
											Contrato: {contractId.slice(0, 8)}...
										</a>
									{/each}
								</div>
							{/if}
						{/each}
					</div>
				{/if}

				<!-- Timeline -->
				<h2 class="mt-6 text-xs font-semibold uppercase tracking-wide text-surface-500">Timeline</h2>
				<div class="mt-3 space-y-3">
					{#each stateEvents as evt (evt.id)}
						<div class="relative border-l-2 border-surface-700 pl-4">
							<div class="absolute -left-1 top-1 h-2 w-2 rounded-full bg-surface-600"></div>
							<div class="text-sm text-surface-300">
								{stateLabel(evt.from_state)} → {stateLabel(evt.to_state)}
							</div>
							{#if evt.user_id}
								<div class="text-xs text-surface-500">por {evt.user_id}</div>
							{/if}
							{#if evt.reason}
								<div class="text-xs text-surface-500">{evt.reason}</div>
							{/if}
							<div class="text-xs text-surface-600">{formatDate(evt.event_timestamp)}</div>
						</div>
					{:else}
						<div class="text-sm text-surface-500">Nenhum evento registrado</div>
					{/each}
				</div>
			</div>
		</div>
	</div>
{/if}
