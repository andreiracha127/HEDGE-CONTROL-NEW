<script lang="ts">
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatNumber } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	import EChart from '$lib/components/chart/EChart.svelte';
	import type { IconName } from '$lib/components/alcast/Icon.svelte';
	import type { WhatIfResult } from '$lib/api/types/entities';

	type HeaderAction = {
		label: string;
		icon?: IconName;
		variant?: 'primary' | 'secondary' | 'accent' | 'danger' | 'ghost';
		disabled?: boolean;
		onclick?: () => void | Promise<void>;
	};

	let allowed = $derived(authStore.hasAnyRole('risk_manager', 'auditor'));
	let canRunScenario = $derived(authStore.hasRole('risk_manager'));

	let priceShock = $state(0);
	let volumeChange = $state(0);
	let commodity = $state('ALUMINIUM');
	let result = $state<WhatIfResult | null>(null);
	let isRunning = $state(false);

	const scenarioActions = $derived.by((): HeaderAction[] =>
		canRunScenario
			? [
					{
						label: isRunning ? 'Executando...' : 'Executar cenário',
						icon: 'bolt',
						variant: 'primary',
						disabled: isRunning,
						onclick: runScenario,
					},
				]
			: [],
	);
	const deltaValue = $derived(result ? Number(result.delta ?? result.impact ?? 0) : 0);
	const scenarioMeta = $derived([
		`${commodity}`,
		`Choque de preço ${priceShock >= 0 ? '+' : ''}${priceShock}%`,
		`Volume ${volumeChange >= 0 ? '+' : ''}${volumeChange}%`,
	]);

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

	function applyPreset(kind: 'stress-down' | 'stress-up' | 'volume-cut') {
		if (kind === 'stress-down') {
			priceShock = -7.5;
			volumeChange = 0;
		} else if (kind === 'stress-up') {
			priceShock = 6;
			volumeChange = 0;
		} else {
			priceShock = 0;
			volumeChange = -12;
		}
	}

	let chartOptions = $derived.by(() => {
		const r = result;
		if (!r) return {};
		const base = r.base ?? {};
		const scenario = r.scenario ?? {};
		const categories = Object.keys(base).length > 0 ? Object.keys(base) : ['P&L'];

		return {
			color: ['#1F4A8C', '#E07A45'],
			tooltip: { trigger: 'axis' as const },
			legend: { data: ['Base', 'Cenário'] },
			grid: { left: 48, right: 24, top: 42, bottom: 34 },
			xAxis: { type: 'category' as const, data: categories },
			yAxis: { type: 'value' as const },
			series: [
				{
					name: 'Base',
					type: 'bar' as const,
					data: categories.map((k) => base[k] ?? r.base_pnl ?? 0),
				},
				{
					name: 'Cenário',
					type: 'bar' as const,
					data: categories.map((k) => scenario[k] ?? r.scenario_pnl ?? 0),
				},
			],
		};
	});
</script>

<div class="page">
	<PageHeader
		eyebrow="Análise"
		title="Laboratório de cenários"
		subtitle="Simulações sobre P&L, exposição e volume para decisões de hedge."
		meta={scenarioMeta}
		actions={scenarioActions}
	/>

	{#if !allowed}
		<Card>
			<EmptyState
				icon="lock"
				title="Acesso restrito"
				message="Somente perfis Risk Manager e Auditor podem consultar cenários sensíveis."
			/>
		</Card>
	{:else}
		<div class="scenario-grid">
			<div class="stack gap-4">
				<Card title="Parâmetros" sub="Configure o choque e preserve rastreabilidade da hipótese">
					<div class="field-grid">
						<div class="field" style="grid-column: 1 / -1;">
							<label class="field-label" for="wif-commodity">Commodity</label>
							<select id="wif-commodity" bind:value={commodity} class="select">
								<option value="ALUMINIUM">Alumínio</option>
								<option value="COPPER">Cobre</option>
								<option value="ZINC">Zinco</option>
							</select>
						</div>
						<div class="field">
							<label class="field-label" for="wif-price">Choque de preço (%)</label>
							<input id="wif-price" type="number" step="0.5" bind:value={priceShock} class="input tabular" />
						</div>
						<div class="field">
							<label class="field-label" for="wif-volume">Variação de volume (%)</label>
							<input id="wif-volume" type="number" step="0.5" bind:value={volumeChange} class="input tabular" />
						</div>
					</div>
					<div class="divider"></div>
					<div class="row gap-2">
						<button type="button" class="chip" onclick={() => applyPreset('stress-down')}>Stress baixa</button>
						<button type="button" class="chip" onclick={() => applyPreset('stress-up')}>Stress alta</button>
						<button type="button" class="chip" onclick={() => applyPreset('volume-cut')}>Corte volume</button>
					</div>
				</Card>

				<Card title="Impacto">
					{#if result}
						<dl class="kv">
							<dt>Base</dt><dd class="tabular">{formatNumber(result.base_pnl ?? result.base_total)}</dd>
							<dt>Cenário</dt><dd class="tabular">{formatNumber(result.scenario_pnl ?? result.scenario_total)}</dd>
							<dt>Delta</dt>
							<dd class="tabular strong" style="color: {deltaValue >= 0 ? 'var(--pos)' : 'var(--neg)'};">
								{formatNumber(result.delta ?? result.impact)}
							</dd>
						</dl>
					{:else}
						<EmptyState
							icon="bolt"
							title="Nenhum cenário executado"
							message={canRunScenario ? 'Escolha um preset ou ajuste os parâmetros e execute o cenário.' : 'Auditores podem consultar resultados carregados; a execução de novos cenários é restrita a Risk Manager.'}
						/>
					{/if}
				</Card>
			</div>

			<Card title="Resultado comparativo" sub="Base vs cenário" noPad>
				{#if result}
					<div class="scenario-chart">
						<EChart options={chartOptions} theme="light" style="width:100%;height:420px" />
					</div>
				{:else}
					<EmptyState
						icon="chart"
						title="Aguardando execução"
						message="Execute o cenário para comparar base e simulação."
					/>
				{/if}
			</Card>
		</div>
	{/if}
</div>
