<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { goto } from '$app/navigation';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { apiFetch } from '$lib/api/fetch';
	import { authStore } from '$lib/stores/auth.svelte';
	import type { Counterparty } from '$lib/api/types/entities';

	let counterparties = $state<Counterparty[]>([]);
	let isLoading = $state(true);
	let search = $state('');
	let abortController: AbortController;

	async function loadCounterparties(signal?: AbortSignal) {
		isLoading = true;
		try {
			const res = await apiFetch('/counterparties?limit=200', { signal });
			if (res.ok) {
				const data = await res.json();
				counterparties = data.items ?? data;
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			notifications.error('Erro ao carregar contrapartes');
		} finally {
			isLoading = false;
		}
	}

	onMount(() => {
		abortController = new AbortController();
		loadCounterparties(abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });

	let filtered = $derived(
		counterparties.filter((cp) => {
			if (!search) return true;
			const q = search.toLowerCase();
			return cp.name?.toLowerCase().includes(q) || cp.short_name?.toLowerCase().includes(q);
		})
	);
</script>

<div class="p-6">
	<div class="flex items-center justify-between">
		<h1 class="text-lg font-semibold text-surface-200">Contrapartes</h1>
		{#if authStore.hasAnyRole('trader', 'risk_manager')}
			<a href="/counterparties/new" class="rounded bg-accent px-3 py-1.5 text-sm font-medium text-white hover:bg-accent-hover">
				+ Nova Contraparte
			</a>
		{/if}
	</div>

	<input
		type="text"
		bind:value={search}
		placeholder="Buscar..."
		class="mt-4 w-64 rounded border border-surface-700 bg-surface-800 px-3 py-1.5 text-sm text-surface-200 placeholder-surface-600"
	/>

	<div class="mt-4 overflow-x-auto rounded border border-surface-800">
		<table class="w-full text-sm">
			<thead>
				<tr class="border-b border-surface-800 bg-surface-900 text-left text-xs text-surface-500">
					<th class="px-3 py-2">Nome</th>
					<th class="px-3 py-2">Abreviação</th>
					<th class="px-3 py-2">Tipo</th>
					<th class="px-3 py-2">Telefone</th>
					<th class="px-3 py-2">KYC</th>
				</tr>
			</thead>
			<tbody>
				{#each filtered as cp (cp.id)}
					<tr
						onclick={() => goto(`/counterparties/${cp.id}`)}
						class="border-b border-surface-800/50 cursor-pointer hover:bg-surface-800/30"
					>
						<td class="px-3 py-2 text-surface-200">{cp.name}</td>
						<td class="px-3 py-2 text-surface-400">{cp.short_name ?? '—'}</td>
						<td class="px-3 py-2 text-xs text-surface-400">{cp.type ?? '—'}</td>
						<td class="px-3 py-2 font-mono text-xs text-surface-400">{cp.whatsapp_phone ?? cp.phone ?? '—'}</td>
						<td class="px-3 py-2">
							<span class="rounded px-1.5 py-0.5 text-xs {cp.kyc_status === 'approved' ? 'bg-success/20 text-success' : cp.kyc_status === 'pending' ? 'bg-warning/20 text-warning' : 'bg-surface-700 text-surface-400'}">
								{cp.kyc_status ?? '—'}
							</span>
						</td>
					</tr>
				{:else}
					{#if !isLoading}
						<tr><td colspan="5" class="px-3 py-8 text-center text-surface-500">Nenhuma contraparte encontrada</td></tr>
					{/if}
				{/each}
			</tbody>
		</table>
	</div>
</div>
