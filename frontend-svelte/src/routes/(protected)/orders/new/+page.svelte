<script lang="ts">
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import DecisionDossier from '$lib/components/alcast/DecisionDossier.svelte';
	import InfoTip from '$lib/components/alcast/InfoTip.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	import Validation from '$lib/components/alcast/Validation.svelte';
	import { goto } from '$app/navigation';
	import { client } from '$lib/api/client';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { safeBusinessText } from '$lib/alcast/presentation';
	let { data } = $props();
	const counterparties = $derived(data.counterparties);
	let submitting = $state(false);

	let orderType = $state<'PO' | 'SO'>('PO');
	let commodity = $state('ALUMINIUM');
	let qty = $state('1500');
	let priceType = $state<'fixed' | 'variable'>('fixed');
	let pricingConv = $state<'AVG' | 'AVGInter' | 'C2R'>('AVG');
	let price = $state('2631.00');
	let currency = $state('USD');
	let cp = $state('');
	let delivery = $state('2026-06-30');
	let avgReferenceMonth = $state('2026-06');
	let observationStart = $state('2026-06-01');
	let observationEnd = $state('2026-06-30');
	let fixingDate = $state('2026-06-30');
	let reference = $state('');
	let notes = $state('');

	const isPO = $derived(orderType === 'PO');
	// A PO (compra) sources from a supplier; an SO (venda) from a customer. Filter the
	// selectable partners by order kind so a wrong-domain entity can't be picked
	// (orders FK -> commercial_partners, gated by kind on the backend).
	const eligibleCounterparties = $derived(
		counterparties.filter((c) => c.kind === (isPO ? 'supplier' : 'customer')),
	);
	// Clear a selection that is no longer valid after switching order kind.
	$effect(() => {
		if (cp && !eligibleCounterparties.some((c) => c.id === cp)) {
			cp = '';
		}
	});
	const qtyNum = $derived(Number(qty) || 0);
	const priceNum = $derived(Number(price) || 0);
	const notional = $derived(qtyNum * priceNum);
	const hasPrice = $derived(price.trim() !== '' && Number.isFinite(Number(price)));
	const variablePricingPayload = $derived.by(() => {
		if (priceType !== 'variable') return {};
		if (pricingConv === 'AVG') return { reference_month: avgReferenceMonth };
		if (pricingConv === 'AVGInter') {
			return {
				observation_date_start: observationStart,
				observation_date_end: observationEnd,
			};
		}
		return { fixing_date: fixingDate };
	});
	const pricingWindowReady = $derived.by(() => {
		if (priceType !== 'variable') return true;
		if (pricingConv === 'AVG') return !!avgReferenceMonth;
		if (pricingConv === 'AVGInter') return !!observationStart && !!observationEnd;
		return !!fixingDate;
	});
	const formReady = $derived(!!reference && !!cp && qtyNum > 0 && hasPrice && pricingWindowReady);
	const deliveryLabel = $derived.by(() => {
		if (!delivery) return '—';
		try {
			return new Date(delivery).toLocaleDateString('pt-BR', { month: 'short', year: '2-digit' });
		} catch {
			return delivery;
		}
	});

	const submittedNotes = $derived.by(() => {
		const referenceLine = `Referencia ERP/SAP: ${reference}`;
		const trimmedNotes = notes.trim();
		return trimmedNotes ? `${referenceLine}\n${trimmedNotes}` : referenceLine;
	});
	const selectedCounterpartyLabel = $derived(
		counterparties.find((item) => item.id === cp)?.name ?? '—',
	);

	async function submit() {
		submitting = true;
		const selectedCounterparty = counterparties.find((item) => item.id === cp);
		const orderPath = orderType === 'PO' ? '/orders/purchase' : '/orders/sales';
		const { data: created, error: apiError } = await client.POST(orderPath, {
			body: {
				commodity,
				quantity_mt: qty,
				price_type: priceType,
				external_reference: reference,
				...(priceType === 'fixed'
					? { avg_entry_price: price }
					: { avg_entry_price: price, pricing_convention: pricingConv, ...variablePricingPayload }),
				currency,
				counterparty_id: selectedCounterparty?.id ?? null,
				counterparty_name: selectedCounterparty?.name ?? cp,
				delivery_date_start: delivery,
				delivery_date_end: delivery,
				notes: submittedNotes,
			},
		});
		submitting = false;
		if (apiError) {
			notifications.error(`Falha ao criar ordem: ${safeBusinessText(apiError.detail, 'não foi possível criar a ordem')}`);
			return;
		}
		notifications.success('Ordem criada');
		await goto(`/orders/${created?.id}`);
	}
</script>

