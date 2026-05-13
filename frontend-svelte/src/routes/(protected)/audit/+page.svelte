<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatDate } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { auditEventsPath, auditEventVerifyPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import type { AuditEventRead, AuditVerifyResponse } from '$lib/api/types/entities';

	// J-A6-09: read-only auditor surface for signed events + per-event
	// HMAC verification. Backend `require_role("auditor")` is the
	// authoritative gate; this page also hides itself for non-auditors
	// as a UX courtesy so unauthorised users do not land on a 403.

	type ViewState = 'loading' | 'ready' | 'forbidden' | 'error';
	type VerifyStatus = 'unverified' | 'verifying' | 'valid' | 'invalid' | 'unverifiable';

	interface VerifyState {
		status: VerifyStatus;
		detail?: string;
	}

	const isAuditor = $derived(authStore.hasRole('auditor'));

	let events = $state<AuditEventRead[]>([]);
	let nextCursor = $state<string | null>(null);
	let viewState = $state<ViewState>('loading');
	let viewError = $state<string>('');
	let verifyByEvent = $state<Record<string, VerifyState>>({});
	let expanded = $state<Record<string, boolean>>({});
	let abortController: AbortController;

	// Filters
	let entityTypeFilter = $state('');
	let entityIdFilter = $state('');

	async function loadEvents(signal?: AbortSignal) {
		if (!isAuditor) {
			events = [];
			viewState = 'forbidden';
			return;
		}
		viewState = 'loading';
		try {
			const path = auditEventsPath({
				entity_type: entityTypeFilter.trim() || null,
				entity_id: entityIdFilter.trim() || null,
				limit: 50,
			});
			const res = await apiFetch(path, { signal });
			if (res.ok) {
				const body = await res.json();
				events = Array.isArray(body?.events) ? body.events : [];
				nextCursor = typeof body?.next_cursor === 'string' ? body.next_cursor : null;
				viewState = 'ready';
			} else if (res.status === 403) {
				events = [];
				viewState = 'forbidden';
				viewError = await describeApiError(res);
			} else {
				events = [];
				viewState = 'error';
				viewError = await describeApiError(res);
				notifications.error(`Audit: ${viewError}`);
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			events = [];
			viewState = 'error';
			viewError = e instanceof Error ? e.message : 'Erro de conexão';
			notifications.error('Erro ao carregar eventos de auditoria');
		}
	}

	async function verifyEvent(eventId: string) {
		// J-A6-09: drive the per-event status machine off the
		// `AuditVerifyResponse.valid` field; unsigned events surface as
		// `unverifiable` rather than `invalid` so auditors can tell
		// "checksum mismatch" apart from "no signature configured".
		verifyByEvent = { ...verifyByEvent, [eventId]: { status: 'verifying' } };
		try {
			const res = await apiFetch(auditEventVerifyPath(eventId));
			if (res.ok) {
				const body: AuditVerifyResponse = await res.json();
				const status: VerifyStatus = body.valid
					? 'valid'
					: /unsigned|no signature/i.test(body.detail ?? '')
						? 'unverifiable'
						: 'invalid';
				verifyByEvent = {
					...verifyByEvent,
					[eventId]: { status, detail: body.detail ?? '' },
				};
			} else {
				const detail = await describeApiError(res);
				verifyByEvent = {
					...verifyByEvent,
					[eventId]: { status: 'unverifiable', detail },
				};
				notifications.error(`Falha ao verificar evento: ${detail}`);
			}
		} catch (e) {
			const detail = e instanceof Error ? e.message : 'Erro de conexão';
			verifyByEvent = {
				...verifyByEvent,
				[eventId]: { status: 'unverifiable', detail },
			};
		}
	}

	function verifyClass(status: VerifyStatus): string {
		switch (status) {
			case 'valid':
				return 'border-success/40 bg-success/10 text-success';
			case 'invalid':
				return 'border-danger/40 bg-danger/10 text-danger';
			case 'unverifiable':
				return 'border-warning/40 bg-warning/10 text-warning';
			case 'verifying':
				return 'border-surface-700 bg-surface-800 text-surface-300';
			default:
				return 'border-surface-800 bg-surface-900 text-surface-400';
		}
	}

	function verifyLabel(status: VerifyStatus): string {
		switch (status) {
			case 'valid':
				return 'Assinatura válida';
			case 'invalid':
				return 'Assinatura inválida';
			case 'unverifiable':
				return 'Não verificável';
			case 'verifying':
				return 'Verificando...';
			default:
				return 'Verificar';
		}
	}

	function toggleExpand(id: string) {
		expanded = { ...expanded, [id]: !expanded[id] };
	}

	onMount(() => {
		abortController = new AbortController();
		loadEvents(abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });
</script>

<div class="p-6">
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-lg font-semibold text-surface-200">Audit Trail</h1>
			<p class="mt-1 text-xs text-surface-500">
				Eventos assinados (HMAC). Verificação por evento usa `/audit/events/&lcub;id&rcub;/verify`.
			</p>
		</div>
	</div>

	{#if !isAuditor}
		<div
			class="mt-4 rounded border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning"
			data-testid="audit-forbidden"
		>
			Acesso restrito ao papel <code>auditor</code>. A página é somente leitura e o backend
			rejeita outros papéis em <code>/audit/events</code>.
		</div>
	{:else}
		<div class="mt-4 grid grid-cols-4 gap-3 items-end">
			<div>
				<label class="block text-xs text-surface-500" for="audit-entity-type">entity_type</label>
				<input
					id="audit-entity-type"
					type="text"
					bind:value={entityTypeFilter}
					placeholder="rfq, contract, …"
					class="w-full rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200"
				/>
			</div>
			<div>
				<label class="block text-xs text-surface-500" for="audit-entity-id">entity_id</label>
				<input
					id="audit-entity-id"
					type="text"
					bind:value={entityIdFilter}
					placeholder="uuid"
					class="w-full rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200"
				/>
			</div>
			<button
				onclick={() => loadEvents()}
				class="rounded border border-surface-700 px-3 py-1 text-sm text-surface-400 hover:bg-surface-800"
			>
				Atualizar
			</button>
		</div>

		<div class="mt-6">
			{#if viewState === 'loading'}
				<div class="text-surface-500">Carregando...</div>
			{:else if viewState === 'forbidden'}
				<div
					class="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning"
					data-testid="audit-backend-forbidden"
				>
					Backend recusou (403): {viewError}
				</div>
			{:else if viewState === 'error'}
				<div class="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
					Erro: {viewError}
				</div>
			{:else if events.length === 0}
				<div class="text-surface-500" data-testid="audit-empty">Nenhum evento encontrado</div>
			{:else}
				<div class="overflow-x-auto rounded border border-surface-800" data-testid="audit-events-table">
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-surface-800 bg-surface-900 text-left text-xs text-surface-500">
								<th class="px-3 py-2">Timestamp (UTC)</th>
								<th class="px-3 py-2">Entidade</th>
								<th class="px-3 py-2">Evento</th>
								<th class="px-3 py-2">Checksum</th>
								<th class="px-3 py-2">Verificação</th>
								<th class="px-3 py-2"></th>
							</tr>
						</thead>
						<tbody>
							{#each events as event (event.id)}
								{@const verifyState = verifyByEvent[event.id] ?? { status: 'unverified' as const }}
								<tr class="border-b border-surface-800/50 align-top">
									<td class="px-3 py-2 text-xs text-surface-400">{formatDate(event.timestamp_utc)}</td>
									<td class="px-3 py-2 text-xs">
										<div class="text-surface-200">{event.entity_type}</div>
										<div class="font-mono text-surface-500">{event.entity_id}</div>
									</td>
									<td class="px-3 py-2 text-surface-200">{event.event_type}</td>
									<td class="px-3 py-2 font-mono text-xs text-surface-500">{event.checksum.slice(0, 12)}…</td>
									<td class="px-3 py-2">
										<button
											onclick={() => verifyEvent(event.id)}
											disabled={verifyState.status === 'verifying'}
											data-testid="audit-verify-button"
											data-event-id={event.id}
											data-verify-status={verifyState.status}
											class="rounded border px-2 py-1 text-xs disabled:opacity-50 {verifyClass(verifyState.status)}"
										>
											{verifyLabel(verifyState.status)}
										</button>
										{#if verifyState.detail && verifyState.status !== 'unverified' && verifyState.status !== 'verifying'}
											<div
												class="mt-1 text-xs text-surface-500"
												data-testid="audit-verify-detail"
											>
												{verifyState.detail}
											</div>
										{/if}
									</td>
									<td class="px-3 py-2">
										<button
											onclick={() => toggleExpand(event.id)}
											class="text-xs text-accent hover:underline"
										>
											{expanded[event.id] ? 'Ocultar' : 'Payload'}
										</button>
									</td>
								</tr>
								{#if expanded[event.id]}
									<tr class="border-b border-surface-800/50 bg-surface-950/30">
										<td colspan="6" class="px-3 py-2">
											<pre class="overflow-x-auto whitespace-pre-wrap text-xs text-surface-400" data-testid="audit-payload">{JSON.stringify(event.payload, null, 2)}</pre>
											{#if event.signature}
												<div class="mt-2 font-mono text-xs text-surface-500">
													signature: {event.signature.slice(0, 24)}…
												</div>
											{:else}
												<div class="mt-2 text-xs text-warning">Evento sem assinatura — verificação retorna unverifiable.</div>
											{/if}
										</td>
									</tr>
								{/if}
							{/each}
						</tbody>
					</table>
				</div>
				{#if nextCursor}
					<p class="mt-3 text-xs text-surface-500">
						Cursor de próxima página disponível (paginação cursor-based, não implementada nesta wave).
					</p>
				{/if}
			{/if}
		</div>
	{/if}
</div>
