<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { apiFetch } from '$lib/api/fetch';
	import { validateMtQuantity } from '$lib/rfq/quantity';

	// ─── Form State ─────────────────────────────────────────────────────
	let commodity = $state('ALUMINIUM');
	// J-A6-11: MT quantity is a three-decimal Decimal on the backend
	// (`MTQuantity`, `MT_NUMERIC_SCALE = 3`). Keep the raw literal the
	// user typed as a string so neither the bind nor the JSON payload
	// routes it through `Number()` and silently truncates digits.
	let quantityMtRaw = $state<string>('');
	let direction = $state('BUY');
	let intent = $state('COMMERCIAL_HEDGE');
	let deliveryStart = $state('');
	let deliveryEnd = $state('');

	// Spread fields
	let buyTradeId = $state('');
	let sellTradeId = $state('');

	// Counterparties
	let counterparties = $state<any[]>([]);
	let selectedCounterpartyIds = $state<string[]>([]);
	let counterpartySearch = $state('');
	let loadingCounterparties = $state(false);

	// Preview
	let previewText = $state('');
	let showPreview = $state(false);

	let submitting = $state(false);

	let quantityValidation = $derived(validateMtQuantity(quantityMtRaw));
	let quantityError = $derived(
		quantityValidation.ok ? null : quantityValidation.reason,
	);

	// ─── Fetch counterparties ───────────────────────────────────────────
	async function fetchCounterparties() {
		loadingCounterparties = true;
		try {
			const response = await apiFetch('/counterparties?limit=200');
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			const data = await response.json();
			counterparties = data.items ?? data;
		} catch {
			notifications.error('Erro ao carregar contrapartes');
		} finally {
			loadingCounterparties = false;
		}
	}

	onMount(() => {
		fetchCounterparties();
	});

	let filteredCounterparties = $derived(
		counterparties.filter((cp) => {
			if (!counterpartySearch) return true;
			const q = counterpartySearch.toLowerCase();
			return (
				cp.name?.toLowerCase().includes(q) ||
				cp.short_name?.toLowerCase().includes(q)
			);
		})
	);

	function toggleCounterparty(id: string) {
		if (selectedCounterpartyIds.includes(id)) {
			selectedCounterpartyIds = selectedCounterpartyIds.filter((x) => x !== id);
		} else {
			selectedCounterpartyIds = [...selectedCounterpartyIds, id];
		}
	}

	// ─── Preview ────────────────────────────────────────────────────────
	async function loadPreview() {
		// J-A6-11: never generate a preview for a quantity that exceeds the
		// three-decimal MT scale. The same canonical decimal string used
		// here is the one that will be submitted on create — preview and
		// submit must share precision behaviour.
		if (!quantityValidation.ok) {
			notifications.warning(`Quantidade inválida: ${quantityValidation.reason}`);
			return;
		}
		try {
			const response = await apiFetch('/rfqs/preview-text', {
				method: 'POST',
				body: JSON.stringify({
					commodity,
					quantity_mt: quantityValidation.canonical,
					direction,
					intent,
					delivery_window_start: deliveryStart,
					delivery_window_end: deliveryEnd,
				}),
			});
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			const data = await response.json();
			previewText = data.text_pt || data.text_en || '';
			showPreview = true;
		} catch {
			notifications.warning('Não foi possível gerar preview do texto');
		}
	}

	// ─── Submit ─────────────────────────────────────────────────────────
	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();
		// J-A6-11: gate submission on the same MT-precision rule the
		// preview applies, before any payload construction.
		if (!quantityValidation.ok) {
			notifications.warning(`Quantidade inválida: ${quantityValidation.reason}`);
			return;
		}
		if (selectedCounterpartyIds.length === 0) {
			notifications.warning('Selecione pelo menos uma contraparte');
			return;
		}

		// J-A6-04: never fabricate actor identity. The RFQ create payload's
		// user_id must be the authenticated JWT subject (immutable claim).
		// If no sub is available, hard-fail visibly instead of sending a
		// display name or literal 'trader' fallback.
		const actorSub = authStore.userSub;
		if (!actorSub) {
			notifications.error(
				'Sessão sem identidade verificável (sub). Faça login novamente para criar RFQs.',
			);
			return;
		}

		submitting = true;
		try {
			const body: Record<string, unknown> = {
				commodity,
				quantity_mt: quantityValidation.canonical,
				direction,
				intent,
				delivery_window_start: deliveryStart,
				delivery_window_end: deliveryEnd,
				counterparty_ids: selectedCounterpartyIds,
				user_id: actorSub,
			};
			if (intent === 'SPREAD') {
				if (buyTradeId) body.buy_trade_id = buyTradeId;
				if (sellTradeId) body.sell_trade_id = sellTradeId;
			}

			const response = await apiFetch('/rfqs', {
				method: 'POST',
				body: JSON.stringify(body),
			});
			if (!response.ok) {
				const err = await response.json().catch(() => ({ detail: 'Erro desconhecido' }));
				throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
			}
			const rfq = await response.json();
			notifications.success('RFQ criada com sucesso');
			goto(`/rfq/${rfq.id}`);
		} catch (e) {
			notifications.error(e instanceof Error ? e.message : 'Erro ao criar RFQ');
		} finally {
			submitting = false;
		}
	}

	const commodities = ['ALUMINIUM', 'COPPER', 'ZINC', 'LEAD', 'NICKEL', 'TIN'];