<div class="page">
	<PageHeader
		eyebrow="Registro comercial"
		title="Nova ordem comercial"
		subtitle={`Registra a fonte da exposição: ${isPO ? 'compra de matéria-prima (PO)' : 'venda de produto final (SO)'}.`}
		meta={[orderType, commodity, `${qtyNum.toLocaleString('pt-BR')} MT`, `${currency} ${notional.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}`]}
		actions={[
			{ label: 'Cancelar', variant: 'ghost', href: '/orders' },
			{ label: 'Salvar rascunho', variant: 'secondary' },
			{ label: submitting ? 'Criando...' : 'Criar ordem', icon: 'shieldCheck', variant: 'primary', disabled: submitting || !formReady, onclick: submit },
		]}
	/>

	<div class="detail-grid institutional-order-entry">
		<div class="stack gap-4">
			<Card>
				{#snippet title()}
					1. Tipo de ordem
					<InfoTip>Define se a ordem gera <strong>exposição ativa</strong> (venda futura) ou <strong>passiva</strong> (compra futura).</InfoTip>
				{/snippet}
				<div class="grid-2">
					<button
						type="button"
						class="card"
						style="padding: 14px; text-align: left; cursor: pointer; border-color: {orderType === 'PO' ? 'var(--navy)' : 'var(--line-strong)'}; background: {orderType === 'PO' ? 'var(--surface-sel)' : 'var(--surface)'};"
						onclick={() => (orderType = 'PO')}
					>
						<div class="row gap-2">
					<Badge kind="info" dot>PO · Compra</Badge>
							<InfoTip>Compra de matéria-prima — gera <strong>exposição passiva</strong>. Hedge se faz com <strong>compra</strong> de derivativo.</InfoTip>
							{#if orderType === 'PO'}<span style="margin-left: auto; color: var(--navy);">●</span>{/if}
						</div>
					</button>
					<button
						type="button"
						class="card"
						style="padding: 14px; text-align: left; cursor: pointer; border-color: {orderType === 'SO' ? 'var(--navy)' : 'var(--line-strong)'}; background: {orderType === 'SO' ? 'var(--surface-sel)' : 'var(--surface)'};"
						onclick={() => (orderType = 'SO')}
					>
						<div class="row gap-2">
							<Badge kind="pos" dot>SO · Venda</Badge>
							<InfoTip>Venda de produto final — gera <strong>exposição ativa</strong>. Hedge se faz com <strong>venda</strong> de derivativo.</InfoTip>
							{#if orderType === 'SO'}<span style="margin-left: auto; color: var(--navy);">●</span>{/if}
						</div>
					</button>
				</div>
			</Card>

			<Card title="2. Identificação">
				<div class="field-grid">
					<div class="field">
						<label class="field-label" for="order-reference">
							Número de referência (PO/SO) <span class="req">*</span>
							<InfoTip>Espelho do ERP/SAP. Usado para vincular RFQs de hedge a esta ordem comercial.</InfoTip>
						</label>
						<input id="order-reference" class="input mono" placeholder={isPO ? 'PO-2026-1185' : 'SO-2026-0943'} bind:value={reference}/>
					</div>
					<div class="field">
						<label class="field-label" for="order-counterparty">Contraparte <span class="req">*</span></label>
						<select id="order-counterparty" class="select" bind:value={cp}>
							<option value="">— Selecione —</option>
							{#each eligibleCounterparties as c (c.id)}
								<option value={c.id}>{c.name} ({c.short})</option>
							{/each}
						</select>
					</div>
				</div>
			</Card>

			<Card title="3. Volume e precificação">
				<div class="field-grid">
					<div class="field">
						<label class="field-label" for="order-commodity">Commodity <span class="req">*</span></label>
						<select id="order-commodity" class="select" bind:value={commodity}>
							<option value="ALUMINIUM">ALUMINIUM</option>
						</select>
					</div>
					<div class="field">
						<label class="field-label" for="order-quantity">Quantidade <span class="req">*</span></label>
						<div class="input-suffix">
							<input id="order-quantity" class="input" type="number" step="0.001" bind:value={qty}/>
							<span class="suffix">MT</span>
						</div>
					</div>

					<div class="field" style="grid-column: 1 / -1;">
						<span class="field-label" id="order-price-type-label">
							Tipo de preço <span class="req">*</span>
							<InfoTip width={280}>
								<strong>Fixo:</strong> preço definido em contrato — sem exposição a preço, mas pode haver exposição cambial.<br/><br/>
								<strong>Variável:</strong> atrelado ao LME — gera exposição à commodity até a liquidação.
							</InfoTip>
						</span>
						<div class="radio-group" role="group" aria-labelledby="order-price-type-label">
							<button type="button" class:active={priceType === 'fixed'} onclick={() => (priceType = 'fixed')}>Preço fixo</button>
							<button type="button" class:active={priceType === 'variable'} onclick={() => (priceType = 'variable')}>Preço variável (indexado)</button>
						</div>
					</div>

					<div class="field">
						<label class="field-label" for="order-pricing-convention">
							Convenção de precificação <span class="req">*</span>
							<InfoTip width={260}>Define qual cotação LME será usada na liquidação variável (Official, Cash, 3-Month, ou médias mensais).</InfoTip>
						</label>
						<select id="order-pricing-convention" class="select" bind:value={pricingConv}>
							<option value="AVG">LME Average (mês de entrega)</option>
							<option value="AVGInter">LME Average entre datas</option>
							<option value="C2R">C2R / fixing date</option>
						</select>
					</div>

					{#if priceType === 'variable' && pricingConv === 'AVG'}
						<div class="field">
							<label class="field-label" for="order-reference-month">Mês de referência <span class="req">*</span></label>
							<input id="order-reference-month" class="input" type="month" bind:value={avgReferenceMonth}/>
						</div>
					{:else if priceType === 'variable' && pricingConv === 'AVGInter'}
						<div class="field">
							<label class="field-label" for="order-observation-start">Início da observação <span class="req">*</span></label>
							<input id="order-observation-start" class="input" type="date" bind:value={observationStart}/>
						</div>
						<div class="field">
							<label class="field-label" for="order-observation-end">Fim da observação <span class="req">*</span></label>
							<input id="order-observation-end" class="input" type="date" bind:value={observationEnd}/>
						</div>
					{:else if priceType === 'variable' && pricingConv === 'C2R'}
						<div class="field">
							<label class="field-label" for="order-fixing-date">Data de fixing <span class="req">*</span></label>
							<input id="order-fixing-date" class="input" type="date" bind:value={fixingDate}/>
						</div>
					{/if}

					<div class="field">
						<label class="field-label" for="order-price">{priceType === 'fixed' ? 'Preço fixo' : 'Prêmio / desconto vs LME'} <span class="req">*</span></label>
						<div class="input-suffix">
							<input id="order-price" class="input" type="number" step="0.01" bind:value={price}/>
							<span class="suffix">{currency}/MT</span>
						</div>
					</div>

					<div class="field">
						<label class="field-label" for="order-currency">Moeda <span class="req">*</span></label>
						<select id="order-currency" class="select" bind:value={currency}>
							<option value="USD">USD</option>
							<option value="BRL">BRL</option>
							<option value="EUR">EUR</option>
						</select>
					</div>

					<div class="field">
						<label class="field-label" for="order-delivery">
							Data de entrega <span class="req">*</span>
							<InfoTip>Define a janela de exposição.</InfoTip>
						</label>
						<input id="order-delivery" class="input" type="date" bind:value={delivery}/>
					</div>
				</div>
			</Card>

			<Card title="4. Observações" sub="Visível apenas internamente">
				<textarea class="textarea" placeholder="Notas internas, link com contrato, condições especiais…" bind:value={notes}></textarea>
			</Card>
		</div>

		<div class="stack gap-4" style="position: sticky; top: 72px; align-self: start;">
			<Card noPad>
				<DecisionDossier
					title="Dossiê da ordem"
					verdict={reference && cp && qtyNum > 0 ? 'Pronta para criação' : 'Campos obrigatórios pendentes'}
					verdictKind={reference && cp && qtyNum > 0 ? 'pos' : 'warn'}
					items={[
						{ label: 'Tipo', value: isPO ? 'PO · Compra' : 'SO · Venda' },
						{ label: 'Referência', value: reference || '—' },
						{ label: 'Contraparte', value: selectedCounterpartyLabel },
						{ label: 'Commodity', value: commodity },
						{ label: 'Quantidade', value: `${qtyNum.toLocaleString('pt-BR')} MT` },
						{ label: 'Preço', value: `${priceNum.toLocaleString('pt-BR', { minimumFractionDigits: 2 })} ${currency}/MT` },
						{ label: 'Notional', value: `${currency} ${notional.toLocaleString('pt-BR', { maximumFractionDigits: 0 })}` },
						{ label: 'Entrega', value: delivery.split('-').reverse().join('/') },
					]}
				/>
			</Card>

			<Card title="Impacto em exposições">
				<dl class="kv">
					<dt>Janela</dt><dd>{deliveryLabel}</dd>
					<dt>+ Esta ordem</dt>
					<dd class="tabular" style="color: {isPO ? 'var(--info)' : 'var(--pos)'};">
						+{qtyNum.toLocaleString('pt-BR')} MT {isPO ? '(passiva)' : '(ativa)'}
					</dd>
					<dt>Referência</dt><dd class="mono">{reference || '—'}</dd>
					<dt>Próximo passo</dt><dd>{priceType === 'variable' ? 'Criar RFQ de hedge após registro' : 'Monitorar liquidação'}</dd>
				</dl>
				{#if priceType === 'variable'}
					<div class="row gap-2" style="margin-top: 8px; font-size: 11.5px;">
						<Badge kind="warn" dot>Sugestão</Badge>
						<span style="color: var(--muted);">Criar RFQ de hedge para esta ordem após o registro</span>
					</div>
				{/if}
			</Card>

			<Card title="Pré-validações">
				<div class="stack gap-2">
					<Validation ok={!!reference} label={reference ? 'Referência informada' : 'Referência obrigatória'}/>
					<Validation ok={!!cp} label={cp ? 'Contraparte selecionada' : 'Sem contraparte'}/>
					<Validation ok={qtyNum > 0} label="Quantidade válida"/>
					<Validation ok={hasPrice} label={hasPrice ? 'Preço informado' : 'Preço obrigatório'}/>
					<Validation ok={pricingWindowReady} label={pricingWindowReady ? 'Janela de precificação informada' : 'Janela de precificação obrigatória'}/>
				</div>
			</Card>
		</div>
	</div>
</div>
