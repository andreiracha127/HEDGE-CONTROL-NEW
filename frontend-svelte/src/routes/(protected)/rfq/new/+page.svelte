<script lang="ts">
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Bar from '$lib/components/alcast/Bar.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import InfoTip from '$lib/components/alcast/InfoTip.svelte';
	import DirectionBadge from '$lib/components/alcast/DirectionBadge.svelte';
	import Validation from '$lib/components/alcast/Validation.svelte';
	import LegEditor, { type Leg, type LegSide } from '$lib/components/alcast/LegEditor.svelte';
	import { goto } from '$app/navigation';
	import { client } from '$lib/api/client';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { validateMtQuantity } from '$lib/rfq/quantity';
	let { data } = $props();
	const counterparties = $derived(data.counterparties);
	const orders = $derived(data.orders ?? []);
	let submitting = $state(false);

	function emptyLeg(side: LegSide): Leg {
		return {
			side,
			priceType: '',
			monthName: 'May',
			year: 2026,
			startDate: '',
			endDate: '',
			fixingDate: '',
			fixingDateInherited: false,
			orderType: '',
			orderValidity: '',
			limitPrice: '',
		};
	}

	let company = $state<'Alcast Brasil' | 'Alcast Trading'>('Alcast Brasil');
	let commodity = $state('ALUMINIUM');
	let intent = $state<'GLOBAL_POSITION' | 'COMMERCIAL_HEDGE' | 'SPREAD'>('GLOBAL_POSITION');
	let tradeType = $state<'Swap' | 'Forward'>('Swap');
	let quantityMtRaw = $state<string>('1200');
	let orderId = $state('');
	let buyTradeId = $state('');
	let sellTradeId = $state('');
	let leg1 = $state<Leg>(emptyLeg('buy'));
	let leg2 = $state<Leg>(emptyLeg('sell'));
	let cps = $state<string[]>([]);
	let initializedCounterparties = $state(false);
	let cpSearch = $state('');

	const showLeg2 = $derived(tradeType === 'Swap');
	const legsReady = $derived(legFieldsReady(leg1) && (!showLeg2 || legFieldsReady(leg2)));
	const direction = $derived(leg1.side === 'sell' ? 'SELL' : 'BUY');
	const quantityValidation = $derived(validateMtQuantity(quantityMtRaw));
	const quantityError = $derived(quantityValidation.ok ? null : quantityValidation.reason);
	const qtyNum = $derived(Number(quantityMtRaw) || 0);
	const rfqRoleReady = $derived(authStore.hasRole('risk_manager'));
	const deliveryWindow = $derived(legDeliveryWindow(leg1));
	const datesReady = $derived(deliveryWindow != null);
	const intentReady = $derived(
		intent === 'GLOBAL_POSITION' ||
			(intent === 'COMMERCIAL_HEDGE' && !!orderId) ||
			(intent === 'SPREAD' && !!buyTradeId && !!sellTradeId),
	);
	const selectedCounterparties = $derived(counterparties.filter((cp) => canReceiveRfq(cp) && cps.includes(cp.id)));
	const recipientsReady = $derived(selectedCounterparties.length > 0 && selectedCounterparties.every(canReceiveRfq));
	const cpList = $derived(
		counterparties.filter(
			(cp) =>
				!cpSearch ||
				cp.name.toLowerCase().includes(cpSearch.toLowerCase()) ||
				cp.short.toLowerCase().includes(cpSearch.toLowerCase()),
		),
	);

	function toggleCP(id: string) {
		cps = cps.includes(id) ? cps.filter((c) => c !== id) : [...cps, id];
	}

	function canReceiveRfq(cp: Record<string, any>): boolean {
		return cp.is_active !== false && cp.kyc_status === 'approved' && !!cp.whatsapp_phone;
	}

	function monthNumber(monthName: string): number | null {
		const months = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
		const index = months.indexOf(monthName);
		return index >= 0 ? index + 1 : null;
	}

	function monthWindow(leg: Leg): { start: string; end: string } | null {
		const month = monthNumber(leg.monthName);
		if (!month || !Number.isFinite(leg.year)) return null;
		const start = `${leg.year}-${String(month).padStart(2, '0')}-01`;
		const endDate = new Date(Date.UTC(leg.year, month, 0));
		const end = `${leg.year}-${String(month).padStart(2, '0')}-${String(endDate.getUTCDate()).padStart(2, '0')}`;
		return { start, end };
	}

	function legDeliveryWindow(leg: Leg): { start: string; end: string } | null {
		if (leg.priceType === 'AVG') return monthWindow(leg);
		if (leg.priceType === 'AVGInter' && leg.startDate && leg.endDate) return { start: leg.startDate, end: leg.endDate };
		if ((leg.priceType === 'Fix' || leg.priceType === 'C2R') && leg.fixingDate) return { start: leg.fixingDate, end: leg.fixingDate };
		return null;
	}

	function legFieldsReady(leg: Leg): boolean {
		if (!leg.priceType) return false;
		if (leg.priceType === 'AVG') return monthWindow(leg) != null;
		if (leg.priceType === 'AVGInter') return !!leg.startDate && !!leg.endDate;
		if (leg.priceType === 'C2R') return !!leg.fixingDate;
		if (leg.orderType === 'Limit') return !!leg.limitPrice;
		return true;
	}

	$effect(() => {
		if (!initializedCounterparties && counterparties.length > 0) {
			cps = counterparties.filter(canReceiveRfq).slice(0, 4).map((cp) => cp.id);
			initializedCounterparties = true;
		}
	});

	function orderLabel(order: Record<string, any>): string {
		const ref = order.order_type ?? 'ORDEM';
		const qty = Number(order.qty ?? order.quantity_mt ?? 0).toLocaleString('pt-BR', {
			maximumFractionDigits: 3,
		});
		const window = order.delivery_start ?? order.delivery_date_start ?? order.reference_month ?? 'sem janela';
		return `${ref} · ${qty} MT · ${window}`;
	}

	function applyTemplate(tpl: 'queda' | 'alta' | 'spread') {
		if (tpl === 'queda') {
			leg1 = { ...emptyLeg('buy'),  priceType: 'AVG' };
			leg2 = { ...emptyLeg('sell'), priceType: 'Fix' };
		} else if (tpl === 'alta') {
			leg1 = { ...emptyLeg('sell'), priceType: 'AVG' };
			leg2 = { ...emptyLeg('buy'),  priceType: 'Fix' };
		} else {
			leg1 = { ...emptyLeg('buy'),  priceType: 'AVG' };
			leg2 = { ...emptyLeg('sell'), priceType: 'AVG' };
		}
	}

	function setLeg1Side(side: LegSide) {
		const opp: LegSide = side === 'buy' ? 'sell' : 'buy';
		leg1 = { ...leg1, side };
		leg2 = { ...leg2, side: opp };
	}

	function setLeg2Side(side: LegSide) {
		const opp: LegSide = side === 'buy' ? 'sell' : 'buy';
		leg2 = { ...leg2, side };
		leg1 = { ...leg1, side: opp };
	}

	function previewLeg(leg: Leg) {
		const priceType = leg.priceType as Exclude<Leg['priceType'], ''>;
		const orderType = leg.orderType ? (leg.orderType as Exclude<Leg['orderType'], ''>) : null;
		return {
			side: leg.side,
			price_type: priceType,
			quantity_mt: quantityValidation.ok ? quantityValidation.canonical : quantityMtRaw,
			month_name: priceType === 'AVG' ? leg.monthName : null,
			year: priceType === 'AVG' ? leg.year : null,
			start_date: priceType === 'AVGInter' ? leg.startDate || null : null,
			end_date: priceType === 'AVGInter' ? leg.endDate || null : null,
			fixing_date: priceType === 'Fix' || priceType === 'C2R' ? leg.fixingDate || null : null,
			order_type: orderType,
			order_validity: leg.orderValidity || null,
			order_limit_price: leg.limitPrice || null,
		};
	}

	function buildPreviewPayload() {
		return {
			trade_type: tradeType,
			leg1: previewLeg(leg1),
			leg2: showLeg2 ? previewLeg(leg2) : null,
			sync_ppt: false,
			company_header: company,
			company_label_for_payoff: company,
			channel_type: 'BROKER_LME',
		};
	}

	function intentError(): string {
		if (intent === 'COMMERCIAL_HEDGE') return 'Selecione a ordem comercial vinculada antes de enviar a RFQ.';
		if (intent === 'SPREAD') return 'Informe Buy Trade ID e Sell Trade ID antes de enviar a RFQ de spread.';
		return 'Complete as referências da intenção antes de enviar a RFQ.';
	}

	async function requestPreviewText() {
		const { data: preview, error: previewError } = await client.POST('/rfqs/preview-text', {
			body: buildPreviewPayload(),
		});
		if (previewError || !preview) {
			notifications.error(`Falha ao gerar texto da RFQ: ${previewError?.detail ?? 'erro desconhecido'}`);
			return null;
		}
		return preview;
	}

	async function previewText() {
		if (!quantityValidation.ok) {
			notifications.error(quantityValidation.reason);
			return;
		}
		if (!legsReady) {
			notifications.error('Configure todas as pernas obrigatórias antes de pré-visualizar a RFQ.');
			return;
		}
		if (!datesReady) {
			notifications.error('Informe a janela de entrega antes de pré-visualizar a RFQ.');
			return;
		}
		const preview = await requestPreviewText();
		if (preview) notifications.success('Texto da RFQ gerado a partir das pernas configuradas.');
	}

	async function submit() {
		const actorSub = authStore.userSub;
		if (!actorSub) {
			notifications.error('Sessão sem sub autenticado; refaça login antes de enviar RFQ.');
			return;
		}
		if (!quantityValidation.ok) {
			notifications.error(quantityValidation.reason);
			return;
		}
		if (!legsReady) {
			notifications.error('Configure todas as pernas obrigatórias antes de enviar a RFQ.');
			return;
		}
		if (!datesReady) {
			notifications.error('Informe a janela de entrega antes de enviar a RFQ.');
			return;
		}
		if (selectedCounterparties.length === 0) {
			notifications.error('Selecione pelo menos uma contraparte válida.');
			return;
		}
		if (!recipientsReady) {
			notifications.error('Selecione apenas contrapartes com KYC aprovado e WhatsApp cadastrado.');
			return;
		}
		if (!rfqRoleReady) {
			notifications.error('Criação de RFQ requer perfil risk_manager.');
			return;
		}
		if (!intentReady) {
			notifications.error(intentError());
			return;
		}
		submitting = true;
		const preview = await requestPreviewText();
		if (!preview) {
			submitting = false;
			return;
		}
		const deliveryStart = deliveryWindow?.start ?? '';
		const deliveryEnd = deliveryWindow?.end ?? deliveryStart;
		const { data: created, error: apiError } = await client.POST('/rfqs', {
			body: {
				commodity,
				direction,
				intent,
				quantity_mt: quantityValidation.canonical,
				delivery_window_start: deliveryStart,
				delivery_window_end: deliveryEnd,
				text_en: preview.text_en ?? preview.text,
				text_pt: preview.text_pt ?? preview.text,
				invitations: selectedCounterparties.map((cp) => ({
					counterparty_id: cp.id,
					channel: 'whatsapp',
				})),
				...(intent === 'COMMERCIAL_HEDGE' && orderId ? { order_id: orderId } : {}),
				...(intent === 'SPREAD' && buyTradeId && sellTradeId ? { buy_trade_id: buyTradeId, sell_trade_id: sellTradeId } : {}),
			},
		});
		submitting = false;
		if (apiError) {
			notifications.error(`Falha ao enviar RFQ: ${apiError.detail ?? 'erro desconhecido'}`);
			return;
		}
		notifications.success(`RFQ ${created?.rfq_number ?? created?.id} enviada a ${selectedCounterparties.length} contraparte(s)`);
		await goto(`/rfq/${created?.id}`);
	}

	const INTENT_LABEL: Record<typeof intent, string> = {
		GLOBAL_POSITION:   'Posição global',
		COMMERCIAL_HEDGE:  'Hedge comercial',
		SPREAD:            'Spread',
	};
