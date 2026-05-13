<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatNumber, formatDate, formatPrice, formatQuantityMT } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { cashflowAnalyticPath, cashflowProjectionPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import type {
		CashFlowItem,
		CashFlowAnalyticResponse,
		CashFlowProjectionItem,
		CashFlowProjectionResponse,
		CashFlowProjectionSummary,
	} from '$lib/api/types/entities';

	type TabState = 'idle' | 'loading' | 'ready' | 'missing-param' | 'error' | 'malformed';

	let activeTab = $state<'analytics' | 'projections' | 'ledger'>('analytics');
	let isLoading = $state(false);

	// Canonical analytic response shape (CashFlowAnalyticResponse): a list of
	// per-position `cashflow_items` plus a scalar `total_net_cashflow`.
	let cashflowItems = $state<CashFlowItem[]>([]);
	let totalNetCashflow = $state<string | null>(null);
	let analyticAsOfDate = $state<string | null>(null);

	// Canonical projection response shape (CashFlowProjectionResponse): a
	// list of `items` plus a `summary` with total_inflows, total_outflows,
	// net_cashflow, instrument_count (all Decimal-as-string except count).
	let projectionItems = $state<CashFlowProjectionItem[]>([]);
	let projectionSummary = $state<CashFlowProjectionSummary | null>(null);
	let projectionAsOfDate = $state<string | null>(null);

	// Tab states distinguish loading / ready / error / malformed / missing-param.
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

	function clearAnalytic() {
		cashflowItems = [];
		totalNetCashflow = null;
		analyticAsOfDate = null;
	}

	function clearProjection() {
		projectionItems = [];
		projectionSummary = null;
		projectionAsOfDate = null;
	}

	async function loadData(signal?: AbortSignal) {
		const asOfDate = dateTo.trim();

		if (!asOfDate) {
			analyticsState = 'missing-param';
			projectionsState = 'missing-param';
			analyticsError = 'Selecione a data "Até" (as_of_date) para carregar';
			projectionsError = 'Selecione a data "Até" (as_of_date) para carregar';
			clearAnalytic();
			clearProjection();
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
					const data = (await analyticsRes.json()) as CashFlowAnalyticResponse;
					cashflowItems = Array.isArray(data?.cashflow_items) ? data.cashflow_items : [];
					totalNetCashflow = typeof data?.total_net_cashflow === 'string' ? data.total_net_cashflow : null;
					analyticAsOfDate = typeof data?.as_of_date === 'string' ? data.as_of_date : null;
					analyticsState = 'ready';
				} catch {
					clearAnalytic();
					analyticsState = 'malformed';
					analyticsError = 'Resposta do servidor não pôde ser interpretada';
					notifications.error('Cashflow analytic: resposta malformada');
				}
			} else {
				clearAnalytic();
				analyticsState = 'error';
				analyticsError = await describeApiError(analyticsRes);
				notifications.error(`Cashflow analytic: ${analyticsError}`);
			}

			if (projectionsRes.ok) {
				try {
					const data = (await projectionsRes.json()) as CashFlowProjectionResponse;
					projectionItems = Array.isArray(data?.items) ? data.items : [];
					projectionSummary = data?.summary ?? null;
					projectionAsOfDate = typeof data?.as_of_date === 'string' ? data.as_of_date : null;
					projectionsState = 'ready';
				} catch {
					clearProjection();
					projectionsState = 'malformed';
					projectionsError = 'Resposta do servidor não pôde ser interpretada';
					notifications.error('Cashflow projection: resposta malformada');
				}
			} else {
				clearProjection();
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

	// Helpers for sign-based colouring on Decimal-as-string totals.
	function signOf(value: string | null | undefined): number {
		if (value == null || value === '') return Number.NaN;
		const n = Number(value);
		return Number.isFinite(n) ? n : Number.NaN;
	}

	const netSign = $derived(signOf(totalNetCashflow));
	const projectionNetSign = $derived(signOf(projectionSummary?.net_cashflow ?? null));
</script>

<div class="p-6">
	<h1 class="text-lg font-semibold text-surface-200">Cashflow</h1>

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
			{:else}
				<!--
					CashFlowAnalyticResponse: total_net_cashflow is a scalar
					Decimal-string; cashflow_items is the per-position list.
				-->
				<div class="grid grid-cols-3 gap-4">
					<div class="rounded border border-surface-800 bg-surface-900 p-3">
						<div class="text-xs text-surface-500">Net Cashflow</div>
						<div
							class="text-lg font-semibold tabular-nums {Number.isFinite(netSign) && netSign >= 0 ? 'text-success' : 'text-danger'}"
							data-testid="analytic-total-net-cashflow"
						>
							{formatNumber(totalNetCashflow)}
						</div>
					</div>
					<div class="rounded border border-surface-800 bg-surface-900 p-3">
						<div class="text-xs text-surface-500">As Of</div>
						<div class="text-lg font-semibold text-surface-200">{formatDate(analyticAsOfDate)}</div>
					</div>
					<div class="rounded border border-surface-800 bg-surface-900 p-3">
						<div class="text-xs text-surface-500">Itens</div>
						<div class="text-lg font-semibold tabular-nums text-surface-200">{cashflowItems.length}</div>
					</div>
				</div>

				{#if cashflowItems.length > 0}
					<div class="mt-4 overflow-x-auto rounded border border-surface-800">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-surface-800 bg-surface-900 text-left text-xs text-surface-500">
									<th class="px-3 py-2">Settlement</th>
									<th class="px-3 py-2">Objeto</th>
									<th class="px-3 py-2">Amount USD</th>
									<th class="px-3 py-2">MTM</th>
									<th class="px-3 py-2">Preço</th>
									<th class="px-3 py-2">Fonte</th>
								</tr>
							</thead>
							<tbody>
								{#each cashflowItems as item, idx (item.object_id + ':' + item.settlement_date + ':' + idx)}
									<tr class="border-b border-surface-800/50">
										<td class="px-3 py-2 text-surface-300">{formatDate(item.settlement_date)}</td>
										<td class="px-3 py-2 text-xs text-surface-400">
											<span class="font-mono">{item.object_type}</span> /
											<span class="font-mono">{item.object_id.slice(0, 8)}</span>
										</td>
										<td class="px-3 py-2 tabular-nums text-surface-200">{formatNumber(item.amount_usd)}</td>
										<td class="px-3 py-2 tabular-nums text-surface-300">{formatNumber(item.mtm_value)}</td>
										<td class="px-3 py-2 tabular-nums text-xs text-surface-400">{formatPrice(item.price_value ?? null)}</td>
										<td class="px-3 py-2 text-xs text-surface-500">{item.price_source ?? '—'}{item.price_symbol ? ` / ${item.price_symbol}` : ''}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div class="mt-4 text-sm text-surface-500">Nenhum item analítico disponível</div>
				{/if}
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
			{:else}
				<!--
					CashFlowProjectionResponse: summary carries total_inflows /
					total_outflows / net_cashflow (Decimal strings) and
					instrument_count (int). Items expose settlement_date,
					reference, commodity, counterparty, amount_usd, etc.
				-->
				{#if projectionSummary}
					<div class="grid grid-cols-4 gap-4">
						<div class="rounded border border-surface-800 bg-surface-900 p-3">
							<div class="text-xs text-surface-500">Total Entradas</div>
							<div
								class="text-lg font-semibold tabular-nums text-success"
								data-testid="projection-total-inflows"
							>
								{formatNumber(projectionSummary.total_inflows)}
							</div>
						</div>
						<div class="rounded border border-surface-800 bg-surface-900 p-3">
							<div class="text-xs text-surface-500">Total Saídas</div>
							<div
								class="text-lg font-semibold tabular-nums text-danger"
								data-testid="projection-total-outflows"
							>
								{formatNumber(projectionSummary.total_outflows)}
							</div>
						</div>
						<div class="rounded border border-surface-800 bg-surface-900 p-3">
							<div class="text-xs text-surface-500">Net Cashflow</div>
							<div
								class="text-lg font-semibold tabular-nums {Number.isFinite(projectionNetSign) && projectionNetSign >= 0 ? 'text-success' : 'text-danger'}"
								data-testid="projection-net-cashflow"
							>
								{formatNumber(projectionSummary.net_cashflow)}
							</div>
						</div>
						<div class="rounded border border-surface-800 bg-surface-900 p-3">
							<div class="text-xs text-surface-500">Instrumentos</div>
							<div class="text-lg font-semibold tabular-nums text-surface-200">{projectionSummary.instrument_count}</div>
						</div>
					</div>
				{/if}

				{#if projectionItems.length > 0}
					<div class="mt-4 overflow-x-auto rounded border border-surface-800">
						<table class="w-full text-sm">
							<thead>
								<tr class="border-b border-surface-800 bg-surface-900 text-left text-xs text-surface-500">
									<th class="px-3 py-2">Settlement</th>
									<th class="px-3 py-2">Referência</th>
									<th class="px-3 py-2">Commodity</th>
									<th class="px-3 py-2">Contraparte</th>
									<th class="px-3 py-2">Qty (MT)</th>
									<th class="px-3 py-2">Preço / MT</th>
									<th class="px-3 py-2">Amount USD</th>
									<th class="px-3 py-2">Tipo</th>
								</tr>
							</thead>
							<tbody>
								{#each projectionItems as item, idx (item.instrument_id + ':' + idx)}
									<tr class="border-b border-surface-800/50">
										<td class="px-3 py-2 text-surface-300">{formatDate(item.settlement_date)}</td>
										<td class="px-3 py-2 font-mono text-xs text-surface-400">{item.reference || '—'}</td>
										<td class="px-3 py-2 text-surface-300">{item.commodity || '—'}</td>
										<td class="px-3 py-2 text-surface-400">{item.counterparty || '—'}</td>
										<td class="px-3 py-2 tabular-nums text-surface-300">{formatQuantityMT(item.quantity_mt)}</td>
										<td class="px-3 py-2 tabular-nums text-surface-300">{formatPrice(item.price_per_mt)}</td>
										<td class="px-3 py-2 tabular-nums text-surface-200">{formatNumber(item.amount_usd)}</td>
										<td class="px-3 py-2 text-xs text-surface-500">{item.instrument_type}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<div class="mt-4 text-sm text-surface-500">Nenhuma projeção disponível</div>
				{/if}
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
		{/if}
	</div>
</div>
