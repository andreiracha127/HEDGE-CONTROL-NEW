<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { apiFetch } from '$lib/api/fetch';
	import { authStore } from '$lib/stores/auth.svelte';
	import type { Counterparty } from '$lib/api/types/entities';

	const cpId = $derived(page.params.id ?? '');
	let cp = $state<Counterparty | null>(null);
	let isLoading = $state(true);
	let isSubmitting = $state(false);
	let abortController: AbortController;

	async function loadCounterparty(signal?: AbortSignal) {
		isLoading = true;
		try {
			const res = await apiFetch(`/counterparties/${cpId}`, { signal });
			if (res.ok) cp = await res.json();
			else if (res.status === 404) goto('/counterparties');
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			notifications.error('Erro ao carregar contraparte');
		} finally {
			isLoading = false;
		}
	}

	async function updateKycStatus(newStatus: string, selectEl: HTMLSelectElement) {
		const previousStatus = cp?.kyc_status ?? '';
		const reason = window.prompt(
			`Justificativa para alterar status KYC para "${newStatus}" (mínimo 8 caracteres, obrigatório para auditoria):`
		);
		if (reason === null) {
			selectEl.value = previousStatus;
			return;
		}
		const trimmed = reason.trim();
		if (trimmed.length < 8) {
			notifications.error('Justificativa deve ter no mínimo 8 caracteres');
			selectEl.value = previousStatus;
			return;
		}
		isSubmitting = true;
		try {
			const res = await apiFetch(`/counterparties/${cpId}/kyc-status`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ new_status: newStatus, reason: trimmed })
			});
			if (res.ok) {
				cp = await res.json();
				notifications.success('Status KYC atualizado com sucesso');
			} else {
				const err = await res.json();
				notifications.error(err.detail || 'Erro ao atualizar status KYC');
				selectEl.value = previousStatus;
			}
		} catch (e) {
			notifications.error('Erro de conexão ao atualizar status KYC');
			selectEl.value = previousStatus;
		} finally {
			isSubmitting = false;
		}
	}

	onMount(() => {
		abortController = new AbortController();
		loadCounterparty(abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });
</script>

<div class="p-6">
	<a href="/counterparties" class="text-sm text-surface-500 hover:text-surface-300">← Contrapartes</a>

	{#if isLoading}
		<div class="mt-4 text-surface-500">Carregando...</div>
	{:else if cp}
		<h1 class="mt-4 text-lg font-semibold text-surface-200">{cp.name}</h1>

		<div class="mt-4 grid grid-cols-2 gap-4">
			<div class="rounded border border-surface-800 bg-surface-900 p-4 space-y-2">
				<h2 class="text-xs font-semibold uppercase text-surface-500">Informações</h2>
				<div class="text-sm"><span class="text-surface-500">Nome:</span> <span class="text-surface-200">{cp.name}</span></div>
				<div class="text-sm"><span class="text-surface-500">Abreviação:</span> <span class="text-surface-200">{cp.short_name ?? '—'}</span></div>
				<div class="text-sm"><span class="text-surface-500">Tipo:</span> <span class="text-surface-200">{cp.type ?? '—'}</span></div>
				<div class="text-sm"><span class="text-surface-500">WhatsApp:</span> <span class="text-surface-200 font-mono">{cp.whatsapp_phone ?? '—'}</span></div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-4 space-y-2">
				<h2 class="text-xs font-semibold uppercase text-surface-500">Compliance</h2>
				<div class="text-sm"><span class="text-surface-500">KYC:</span>
					<span class="rounded px-1.5 py-0.5 text-xs {cp.kyc_status === 'approved' ? 'bg-success/20 text-success' : 'bg-warning/20 text-warning'}">
						{cp.kyc_status ?? '—'}
					</span>
				</div>
				<div class="text-sm"><span class="text-surface-500">Sanções:</span>
					<span class="text-surface-200">{cp.sanctions_status ?? '—'}</span>
				</div>

				{#if authStore.hasRole('risk_manager')}
					<div class="mt-4 pt-4 border-t border-surface-800 space-y-2">
						<label for="kyc-status-select" class="block text-xs font-semibold uppercase text-surface-500">Alterar Status KYC</label>
						<select
							id="kyc-status-select"
							value={cp.kyc_status}
							disabled={isSubmitting}
							onchange={(e) => {
								const target = e.target as HTMLSelectElement;
								updateKycStatus(target.value, target);
							}}
							class="rounded border border-surface-700 bg-surface-800 px-2 py-1 text-sm text-surface-300 w-full max-w-[200px]"
						>
							<option value="pending">pending</option>
							<option value="approved">approved</option>
							<option value="expired">expired</option>
							<option value="rejected">rejected</option>
						</select>
					</div>
				{/if}
			</div>
		</div>
	{/if}
</div>
