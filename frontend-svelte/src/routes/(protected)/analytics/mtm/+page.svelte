<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { apiFetch } from '$lib/api/fetch';
	import { mtmSnapshotsPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import EChart from '$lib/components/chart/EChart.svelte';
	import type { MtmSnapshot } from '$lib/api/types/entities';

	type ViewState = 'idle' | 'missing-param' | 'loading' | 'ready' | 'error' | 'malformed';

	let mtmData = $state<MtmSnapshot | null>(null);
	let viewState = $state<ViewState>('idle');
	let viewError = $state<string>('');

	// Operator-supplied parameters. `/mtm/snapshots` is a singleton lookup,
	// not a collection; no request fires until all three are provided.
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
				try {
					mtmData = await res.json();
					viewState = 'ready';
				} catch {
					mtmData = null;
					viewState = 'malformed';
					viewError = 'Resposta do servidor não pôde ser interpretada';
					notifications.error(`MTM: ${viewError}`);
				}
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

	let chartOptions = $derived.by(() => {
		if (!mtmData?.items && !mtmData?.entries) return {};
		const entries = mtmData.items ?? mtmData.entries ?? [];
		return {
			tooltip: { trigger: 'axis' as const },
			xAxis: {
				type: 'category' as const,
				data: entries.map((e: any) => e.date ?? e.snapshot_date ?? e.label ?? ''),
			},
			yAxis: { type: 'value' as const },
			series: [
				{
					name: 'MTM',
					type: 'line' as const,
					data: entries.map((e: any) => e.mtm_value ?? e.value ?? 0),
					smooth: true,
					areaStyle: { opacity: 0.1 },
					itemStyle: { color: '#3b82f6' },
				},
			],
			dataZoom: [{ type: 'inside' as const }],
		};
	});
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
			<EChart options={chartOptions} style="width:100%;height:450px" />
		{:else}
			<div class="text-surface-500">Nenhum dado de MTM disponível</div>
		{/if}
	</div>
</div>
