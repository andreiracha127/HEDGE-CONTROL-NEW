<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatNumber, formatDate } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { cashflowAnalyticPath, cashflowProjectionPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import { type ColumnDef } from '@tanstack/table-core';
	import DataTable from '$lib/components/table/DataTable.svelte';
	import type { CashflowAnalyticsEntry, CashflowProjection, CashflowLedgerEntry, CashflowSummary } from '$lib/api/types/entities';

	type TabState = 'idle' | 'loading' | 'ready' | 'missing-param' | 'error' | 'malformed';

	let activeTab = $state<'analytics' | 'projections' | 'ledger'>('analytics');
	let isLoading = $state(false);

	// Data
	let analytics = $state<CashflowAnalyticsEntry[]>([]);
	let projections = $state<CashflowProjection[]>([]);
	let ledger = $state<CashflowLedgerEntry[]>([]);
	let summary = $state<CashflowSummary | null>(null);

	// Tab states (load/empty/error/malformed/missing-param distinguished)
	let analyticsState = $state<TabState>('idle');
	let projectionsState = $state<TabState>('idle');
	let analyticsError = $state<string>('');
	let projectionsError = $state<string>('');

	// Date filter — `as_of_date` derives from dateTo; user picks the date
	// explicitly through the inputs. No request fires until a date is set.
	let dateFrom = $state('');
	let dateTo = $state('');
	let abortController: AbortController;

	function today(): string {
		const d = new Date();
		const m = String(d.getMonth() + 1).padStart(2, '0');
		const day = String(d.getDate()).padStart(2, '0');
		return `${d.getFullYear()}-${m}-${day}`;
	}

	async function loadData(signal?: AbortSignal) {
		const asOfDate = dateTo.trim();

		if (!asOfDate) {
			analyticsState = 'missing-param';
			projectionsState = 'missing-param';
			analyticsError = 'Selecione a data "Até" (as_of_date) para carregar';
			projectionsError = 'Selecione a data "Até" (as_of_date) para carregar';
			analytics = [];
			projections = [];
			summary = null;
			return;
		}

		isLoading = true;
		analyticsState = 'loading';
		projectionsState = 'loading';

		try {
			const [analyticsRes, projectionsRes] = await Promise.all([
				apiFetch(cashflowAnalyticPath({ as_of_date: asOfDate }), { signal }),
				apiFetch(cashflowProjectionPath({ as_of_date: asOfDate }), { signal }),
			]);

			if (analyticsRes.ok) {
				try {
					const data = await analyticsRes.json();
					analytics = data.items ?? data.entries ?? data;
					summary = data.summary ?? null;
					analyticsState = 'ready';
				} catch {
					analytics = [];
					summary = null;
					analyticsState = 'malformed';
					analyticsError = 'Resposta do servidor não pôde ser interpretada';
					notifications.error('Cashflow analytic: resposta malformada');
				}
			} else {
				analytics = [];
				summary = null;
				analyticsState = 'error';
				analyticsError = await describeApiError(analyticsRes);
				notifications.error(`Cashflow analytic: ${analyticsError}`);
			}

			if (projectionsRes.ok) {
				try {
					const data = await projectionsRes.json();
					projections = data.items ?? data;
					projectionsState = 'ready';
				} catch {
					projections = [];
					projectionsState = 'malformed';
					projectionsError = 'Resposta do servidor não pôde ser interpretada';
					notifications.error('Cashflow projection: resposta malformada');
				}
			} else {
				projections = [];
				projectionsState = 'error';
				projectionsError = await describeApiError(projectionsRes);
				notifications.error(`Cashflow projection: ${projectionsError}`);
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			analyticsState = 'error';
			projectionsState = 'error';
			analyticsError = e instanceof Error ? e.message : 'Erro de conexão';
			projectionsError = analyticsError;
			notifications.error('Erro ao carregar cashflow');
		} finally {
			isLoading = false;
		}
	}

	onMount(() => {
		abortController = new AbortController();
		// Default to today so the operator sees data on mount. The filter
		// inputs remain editable for explicit date selection.
		if (!dateTo) dateTo = today();
		loadData(abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });

	// ─── Ledger Columns ─────────────────────────────────────────────────
	const ledgerColumns: ColumnDef<any, any>[] = [
		{
			accessorFn: (row) => row.date ?? row.settlement_date,
			id: 'date',
			header: 'Data',
			cell: (info) => formatDate(info.getValue() as string),
		},
		{
			accessorFn: (row) => row.contract_reference ?? row.reference,
			id: 'reference',
			header: 'Referência',
		},
		{
			accessorFn: (row) => row.counterparty_name ?? row.counterparty,
			id: 'counterparty',
			header: 'Contraparte',
		},
		{
			accessorFn: (row) => row.commodity,
			id: 'commodity',
			header: 'Commodity',
		},
		{
			accessorFn: (row) => row.inflow ?? (row.amount > 0 ? row.amount : null),
			id: 'inflow',
			header: 'Entrada',
			cell: (info) => {
				const v = info.getValue() as number | null;
				return v != null && v > 0 ? formatNumber(v) : '—';
			},
		},
		{
			accessorFn: (row) => row.outflow ?? (row.amount < 0 ? Math.abs(row.amount) : null),
			id: 'outflow',
			header: 'Saída',
			cell: (info) => {
				const v = info.getValue() as number | null;
				return v != null && v > 0 ? formatNumber(v) : '—';
			},
		},
		{
			accessorFn: (row) => row.balance ?? row.running_balance,
			id: 'balance',
			header: 'Saldo',
			cell: (info) => formatNumber(info.getValue() as number),
		},
	];
</script>

<div class="p-6">
	<h1 class="text-lg font-semibold text-surface-200">Cashflow</h1>

	<!-- Summary cards -->
	{#if summary}
		<div class="mt-4 grid grid-cols-3 gap-4">
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Total Entradas</div>
				<div class="text-lg font-semibold tabular-nums text-success">{formatNumber(summary.total_inflows)}</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Total Saídas</div>
				<div class="text-lg font-semibold tabular-nums text-danger">{formatNumber(summary.total_outflows)}</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Saldo Líquido</div>
				<div class="text-lg font-semibold tabular-nums text-surface-200">{formatNumber(summary.net_balance)}</div>
			</div>
		</div>
	{/if}

	<!-- Date filter -->
	<div class="mt-4 flex gap-3 items-end">
		<div>
			<label class="block text-xs text-surface-500" for="cf-from">De</label>
			<input id="cf-from" type="date" bind:value={dateFrom} class="rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200" />
		</div>
		<div>
			<label class="block text-xs text-surface-500" for="cf-to">Até (as_of_date)</label>
			<input id="cf-to" type="date" bind:value={dateTo} class="rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-200" />
		</div>
		<button onclick={() => loadData()} class="rounded border border-surface-700 px-3 py-1 text-sm text-surface-400 hover:bg-surface-800">
			Filtrar
		</button>
	</div>

	<!-- Tabs -->
	<div class="mt-6 flex gap-4 border-b border-surface-800">
		<button
			onclick={() => activeTab = 'analytics'}
			class="pb-2 text-sm {activeTab === 'analytics' ? 'border-b-2 border-accent text-accent' : 'text-surface-500 hover:text-surface-300'}"
		>
			Analytics
		</button>
		<button
			onclick={() => activeTab = 'projections'}
			class="pb-2 text-sm {activeTab === 'projections' ? 'border-b-2 border-accent text-accent' : 'text-surface-500 hover:text-surface-300'}"
		>
			Projeções
		</button>
		<button
			onclick={() => activeTab = 'ledger'}
			class="pb-2 text-sm {activeTab === 'ledger' ? 'border-b-2 border-accent text-accent' : 'text-surface-500 hover:text-surface-300'}"
		>
			Ledger
		</button>
	</div>

	<div class="mt-4">
		{#if activeTab === 'analytics'}
			{#if analyticsState === 'loading'}
				<div class="text-sm text-surface-500">Carregando analytics...</div>
			{:else if analyticsState === 'missing-param'}
				<div class="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
					{analyticsError}
				</div>
			{:else if analyticsState === 'error' || analyticsState === 'malformed'}
				<div class="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
					Erro ao carregar analytic: {analyticsError}
				</div>
			{:else if Array.isArray(analytics) && analytics.length > 0}
				<div class="space-y-3">
					{#each analytics as entry (entry.id ?? entry.month ?? entry.period)}
						<div class="rounded border border-surface-800 bg-surface-900 p-3">
							<div class="flex items-center justify-between">
								<span class="text-sm font-medium text-surface-200">{entry.period ?? entry.month ?? entry.commodity}</span>
								<span class="text-sm tabular-nums text-surface-300">{formatNumber(entry.net_amount ?? entry.net)}</span>
							</div>
							<div class="mt-1 flex gap-4 text-xs text-surface-500">
								<span class="text-success">+{formatNumber(entry.inflows ?? entry.total_inflows)}</span>
								<span class="text-danger">-{formatNumber(entry.outflows ?? entry.total_outflows)}</span>
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<div class="text-sm text-surface-500">Nenhum dado analítico disponível</div>
			{/if}

		{:else if activeTab === 'projections'}
			{#if projectionsState === 'loading'}
				<div class="text-sm text-surface-500">Carregando projeções...</div>
			{:else if projectionsState === 'missing-param'}
				<div class="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
					{projectionsError}
				</div>
			{:else if projectionsState === 'error' || projectionsState === 'malformed'}
				<div class="rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
					Erro ao carregar projeção: {projectionsError}
				</div>
			{:else if projections.length > 0}
				<div class="space-y-2">
					{#each projections as proj (proj.id ?? proj.month)}
						<div class="flex items-center gap-3 rounded border border-surface-800 bg-surface-900 px-4 py-2">
							<span class="text-sm text-surface-300 w-24">{proj.month ?? proj.period}</span>
							<div class="flex-1 h-4 rounded bg-surface-800 overflow-hidden">
								{#if proj.projected_inflow || proj.inflow}
									<div
										class="h-full bg-success/60"
										style="width: {Math.min(((proj.projected_inflow ?? proj.inflow ?? 0) / (Math.max(proj.projected_inflow ?? proj.inflow ?? 1, proj.projected_outflow ?? proj.outflow ?? 1))) * 100, 100)}%"
									></div>
								{/if}
							</div>
							<span class="text-xs tabular-nums text-surface-400 w-24 text-right">
								{formatNumber(proj.net ?? proj.projected_net)}
							</span>
						</div>
					{/each}
				</div>
			{:else}
				<div class="text-sm text-surface-500">Nenhuma projeção disponível</div>
			{/if}

		{:else}
			<!--
				Ledger requires `source_event_id` per `/cashflow/ledger`. The
				cashflow dashboard has no reliable source for it (this is a
				summary surface, not an event detail surface), so we render an
				explicit missing-parameter state and do not issue a request.
				A dedicated event-scoped ledger view is out of scope for
				PR-A6-1.
			-->
			<div class="rounded border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning">
				Ledger requer um source_event_id. Acesse o ledger a partir de um evento ou contrato específico.
			</div>
			<div class="mt-3 opacity-60 pointer-events-none">
				<DataTable
					data={ledger}
					columns={ledgerColumns}
					isLoading={false}
					emptyMessage="Selecione um evento ou contrato para visualizar o ledger"
				/>
			</div>
		{/if}
	</div>
</div>
