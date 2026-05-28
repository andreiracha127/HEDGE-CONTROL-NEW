<script lang="ts">
	import { goto } from '$app/navigation';
	import { client } from '$lib/api/client';
	import Card from '$lib/components/alcast/Card.svelte';
	import DecisionDossier from '$lib/components/alcast/DecisionDossier.svelte';
	import InfoTip from '$lib/components/alcast/InfoTip.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
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
	const limitUsd = $derived(Number(creditLimit || 0));
	const limitSummary = $derived(`US$ ${(limitUsd / 1_000_000).toFixed(1)} M`);
	const onboardingReady = $derived(Boolean(name && country && sanctions !== 'blocked'));

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
	<PageHeader
		eyebrow="Counterparty onboarding"
		title="Nova contraparte"
		subtitle="Cadastro inicial com KYC, sanctions screening e limite para revisão de Risco."
		meta={[TYPE_LABEL[type], `País ${country}`, `Limite ${limitSummary}`]}
		actions={[
			{ label: 'Cancelar', variant: 'ghost', href: '/counterparties' },
			{ label: 'Salvar rascunho', variant: 'secondary' },
			{ label: submitting ? 'Criando...' : 'Criar contraparte', icon: 'plus', variant: 'primary', disabled: submitting || !name || !country, onclick: submit },
		]}
	/>

	<div class="detail-grid institutional-counterparty">
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
						<input id="counterparty-contact-name" class="input" placeholder="Nome do contato" bind:value={contactName}/>
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
			<Card noPad>
				<DecisionDossier
					title="Onboarding dossier"
					verdict={onboardingReady ? 'Ready to submit' : 'Missing required fields'}
					verdictKind={onboardingReady ? 'pos' : 'warn'}
					items={[
						{ label: 'Tipo', value: TYPE_LABEL[type] },
						{ label: 'Razão social', value: name || '—' },
						{ label: 'Abreviação', value: shortName || '—' },
						{ label: 'País', value: country },
						{ label: 'Limite', value: limitSummary },
						{ label: 'Risco', value: riskRating },
						{ label: 'Sanctions', value: sanctions },
					]}
				/>
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
