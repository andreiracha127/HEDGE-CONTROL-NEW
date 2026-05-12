<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatDate, formatPrice, formatQuantityMT } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { contractsHedgeListPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import type { Contract } from '$lib/api/types/entities';

	type ListState = 'loading' | 'ready' | 'error' | 'malformed';

	let contracts = $state<Contract[]>([]);
	let isLoading = $state(true);
	let listState = $state<ListState>('loading');
	let listError = $state<string>('');
	let filterStatus = $state('');
	let abortController: AbortController;

	async function loadContracts(signal?: AbortSignal) {
		isLoading = true;
		listState = 'loading';
		try {
			const path = contractsHedgeListPath({
				limit: 100,
				status: filterStatus || undefined,
			});
			const res = await apiFetch(path, { signal });
			if (res.ok) {
				try {
					const data = await res.json();
					contracts = data.items ?? data;
					listState = 'ready';
				} catch {
					contracts = [];
					listState = 'malformed';
					listError = 'Resposta do servidor não pôde ser interpretada';
					notifications.error('Contratos: resposta malformada');
				}
			} else {
				contracts = [];
				listState = 'error';
				listError = await describeApiError(res);
				notifications.error(`Contratos: ${listError}`);
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			contracts = [];
			listState = 'error';
			listError = e instanceof Error ? e.message : 'Erro de conexão';
			notifications.error('Erro ao carregar contratos');
		} finally {
			isLoading = false;
		}
	}

	onMount(() => {
		abortController = new AbortController();
		loadContracts(abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });
</script>

<div class="p-6">
	<h1 class="text-lg font-semibold text-surface-200">Contratos</h1>

	<div class="mt-4 flex gap-3">
		<select
			bind:value={filterStatus}
			onchange={() => loadContracts()}
			class="rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-300"
		>
			<option value="">Todos</option>
			<option value="active">Ativo</option>
			<option value="settled">Liquidado</option>
			<option value="cancelled">Cancelado</option>
		</select>
	</div>

	{#if listState === 'error' || listState === 'malformed'}
		<div class="mt-4 rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
			Erro ao carregar contratos: {listError}
		</div>
	{/if}

	<div class="mt-4 overflow-x-auto rounded border border-surface-800">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-surface-800 bg-surface-900 text-left text-xs text-surface-500">
					<th class="px-3 py-2">Referência</th>
					<th class="px-3 py-2">Commodity</th>
					<th class="px-3 py-2">Qty (MT)</th>
					<th class="px-3 py-2">Preço Fixo</th>
					<th class="px-3 py-2">Contraparte</th>
					<th class="px-3 py-2">Status</th>
					<th class="px-3 py-2">Data</th>
				</tr>
			</thead>
			<tbody>
				{#each contracts as contract (contract.id)}
					<tr
						onclick={() => goto(`/contracts/${contract.id}`)}
						class="border-b border-surface-800/50 cursor-pointer hover:bg-surface-800/30"
					>
						<td class="px-3 py-2 font-mono text-xs text-surface-400">{contract.reference}</td>
						<td class="px-3 py-2 text-surface-300">{contract.commodity}</td>
						<td class="px-3 py-2 tabular-nums text-surface-300">{formatQuantityMT(contract.quantity_mt)}</td>
						<td class="px-3 py-2 tabular-nums text-surface-200">{formatPrice(contract.fixed_price_value, contract.fixed_price_unit ?? undefined)}</td>
						<td class="px-3 py-2 text-surface-400">{contract.counterparty_name ?? contract.counterparty_id ?? '—'}</td>
						<td class="px-3 py-2">
							<span class="rounded px-1.5 py-0.5 text-xs {contract.status === 'active' ? 'bg-success/20 text-success' : contract.status === 'settled' ? 'bg-surface-700 text-surface-400' : 'bg-danger/20 text-danger'}">
								{contract.status ?? '—'}
							</span>
						</td>
						<td class="px-3 py-2 text-xs text-surface-500">{formatDate(contract.trade_date ?? contract.created_at)}</td>
					</tr>
				{:else}
					{#if !isLoading && listState === 'ready'}
						<tr><td colspan="7" class="px-3 py-8 text-center text-surface-500">Nenhum contrato encontrado</td></tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>

	{#if isLoading}
		<div class="mt-4 text-center text-sm text-surface-500">Carregando...</div>
	{/if}
</div>
