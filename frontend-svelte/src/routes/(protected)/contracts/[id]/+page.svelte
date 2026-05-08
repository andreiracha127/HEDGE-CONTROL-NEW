<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatDate, formatPrice, formatQuantityMT } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import type { Contract } from '$lib/api/types/entities';
	const contractId = $derived(page.params.id ?? '');
	let contract = $state<Contract | null>(null);
	let isLoading = $state(true);
	let isTransitioning = $state(false);
	let confirmAction = $state<string | null>(null);
	let abortController: AbortController;

	const VALID_TRANSITIONS: Record<string, string[]> = {
		active: ['partially_settled', 'settled', 'cancelled'],
		partially_settled: ['settled', 'cancelled'],
	};

	const STATUS_LABELS: Record<string, string> = {
		active: 'Ativo',
		partially_settled: 'Parc. Liquidado',
		settled: 'Liquidado',
		cancelled: 'Cancelado',
	};

	const TRANSITION_CONFIG: Record<string, { label: string; style: string; confirm: string }> = {
		partially_settled: {
			label: 'Liquidar Parcial',
			style: 'bg-warning/20 text-warning hover:bg-warning/30',
			confirm: 'Confirma liquidação parcial deste contrato?',
		},
		settled: {
			label: 'Liquidar',
			style: 'bg-success/20 text-success hover:bg-success/30',
			confirm: 'Confirma liquidação total deste contrato?',
		},
		cancelled: {
			label: 'Cancelar',
			style: 'bg-danger/20 text-danger hover:bg-danger/30',
			confirm: 'Confirma cancelamento deste contrato? Esta ação não pode ser revertida.',
		},
	};

	const allowedTransitions = $derived<string[]>(
		contract?.status ? VALID_TRANSITIONS[contract.status] ?? [] : [],
	);
	const isTrader = $derived(authStore.hasRole('trader'));

	async function loadContract(signal?: AbortSignal) {
		isLoading = true;
		try {
			const res = await apiFetch(`/contracts/${contractId}`, { signal });
			if (res.ok) contract = await res.json();
			else if (res.status === 404) goto('/contracts');
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			notifications.error('Erro ao carregar contrato');
		} finally {
			isLoading = false;
		}
	}

	async function transitionStatus(targetStatus: string) {
		confirmAction = null;
		isTransitioning = true;
		try {
			const res = await apiFetch(`/contracts/${contractId}/status`, {
				method: 'PATCH',
				body: JSON.stringify({ status: targetStatus }),
			});
			if (res.ok) {
				contract = await res.json();
				notifications.success(`Status alterado para ${STATUS_LABELS[targetStatus] ?? targetStatus}`);
			} else if (res.status === 409) {
				const data = await res.json().catch(() => null);
				notifications.error(data?.detail ?? 'Transição de status não permitida');
				await loadContract();
			} else {
				notifications.error('Erro ao alterar status');
			}
		} catch {
			notifications.error('Erro de conexão ao alterar status');
		} finally {
			isTransitioning = false;
		}
	}

	function statusBadgeClass(status: string): string {
		switch (status) {
			case 'active':
				return 'bg-success/20 text-success';
			case 'partially_settled':
				return 'bg-warning/20 text-warning';
			case 'settled':
				return 'bg-surface-700 text-surface-400';
			case 'cancelled':
				return 'bg-danger/20 text-danger';
			default:
				return 'bg-surface-700 text-surface-400';
		}
	}

	onMount(() => {
		abortController = new AbortController();
		loadContract(abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });
</script>

<div class="p-6">
	<a href="/contracts" class="text-sm text-surface-500 hover:text-surface-300">← Contratos</a>

	{#if isLoading}
		<div class="mt-4 text-surface-500">Carregando...</div>
	{:else if contract}
		<div class="mt-4 flex items-center gap-3">
			<h1 class="text-lg font-semibold text-surface-200">{contract.reference}</h1>
			<span class="rounded px-1.5 py-0.5 text-xs {statusBadgeClass(contract.status ?? '')}">
				{STATUS_LABELS[contract.status ?? ''] ?? contract.status}
			</span>
		</div>

		{#if isTrader && allowedTransitions.length > 0}
			<div class="mt-3 flex gap-2">
				{#each allowedTransitions as target}
					{@const config = TRANSITION_CONFIG[target]}
					{#if config}
						<button
							onclick={() => (confirmAction = target)}
							disabled={isTransitioning}
							class="rounded px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 {config.style}"
						>
							{config.label}
						</button>
					{/if}
				{/each}
			</div>
		{/if}

		{#if confirmAction}
			{@const config = TRANSITION_CONFIG[confirmAction]}
			<div class="mt-3 rounded border border-surface-700 bg-surface-800 p-3">
				<p class="text-sm text-surface-300">{config?.confirm}</p>
				<div class="mt-2 flex gap-2">
					<button
						onclick={() => transitionStatus(confirmAction!)}
						disabled={isTransitioning}
						class="rounded px-3 py-1 text-xs font-medium bg-surface-600 text-surface-200 hover:bg-surface-500 disabled:opacity-50"
					>
						{isTransitioning ? 'Processando...' : 'Confirmar'}
					</button>
					<button
						onclick={() => (confirmAction = null)}
						disabled={isTransitioning}
						class="rounded px-3 py-1 text-xs text-surface-400 hover:text-surface-300"
					>
						Cancelar
					</button>
				</div>
			</div>
		{/if}

		<div class="mt-4 grid grid-cols-2 gap-4">
			<div class="rounded border border-surface-800 bg-surface-900 p-4 space-y-2">
				<h2 class="text-xs font-semibold uppercase text-surface-500">Detalhes</h2>
				<div class="text-sm"><span class="text-surface-500">Commodity:</span> <span class="text-surface-200">{contract.commodity}</span></div>
				<div class="text-sm"><span class="text-surface-500">Quantidade:</span> <span class="text-surface-200 tabular-nums">{formatQuantityMT(contract.quantity_mt)} MT</span></div>
				<div class="text-sm"><span class="text-surface-500">Preço Fixo:</span> <span class="text-surface-200 tabular-nums">{formatPrice(contract.fixed_price_value, contract.fixed_price_unit ?? undefined)}</span></div>
				<div class="text-sm"><span class="text-surface-500">Classificação:</span> <span class="text-surface-200">{contract.classification ?? '—'}</span></div>
				<div class="text-sm"><span class="text-surface-500">Trade Date:</span> <span class="text-surface-200">{formatDate(contract.trade_date)}</span></div>
			</div>

			<div class="rounded border border-surface-800 bg-surface-900 p-4 space-y-2">
				<h2 class="text-xs font-semibold uppercase text-surface-500">Legs</h2>
				<div class="text-sm"><span class="text-surface-500">Fixed Leg:</span> <span class="text-surface-200">{contract.fixed_leg_side ?? '—'}</span></div>
				<div class="text-sm"><span class="text-surface-500">Variable Leg:</span> <span class="text-surface-200">{contract.variable_leg_side ?? '—'}</span></div>
				<div class="text-sm"><span class="text-surface-500">Float Convention:</span> <span class="text-surface-200">{contract.float_pricing_convention ?? '—'}</span></div>
				<div class="text-sm"><span class="text-surface-500">Source:</span> <span class="text-surface-200">{contract.source_type ?? '—'}</span></div>
			</div>
		</div>
	{/if}
</div>
