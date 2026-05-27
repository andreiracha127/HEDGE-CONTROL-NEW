<script lang="ts">
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatNumber } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import EChart from '$lib/components/chart/EChart.svelte';
	import type { WhatIfResult } from '$lib/api/types/entities';

	// Only risk_manager and auditor
	let allowed = $derived(authStore.hasAnyRole('risk_manager', 'auditor'));

	// Parameters
	let priceShock = $state(0);
	let volumeChange = $state(0);
	let commodity = $state('ALUMINIUM');
	let result = $state<WhatIfResult | null>(null);
	let isRunning = $state(false);

	async function runScenario() {
		isRunning = true;
		try {
			const res = await apiFetch('/scenario/what-if/run', {
				method: 'POST',
				body: JSON.stringify({
					price_shock_pct: priceShock,
					volume_change_pct: volumeChange,
					commodity,
				}),
			});
			if (res.ok) {
				result = await res.json();
			} else {
				const err = await res.json().catch(() => ({ detail: 'Erro' }));
				notifications.error(typeof err.detail === 'string' ? err.detail : 'Erro no cenário');
			}
		} catch {
			notifications.error('Erro ao executar cenário');
		} finally {
			isRunning = false;
		}
	}

	let chartOptions = $derived.by(() => {
		const r = result;
		if (!r) return {};
		const base = r.base ?? {};
		const scenario = r.scenario ?? {};
		const categories = Object.keys(base).length > 0 ? Object.keys(base) : ['P&L'];

		return {
			tooltip: { trigger: 'axis' as const },
			legend: { data: ['Base', 'Cenário'] },
			xAxis: { type: 'category' as const, data: categories },
			yAxis: { type: 'value' as const },
			series: [
				{
					name: 'Base',
					type: 'bar' as const,
					data: categories.map((k) => base[k] ?? r.base_pnl ?? 0),
					itemStyle: { color: '#64748b' },
				},
				{
					name: 'Cenário',
					type: 'bar' as const,
					data: categories.map((k) => scenario[k] ?? r.scenario_pnl ?? 0),
					itemStyle: { color: '#f59e0b' },
				},
			],
		};
	});
</script>

{#if !allowed}
	<div class="text-gray-500">Acesso restrito a Risk Manager e Auditor.</div>
{:else}
	<div class="grid grid-cols-[300px_1fr] gap-6">
		<!-- Parameters -->
		<div class="space-y-4">
			<div>
				<label class="block text-xs text-gray-500" for="wif-commodity">Commodity</label>
				<select id="wif-commodity" bind:value={commodity} class="mt-1 w-full rounded border border-gray-300 bg-gray-100 px-2 py-1.5 text-sm text-gray-900">
					<option value="ALUMINIUM">Aluminium</option>
					<option value="COPPER">Copper</option>
					<option value="ZINC">Zinc</option>
				</select>
			</div>
			<div>
				<label class="block text-xs text-gray-500" for="wif-price">Price Shock (%)</label>
				<input id="wif-price" type="number" step="0.5" bind:value={priceShock} class="mt-1 w-full rounded border border-gray-300 bg-gray-100 px-2 py-1.5 text-sm text-gray-900 tabular-nums" />
			</div>
			<div>
				<label class="block text-xs text-gray-500" for="wif-volume">Volume Change (%)</label>
				<input id="wif-volume" type="number" step="0.5" bind:value={volumeChange} class="mt-1 w-full rounded border border-gray-300 bg-gray-100 px-2 py-1.5 text-sm text-gray-900 tabular-nums" />
			</div>
			<button
				onclick={runScenario}
				disabled={isRunning}
				class="w-full rounded bg-amber-400 px-4 py-2 text-sm font-medium text-gray-950 hover:bg-amber-500 disabled:opacity-50"
			>
				{isRunning ? 'Executando...' : 'Executar Cenário'}
			</button>

			{#if result}
				<div class="rounded border border-gray-200 bg-white p-3 space-y-1">
					<div class="text-xs text-gray-500">Impacto</div>
					<div class="text-sm tabular-nums text-gray-900">
						Base: {formatNumber(result.base_pnl ?? result.base_total)}
					</div>
					<div class="text-sm tabular-nums text-amber-700">
						Cenário: {formatNumber(result.scenario_pnl ?? result.scenario_total)}
					</div>
					<div class="text-sm tabular-nums font-medium {(result.delta ?? result.impact ?? 0) >= 0 ? 'text-green-700' : 'text-red-700'}">
						Delta: {formatNumber(result.delta ?? result.impact)}
					</div>
				</div>
			{/if}
		</div>

		<!-- Chart -->
		<div>
			{#if result}
				<EChart options={chartOptions} style="width:100%;height:450px" />
			{:else}
				<div class="flex h-[450px] items-center justify-center text-gray-500">
					Configure os parâmetros e execute o cenário
				</div>
			{/if}
		</div>
	</div>
{/if}