</script>

<div class="page">
	<div class="page-head">
		<div>
			<div class="row gap-2" style="margin-bottom: 4px;">
				<a href="/rfq" class="btn btn-link"><Icon name="arrowLeft"/> RFQ</a>
				<span style="color: var(--muted);">/</span>
				<span style="font-size: 12px; color: var(--muted);">Nova solicitação</span>
			</div>
			<h1 class="page-title">Nova RFQ</h1>
			<div class="page-sub">
				{company} · {commodity} · {tradeType} · <DirectionBadge dir={direction}/>
			</div>
		</div>
		<div class="page-actions">
			<a href="/rfq" class="btn btn-ghost">Cancelar</a>
			<button type="button" data-testid="rfq-preview-button" class="btn btn-secondary" onclick={previewText} disabled={!quantityValidation.ok || !legsReady || !datesReady}>Pré-visualizar texto</button>
			<button type="button" class="btn btn-secondary">Salvar rascunho</button>
			<button
				type="button"
				class="btn btn-primary"
				onclick={submit}
				data-testid="rfq-submit-button"
				disabled={submitting || !quantityValidation.ok || selectedCounterparties.length === 0 || !legsReady || !datesReady || !intentReady || !recipientsReady || !rfqRoleReady}
			>
				<Icon name="bolt"/>{submitting ? 'Enviando...' : `Enviar a ${selectedCounterparties.length} contraparte${selectedCounterparties.length === 1 ? '' : 's'}`}
			</button>
		</div>
	</div>

	<div class="detail-grid">
		<div class="stack gap-4">
			<Card title="1. Trade setup" sub="Empresa, commodity, intenção e quantidade">
				<div class="field-grid">
					<div class="field" style="grid-column: 1 / -1;">
						<div class="field-label">Empresa <span class="req">*</span></div>
						<div class="radio-group">
							<button type="button" class:active={company === 'Alcast Brasil'} onclick={() => (company = 'Alcast Brasil')}>Alcast Brasil</button>
							<button type="button" class:active={company === 'Alcast Trading'} onclick={() => (company = 'Alcast Trading')}>Alcast Trading</button>
						</div>
					</div>

					<div class="field">
						<label class="field-label" for="rfq-commodity">Commodity <span class="req">*</span></label>
						<select id="rfq-commodity" class="select" bind:value={commodity}>
							<option value="ALUMINIUM">ALUMINIUM</option>
						</select>
					</div>

					<div class="field">
						<label class="field-label">
							Intenção <span class="req">*</span>
							<InfoTip width={280}>
								<strong>Posição global:</strong> tomada de posição direcional · sujeita a limites de risco.<br/><br/>
								<strong>Hedge comercial:</strong> vinculada a uma ordem (PO/SO) · reduz exposição da janela.<br/><br/>
								<strong>Spread:</strong> diferença entre duas RFQs (compra × venda).
							</InfoTip>
						</label>
						<select class="select" bind:value={intent}>
							<option value="GLOBAL_POSITION">Posição global</option>
							<option value="COMMERCIAL_HEDGE">Hedge comercial</option>
							<option value="SPREAD">Spread</option>
						</select>
					</div>

					<div class="field">
						<div class="field-label">Tipo de trade <span class="req">*</span></div>
						<div class="radio-group">
							<button type="button" class:active={tradeType === 'Swap'} onclick={() => (tradeType = 'Swap')}>Swap (2 legs)</button>
							<button type="button" class:active={tradeType === 'Forward'} onclick={() => (tradeType = 'Forward')}>Forward (1 leg)</button>
						</div>
					</div>

					<div class="field">
						<label class="field-label">
							Quantidade <span class="req">*</span>
							<InfoTip>Lote LME mínimo: 25 MT · padrão: 250 MT.</InfoTip>
						</label>
						<div class="input-suffix">
							<input
								class="input"
								type="number"
								step="0.001"
								aria-invalid={quantityError != null}
								bind:value={quantityMtRaw}
							/>
							<span class="suffix">MT</span>
						</div>
						{#if quantityError}
							<div data-testid="rfq-quantity-error" class="badge neg" style="margin-top: 6px;">{quantityError}</div>
						{/if}
					</div>

					{#if intent === 'COMMERCIAL_HEDGE'}
						<div class="field" style="grid-column: 1 / -1;">
							<label class="field-label" for="rfq-order-id">Ordem vinculada (PO / SO) <span class="req">*</span></label>
							<select id="rfq-order-id" class="select" bind:value={orderId}>
								<option value="">— Selecione uma ordem comercial —</option>
								{#each orders as order (order.id)}
									<option value={order.id}>{orderLabel(order)}</option>
								{/each}
							</select>
						</div>
					{/if}

					{#if intent === 'SPREAD'}
						<div class="field">
							<label class="field-label" for="rfq-buy-trade-id">Buy Trade ID <span class="req">*</span></label>
							<input id="rfq-buy-trade-id" class="input mono" placeholder="UUID da RFQ de compra" bind:value={buyTradeId}/>
						</div>
						<div class="field">
							<label class="field-label" for="rfq-sell-trade-id">Sell Trade ID <span class="req">*</span></label>
							<input id="rfq-sell-trade-id" class="input mono" placeholder="UUID da RFQ de venda" bind:value={sellTradeId}/>
						</div>
					{/if}
				</div>
			</Card>

			<Card
				title="2. Trade 1"
				sub={showLeg2 ? 'Swap · configure duas pernas (compra fixa × venda variável ou inverso)' : 'Forward · configure uma única perna'}
			>
				{#snippet actions()}
					<div class="row gap-2">
						<span style="font-size: 11px; color: var(--muted);">Templates:</span>
						<button type="button" class="chip" style="color: var(--neg); border-color: var(--neg-soft);" onclick={() => applyTemplate('queda')}>↓ Proteção de queda</button>
						<button type="button" class="chip" style="color: var(--pos); border-color: var(--pos-soft);" onclick={() => applyTemplate('alta')}>↑ Proteção de alta</button>
						<button type="button" class="chip" style="color: var(--info); border-color: var(--info-soft);" onclick={() => applyTemplate('spread')}>⇄ Spread</button>
					</div>
				{/snippet}

				<LegEditor bind:leg={leg1} label="Leg 1" onSideChange={setLeg1Side}/>
				{#if showLeg2}
					<div class="divider"></div>
					<LegEditor bind:leg={leg2} label="Leg 2" onSideChange={setLeg2Side}/>
				{/if}
			</Card>

			<Card
				title="3. Contrapartes"
				sub={`${selectedCounterparties.length} de ${counterparties.length} selecionadas · RFQ será enviada simultaneamente`}
			>
				{#snippet actions()}
					<div class="input-suffix" style="width: 220px;">
						<input class="input" placeholder="Buscar contraparte…" style="height: 28px;" bind:value={cpSearch}/>
					</div>
				{/snippet}

				<div style="display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px;">
					{#each cpList as cp (cp.id)}
						{@const on = cps.includes(cp.id)}
						{@const usePct = (cp.used / cp.limit) * 100}
						{@const disabled = !canReceiveRfq(cp)}
						<button
							type="button"
							{disabled}
							onclick={() => toggleCP(cp.id)}
							class="card"
							style="padding: 12px; text-align: left; cursor: {disabled ? 'not-allowed' : 'pointer'}; border-color: {on ? 'var(--navy)' : 'var(--line-strong)'}; opacity: {disabled ? 0.5 : 1}; background: {on ? '#F4F7FC' : '#fff'};"
						>
							<div class="row gap-3">
								<span class="check" class:on><span class="box"></span></span>
								<div style="flex: 1;">
									<div class="row gap-2" style="margin-bottom: 2px;">
										<span style="font-weight: 500; font-size: 13px;">{cp.name}</span>
										<Badge kind="neutral">{cp.rating}</Badge>
										{#if disabled}<Badge kind="warn" dot>{cp.is_active === false || cp.kyc_status !== 'approved' ? 'Em análise' : 'Sem WhatsApp'}</Badge>{/if}
									</div>
									<div class="row gap-2" style="font-size: 11px; color: var(--muted);">
										<span>Limite</span>
										<Bar pct={usePct} kind={usePct > 80 ? 'neg' : usePct > 60 ? 'warn' : 'pos'}/>
										<span class="tabular">US$ {(cp.used / 1_000_000).toFixed(1)} / {(cp.limit / 1_000_000).toFixed(1)} M</span>
									</div>
								</div>
							</div>
						</button>
					{/each}
				</div>
			</Card>

			<Card title="4. Observações" sub="Visível apenas internamente">
				<textarea class="textarea" placeholder="Notas internas, justificativa, link com aprovação…"></textarea>
			</Card>
		</div>

		<div class="stack gap-4" style="position: sticky; top: 72px; align-self: start;">
			<Card title="Resumo">
				<dl class="kv">
					<dt>Empresa</dt><dd>{company}</dd>
					<dt>Commodity</dt><dd>{commodity}</dd>
					<dt>Intenção</dt><dd>{INTENT_LABEL[intent]}</dd>
					<dt>Trade</dt><dd>{tradeType}</dd>
					<dt>Quantidade</dt><dd class="tabular">{qtyNum.toLocaleString('pt-BR')} MT</dd>
					<dt>Direção</dt><dd><DirectionBadge dir={direction}/></dd>
					{#if leg1.priceType}
						<dt>Leg 1</dt><dd>{leg1.side === 'buy' ? 'Compra' : 'Venda'} · {leg1.priceType}</dd>
					{/if}
					{#if showLeg2 && leg2.priceType}
						<dt>Leg 2</dt><dd>{leg2.side === 'buy' ? 'Compra' : 'Venda'} · {leg2.priceType}</dd>
					{/if}
				</dl>
			</Card>

			<Card title="Pré-validações">
				<div class="stack gap-2">
					<Validation ok={!!commodity} label="Commodity definida"/>
					<Validation
						ok={qtyNum >= 25}
						label={qtyNum >= 25 ? 'Quantidade ≥ lote mínimo (25 MT)' : 'Quantidade abaixo do lote mínimo'}
					/>
					<Validation
						ok={!!leg1.priceType}
						label={leg1.priceType ? `Leg 1 configurada (${leg1.priceType})` : 'Leg 1 sem price type'}
					/>
					{#if showLeg2}
						<Validation
							ok={!!leg2.priceType}
							label={leg2.priceType ? `Leg 2 configurada (${leg2.priceType})` : 'Leg 2 sem price type'}
						/>
					{/if}
					<Validation
						ok={selectedCounterparties.length > 0}
						label={selectedCounterparties.length > 0 ? `${selectedCounterparties.length} contraparte(s) selecionada(s)` : 'Sem contrapartes selecionadas'}
					/>
					<Validation
						ok={intent !== 'COMMERCIAL_HEDGE' || !!orderId}
						label={intent === 'COMMERCIAL_HEDGE' ? (orderId ? 'Ordem comercial vinculada' : 'Sem ordem vinculada') : 'Intenção sem ordem'}
					/>
					{#if intent === 'SPREAD'}
						<Validation
							ok={!!buyTradeId && !!sellTradeId}
							label={buyTradeId && sellTradeId ? 'Trades do spread vinculados' : 'Spread sem buy/sell trade'}
						/>
					{/if}
				</div>
			</Card>

			<Card title="Governança">
				<dl class="kv">
					<dt>Alçada</dt><dd>Trader · até US$ 5 M</dd>
					<dt>Aprovação</dt><dd><Badge kind="pos" dot>Dentro da alçada</Badge></dd>
					<dt>Política IFRS</dt><dd>Hedge accounting</dd>
					<dt>Mark-to-market</dt><dd>Diário · LME 11:30 BST</dd>
				</dl>
			</Card>
		</div>
	</div>
</div>