</script>

<div class="mx-auto max-w-3xl p-6">
	<div class="flex items-center gap-3">
		<a href="/rfq" class="text-surface-500 hover:text-surface-300">← Voltar</a>
		<h1 class="text-lg font-semibold text-surface-200">Nova RFQ</h1>
	</div>

	<form onsubmit={handleSubmit} class="mt-6 space-y-6">
		<!-- Grid: commodity, direction, qty, intent -->
		<div class="grid grid-cols-2 gap-4">
			<div>
				<label class="block text-sm font-medium text-surface-400" for="commodity">Commodity</label>
				<select
					id="commodity"
					bind:value={commodity}
					class="mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200"
				>
					{#each commodities as c}
						<option value={c}>{c}</option>
					{/each}
				</select>
			</div>

			<div>
				<label class="block text-sm font-medium text-surface-400" for="direction">Direção</label>
				<select
					id="direction"
					bind:value={direction}
					class="mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200"
				>
					<option value="BUY">Compra</option>
					<option value="SELL">Venda</option>
				</select>
			</div>

			<div>
				<label class="block text-sm font-medium text-surface-400" for="qty">Quantidade (MT)</label>
				<!--
					J-A6-11: `step` and `min` on a `type="number"` input
					are a UX convenience only — browsers expose spinner
					steps from them but do *not* enforce precision on what
					is committed to `.value`. The authoritative gate
					against >3-decimal MT input is the
					`validateMtQuantity` derivation below, which the
					Preview/Submit buttons read through
					`quantityValidation.ok` and which renders the inline
					error on the field. Do not rely on the HTML5 step/min
					constraints for institutional precision.
				-->
				<input
					id="qty"
					type="number"
					step="0.001"
					min="0"
					value={quantityMtRaw}
					oninput={(e) => (quantityMtRaw = e.currentTarget.value)}
					required
					aria-invalid={quantityError != null}
					aria-describedby={quantityError ? 'qty-error' : undefined}
					data-testid="rfq-quantity-input"
					class="mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200 tabular-nums"
				/>
				{#if quantityMtRaw !== '' && quantityError}
					<p
						id="qty-error"
						class="mt-1 text-xs text-danger"
						data-testid="rfq-quantity-error"
					>
						{quantityError}
					</p>
				{/if}
			</div>

			<div>
				<label class="block text-sm font-medium text-surface-400" for="intent">Intenção</label>
				<select
					id="intent"
					bind:value={intent}
					class="mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200"
				>
					<option value="COMMERCIAL_HEDGE">Hedge Comercial</option>
					<option value="GLOBAL_POSITION">Posição Global</option>
					<option value="SPREAD">Spread</option>
				</select>
			</div>

			<div>
				<label class="block text-sm font-medium text-surface-400" for="delivery-start">Settlement Início</label>
				<input
					id="delivery-start"
					type="date"
					bind:value={deliveryStart}
					required
					class="mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200"
				/>
			</div>

			<div>
				<label class="block text-sm font-medium text-surface-400" for="delivery-end">Settlement Fim</label>
				<input
					id="delivery-end"
					type="date"
					bind:value={deliveryEnd}
					required
					class="mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200"
				/>
			</div>
		</div>

		<!-- Spread-specific fields -->
		{#if intent === 'SPREAD'}
			<div class="grid grid-cols-2 gap-4 rounded border border-surface-700 bg-surface-900/50 p-4">
				<div>
					<label class="block text-sm font-medium text-surface-400" for="buy-trade">Buy Trade ID</label>
					<input id="buy-trade" type="text" bind:value={buyTradeId} class="mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200 font-mono" />
				</div>
				<div>
					<label class="block text-sm font-medium text-surface-400" for="sell-trade">Sell Trade ID</label>
					<input id="sell-trade" type="text" bind:value={sellTradeId} class="mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200 font-mono" />
				</div>
			</div>
		{/if}

		<!-- Counterparty selection -->
		<div>
			<label for="counterparty-search" class="block text-sm font-medium text-surface-400">
				Contrapartes ({selectedCounterpartyIds.length} selecionadas)
			</label>
			<input
				id="counterparty-search"
				type="text"
				bind:value={counterpartySearch}
				placeholder="Buscar contraparte..."
				class="mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200 placeholder-surface-600"
			/>
			<div class="mt-2 max-h-48 overflow-y-auto rounded border border-surface-800 bg-surface-900">
				{#if loadingCounterparties}
					<div class="px-3 py-2 text-sm text-surface-500">Carregando...</div>
				{:else}
					{#each filteredCounterparties as cp (cp.id)}
						<label class="flex items-center gap-2 px-3 py-1.5 hover:bg-surface-800 cursor-pointer text-sm">
							<input
								type="checkbox"
								checked={selectedCounterpartyIds.includes(cp.id)}
								onchange={() => toggleCounterparty(cp.id)}
								class="accent-accent"
							/>
							<span class="text-surface-300">{cp.name}</span>
							{#if cp.short_name}
								<span class="text-xs text-surface-500">({cp.short_name})</span>
							{/if}
						</label>
					{:else}
						<div class="px-3 py-2 text-sm text-surface-500">Nenhuma contraparte encontrada</div>
					{/each}
				{/if}
			</div>
		</div>

		<!-- Preview + Submit -->
		<div class="flex items-center gap-3">
			<button
				type="button"
				onclick={loadPreview}
				disabled={!quantityValidation.ok}
				data-testid="rfq-preview-button"
				class="rounded border border-surface-700 px-4 py-2 text-sm text-surface-400 hover:bg-surface-800 disabled:opacity-50"
			>
				Preview WhatsApp
			</button>
			<button
				type="submit"
				disabled={submitting || !quantityValidation.ok}
				data-testid="rfq-submit-button"
				class="rounded bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
			>
				{submitting ? 'Criando...' : 'Criar RFQ'}
			</button>
		</div>

		{#if showPreview && previewText}
			<div class="rounded border border-surface-700 bg-surface-900 p-4">
				<div class="text-xs font-medium text-surface-500 mb-2">Preview da mensagem WhatsApp</div>
				<pre class="whitespace-pre-wrap text-sm text-surface-300">{previewText}</pre>
			</div>
		{/if}
	</form>
</div>
