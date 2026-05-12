<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatNumber, formatDate } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { pnlSnapshotsPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import type { PnlSnapshot } from '$lib/api/types/entities';

	type ViewState = 'idle' | 'missing-param' | 'loading' | 'ready' | 'error' | 'malformed';

	let pnlData = $state<PnlSnapshot | null>(null);
	let viewState = $state<ViewState>('idle');
	let viewError = $state<string>('');

	// `/pl/snapshots` returns a single scalar `PLSnapshotResponse`
	// (realized_pl + unrealized_mtm — Decimal-as-string, see
	// schema.d.ts:2888). No request fires until all four required
	// singleton params are supplied.
	let entityType = $state<string>('hedge_contract');
	let entityId = $state<string>('');
	let periodStart = $state<string>('');
	let periodEnd = $state<string>('');
	let abortController: AbortController;

	function paramsReady(): boolean {
		return (
			entityType.trim() !== '' &&
			entityId.trim() !== '' &&
			periodStart.trim() !== '' &&
			periodEnd.trim() !== ''
		);
	}

	async function loadData(signal?: AbortSignal) {
		if (!paramsReady()) {
			pnlData = null;
			viewState = 'missing-param';
			const missing: string[] = [];
			if (!entityType.trim()) missing.push('entity_type');
			if (!entityId.trim()) missing.push('entity_id');
			if (!periodStart.trim()) missing.push('period_start');
			if (!periodEnd.trim()) missing.push('period_end');
			viewError = `Parâmetros obrigatórios: ${missing.join(', ')}`;
			notifications.error(`P&L: ${viewError}`);
			return;
		}

		viewState = 'loading';
		try {
			const res = await apiFetch(
				pnlSnapshotsPath({
					entity_type: entityType,
					entity_id: entityId,
					period_start: periodStart,
					period_end: periodEnd,
				}),
				{ signal },
			);
			if (res.ok) {
				try {
					pnlData = await res.json();
					viewState = 'ready';
				} catch {
					pnlData = null;
					viewState = 'malformed';
					viewError = 'Resposta do servidor não pôde ser interpretada';
					notifications.error(`P&L: ${viewError}`);
				}
			} else {
				pnlData = null;
				viewState = 'error';
				viewError = await describeApiError(res);
				notifications.error(`P&L: ${viewError}`);
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			pnlData = null;
			viewState = 'error';
			viewError = e instanceof Error ? e.message : 'Erro de conexão';
			notifications.error('Erro ao carregar P&L');
		}
	}

	onMount(() => {
		abortController = new AbortController();
		// Do not fire a request on mount — required singleton params are not
		// derivable from the page context. Operator must select them.
		viewState = 'missing-param';
		viewError =
			'Informe entity_type, entity_id, period_start e period_end para carregar o snapshot.';
	});

	onDestroy(() => { abortController?.abort(); });

	// realized_pl / unrealized_mtm are Decimal-as-string. Parse for sign
	// (positive vs negative colour) and totals; the displayed scalar is
	// fed through formatNumber, which preserves Decimal-string precision
	// at the boundary.
	function signOf(value: string | null | undefined): number {
		if (value == null || value === '') return Number.NaN;
		const n = Number(value);
		return Number.isFinite(n) ? n : Number.NaN;
	}

	const realizedPlSign = $derived(pnlData ? signOf(pnlData.realized_pl) : Number.NaN);
	const unrealizedMtmSign = $derived(pnlData ? signOf(pnlData.unrealized_mtm) : Number.NaN);
	const totalPl = $derived(
		Number.isFinite(realizedPlSign) && Number.isFinite(unrealizedMtmSign)
			? realizedPlSign + unrealizedMtmSign
			: Number.NaN,
	);
</script>

<div class="p-6">
	<h1 class="text-lg font-semibold text-surface-200">P&L Snapshot</h1>

	<div class="mt-4 grid grid-cols-5 gap-3 items-end">
		<div>
			<label class="block text-xs text-surface-500" for="pnl-entity-type">entity_type</label>
			<input
				id="pnl-entity-type"
				type="text"
				bind:value={entityType}
				class="w-full rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200"
			/>
		</div>
		<div>
			<label class="block text-xs text-surface-500" for="pnl-entity-id">entity_id (uuid)</label>
			<input
				id="pnl-entity-id"
				type="text"
				bind:value={entityId}
				class="w-full rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200"
			/>
		</div>
		<div>
			<label class="block text-xs text-surface-500" for="pnl-period-start">period_start</label>
			<input
				id="pnl-period-start"
				type="date"
				bind:value={periodStart}
				class="w-full rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200"
			/>
		</div>
		<div>
			<label class="block text-xs text-surface-500" for="pnl-period-end">period_end</label>
			<input
				id="pnl-period-end"
				type="date"
				bind:value={periodEnd}
				class="w-full rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200"
			/>
		</div>
		<button
			onclick={() => loadData()}
			class="rounded border border-surface-700 px-3 py-1 text-sm text-surface-400 hover:bg-surface-800"
		>
			Carregar
		</button>
	</div>

	<div class="mt-6">
		{#if viewState === 'loading'}
			<div class="text-surface-500">Carregando P&L...</div>
		{:else if viewState === 'missing-param'}
			<div
				class="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning"
				data-testid="pnl-missing-param"
			>
				{viewError}
			</div>
		{:else if viewState === 'error' || viewState === 'malformed'}
			<div class="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
				Erro ao carregar P&L: {viewError}
			</div>
		{:else if pnlData}
			<!--
				/pl/snapshots returns a single PLSnapshotResponse with scalar
				`realized_pl` and `unrealized_mtm`. Render the scalar
				summary directly; there is no entries[] collection.
			-->
			<div class="grid grid-cols-3 gap-4">
				<div class="rounded border border-surface-800 bg-surface-900 p-3">
					<div class="text-xs text-surface-500">P&L Realizado</div>
					<div
						class="text-lg font-semibold tabular-nums {Number.isFinite(realizedPlSign) && realizedPlSign >= 0 ? 'text-success' : 'text-danger'}"
						data-testid="pnl-realized"
					>
						{formatNumber(pnlData.realized_pl)}
					</div>
				</div>
				<div class="rounded border border-surface-800 bg-surface-900 p-3">
					<div class="text-xs text-surface-500">MTM Não-realizado</div>
					<div
						class="text-lg font-semibold tabular-nums {Number.isFinite(unrealizedMtmSign) && unrealizedMtmSign >= 0 ? 'text-accent' : 'text-danger'}"
						data-testid="pnl-unrealized-mtm"
					>
						{formatNumber(pnlData.unrealized_mtm)}
					</div>
				</div>
				<div class="rounded border border-surface-800 bg-surface-900 p-3">
					<div class="text-xs text-surface-500">P&L Total</div>
					<div class="text-lg font-semibold tabular-nums text-surface-200">
						{formatNumber(totalPl)}
					</div>
				</div>
			</div>

			<div class="mt-4 rounded border border-surface-800 bg-surface-900 p-3 text-sm space-y-1">
				<div><span class="text-surface-500">Entity:</span> <span class="text-surface-200">{pnlData.entity_type} / {pnlData.entity_id}</span></div>
				<div><span class="text-surface-500">Período:</span> <span class="text-surface-200">{formatDate(pnlData.period_start)} → {formatDate(pnlData.period_end)}</span></div>
				<div><span class="text-surface-500">Correlation:</span> <span class="font-mono text-xs text-surface-400">{pnlData.correlation_id ?? '—'}</span></div>
				<div><span class="text-surface-500">Created:</span> <span class="text-surface-400">{formatDate(pnlData.created_at)}</span></div>
			</div>
		{:else}
			<div class="text-surface-500">Nenhum dado de P&L disponível</div>
		{/if}
	</div>
</div>
