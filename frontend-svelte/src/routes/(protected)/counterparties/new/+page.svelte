<script lang="ts">
	import { goto } from '$app/navigation';
	import { client } from '$lib/api/client';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import InfoTip from '$lib/components/alcast/InfoTip.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';

	let type = $state<'broker' | 'bank_br' | 'customer' | 'supplier'>('supplier');
	let name = $state('');
	let shortName = $state('');
	let taxId = $state('');
	let country = $state('BRA');
	let city = $state('');
	let address = $state('');
	let contactName = $state('');
	let contactEmail = $state('');
	let contactPhone = $state('');
	let whatsapp = $state('');
	let paymentTerms = $state('30');
	let creditLimit = $state('5000000');
	let riskRating = $state<'low' | 'medium' | 'high'>('medium');
	let sanctions = $state<'clear' | 'flagged' | 'blocked'>('clear');
	let notes = $state('');
	let submitting = $state(false);

	const TYPE_LABEL: Record<string, string> = {
		broker:   'Broker',
		bank_br:  'Banco BR',
		customer: 'Cliente',
		supplier: 'Fornecedor',
	};

	async function submit() {
		submitting = true;
		const { data: created, error: apiError } = await client.POST('/counterparties', {
			body: {
				type,
				name,
				short_name: shortName || null,
				tax_id: taxId || null,
				country,
				city: city || null,
				address: address || null,
				contact_name: contactName || null,
				contact_email: contactEmail || null,
				contact_phone: contactPhone || null,
				whatsapp_phone: whatsapp || null,
				payment_terms_days: Number(paymentTerms || 30),
				credit_limit_usd: Number(creditLimit || 0),
				risk_rating: riskRating,
				sanctions_status: sanctions,
				notes: notes || null,
				is_active: true,
			},
		});
		submitting = false;
		if (apiError) {
			notifications.error(`Falha ao criar contraparte: ${apiError.detail ?? 'erro desconhecido'}`);
			return;
		}
		notifications.success(`Contraparte ${created?.name ?? name} criada`);
		await goto(`/counterparties/${created?.id}`);
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<div class="row gap-2" style="margin-bottom: 4px;">
				<a href="/counterparties" class="btn btn-link"><Icon name="arrowLeft"/> Contrapartes</a>
				<span style="color: var(--muted);">/</span>
				<span style="font-size: 12px; color: var(--muted);">Nova contraparte</span>
			</div>
			<h1 class="page-title">Nova contraparte</h1>
			<div class="page-sub">Cadastro inicial — KYC, sanctions screening e limite serão revisados pelo time de Risco</div>
		</div>
		<div class="page-actions">
			<a href="/counterparties" class="btn btn-ghost">Cancelar</a>
			<button type="button" class="btn btn-secondary">Salvar rascunho</button>
			<button type="button" class="btn btn-primary" onclick={submit} disabled={submitting || !name || !country}>
				<Icon name="plus"/>{submitting ? 'Criando...' : 'Criar contraparte'}
			</button>
		</div>
	</div>

	<div class="detail-grid">
		<div class="stack gap-4">
			<Card title="1. Identificação" sub="Dados cadastrais e jurídicos">
				<div class="field-grid">
					<div class="field">
						<label class="field-label" for="counterparty-type">Tipo <span class="req">*</span></label>
						<select id="counterparty-type" class="select" bind:value={type}>
							<option value="broker">Broker / corretora</option>
							<option value="bank_br">Banco BR</option>
							<option value="customer">Cliente</option>
							<option value="supplier">Fornecedor</option>
						</select>
					</div>
					<div class="field">
						<label class="field-label" for="counterparty-name">Razão social <span class="req">*</span></label>
						<input id="counterparty-name" class="input" placeholder="Itaú BBA S.A." maxlength="200" bind:value={name}/>
					</div>
					<div class="field">
						<label class="field-label">
							Abreviação
							<InfoTip>Sigla curta usada em tabelas e badges (até 6 caracteres).</InfoTip>
						</label>
						<input class="input" placeholder="ITAU" maxlength="50" bind:value={shortName}/>
					</div>
					<div class="field">
						<label class="field-label" for="counterparty-tax-id">Tax ID</label>
						<input id="counterparty-tax-id" class="input mono" placeholder="CNPJ ou VAT internacional" bind:value={taxId}/>
					</div>
					<div class="field">
						<label class="field-label">
							País <span class="req">*</span>
							<InfoTip>ISO 3166-1 alfa-3 · 3 letras maiúsculas (BRA, USA, GBR, DEU…).</InfoTip>
						</label>
						<input
							class="input"
							placeholder="BRA"
							maxlength="3"
							style="text-transform: uppercase;"
							value={country}
							oninput={(e) => (country = e.currentTarget.value.toUpperCase())}
						/>
					</div>
					<div class="field">
						<label class="field-label" for="counterparty-city">Cidade</label>
						<input id="counterparty-city" class="input" placeholder="São Paulo" bind:value={city}/>
					</div>
					<div class="field" style="grid-column: 1 / -1;">
						<label class="field-label" for="counterparty-address">Endereço</label>
						<input id="counterparty-address" class="input" placeholder="Av. Brigadeiro Faria Lima, 3500 — 04538-132" bind:value={address}/>
					</div>
				</div>
			</Card>

			<Card title="2. Contato">
				<div class="field-grid">
					<div class="field">
						<label class="field-label" for="counterparty-contact-name">Nome do contato</label>
						<input id="counterparty-contact-name" class="input" placeholder="Maria Santos" bind:value={contactName}/>
					</div>
					<div class="field">
						<label class="field-label" for="counterparty-contact-email">Email</label>
						<input id="counterparty-contact-email" class="input" type="email" placeholder="msantos@contraparte.com.br" bind:value={contactEmail}/>
					</div>
					<div class="field">
						<label class="field-label" for="counterparty-contact-phone">Telefone</label>
						<input id="counterparty-contact-phone" class="input" placeholder="+55 11 3000-0000" bind:value={contactPhone}/>
					</div>
					<div class="field">
						<label class="field-label">
							WhatsApp
							<InfoTip>Usado para envio de RFQ via mensageria.</InfoTip>
						</label>
						<input class="input" placeholder="+5511999999999" bind:value={whatsapp}/>
					</div>
				</div>
			</Card>

			<Card title="3. Financeiro & compliance" sub="Limites de crédito, classificação e screening de sanções">
				<div class="field-grid">
					<div class="field">
						<label class="field-label" for="counterparty-payment-terms">Prazo de pagamento</label>
						<div class="input-suffix">
							<input id="counterparty-payment-terms" class="input" type="number" min="1" bind:value={paymentTerms}/>
							<span class="suffix">dias</span>
						</div>
					</div>
					<div class="field">
						<label class="field-label">
							Limite de crédito
							<InfoTip>Aprovação adicional necessária acima de US$ 10 M.</InfoTip>
						</label>
						<div class="input-suffix">
							<input class="input" type="number" bind:value={creditLimit}/>
							<span class="suffix">USD</span>
						</div>
					</div>
					<div class="field">
						<div class="field-label">Classificação de risco</div>
						<div class="radio-group">
							<button type="button" class:active={riskRating === 'low'} onclick={() => (riskRating = 'low')}>Baixo</button>
							<button type="button" class:active={riskRating === 'medium'} onclick={() => (riskRating = 'medium')}>Médio</button>
							<button type="button" class:active={riskRating === 'high'} onclick={() => (riskRating = 'high')}>Alto</button>
						</div>
					</div>
					<div class="field">
						<label class="field-label">
							Sanctions screening
							<InfoTip>Resultado da varredura OFAC / Bacen / EU sanctions.</InfoTip>
						</label>
						<div class="radio-group">
							<button type="button" class:active={sanctions === 'clear'} onclick={() => (sanctions = 'clear')}>Clear</button>
							<button type="button" class:active={sanctions === 'flagged'} onclick={() => (sanctions = 'flagged')}>Flagged</button>
							<button type="button" class:active={sanctions === 'blocked'} onclick={() => (sanctions = 'blocked')}>Blocked</button>
						</div>
					</div>
					<div class="field" style="grid-column: 1 / -1;">
						<label class="field-label" for="counterparty-notes">Observações</label>
						<textarea id="counterparty-notes" class="textarea" placeholder="Histórico, restrições, instruções específicas para a mesa…" bind:value={notes}></textarea>
					</div>
				</div>
			</Card>
		</div>

		<div class="stack gap-4" style="position: sticky; top: 72px; align-self: start;">
			<Card title="Resumo">
				<dl class="kv">
					<dt>Tipo</dt><dd>{TYPE_LABEL[type]}</dd>
					<dt>Razão social</dt><dd>{name || '—'}</dd>
					<dt>Abreviação</dt><dd>{shortName || '—'}</dd>
					<dt>País</dt><dd>{country}</dd>
					<dt>Limite</dt><dd class="tabular">US$ {(Number(creditLimit || 0) / 1_000_000).toFixed(1)} M</dd>
					<dt>Risco</dt>
					<dd>
						{#if riskRating === 'low'}
							<Badge kind="pos" dot>Baixo</Badge>
						{:else if riskRating === 'high'}
							<Badge kind="neg" dot>Alto</Badge>
						{:else}
							<Badge kind="warn" dot>Médio</Badge>
						{/if}
					</dd>
					<dt>Sanctions</dt>
					<dd>
						{#if sanctions === 'clear'}
							<Badge kind="pos" dot>Clear</Badge>
						{:else if sanctions === 'blocked'}
							<Badge kind="neg" dot>Blocked</Badge>
						{:else}
							<Badge kind="warn" dot>Flagged</Badge>
						{/if}
					</dd>
				</dl>
			</Card>

			<Card title="Próximos passos">
				<div class="stack gap-2" style="font-size: 12.5px;">
					<div class="row gap-2">
						<span style="width: 18px; height: 18px; border-radius: 50%; background: var(--orange); color: #fff; display: grid; place-items: center; font-size: 10px; font-weight: 600;">1</span>
						Time de Risco revisa KYC (até 2 dias úteis)
					</div>
					<div class="row gap-2">
						<span style="width: 18px; height: 18px; border-radius: 50%; background: var(--line-strong); color: #fff; display: grid; place-items: center; font-size: 10px; font-weight: 600;">2</span>
						Aprovação do limite no comitê
					</div>
					<div class="row gap-2">
						<span style="width: 18px; height: 18px; border-radius: 50%; background: var(--line-strong); color: #fff; display: grid; place-items: center; font-size: 10px; font-weight: 600;">3</span>
						Habilitação para operar RFQs
					</div>
				</div>
			</Card>
		</div>
	</div>
</div>
