<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { apiFetch } from '$lib/api/fetch';
	import { authStore } from '$lib/stores/auth.svelte';
	import { wsStore } from '$lib/stores/ws.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatNumber, formatDate, stateLabel, stateColor, intentLabel, directionLabel, directionColor } from '$lib/utils/format';
	import type { Rfq } from '$lib/api/types/entities';

	// ─── State ──────────────────────────────────────────────────────────
	let rfqs = $state<Rfq[]>([]);
	let isLoading = $state(false);
	let nextCursor = $state<string | null>(null);

	// Filters
	let filterState = $state('');
	let filterIntent = $state('');
	let filterDirection = $state('');
	let filterCommodity = $state('');

	// Quote count badges (updated via WS)
	let quoteBadges = $state<Record<string, number>>({});

	// ─── Fetch ──────────────────────────────────────────────────────────
	async function fetchRfqs(cursor: string | null = null) {
		isLoading = true;
		try {
			const params: Record<string, string> = {};
			if (filterState) params.state = filterState;
			if (filterIntent) params.intent = filterIntent;
			if (filterDirection) params.direction = filterDirection;
			if (filterCommodity) params.commodity = filterCommodity;
			if (cursor) params.cursor = cursor;

			const response = await apiFetch(`/rfqs?${new URLSearchParams(params)}`);
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			const data = await response.json();

			if (cursor) {
				rfqs = [...rfqs, ...data.items];
			} else {
				rfqs = data.items;
			}
			nextCursor = data.next_cursor;
		} catch (e) {
			notifications.error('Erro ao carregar RFQs');
		} finally {
			isLoading = false;
		}
	}

	function applyFilters() {
		nextCursor = null;
		fetchRfqs();
	}

	function clearFilters() {
		filterState = '';
		filterIntent = '';
		filterDirection = '';
		filterCommodity = '';
		applyFilters();
	}

	// ─── WS badge updates ───────────────────────────────────────────────
	let unsubWs: (() => void) | null = null;

	onMount(() => {
		fetchRfqs();

		unsubWs = wsStore.on('quote_received', (event) => {
			const rfqId = event.rfq_id;
			quoteBadges = {
				...quoteBadges,
				[rfqId]: (quoteBadges[rfqId] ?? 0) + 1,
			};
		});
	});

	onDestroy(() => {
		unsubWs?.();
	});

	function getQuoteCount(rfq: Rfq): number {
		const base = rfq.quotes?.length ?? 0;
		return base + (quoteBadges[rfq.id] ?? 0);
	}

	const states = ['CREATED', 'SENT', 'QUOTED', 'AWARDED', 'CLOSED'];
	const intents = ['COMMERCIAL_HEDGE', 'GLOBAL_POSITION', 'SPREAD'];
	const directions = ['BUY', 'SELL'];
</script>

<div class="p-6">
	<!-- Header -->
	<div class="flex items-center justify-between">
		<h1 class="text-lg font-semibold text-surface-200">RFQs</h1>
		{#if authStore.hasRole('trader')}
			<a
				href="/rfq/new"
				class="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover"
			>
				+ Nova RFQ
			</a>
		{/if}
	</div>

	<!-- Filters -->
	<div class="mt-4 flex flex-wrap gap-3">
		<select
			bind:value={filterState}
			onchange={applyFilters}
			class="rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-300"
		>
			<option value="">Estado</option>
			{#each states as s}
				<option value={s}>{stateLabel(s)}</option>
			{/each}
		</select>

		<select
			bind:value={filterIntent}
			onchange={applyFilters}
			class="rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-300"
		>
			<option value="">Intenção</option>
			{#each intents as i}
				<option value={i}>{intentLabel(i)}</option>
			{/each}
		</select>

		<select
			bind:value={filterDirection}
			onchange={applyFilters}
			class="rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-300"
		>
			<option value="">Direção</option>
			{#each directions as d}
				<option value={d}>{directionLabel(d)}</option>
			{/each}
		</select>

		<input
			type="text"
			bind:value={filterCommodity}
			placeholder="Commodity..."
			onkeydown={(e) => { if (e.key === 'Enter') applyFilters(); }}
			class="rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-300 placeholder-surface-600 w-36"
		/>

		{#if filterState || filterIntent || filterDirection || filterCommodity}
			<button onclick={clearFilters} class="text-xs text-surface-500 hover:text-surface-300">
				Limpar filtros
			</button>
		{/if}
	</div>

	<!-- Table -->
	<div class="mt-4 overflow-x-auto rounded border border-surface-800">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-surface-800 bg-surface-900 text-left text-xs text-surface-500">
					<th class="px-3 py-2">#</th>
					<th class="px-3 py-2">Estado</th>
					<th class="px-3 py-2">Commodity</th>
					<th class="px-3 py-2">Direção</th>
					<th class="px-3 py-2">Qty (MT)</th>
					<th class="px-3 py-2">Intenção</th>
					<th class="px-3 py-2">Contrapartes</th>
					<th class="px-3 py-2">Cotações</th>
					<th class="px-3 py-2">Criado</th>
				</tr>
			</thead>
			<tbody>
				{#each rfqs as rfq (rfq.id)}
					<tr
						onclick={() => goto(`/rfq/${rfq.id}`)}
						class="border-b border-surface-800/50 cursor-pointer hover:bg-surface-800/50 transition-colors"
					>
						<td class="px-3 py-2 font-mono text-xs text-surface-400">{rfq.rfq_number}</td>
						<td class="px-3 py-2">
							<span class="inline-block rounded px-1.5 py-0.5 text-xs font-medium {stateColor(rfq.state)}">
								{stateLabel(rfq.state)}
							</span>
						</td>
						<td class="px-3 py-2 text-surface-300">{rfq.commodity}</td>
						<td class="px-3 py-2 font-medium {directionColor(rfq.direction)}">
							{directionLabel(rfq.direction)}
						</td>
						<td class="px-3 py-2 text-surface-300 tabular-nums">{formatNumber(rfq.quantity_mt)}</td>
						<td class="px-3 py-2 text-surface-400 text-xs">{intentLabel(rfq.intent)}</td>
						<td class="px-3 py-2 text-surface-400 text-center">{rfq.invitations?.length ?? 0}</td>
						<td class="px-3 py-2 text-center">
							{#if quoteBadges[rfq.id]}
								<span class="inline-flex items-center rounded-full bg-accent/20 px-2 py-0.5 text-xs font-medium text-accent">
									+{quoteBadges[rfq.id]}
								</span>
							{:else}
								<span class="text-surface-500">{getQuoteCount(rfq)}</span>
							{/if}
						</td>
						<td class="px-3 py-2 text-surface-500 text-xs">{formatDate(rfq.created_at)}</td>
					</tr>
				{:else}
					{#if !isLoading}
						<tr>
							<td colspan="9" class="px-3 py-8 text-center text-surface-500">
								Nenhuma RFQ encontrada.
							</td>
						</tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>

	<!-- Loading / Pagination -->
	{#if isLoading}
		<div class="mt-4 text-center text-sm text-surface-500">Carregando...</div>
	{/if}

	{#if nextCursor && !isLoading}
		<div class="mt-4 text-center">
			<button
				onclick={() => fetchRfqs(nextCursor)}
				class="rounded border border-surface-700 px-4 py-1.5 text-sm text-surface-400 hover:bg-surface-800"
			>
				Carregar mais
			</button>
		</div>
	{/if}
</div>
