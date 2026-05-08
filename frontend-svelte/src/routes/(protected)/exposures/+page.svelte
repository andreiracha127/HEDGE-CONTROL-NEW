<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatQuantityMT } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { type ColumnDef } from '@tanstack/table-core';
	import DataTable from '$lib/components/table/DataTable.svelte';
	import type { Exposure, NetExposure, HedgeTask } from '$lib/api/types/entities';

	// ─── State ──────────────────────────────────────────────────────────
	let exposures = $state<Exposure[]>([]);
	let netExposure = $state<NetExposure | null>(null);
	let hedgeTasks = $state<HedgeTask[]>([]);
	let isLoading = $state(true);
	let activeTab = $state<'exposures' | 'tasks'>('exposures');

	// Grouping
	let groupBy = $state<string[]>([]);
	let abortController: AbortController;

	async function loadData(signal?: AbortSignal) {
		isLoading = true;
		try {
			const [expRes, netRes, tasksRes] = await Promise.all([
				apiFetch('/exposures/list?limit=200', { signal }),
				apiFetch('/exposures/net', { signal }),
				apiFetch('/exposures/tasks', { signal }),
			]);

			if (expRes.ok) {
				const data = await expRes.json();
				exposures = data.items ?? data;
			}
			if (netRes.ok) netExposure = await netRes.json();
			if (tasksRes.ok) {
				const data = await tasksRes.json();
				hedgeTasks = data.items ?? data;
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			notifications.error('Erro ao carregar exposições');
		} finally {
			isLoading = false;
		}
	}

	onMount(() => {
		abortController = new AbortController();
		loadData(abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });

	// ─── Column Defs ────────────────────────────────────────────────────
	const columns: ColumnDef<any, any>[] = [
		{
			accessorFn: (row) => row.commodity,
			id: 'commodity',
			header: 'Commodity',
			enableGrouping: true,
		},
		{
			accessorFn: (row) => row.settlement_month,
			id: 'settlement_month',
			header: 'Mês',
			enableGrouping: true,
		},
		{
			accessorFn: (row) => row.source_type,
			id: 'source_type',
			header: 'Tipo',
			enableGrouping: true,
		},
		{
			accessorFn: (row) => row.quantity_mt,
			id: 'quantity_mt',
			header: 'Qty (MT)',
			cell: (info) => formatQuantityMT(info.getValue() as number),
		},
		{
			accessorFn: (row) => row.direction,
			id: 'direction',
			header: 'Direção',
		},
		{
			accessorFn: (row) => row.hedge_status,
			id: 'hedge_status',
			header: 'Status Hedge',
			cell: (info) => {
				const v = info.getValue() as string;
				return v ?? '—';
			},
		},
		{
			accessorFn: (row) => row.net_exposure_mt,
			id: 'net_exposure_mt',
			header: 'Exposição Líquida',
			cell: (info) => formatQuantityMT(info.getValue() as number),
		},
	];

	function hedgeStatusColor(status: string): string {
		switch (status) {
			case 'fully_hedged': return 'text-success';
			case 'partially_hedged': return 'text-warning';
			case 'open': return 'text-danger';
			default: return 'text-surface-400';
		}
	}

	function toggleGroupBy(field: string) {
		if (groupBy.includes(field)) {
			groupBy = groupBy.filter(g => g !== field);
		} else {
			groupBy = [...groupBy, field];
		}
	}
</script>

<div class="p-6">
	<h1 class="text-lg font-semibold text-surface-200">Exposições</h1>

	<!-- Net exposure summary cards -->
	{#if netExposure}
		<div class="mt-4 grid grid-cols-4 gap-4">
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Exposição Bruta</div>
				<div class="text-lg font-semibold tabular-nums text-surface-200">
					{formatQuantityMT(netExposure.gross_exposure_mt)} MT
				</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Exposição Líquida</div>
				<div class="text-lg font-semibold tabular-nums text-surface-200">
					{formatQuantityMT(netExposure.net_exposure_mt)} MT
				</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Hedge Ratio</div>
				<div class="text-lg font-semibold tabular-nums text-surface-200">
					{netExposure.hedge_ratio != null ? (netExposure.hedge_ratio * 100).toFixed(1) + '%' : '—'}
				</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Posições Abertas</div>
				<div class="text-lg font-semibold tabular-nums text-surface-200">
					{netExposure.open_positions ?? '—'}
				</div>
			</div>
		</div>
	{/if}

	<!-- Tabs -->
	<div class="mt-6 flex gap-4 border-b border-surface-800">
		<button
			onclick={() => activeTab = 'exposures'}
			class="pb-2 text-sm {activeTab === 'exposures' ? 'border-b-2 border-accent text-accent' : 'text-surface-500 hover:text-surface-300'}"
		>
			Exposições
		</button>
		<button
			onclick={() => activeTab = 'tasks'}
			class="pb-2 text-sm {activeTab === 'tasks' ? 'border-b-2 border-accent text-accent' : 'text-surface-500 hover:text-surface-300'}"
		>
			Hedge Tasks ({hedgeTasks.length})
		</button>
	</div>

	{#if activeTab === 'exposures'}
		<!-- Grouping controls -->
		<div class="mt-4 flex gap-2">
			<span class="text-xs text-surface-500">Agrupar por:</span>
			{#each ['commodity', 'settlement_month', 'source_type'] as field}
				<button
					onclick={() => toggleGroupBy(field)}
					class="rounded px-2 py-0.5 text-xs {groupBy.includes(field) ? 'bg-accent/20 text-accent' : 'bg-surface-800 text-surface-400 hover:text-surface-300'}"
				>
					{field === 'commodity' ? 'Commodity' : field === 'settlement_month' ? 'Mês' : 'Tipo'}
				</button>
			{/each}
		</div>

		<div class="mt-4">
			<DataTable
				data={exposures}
				{columns}
				enableGrouping={groupBy.length > 0}
				{isLoading}
				emptyMessage="Nenhuma exposição encontrada"
			/>
		</div>
	{:else}
		<!-- Hedge Tasks -->
		<div class="mt-4 space-y-3">
			{#each hedgeTasks as task (task.id ?? task.exposure_id)}
				<div class="rounded border border-surface-800 bg-surface-900 p-4">
					<div class="flex items-center justify-between">
						<div>
							<span class="text-sm font-medium text-surface-200">{task.commodity}</span>
							<span class="ml-2 text-xs text-surface-500">{task.action ?? task.recommendation}</span>
						</div>
						{#if task.action === 'hedge_new' || task.recommendation === 'hedge_new'}
							<a
								href="/rfq/new"
								class="rounded bg-accent/10 px-3 py-1 text-xs text-accent hover:bg-accent/20"
							>
								Criar RFQ
							</a>
						{/if}
					</div>
					<div class="mt-1 text-xs text-surface-500">
						{formatQuantityMT(task.quantity_mt)} MT · {task.settlement_month ?? '—'}
					</div>
				</div>
			{:else}
				<div class="text-sm text-surface-500">Nenhuma tarefa de hedge pendente</div>
			{/each}
		</div>
	{/if}
</div>
