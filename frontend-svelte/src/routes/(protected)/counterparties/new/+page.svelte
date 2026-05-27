<script lang="ts">
	import { goto } from '$app/navigation';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { apiFetch } from '$lib/api/fetch';
	import { authStore } from '$lib/stores/auth.svelte';

	type CounterpartyType = 'broker' | 'bank_br' | 'customer' | 'supplier';

	const allTypeOptions: Array<{ value: CounterpartyType; label: string }> = [
		{ value: 'broker', label: 'Broker' },
		{ value: 'bank_br', label: 'Banco BR' },
		{ value: 'customer', label: 'Cliente' },
		{ value: 'supplier', label: 'Fornecedor' },
	];
	const traderTypeOptions = allTypeOptions.filter((option) =>
		['customer', 'supplier'].includes(option.value),
	);

	let type = $state<CounterpartyType>('broker');
	let name = $state('');
	let shortName = $state('');
	let taxId = $state('');
	let country = $state('');
	let city = $state('');
	let address = $state('');
	let contactName = $state('');
	let contactEmail = $state('');
	let contactPhone = $state('');
	let whatsappPhone = $state('');
	let paymentTermsDays = $state<number | null>(30);
	let creditLimitUsd = $state<number | null>(null);
	let sanctionsStatus = $state('clear');
	let riskRating = $state('medium');
	let notes = $state('');

	let submitting = $state(false);

	const canCreate = $derived(authStore.hasAnyRole('trader', 'risk_manager'));
	const isTraderOnly = $derived(authStore.isTraderOnly());
	const typeOptions = $derived(isTraderOnly ? traderTypeOptions : allTypeOptions);

	$effect(() => {
		if (isTraderOnly && !['customer', 'supplier'].includes(type)) {
			type = 'customer';
		}
	});

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();

		if (!canCreate) {
			notifications.error('Perfil sem permissão para criar contraparte');
			return;
		}
		if (!name.trim()) {
			notifications.warning('Nome é obrigatório');
			return;
		}
		if (!country.trim() || country.trim().length !== 3) {
			notifications.warning('País deve ter exatamente 3 caracteres (ex: BRA, USA)');
			return;
		}

		submitting = true;
		try {
			const body: Record<string, unknown> = {
				type,
				name: name.trim(),
				country: country.trim().toUpperCase(),
				sanctions_status: sanctionsStatus,
				risk_rating: riskRating,
			};

			if (shortName.trim()) body.short_name = shortName.trim();
			if (taxId.trim()) body.tax_id = taxId.trim();
			if (city.trim()) body.city = city.trim();
			if (address.trim()) body.address = address.trim();
			if (contactName.trim()) body.contact_name = contactName.trim();
			if (contactEmail.trim()) body.contact_email = contactEmail.trim();
			if (contactPhone.trim()) body.contact_phone = contactPhone.trim();
			if (whatsappPhone.trim()) body.whatsapp_phone = whatsappPhone.trim();
			if (paymentTermsDays != null && paymentTermsDays > 0) body.payment_terms_days = paymentTermsDays;
			if (creditLimitUsd != null && creditLimitUsd > 0) body.credit_limit_usd = creditLimitUsd;
			if (notes.trim()) body.notes = notes.trim();

			const response = await apiFetch('/counterparties', {
				method: 'POST',
				body: JSON.stringify(body),
			});

			if (!response.ok) {
				const err = await response.json().catch(() => ({ detail: 'Erro desconhecido' }));
				throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
			}

			const cp = await response.json();
			notifications.success('Contraparte criada com sucesso');
			goto(`/counterparties/${cp.id}`);
		} catch (e) {
			notifications.error(e instanceof Error ? e.message : 'Erro ao criar contraparte');
		} finally {
			submitting = false;
		}
	}

	const inputClass =
		'mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200';
	const labelClass = 'block text-sm font-medium text-surface-400';
</script>

