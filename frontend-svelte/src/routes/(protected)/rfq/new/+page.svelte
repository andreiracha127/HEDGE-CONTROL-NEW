<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { apiFetch } from '$lib/api/fetch';
	import { validateMtQuantity } from '$lib/rfq/quantity';

	type LegKey = 'leg1' | 'leg2';
	type LegSide = 'buy' | 'sell';
	type LegPriceType = '' | 'AVG' | 'AVGInter' | 'Fix' | 'C2R';

	interface LegState {
		side: LegSide;
		priceType: LegPriceType;
		monthName: string;
		year: number;
		startDate: string;
		endDate: string;
		fixingDate: string;
		fixingDateInherited: boolean;
		orderType: string;
		orderValidity: string;
		limitPrice: string;
	}

	interface TradeState {
		title: string;
		leg1: LegState;
		leg2: LegState;
	}

	const months = [
		'January',
		'February',
		'March',
		'April',
		'May',
		'June',
		'July',
		'August',
		'September',
		'October',
		'November',
		'December',
	];

	const lmeHolidays = new Set([
		'2025-01-01',
		'2025-04-18',
		'2025-04-21',
		'2025-05-05',
		'2025-05-26',
		'2025-08-25',
		'2025-12-25',
		'2025-12-26',
		'2026-01-01',
		'2026-04-03',
		'2026-04-06',
		'2026-05-04',
		'2026-05-25',
		'2026-08-31',
		'2026-12-25',
		'2026-12-28',
		'2027-01-01',
		'2027-03-26',
		'2027-03-29',
		'2027-05-03',
		'2027-05-31',
		'2027-08-30',
		'2027-12-27',
		'2027-12-28',
		'2028-01-03',
		'2028-04-14',
		'2028-04-17',
		'2028-05-01',
		'2028-05-29',
		'2028-08-28',
		'2028-12-25',
		'2028-12-26',
		'2029-01-01',
		'2029-03-30',
		'2029-04-02',
		'2029-05-07',
		'2029-05-28',
		'2029-08-27',
		'2029-12-25',
		'2029-12-26',
		'2030-01-01',
		'2030-04-19',
		'2030-04-22',
		'2030-05-06',
		'2030-05-27',
		'2030-08-26',
		'2030-12-25',
		'2030-12-26',
		'2031-01-01',
		'2031-04-11',
		'2031-04-14',
		'2031-05-05',
		'2031-05-26',
		'2031-08-25',
		'2031-12-25',
		'2031-12-26',
		'2032-01-01',
		'2032-03-26',
		'2032-03-29',
		'2032-05-03',
		'2032-05-31',
		'2032-08-30',
		'2032-12-27',
		'2032-12-28',
		'2033-01-03',
		'2033-04-15',
		'2033-04-18',
		'2033-05-02',
		'2033-05-30',
		'2033-08-29',
		'2033-12-26',
		'2033-12-27',
		'2034-01-02',
		'2034-04-07',
		'2034-04-10',
		'2034-05-01',
		'2034-05-29',
		'2034-08-28',
		'2034-12-25',
		'2034-12-26',
		'2035-01-01',
		'2035-03-23',
		'2035-03-26',
		'2035-05-07',
		'2035-05-28',
		'2035-08-27',
		'2035-12-25',
		'2035-12-26',
	]);

	function dateInputValue(date: Date): string {
		const year = date.getFullYear();
		const month = String(date.getMonth() + 1).padStart(2, '0');
		const day = String(date.getDate()).padStart(2, '0');
		return `${year}-${month}-${day}`;
	}

	const today = new Date();
	const todayIso = dateInputValue(today);
	const currentYear = today.getFullYear();
	const currentMonthIndex = today.getMonth();
	const lmeHolidayCoverageEndYear = 2035;
	const lastSelectableYear = Math.min(currentYear + 4, lmeHolidayCoverageEndYear);
	const years = Array.from({ length: lastSelectableYear - currentYear + 1 }, (_, i) => currentYear + i);
	const commodities = ['ALUMINIUM'];

	function emptyLeg(side: LegSide = 'buy'): LegState {
		return {
			side,
			priceType: '',
			monthName: months[currentMonthIndex],
			year: currentYear,
			startDate: '',
			endDate: '',
			fixingDate: '',
			fixingDateInherited: false,
			orderType: '',
			orderValidity: '',
			limitPrice: '',
		};
	}

	function emptyTrade(index: number): TradeState {
		return {
			title: `Trade ${index + 1}`,
			leg1: emptyLeg('buy'),
			leg2: emptyLeg('sell'),
		};
	}

	let companyIndex = $state(0);
	let commodity = $state('ALUMINIUM');
	let intent = $state('GLOBAL_POSITION');
	let tradeType = $state<'Swap' | 'Forward'>('Swap');
	let quantityMtRaw = $state<string>('');

	let orderId = $state('');
	let orders = $state<any[]>([]);
	let exposureInfo = $state('');

	let trades = $state<TradeState[]>([emptyTrade(0)]);

	let counterparties = $state<any[]>([]);
	let selectedCounterpartyIds = $state<string[]>([]);
	let counterpartySearch = $state('');
	let loadingCounterparties = $state(false);

	let previewTextEn = $state('');
	let previewTextPt = $state('');
	let showPreview = $state(false);

	let buyTradeId = $state('');
	let sellTradeId = $state('');

	let submitting = $state(false);

	const companyLabel = $derived(companyIndex === 0 ? 'Alcast Brasil' : 'Alcast Trading');
	const showLeg2 = $derived(tradeType === 'Swap');
	let quantityValidation = $derived(validateMtQuantity(quantityMtRaw));
	let quantityError = $derived(quantityValidation.ok ? null : quantityValidation.reason);

	let filteredCounterparties = $derived(
		counterparties.filter((cp) => {
			if (!counterpartySearch) return true;
			const q = counterpartySearch.toLowerCase();
			return cp.name?.toLowerCase().includes(q) || cp.short_name?.toLowerCase().includes(q);
		}),
	);

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

	async function fetchOrders() {
		try {
			const response = await apiFetch('/orders?limit=200');
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			const data = await response.json();
			orders = (data.items ?? []).map((o: any) => ({
				key: o.id,
				text: `${o.order_type} - ${(o.id ?? '').slice(0, 8)} (${o.quantity_mt} MT)`,
			}));
		} catch {
			orders = [];
		}
	}

	onMount(() => {
		fetchCounterparties();
		fetchOrders();
	});

	function toggleCounterparty(id: string) {
		if (selectedCounterpartyIds.includes(id)) {
			selectedCounterpartyIds = selectedCounterpartyIds.filter((x) => x !== id);
		} else {
			selectedCounterpartyIds = [...selectedCounterpartyIds, id];
		}
	}

	function oppositeSide(side: LegSide): LegSide {
		return side === 'buy' ? 'sell' : 'buy';
	}

	function isFixedPriceType(priceType: LegPriceType) {
		return priceType === 'Fix' || priceType === 'C2R';
	}

	function isVariablePriceType(priceType: LegPriceType) {
		return priceType === 'AVG' || priceType === 'AVGInter';
	}

	function isBusinessDay(date: Date) {
		const day = date.getDay();
		return day !== 0 && day !== 6 && !lmeHolidays.has(dateInputValue(date));
	}

	function lastBusinessDayOfMonthIso(year: number, monthIndex: number): string {
		const date = new Date(year, monthIndex + 1, 0);
		while (!isBusinessDay(date)) {
			date.setDate(date.getDate() - 1);
		}
		return dateInputValue(date);
	}

	function firstDayOfMonthIso(year: number, monthIndex: number): string {
		return dateInputValue(new Date(year, monthIndex, 1));
	}

	function lastDayOfMonthIso(year: number, monthIndex: number): string {
		return dateInputValue(new Date(year, monthIndex + 1, 0));
	}

	function monthIndexFromName(monthName: string) {
		return months.indexOf(monthName);
	}

	function isPastAverageMonth(monthName: string, year: number) {
		const monthIndex = monthIndexFromName(monthName);
		return year < currentYear || (year === currentYear && monthIndex < currentMonthIndex);
	}

	function normaliseAverageMonth(leg: LegState) {
		if (isPastAverageMonth(leg.monthName, leg.year)) {
			leg.monthName = months[currentMonthIndex];
			leg.year = currentYear;
		}
	}

	function isFixingDateInherited(leg: LegState) {
		return leg.fixingDateInherited;
	}

	function syncFixingDatesFromVariableLeg(trade: TradeState) {
		(['leg1', 'leg2'] as LegKey[]).forEach((legKey) => {
			const otherLegKey: LegKey = legKey === 'leg1' ? 'leg2' : 'leg1';
			const fixedLeg = trade[legKey];
			const variableLeg = trade[otherLegKey];
			if (!isFixedPriceType(fixedLeg.priceType) || !isVariablePriceType(variableLeg.priceType)) {
				if (fixedLeg.fixingDateInherited) {
					fixedLeg.fixingDate = '';
					fixedLeg.fixingDateInherited = false;
				}
				return;
			}

			if (variableLeg.priceType === 'AVG') {
				const monthIndex = monthIndexFromName(variableLeg.monthName);
				if (monthIndex >= 0) {
					fixedLeg.fixingDate = lastBusinessDayOfMonthIso(variableLeg.year, monthIndex);
					fixedLeg.fixingDateInherited = true;
				}
			} else if (variableLeg.priceType === 'AVGInter' && variableLeg.endDate) {
				fixedLeg.fixingDate = variableLeg.endDate;
				fixedLeg.fixingDateInherited = true;
			}
		});
	}

	function setLegSide(tradeIndex: number, legKey: LegKey, side: LegSide) {
		const trade = trades[tradeIndex];
		if (!trade) return;
		const otherLeg: LegKey = legKey === 'leg1' ? 'leg2' : 'leg1';
		trade[legKey].side = side;
		trade[otherLeg].side = oppositeSide(side);
		trades = [...trades];
	}

	function setLegPriceType(tradeIndex: number, legKey: LegKey, priceType: LegPriceType) {
		const trade = trades[tradeIndex];
		if (!trade) return;
		trade[legKey].priceType = priceType;
		if (priceType === 'AVG') {
			normaliseAverageMonth(trade[legKey]);
		}
		syncFixingDatesFromVariableLeg(trade);
		trades = [...trades];
	}

	function setLegAverageMonth(tradeIndex: number, legKey: LegKey, monthName: string) {
		const trade = trades[tradeIndex];
		if (!trade) return;
		trade[legKey].monthName = monthName;
		normaliseAverageMonth(trade[legKey]);
		syncFixingDatesFromVariableLeg(trade);
		trades = [...trades];
	}

	function setLegAverageYear(tradeIndex: number, legKey: LegKey, year: number) {
		const trade = trades[tradeIndex];
		if (!trade) return;
		trade[legKey].year = year;
		normaliseAverageMonth(trade[legKey]);
		syncFixingDatesFromVariableLeg(trade);
		trades = [...trades];
	}

	function setLegDate(tradeIndex: number, legKey: LegKey, field: 'startDate' | 'endDate' | 'fixingDate', value: string) {
		const trade = trades[tradeIndex];
		if (!trade) return;
		trade[legKey][field] = value;
		if (field === 'fixingDate') {
			trade[legKey].fixingDateInherited = false;
		}
		if (field === 'startDate' && trade[legKey].endDate && trade[legKey].endDate < value) {
			trade[legKey].endDate = '';
		}
		syncFixingDatesFromVariableLeg(trade);
		trades = [...trades];
	}

	function applyTemplate(tradeIndex: number, template: 'queda' | 'alta' | 'spread') {
		const t = trades[tradeIndex];
		if (!t) return;

		if (template === 'queda') {
			// Protecao de Queda: Buy AVG + Sell Fix
			t.leg1 = { ...emptyLeg('buy'), priceType: 'AVG' };
			t.leg2 = { ...emptyLeg('sell'), priceType: 'Fix' };
		} else if (template === 'alta') {
			// Protecao de Alta: Sell AVG + Buy Fix
			t.leg1 = { ...emptyLeg('sell'), priceType: 'AVG' };
			t.leg2 = { ...emptyLeg('buy'), priceType: 'Fix' };
		} else if (template === 'spread') {
			// Spread: Buy AVG + Sell AVG
			t.leg1 = { ...emptyLeg('buy'), priceType: 'AVG' };
			t.leg2 = { ...emptyLeg('sell'), priceType: 'AVG' };
		}
		syncFixingDatesFromVariableLeg(t);
		trades = [...trades];
	}

	function legReadinessError(leg: LegState, label: string): string | null {
		if (!leg.priceType) {
			return `${label}: selecione o Price Type`;
		}
		if (leg.priceType === 'AVGInter' && (!leg.startDate || !leg.endDate)) {
			return `${label}: informe Data Inicio e Data Fim`;
		}
		if (leg.orderType === 'Limit' && !leg.limitPrice.trim()) {
			return `${label}: informe o Preco Limite`;
		}
		return null;
	}

	function ensureTradeReadyForPreview(trade: TradeState | undefined): string | null {
		if (!trade || !trade.leg1.priceType) {
			return 'Configure pelo menos a Leg 1 do primeiro trade';
		}

		const leg1Error = legReadinessError(trade.leg1, 'Leg 1');
		if (leg1Error) return leg1Error;

		if (tradeType === 'Swap' && !trade.leg2.priceType) {
			return 'Configure a Leg 2 para trades Swap';
		}

		return showLeg2 ? legReadinessError(trade.leg2, 'Leg 2') : null;
	}

	function buildLegPayload(leg: LegState) {
		if (!quantityValidation.ok) {
			throw new Error(quantityValidation.reason);
		}
		const payload: Record<string, unknown> = {
			side: leg.side,
			price_type: leg.priceType,
			quantity_mt: quantityValidation.canonical,
		};

		if (leg.priceType === 'AVG') {
			payload.month_name = leg.monthName;
			payload.year = leg.year;
		} else if (leg.priceType === 'AVGInter') {
			payload.start_date = leg.startDate;
			payload.end_date = leg.endDate;
		} else if (leg.priceType === 'Fix' || leg.priceType === 'C2R') {
			if (leg.fixingDate) payload.fixing_date = leg.fixingDate;
			if (leg.orderType) {
				payload.order_type = leg.orderType;
				if (leg.orderType !== 'At Market') {
					payload.order_validity = leg.orderValidity || null;
				}
				if (leg.orderType === 'Limit' && leg.limitPrice.trim()) {
					payload.order_limit_price = leg.limitPrice.trim();
				}
			}
		}

		return payload;
	}

	function buildPreviewBody(trade: TradeState): Record<string, unknown> {
		const body: Record<string, unknown> = {
			trade_type: tradeType,
			leg1: buildLegPayload(trade.leg1),
			company_header: companyLabel,
			company_label_for_payoff: companyLabel,
		};
		if (showLeg2) {
			body.leg2 = buildLegPayload(trade.leg2);
		}
		return body;
	}

	function deriveRfqDirection(trade: TradeState | undefined): 'BUY' | 'SELL' {
		return trade?.leg1.side === 'sell' ? 'SELL' : 'BUY';
	}

	function deliveryWindowFromLeg(leg: LegState) {
		if (leg.priceType === 'AVG') {
			const monthIndex = monthIndexFromName(leg.monthName);
			if (monthIndex >= 0) {
				return {
					start: firstDayOfMonthIso(leg.year, monthIndex),
					end: lastDayOfMonthIso(leg.year, monthIndex),
				};
			}
		}
		if (leg.priceType === 'AVGInter' && leg.startDate && leg.endDate) {
			return { start: leg.startDate, end: leg.endDate };
		}
		if (isFixedPriceType(leg.priceType) && leg.fixingDate) {
			return { start: leg.fixingDate, end: leg.fixingDate };
		}
		return null;
	}

	function deriveDeliveryWindow(trade: TradeState | undefined) {
		if (!trade) return null;
		const legs = [trade.leg1, trade.leg2];
		const variableLeg = legs.find((leg) => isVariablePriceType(leg.priceType) && deliveryWindowFromLeg(leg));
		return variableLeg
			? deliveryWindowFromLeg(variableLeg)
			: deliveryWindowFromLeg(trade.leg1) || deliveryWindowFromLeg(trade.leg2);
	}

	async function requestPreviewText({ showNotification = true }: { showNotification?: boolean } = {}) {
		if (!quantityValidation.ok) {
			if (showNotification) {
				notifications.warning(`Quantidade inválida: ${quantityValidation.reason}`);
			}
			return null;
		}

		const trade = trades[0];
		const readinessError = ensureTradeReadyForPreview(trade);
		if (readinessError) {
			if (showNotification) {
				notifications.warning(readinessError);
			}
			return null;
		}

		try {
			const response = await apiFetch('/rfqs/preview-text', {
				method: 'POST',
				body: JSON.stringify(buildPreviewBody(trade)),
			});
			if (!response.ok) {
				const err = await response.json().catch(() => ({ detail: 'Erro' }));
				throw new Error(typeof err.detail === 'string' ? err.detail : JSON.stringify(err.detail));
			}
			const data = await response.json();
			return {
				textEn: data.text_en || data.text || '',
				textPt: data.text_pt || '',
			};
		} catch (e) {
			if (showNotification) {
				notifications.warning(e instanceof Error ? e.message : 'Nao foi possivel gerar preview do texto');
			}
			return null;
		}
	}

	async function loadPreview() {
		const preview = await requestPreviewText();
		if (!preview) return;
		previewTextEn = preview.textEn;
		previewTextPt = preview.textPt;
		showPreview = true;
	}

	async function copyText(text: string) {
		await navigator.clipboard.writeText(text);
		notifications.success('Texto copiado');
	}

	function whatsappShareUrl(): string {
		const text = previewTextPt || previewTextEn || '';
		return `https://wa.me/?text=${encodeURIComponent(text)}`;
	}

	async function handleSubmit(e: SubmitEvent) {
		e.preventDefault();

		if (!quantityValidation.ok) {
			notifications.warning(`Quantidade inválida: ${quantityValidation.reason}`);
			return;
		}
		if (selectedCounterpartyIds.length === 0) {
			notifications.warning('Selecione pelo menos uma contraparte');
			return;
		}
		const readinessError = ensureTradeReadyForPreview(trades[0]);
		if (readinessError) {
			notifications.warning(readinessError);
			return;
		}

		const deliveryWindow = deriveDeliveryWindow(trades[0]);
		if (!deliveryWindow) {
			notifications.warning('Configure o periodo de preco ou fixing date no primeiro trade');
			return;
		}

		const actorSub = authStore.userSub;
		if (!actorSub) {
			notifications.error(
				'Sessão sem identidade verificável (sub). Faça login novamente para criar RFQs.',
			);
			return;
		}

		const preview = await requestPreviewText({ showNotification: false });
		if (!preview) {
			notifications.warning('Nao foi possivel atualizar o texto RFQ antes do envio');
			return;
		}

		submitting = true;
		try {
			const body: Record<string, unknown> = {
				commodity,
				quantity_mt: quantityValidation.canonical,
				direction: deriveRfqDirection(trades[0]),
				intent,
				delivery_window_start: deliveryWindow.start,
				delivery_window_end: deliveryWindow.end,
				invitations: selectedCounterpartyIds.map((id) => ({ counterparty_id: id })),
			};

			if (intent === 'COMMERCIAL_HEDGE' && orderId) {
				body.order_id = orderId;
			}
			if (intent === 'SPREAD') {
				if (buyTradeId) body.buy_trade_id = buyTradeId;
				if (sellTradeId) body.sell_trade_id = sellTradeId;
			}
			body.text_en = preview.textEn;
			body.text_pt = preview.textPt;

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

	const inputClass =
		'mt-1 w-full rounded border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200';
	const labelClass = 'block text-sm font-medium text-surface-400';
	const selectClass = inputClass;
	const panelClass = 'rounded border border-surface-700 p-4 space-y-4';
</script>

<div class="mx-auto max-w-5xl p-6">
	<div class="mb-6 flex items-center gap-3">
		<a href="/rfq" class="text-surface-500 hover:text-surface-300">← Voltar</a>
		<h1 class="text-lg font-semibold text-surface-200">Criar RFQ</h1>
	</div>

	<form onsubmit={handleSubmit} class="space-y-6">
		<fieldset class={panelClass}>
			<legend class="px-2 text-sm font-semibold text-surface-300">Trade Setup</legend>

			<div class="grid grid-cols-1 gap-4 md:grid-cols-3">
				<div>
					<div class={labelClass}>Empresa</div>
					<div class="mt-2 flex flex-wrap gap-3">
						<label class="flex cursor-pointer items-center gap-1.5 text-sm text-surface-300">
							<input type="radio" bind:group={companyIndex} value={0} class="accent-accent" />
							Alcast Brasil
						</label>
						<label class="flex cursor-pointer items-center gap-1.5 text-sm text-surface-300">
							<input type="radio" bind:group={companyIndex} value={1} class="accent-accent" />
							Alcast Trading
						</label>
					</div>
				</div>

				<div>
					<label class={labelClass} for="commodity">Commodity</label>
					<select id="commodity" bind:value={commodity} class={selectClass}>
						{#each commodities as c}
							<option value={c}>{c}</option>
						{/each}
					</select>
				</div>

				<div>
					<label class={labelClass} for="intent">Intencao</label>
					<select id="intent" bind:value={intent} class={selectClass}>
						<option value="GLOBAL_POSITION">Posicao Global</option>
						<option value="COMMERCIAL_HEDGE">Hedge Comercial</option>
						<option value="SPREAD">Spread</option>
					</select>
				</div>
			</div>

			{#if intent === 'COMMERCIAL_HEDGE'}
				<div class="grid grid-cols-1 gap-4 rounded border border-surface-700 bg-surface-900/50 p-3 md:grid-cols-2">
					<div>
						<label class={labelClass} for="order-id">Ordem (PO / SO)</label>
						<select id="order-id" bind:value={orderId} required class={selectClass}>
							<option value="">-- Selecione --</option>
							{#each orders as o}
								<option value={o.key}>{o.text}</option>
							{/each}
						</select>
					</div>
					{#if exposureInfo}
						<div class="flex items-end">
							<div class="rounded bg-blue/10 px-3 py-2 text-xs text-blue">{exposureInfo}</div>
						</div>
					{/if}
				</div>
			{/if}

			{#if intent === 'SPREAD'}
				<div class="grid grid-cols-1 gap-4 rounded border border-surface-700 bg-surface-900/50 p-3 md:grid-cols-2">
					<div>
						<label class={labelClass} for="buy-trade-id">Buy Trade ID</label>
						<input
							id="buy-trade-id"
							type="text"
							bind:value={buyTradeId}
							required
							class="{inputClass} font-mono"
							placeholder="UUID da RFQ de compra"
						/>
					</div>
					<div>
						<label class={labelClass} for="sell-trade-id">Sell Trade ID</label>
						<input
							id="sell-trade-id"
							type="text"
							bind:value={sellTradeId}
							required
							class="{inputClass} font-mono"
							placeholder="UUID da RFQ de venda"
						/>
					</div>
				</div>
			{/if}

			<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
				<div>
					<label class={labelClass} for="trade-type">Tipo de Trade</label>
					<select id="trade-type" bind:value={tradeType} class={selectClass}>
						<option value="Swap">Swap</option>
						<option value="Forward">Forward</option>
					</select>
				</div>
				<div>
					<label class={labelClass} for="qty">Quantidade (MT)</label>
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
						class="{inputClass} tabular-nums"
					/>
					{#if quantityMtRaw !== '' && quantityError}
						<p id="qty-error" class="mt-1 text-xs text-danger" data-testid="rfq-quantity-error">
							{quantityError}
						</p>
					{/if}
				</div>
			</div>

			{#each trades as trade, tradeIdx}
				<div class="space-y-4 rounded border border-surface-600 bg-surface-900/30 p-4">
					<div class="flex flex-wrap items-center justify-between gap-3">
						<h3 class="text-sm font-semibold text-surface-300">{trade.title}</h3>
						<div class="flex flex-wrap gap-1">
							<button
								type="button"
								onclick={() => applyTemplate(tradeIdx, 'queda')}
								class="rounded border border-danger/30 px-2 py-1 text-xs text-danger hover:bg-danger/10"
								title="Protecao de Queda: Buy AVG + Sell Fix">Queda</button
							>
							<button
								type="button"
								onclick={() => applyTemplate(tradeIdx, 'alta')}
								class="rounded border border-success/30 px-2 py-1 text-xs text-success hover:bg-success/10"
								title="Protecao de Alta: Sell AVG + Buy Fix">Alta</button
							>
							<button
								type="button"
								onclick={() => applyTemplate(tradeIdx, 'spread')}
								class="rounded border border-blue/30 px-2 py-1 text-xs text-blue hover:bg-blue/10"
								title="Spread: Buy AVG + Sell AVG">Spread</button
							>
						</div>
					</div>

					<div class="space-y-3">
						<h4 class="text-xs font-semibold uppercase tracking-wider text-accent">Leg 1</h4>
						<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
							<div>
								<div class={labelClass}>Side</div>
								<div class="mt-2 flex gap-3">
									<label class="flex cursor-pointer items-center gap-1.5 text-sm text-surface-300">
										<input
											type="radio"
											checked={trade.leg1.side === 'buy'}
											onchange={() => setLegSide(tradeIdx, 'leg1', 'buy')}
											class="accent-accent"
										/>
										Compra
									</label>
									<label class="flex cursor-pointer items-center gap-1.5 text-sm text-surface-300">
										<input
											type="radio"
											checked={trade.leg1.side === 'sell'}
											onchange={() => setLegSide(tradeIdx, 'leg1', 'sell')}
											class="accent-accent"
										/>
										Venda
									</label>
								</div>
							</div>
							<div>
								<label class={labelClass} for="leg1-ptype-{tradeIdx}">Price Type</label>
								<select
									id="leg1-ptype-{tradeIdx}"
									value={trade.leg1.priceType}
									onchange={(e) => setLegPriceType(tradeIdx, 'leg1', e.currentTarget.value as LegPriceType)}
									class={selectClass}
								>
									<option value="">Selecione...</option>
									<option value="AVG">AVG</option>
									<option value="AVGInter">AVG Period</option>
									<option value="Fix">Fix</option>
									<option value="C2R">C2R</option>
								</select>
							</div>
						</div>

						{#if trade.leg1.priceType === 'AVG'}
							<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
								<div>
									<label class={labelClass} for="leg1-month-{tradeIdx}">Mes</label>
									<select
										id="leg1-month-{tradeIdx}"
										value={trade.leg1.monthName}
										onchange={(e) => setLegAverageMonth(tradeIdx, 'leg1', e.currentTarget.value)}
										class={selectClass}
									>
										{#each months as m}
											<option value={m} hidden={isPastAverageMonth(m, trade.leg1.year)} disabled={isPastAverageMonth(m, trade.leg1.year)}>{m}</option>
										{/each}
									</select>
								</div>
								<div>
									<label class={labelClass} for="leg1-year-{tradeIdx}">Ano</label>
									<select
										id="leg1-year-{tradeIdx}"
										value={trade.leg1.year}
										onchange={(e) => setLegAverageYear(tradeIdx, 'leg1', Number(e.currentTarget.value))}
										class={selectClass}
									>
										{#each years as y}<option value={y}>{y}</option>{/each}
									</select>
								</div>
							</div>
						{/if}

						{#if trade.leg1.priceType === 'AVGInter'}
							<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
								<div>
									<label class={labelClass} for="leg1-start-{tradeIdx}">Data Inicio</label>
									<input
										id="leg1-start-{tradeIdx}"
										type="date"
										value={trade.leg1.startDate}
										min={todayIso}
										oninput={(e) => setLegDate(tradeIdx, 'leg1', 'startDate', e.currentTarget.value)}
										class={inputClass}
									/>
								</div>
								<div>
									<label class={labelClass} for="leg1-end-{tradeIdx}">Data Fim</label>
									<input
										id="leg1-end-{tradeIdx}"
										type="date"
										value={trade.leg1.endDate}
										min={trade.leg1.startDate || todayIso}
										oninput={(e) => setLegDate(tradeIdx, 'leg1', 'endDate', e.currentTarget.value)}
										class={inputClass}
									/>
								</div>
							</div>
						{/if}

						{#if trade.leg1.priceType === 'Fix' || trade.leg1.priceType === 'C2R'}
							<div class="grid grid-cols-1 gap-4 md:grid-cols-3">
								<div>
									<label class={labelClass} for="leg1-fixing-{tradeIdx}">Fixing Date</label>
									<input
										id="leg1-fixing-{tradeIdx}"
										type="date"
										value={trade.leg1.fixingDate}
										min={todayIso}
										readonly={isFixingDateInherited(trade.leg1)}
										oninput={(e) => setLegDate(tradeIdx, 'leg1', 'fixingDate', e.currentTarget.value)}
										class={inputClass}
									/>
								</div>
								<div>
									<label class={labelClass} for="leg1-ordertype-{tradeIdx}">Tipo de Ordem</label>
									<select id="leg1-ordertype-{tradeIdx}" bind:value={trade.leg1.orderType} class={selectClass}>
										<option value="">--</option>
										<option value="At Market">At Market</option>
										<option value="Limit">Limit</option>
										<option value="Resting">Resting</option>
									</select>
								</div>
								{#if trade.leg1.orderType && trade.leg1.orderType !== 'At Market'}
									<div>
										<label class={labelClass} for="leg1-validity-{tradeIdx}">Validade</label>
										<select id="leg1-validity-{tradeIdx}" bind:value={trade.leg1.orderValidity} class={selectClass}>
											<option value="Day">Day</option>
											<option value="GTC">GTC</option>
											<option value="3 Hours">3 Hours</option>
											<option value="6 Hours">6 Hours</option>
											<option value="12 Hours">12 Hours</option>
											<option value="Until Further Notice">Until Further Notice</option>
										</select>
									</div>
								{/if}
							</div>
							{#if trade.leg1.orderType === 'Limit'}
								<div class="md:w-1/3">
									<label class={labelClass} for="leg1-limit-{tradeIdx}">Preco Limite (USD)</label>
									<input
										id="leg1-limit-{tradeIdx}"
										type="text"
										bind:value={trade.leg1.limitPrice}
										required={trade.leg1.orderType === 'Limit'}
										placeholder="USD"
										class="{inputClass} tabular-nums"
									/>
								</div>
							{/if}
						{/if}
					</div>

					{#if showLeg2}
						<div class="space-y-3 border-t border-surface-700 pt-4">
							<h4 class="text-xs font-semibold uppercase tracking-wider text-accent">Leg 2</h4>
							<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
								<div>
									<div class={labelClass}>Side</div>
									<div class="mt-2 flex gap-3">
										<label class="flex cursor-pointer items-center gap-1.5 text-sm text-surface-300">
											<input
												type="radio"
												checked={trade.leg2.side === 'buy'}
												onchange={() => setLegSide(tradeIdx, 'leg2', 'buy')}
												class="accent-accent"
											/>
											Compra
										</label>
										<label class="flex cursor-pointer items-center gap-1.5 text-sm text-surface-300">
											<input
												type="radio"
												checked={trade.leg2.side === 'sell'}
												onchange={() => setLegSide(tradeIdx, 'leg2', 'sell')}
												class="accent-accent"
											/>
											Venda
										</label>
									</div>
								</div>
								<div>
									<label class={labelClass} for="leg2-ptype-{tradeIdx}">Price Type</label>
									<select
										id="leg2-ptype-{tradeIdx}"
										value={trade.leg2.priceType}
										onchange={(e) => setLegPriceType(tradeIdx, 'leg2', e.currentTarget.value as LegPriceType)}
										class={selectClass}
									>
										<option value="">Selecione...</option>
										<option value="AVG">AVG</option>
										<option value="AVGInter">AVG Period</option>
										<option value="Fix">Fix</option>
										<option value="C2R">C2R</option>
									</select>
								</div>
							</div>

							{#if trade.leg2.priceType === 'AVG'}
								<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
									<div>
										<label class={labelClass} for="leg2-month-{tradeIdx}">Mes</label>
										<select
											id="leg2-month-{tradeIdx}"
											value={trade.leg2.monthName}
											onchange={(e) => setLegAverageMonth(tradeIdx, 'leg2', e.currentTarget.value)}
											class={selectClass}
										>
											{#each months as m}
												<option value={m} hidden={isPastAverageMonth(m, trade.leg2.year)} disabled={isPastAverageMonth(m, trade.leg2.year)}>{m}</option>
											{/each}
										</select>
									</div>
									<div>
										<label class={labelClass} for="leg2-year-{tradeIdx}">Ano</label>
										<select
											id="leg2-year-{tradeIdx}"
											value={trade.leg2.year}
											onchange={(e) => setLegAverageYear(tradeIdx, 'leg2', Number(e.currentTarget.value))}
											class={selectClass}
										>
											{#each years as y}<option value={y}>{y}</option>{/each}
										</select>
									</div>
								</div>
							{/if}

							{#if trade.leg2.priceType === 'AVGInter'}
								<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
									<div>
										<label class={labelClass} for="leg2-start-{tradeIdx}">Data Inicio</label>
										<input
											id="leg2-start-{tradeIdx}"
											type="date"
											value={trade.leg2.startDate}
											min={todayIso}
											oninput={(e) => setLegDate(tradeIdx, 'leg2', 'startDate', e.currentTarget.value)}
											class={inputClass}
										/>
									</div>
									<div>
										<label class={labelClass} for="leg2-end-{tradeIdx}">Data Fim</label>
										<input
											id="leg2-end-{tradeIdx}"
											type="date"
											value={trade.leg2.endDate}
											min={trade.leg2.startDate || todayIso}
											oninput={(e) => setLegDate(tradeIdx, 'leg2', 'endDate', e.currentTarget.value)}
											class={inputClass}
										/>
									</div>
								</div>
							{/if}

							{#if trade.leg2.priceType === 'Fix' || trade.leg2.priceType === 'C2R'}
								<div class="grid grid-cols-1 gap-4 md:grid-cols-3">
									<div>
										<label class={labelClass} for="leg2-fixing-{tradeIdx}">Fixing Date</label>
										<input
											id="leg2-fixing-{tradeIdx}"
											type="date"
											value={trade.leg2.fixingDate}
											min={todayIso}
											readonly={isFixingDateInherited(trade.leg2)}
											oninput={(e) => setLegDate(tradeIdx, 'leg2', 'fixingDate', e.currentTarget.value)}
											class={inputClass}
										/>
									</div>
									<div>
										<label class={labelClass} for="leg2-ordertype-{tradeIdx}">Tipo de Ordem</label>
										<select id="leg2-ordertype-{tradeIdx}" bind:value={trade.leg2.orderType} class={selectClass}>
											<option value="">--</option>
											<option value="At Market">At Market</option>
											<option value="Limit">Limit</option>
											<option value="Resting">Resting</option>
										</select>
									</div>
									{#if trade.leg2.orderType && trade.leg2.orderType !== 'At Market'}
										<div>
											<label class={labelClass} for="leg2-validity-{tradeIdx}">Validade</label>
											<select id="leg2-validity-{tradeIdx}" bind:value={trade.leg2.orderValidity} class={selectClass}>
												<option value="Day">Day</option>
												<option value="GTC">GTC</option>
												<option value="3 Hours">3 Hours</option>
												<option value="6 Hours">6 Hours</option>
												<option value="12 Hours">12 Hours</option>
												<option value="Until Further Notice">Until Further Notice</option>
											</select>
										</div>
									{/if}
								</div>
								{#if trade.leg2.orderType === 'Limit'}
									<div class="md:w-1/3">
										<label class={labelClass} for="leg2-limit-{tradeIdx}">Preco Limite (USD)</label>
										<input
											id="leg2-limit-{tradeIdx}"
											type="text"
											bind:value={trade.leg2.limitPrice}
											required={trade.leg2.orderType === 'Limit'}
											placeholder="USD"
											class="{inputClass} tabular-nums"
										/>
									</div>
								{/if}
							{/if}
						</div>
					{/if}
				</div>
			{/each}

			<div class="flex flex-wrap items-center gap-3">
				<div class="flex-1"></div>
				<button
					type="button"
					onclick={loadPreview}
					disabled={!quantityValidation.ok}
					data-testid="rfq-preview-button"
					class="rounded bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
				>
					Gerar Texto RFQ
				</button>
			</div>
		</fieldset>

		{#if showPreview}
			<fieldset class={panelClass}>
				<legend class="px-2 text-sm font-semibold text-surface-300">Texto da Cotacao</legend>
				<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
					<div>
						<div class="mb-1 flex items-center justify-between gap-3">
							<span class="text-xs font-medium text-surface-400">English (LME)</span>
							<button type="button" onclick={() => copyText(previewTextEn)} class="text-xs text-surface-500 hover:text-surface-300">Copiar EN</button>
						</div>
						<pre class="max-h-64 overflow-y-auto whitespace-pre-wrap rounded border border-surface-700 bg-surface-900 p-3 text-xs text-surface-300">{previewTextEn}</pre>
					</div>
					<div>
						<div class="mb-1 flex items-center justify-between gap-3">
							<span class="text-xs font-medium text-surface-400">Portugues (Banco)</span>
							<button type="button" onclick={() => copyText(previewTextPt)} class="text-xs text-surface-500 hover:text-surface-300">Copiar PT</button>
						</div>
						<pre class="max-h-64 overflow-y-auto whitespace-pre-wrap rounded border border-surface-700 bg-surface-900 p-3 text-xs text-surface-300">{previewTextPt || '(sem texto PT gerado)'}</pre>
					</div>
				</div>
				<div class="mt-3">
					<a
						href={whatsappShareUrl()}
						target="_blank"
						rel="noopener noreferrer"
						class="inline-flex items-center gap-1.5 rounded bg-success/20 px-3 py-1.5 text-xs font-medium text-success hover:bg-success/30"
					>
						Compartilhar no WhatsApp
					</a>
				</div>
			</fieldset>
		{/if}

		<fieldset class={panelClass}>
			<legend class="px-2 text-sm font-semibold text-surface-300">
				Contrapartes ({selectedCounterpartyIds.length} selecionadas)
			</legend>
			<input
				type="text"
				bind:value={counterpartySearch}
				placeholder="Buscar contraparte..."
				class="{inputClass} placeholder-surface-600"
			/>
			<div class="max-h-56 overflow-y-auto rounded border border-surface-800 bg-surface-900">
				{#if loadingCounterparties}
					<div class="px-3 py-2 text-sm text-surface-500">Carregando...</div>
				{:else}
					<table class="w-full text-sm">
						<thead>
							<tr class="border-b border-surface-800 text-left text-xs text-surface-500">
								<th class="w-10 px-3 py-1.5">Sel.</th>
								<th class="px-3 py-1.5">Nome</th>
								<th class="px-3 py-1.5">Tipo</th>
								<th class="px-3 py-1.5">Idioma RFQ</th>
								<th class="px-3 py-1.5">WhatsApp</th>
							</tr>
						</thead>
						<tbody>
							{#each filteredCounterparties as cp (cp.id)}
								<tr
									class="cursor-pointer border-b border-surface-800/50 hover:bg-surface-800/30"
									onclick={() => toggleCounterparty(cp.id)}
								>
									<td class="px-3 py-1.5">
										<input
											type="checkbox"
											checked={selectedCounterpartyIds.includes(cp.id)}
											onchange={() => toggleCounterparty(cp.id)}
											onclick={(event) => event.stopPropagation()}
											class="accent-accent"
										/>
									</td>
									<td class="px-3 py-1.5 text-surface-300">{cp.name}</td>
									<td class="px-3 py-1.5 text-surface-400">{cp.type ?? '--'}</td>
									<td class="px-3 py-1.5">
										<span class="rounded px-1.5 py-0.5 text-xs {cp.type === 'bank_br' ? 'bg-blue/20 text-blue' : 'bg-success/20 text-success'}">
											{cp.type === 'bank_br' ? 'Portugues' : 'English'}
										</span>
									</td>
									<td class="px-3 py-1.5 font-mono text-xs text-surface-500">{cp.whatsapp_phone ?? '--'}</td>
								</tr>
							{:else}
								<tr><td colspan="5" class="px-3 py-4 text-center text-surface-500">Nenhuma contraparte encontrada</td></tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</div>
		</fieldset>

		<div class="flex items-center justify-end gap-3 border-t border-surface-800 pt-4">
			<a href="/rfq" class="rounded border border-surface-700 px-4 py-2 text-sm text-surface-400 hover:bg-surface-800">
				Cancelar
			</a>
			<button
				type="submit"
				disabled={submitting || !quantityValidation.ok}
				data-testid="rfq-submit-button"
				class="rounded bg-accent px-5 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50"
			>
				{submitting ? 'Enviando...' : 'Enviar RFQ'}
			</button>
		</div>
	</form>
</div>
