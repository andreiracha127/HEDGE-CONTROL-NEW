<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatNumber, formatDate, formatPrice } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { describeApiError } from '$lib/api/errors';
	import EChart from '$lib/components/chart/EChart.svelte';
	import type { MarketPrice } from '$lib/api/types/entities';

	let prices = $state<MarketPrice[]>([]);
	let isLoading = $state(true);
	let isIngesting = $state(false);
	let isRiskManager = $derived(authStore.hasRole('risk_manager'));
	let abortController: AbortController;

	// J-A6-06: /market-data/westmetall/aluminum/cash-settlement/prices
	// returns `CashSettlementPriceRead[]` directly — `price_usd` is a
	// Decimal-as-string with six fractional digits. Discard rows that
	// lack the required identifiers/economics instead of zeroing them.
	function isValidMarketPrice(row: unknown): row is MarketPrice {
		if (!row || typeof row !== 'object') return false;
		const r = row as Record<string, unknown>;
		return (
			typeof r.id === 'string' &&
			typeof r.settlement_date === 'string' &&
			typeof r.price_usd === 'string'
		);
	}

	async function loadPrices(signal?: AbortSignal) {
		isLoading = true;
		try {
			const res = await apiFetch('/market-data/westmetall/aluminum/cash-settlement/prices?limit=90', { signal });
			if (res.ok) {
				const data: unknown = await res.json();
				const arr = Array.isArray(data) ? data : [];
				prices = arr.filter(isValidMarketPrice);
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			notifications.error('Erro ao carregar market data');
		} finally {
			isLoading = false;
		}
	}

	async function triggerIngest() {
		isIngesting = true;
		try {
			const res = await apiFetch('/market-data/westmetall/aluminum/cash-settlement/ingest', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ settlement_date: new Date().toISOString().split('T')[0] }),
			});
			if (res.ok) {
				notifications.success('Ingestão iniciada');
				await loadPrices();
			} else {
				const message = await describeApiError(res);
				notifications.error(`Falha na ingestão de market data: ${message}`);
			}
		} catch (e) {
			notifications.error(
				`Erro ao iniciar ingestão: ${e instanceof Error ? e.message : 'desconhecido'}`,
			);
		} finally {
			isIngesting = false;
		}
	}

	onMount(() => {
		abortController = new AbortController();
		loadPrices(abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });

	// Chronological ordering for both the chart and the row-to-row delta
	// computation in the table.
	let sortedPrices = $derived(
		[...prices].sort(
			(a, b) =>
				new Date(a.settlement_date).getTime() -
				new Date(b.settlement_date).getTime(),
		),
	);

	// `price_usd` is a six-decimal Decimal-as-string. The chart axis is
	// a visual aid where ~15 sig-fig IEEE-754 precision is acceptable
	// (the institutional precision concern is the tabular display, which
	// renders the raw string via formatPrice). Drop rows whose numeric
	// parse fails — those would otherwise plot as NaN points.
	let chartOptions = $derived(() => {
		if (sortedPrices.length === 0) return {};
		return {
			tooltip: { trigger: 'axis' as const },
			xAxis: {
				type: 'category' as const,
				data: sortedPrices.map((p) => p.settlement_date),
			},
			yAxis: { type: 'value' as const, name: 'USD/MT' },
			series: [{
				name: 'LME Aluminium',
				type: 'line' as const,
				data: sortedPrices.map((p) => Number(p.price_usd)),
				smooth: true,
				itemStyle: { color: '#3b82f6' },
				areaStyle: { opacity: 0.05 },
			}],
			dataZoom: [{ type: 'inside' as const }, { type: 'slider' as const }],
		};
	});

	// Most-recent-first for the table view, with the row-to-row change
	// computed against the previous chronological row. `change` is a
	// derived delta of two USD prices; rendered with two fractional
	// digits (settlement-price precision is preserved separately on the
	// `price_usd` column itself).
	let pricesForTable = $derived(
		sortedPrices
			.map((p, idx, arr) => {
				const prev = idx > 0 ? arr[idx - 1] : null;
				const prevN = prev ? Number(prev.price_usd) : Number.NaN;
				const curN = Number(p.price_usd);
				const change =
					Number.isFinite(prevN) && Number.isFinite(curN)
						? curN - prevN
						: null;
				return { ...p, change };
			})
			.reverse(),
	);
</script>

<div class="p-6">
	<div class="flex items-center justify-between">
		<h1 class="text-lg font-semibold text-surface-200">Market Data</h1>
		{#if isRiskManager}
			<button
				onclick={triggerIngest}
				disabled={isIngesting}
				class="rounded border border-surface-700 px-3 py-1.5 text-sm text-surface-400 hover:bg-surface-800 disabled:opacity-50"
			>
				{isIngesting ? 'Importando...' : 'Importar Preços'}
			</button>
		{/if}
	</div>

	{#if isLoading}
		<div class="mt-4 text-surface-500">Carregando...</div>
	{:else if prices.length > 0}
		<div class="mt-4">
			<EChart options={chartOptions()} style="width:100%;height:400px" />
		</div>

		<div class="mt-6 overflow-x-auto rounded border border-surface-800">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-surface-800 bg-surface-900 text-left text-xs text-surface-500">
						<th class="px-3 py-2">Data</th>
						<th class="px-3 py-2">Preço (USD/MT)</th>
						<th class="px-3 py-2">Variação</th>
					</tr>
				</thead>
				<tbody>
					{#each pricesForTable.slice(0, 30) as price (price.id)}
						<tr class="border-b border-surface-800/50">
							<td class="px-3 py-2 text-surface-400 text-xs">{formatDate(price.settlement_date)}</td>
							<td class="px-3 py-2 tabular-nums text-surface-200" data-testid="market-price-usd">{formatPrice(price.price_usd, 'USD/MT')}</td>
							<td class="px-3 py-2 tabular-nums text-xs {price.change != null && price.change >= 0 ? 'text-success' : 'text-danger'}">
								{price.change != null ? (price.change >= 0 ? '+' : '') + formatNumber(price.change) : '—'}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{:else}
		<div class="mt-4 text-surface-500">Nenhum dado de preço disponível</div>
	{/if}
</div>