<div class="mx-auto max-w-3xl p-6">
	<div class="mb-6 flex items-center gap-3">
		<a href="/counterparties" class="text-surface-500 hover:text-surface-300">← Voltar</a>
		<h1 class="text-lg font-semibold text-surface-200">Nova Contraparte</h1>
	</div>

	{#if !canCreate}
		<div class="rounded border border-surface-700 bg-surface-900 p-4 text-sm text-surface-400">
			Perfil sem permissão para criar contraparte.
		</div>
	{:else}
		<form onsubmit={handleSubmit} class="space-y-6">
			<fieldset class="space-y-4 rounded border border-surface-700 p-4">
				<legend class="px-2 text-sm font-semibold text-surface-300">Identificação</legend>
				<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
					<div>
						<label class={labelClass} for="cp-type">Tipo</label>
						<select id="cp-type" bind:value={type} class={inputClass}>
							{#each typeOptions as option}
								<option value={option.value}>{option.label}</option>
							{/each}
						</select>
					</div>
					<div>
						<label class={labelClass} for="cp-name">Nome <span class="text-danger">*</span></label>
						<input id="cp-name" type="text" bind:value={name} required maxlength="200" class={inputClass} />
					</div>
				</div>
				<div class="grid grid-cols-1 gap-4 md:grid-cols-3">
					<div>
						<label class={labelClass} for="cp-short">Abreviação</label>
						<input id="cp-short" type="text" bind:value={shortName} maxlength="50" class={inputClass} />
					</div>
					<div>
						<label class={labelClass} for="cp-tax">Tax ID</label>
						<input id="cp-tax" type="text" bind:value={taxId} maxlength="50" placeholder="CNPJ / VAT" class="{inputClass} placeholder-surface-600" />
					</div>
					<div>
						<label class={labelClass} for="cp-country">País <span class="text-danger">*</span></label>
						<input id="cp-country" type="text" bind:value={country} required maxlength="3" placeholder="BRA" class="{inputClass} uppercase placeholder-surface-600" />
					</div>
				</div>
				<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
					<div>
						<label class={labelClass} for="cp-city">Cidade</label>
						<input id="cp-city" type="text" bind:value={city} maxlength="100" class={inputClass} />
					</div>
					<div>
						<label class={labelClass} for="cp-address">Endereço</label>
						<input id="cp-address" type="text" bind:value={address} class={inputClass} />
					</div>
				</div>
			</fieldset>

			<fieldset class="space-y-4 rounded border border-surface-700 p-4">
				<legend class="px-2 text-sm font-semibold text-surface-300">Contato</legend>
				<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
					<div>
						<label class={labelClass} for="cp-contact-name">Nome do Contato</label>
						<input id="cp-contact-name" type="text" bind:value={contactName} maxlength="200" class={inputClass} />
					</div>
					<div>
						<label class={labelClass} for="cp-email">Email</label>
						<input id="cp-email" type="email" bind:value={contactEmail} maxlength="200" class={inputClass} />
					</div>
				</div>
				<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
					<div>
						<label class={labelClass} for="cp-phone">Telefone</label>
						<input id="cp-phone" type="tel" bind:value={contactPhone} maxlength="50" class={inputClass} />
					</div>
					<div>
						<label class={labelClass} for="cp-whatsapp">WhatsApp</label>
						<input id="cp-whatsapp" type="tel" bind:value={whatsappPhone} maxlength="50" placeholder="+5511999999999" class="{inputClass} placeholder-surface-600" />
					</div>
				</div>
			</fieldset>

			<fieldset class="space-y-4 rounded border border-surface-700 p-4">
				<legend class="px-2 text-sm font-semibold text-surface-300">Financeiro e Compliance</legend>
				<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
					<div>
						<label class={labelClass} for="cp-payment">Prazo de Pagamento (dias)</label>
						<input id="cp-payment" type="number" step="1" min="1" bind:value={paymentTermsDays} class="{inputClass} tabular-nums" />
					</div>
					<div>
						<label class={labelClass} for="cp-credit">Limite de Crédito (USD)</label>
						<input id="cp-credit" type="number" step="0.01" min="0" bind:value={creditLimitUsd} class="{inputClass} tabular-nums" />
					</div>
					<div>
						<label class={labelClass} for="cp-risk">Classificação de Risco</label>
						<select id="cp-risk" bind:value={riskRating} class={inputClass}>
							<option value="low">Low</option>
							<option value="medium">Medium</option>
							<option value="high">High</option>
						</select>
					</div>
					<div>
						<label class={labelClass} for="cp-sanctions">Sanções</label>
						<select id="cp-sanctions" bind:value={sanctionsStatus} class={inputClass}>
							<option value="clear">Clear</option>
							<option value="flagged">Flagged</option>
							<option value="blocked">Blocked</option>
						</select>
					</div>
				</div>
				<div>
					<label class={labelClass} for="cp-notes">Observações</label>
					<textarea id="cp-notes" bind:value={notes} rows="3" class="{inputClass} placeholder-surface-600"></textarea>
				</div>
			</fieldset>

			<div class="flex items-center gap-3">
				<button
					type="submit"
					disabled={submitting}
					class="rounded bg-accent px-5 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
				>
					{submitting ? 'Criando...' : 'Criar Contraparte'}
				</button>
				<a href="/counterparties" class="rounded border border-surface-700 px-4 py-2 text-sm text-surface-400 hover:bg-surface-800">
					Cancelar
				</a>
			</div>
		</form>
	{/if}
</div>
