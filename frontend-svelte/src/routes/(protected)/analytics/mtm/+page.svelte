<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatNumber, formatDate, formatQuantityMT, formatPrice } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { mtmSnapshotsPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import type { MtmSnapshot } from '$lib/api/types/entities';
	import { validateMtmSnapshot } from '$lib/api/analytics-response-shape';

	type ViewState = 'idle' | 'missing-param' | 'loading' | 'ready' | 'error' | 'malformed';

	let mtmData = $state<MtmSnapshot | null>(null);
	let viewState = $state<ViewState>('idle');
	let viewError = $state<string>('');

	// `/mtm/snapshots` returns a single scalar `MTMSnapshotResponse`
	// (mtm_value, entry_price, price_d1, quantity_mt — all Decimal-as-string,
	// see schema.d.ts:2672). No request fires until all three required
	// singleton params are supplied.
	let objectType = $state<string>('hedge_contract');
	let objectId = $state<string>('');
	let asOfDate = $state<string>('');
	let abortController: AbortController;

	function paramsReady(): boolean {
		return objectType.trim() !== '' && objectId.trim() !== '' && asOfDate.trim() !== '';
	}

	async function loadData(signal?: AbortSignal) {
		if (!paramsReady()) {
			mtmData = null;
			viewState = 'missing-param';
			const missing: string[] = [];
			if (!objectType.trim()) missing.push('object_type');
			if (!objectId.trim()) missing.push('object_id');
			if (!asOfDate.trim()) missing.push('as_of_date');
			viewError = `Parâmetros obrigatórios: ${missing.join(', ')}`;
			notifications.error(`MTM: ${viewError}`);
			return;
		}

		viewState = 'loading';
		try {
			const res = await apiFetch(
				mtmSnapshotsPath({ object_type: objectType, object_id: objectId, as_of_date: asOfDate }),
				{ signal },
			);
			if (res.ok) {
				let body: unknown;
				try {
					body = await res.json();
				} catch {
					mtmData = null;
					viewState = 'malformed';
					viewError = 'Resposta do servidor não pôde ser interpretada';
					notifications.error(`MTM: ${viewError}`);
					return;
				}
				// J-A6-03: missing required Decimal/identifier fields must
				// surface as an explicit malformed state — never let the
				// formatter render `undefined` as a blank/zero MTM value.
				const validation = validateMtmSnapshot(body);
				if (!validation.ok) {
					mtmData = null;
					viewState = 'malformed';
					viewError = `Snapshot MTM com campos obrigatórios ausentes ou inválidos: ${validation.missing.join(', ')}`;
					notifications.error(`MTM: ${viewError}`);
					return;
				}
				mtmData = validation.value;
				viewState = 'ready';
			} else {
				mtmData = null;
				viewState = 'error';
				viewError = await describeApiError(res);
				notifications.error(`MTM: ${viewError}`);
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			mtmData = null;
			viewState = 'error';
			viewError = e instanceof Error ? e.message : 'Erro de conexão';
			notifications.error('Erro ao carregar MTM');
		}
	}

	onMount(() => {
		abortController = new AbortController();
		// Do not fire a request on mount — required parameters are not
		// derivable from the page context. Operator must select them.
		viewState = 'missing-param';
		viewError = 'Informe object_type, object_id e as_of_date para carregar o snapshot.';
	});

	onDestroy(() => { abortController?.abort(); });

	// `mtm_value` etc. are Decimal-as-string; the format.ts helpers preserve
	// precision when given a string. Parse only for sign-based colour logic
	// (positive vs negative MTM); the displayed value goes through the
	// Decimal-aware formatter.
	function signOf(value: string | null | undefined): number {
		if (value == null || value === '') return Number.NaN;
		const n = Number(value);
		return Number.isFinite(n) ? n : Number.NaN;
	}

	const mtmValueSign = $derived(mtmData ? signOf(mtmData.mtm_value) : Number.NaN);
</script>

<div class="p-6">
	<h1 class="text-lg font-semibold text-surface-200">MTM Snapshot</h1>

	<div class="mt-4 grid grid-cols-4 gap-3 items-end">
		<div>
			<label class="block text-xs text-surface-500" for="mtm-object-type">object_type</label>
			<input
				id="mtm-object-type"
				type="text"
				bind:value={objectType}
				class="w-full rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200"
			/>
		</div>
		<div>
			<label class="block text-xs text-surface-500" for="mtm-object-id">object_id (uuid)</label>
			<input
				id="mtm-object-id"
				type="text"
				bind:value={objectId}
				class="w-full rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200"
			/>
		</div>
		<div>
			<label class="block text-xs text-surface-500" for="mtm-as-of-date">as_of_date</label>
			<input
				id="mtm-as-of-date"
				type="date"
				bind:value={asOfDate}
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
			<div class="text-surface-500">Carregando MTM...</div>
		{:else if viewState === 'missing-param'}
			<div
				class="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning"
				data-testid="mtm-missing-param"
			>
				{viewError}
			</div>
		{:else if viewState === 'error' || viewState === 'malformed'}
			<div class="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
				Erro ao carregar MTM: {viewError}
			</div>
		{:else if mtmData}
			<!--
				/mtm/snapshots returns a single scalar snapshot (see
				MTMSnapshotResponse). Render the scalar fields directly —
				there is no entries[] collection to chart.
			-->
			<div class="grid grid-cols-4 gap-4">
				<div class="rounded border border-surface-800 bg-surface-900 p-3">
					<div class="text-xs text-surface-500">MTM Value</div>
					<div
						class="text-lg font-semibold tabular-nums {Number.isFinite(mtmValueSign) && mtmValueSign >= 0 ? 'text-success' : 'text-danger'}"
						data-testid="mtm-value"
					>
						{formatNumber(mtmData.mtm_value)}
					</div>
				</div>
				<div class="rounded border border-surface-800 bg-surface-900 p-3">
					<div class="text-xs text-surface-500">Entry Price</div>
					<div class="text-lg font-semibold tabular-nums text-surface-200">
						{formatPrice(mtmData.entry_price)}
					</div>
				</div>
				<div class="rounded border border-surface-800 bg-surface-900 p-3">
					<div class="text-xs text-surface-500">Price D-1</div>
					<div class="text-lg font-semibold tabular-nums text-surface-200">
						{formatPrice(mtmData.price_d1)}
					</div>
				</div>
				<div class="rounded border border-surface-800 bg-surface-900 p-3">
					<div class="text-xs text-surface-500">Quantidade (MT)</div>
					<div class="text-lg font-semibold tabular-nums text-surface-200">
						{formatQuantityMT(mtmData.quantity_mt)}
					</div>
				</div>
			</div>

			<div class="mt-4 rounded border border-surface-800 bg-surface-900 p-3 text-sm space-y-1">
				<div><span class="text-surface-500">As of:</span> <span class="text-surface-200">{formatDate(mtmData.as_of_date)}</span></div>
				<div><span class="text-surface-500">Object:</span> <span class="text-surface-200">{mtmData.object_type} / {mtmData.object_id}</span></div>
				{#if mtmData.price_symbol}
					<div><span class="text-surface-500">Price source:</span> <span class="text-surface-200">{mtmData.price_source ?? '—'} / {mtmData.price_symbol}</span></div>
				{/if}
				{#if mtmData.price_settlement_date}
					<div><span class="text-surface-500">Settlement date:</span> <span class="text-surface-200">{formatDate(mtmData.price_settlement_date)}</span></div>
				{/if}
				<div><span class="text-surface-500">Correlation:</span> <span class="font-mono text-xs text-surface-400">{mtmData.correlation_id}</span></div>
				<div><span class="text-surface-500">Created:</span> <span class="text-surface-400">{formatDate(mtmData.created_at)}</span></div>
			</div>
		{:else}
			<div class="text-surface-500">Nenhum dado de MTM disponível</div>
		{/if}
	</div>
</div>
