<script lang="ts">
	import Badge from './Badge.svelte';

	export type LegSide = 'buy' | 'sell';
	export type LegPriceType = '' | 'AVG' | 'AVGInter' | 'Fix' | 'C2R';
	export type LegOrderType = '' | 'At Market' | 'Limit' | 'Resting';

	export interface Leg {
		side: LegSide;
		priceType: LegPriceType;
		monthName: string;
		year: number;
		startDate: string;
		endDate: string;
		fixingDate: string;
		fixingDateInherited: boolean;
		orderType: LegOrderType;
		orderValidity: string;
		limitPrice: string;
	}

	const PRICE_TYPES: { value: LegPriceType; label: string }[] = [
		{ value: 'AVG',      label: 'AVG · média mensal' },
		{ value: 'AVGInter', label: 'AVG Period · média de período' },
		{ value: 'Fix',      label: 'Fix · preço fixo' },
		{ value: 'C2R',      label: 'C2R · close-to-result' },
	];

	const ORDER_TYPES: { value: LegOrderType; label: string }[] = [
		{ value: 'At Market', label: 'A mercado' },
		{ value: 'Limit',     label: 'Limitada' },
		{ value: 'Resting',   label: 'Em aberto' },
	];

	const VALIDITIES = [
		{ value: 'Day', label: 'Dia' },
		{ value: 'GTC', label: 'GTC' },
		{ value: '3 Hours', label: '3 horas' },
		{ value: '6 Hours', label: '6 horas' },
		{ value: '12 Hours', label: '12 horas' },
		{ value: 'Until Further Notice', label: 'Até nova instrução' },
	];

	const MONTHS_PT = ['Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho', 'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro'];
	const MONTHS_EN = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
	const YEARS = [2026, 2027, 2028, 2029, 2030];

	let {
		leg = $bindable(),
		label,
		onSideChange,
	}: {
		leg: Leg;
		label: string;
		onSideChange: (side: LegSide) => void;
	} = $props();

	const showAVG = $derived(leg.priceType === 'AVG');
	const showAVGInter = $derived(leg.priceType === 'AVGInter');
	const showFix = $derived(leg.priceType === 'Fix' || leg.priceType === 'C2R');
	const idPrefix = $derived(label.toLowerCase().replaceAll(' ', '-'));
</script>

<div>
	<div class="row gap-2" style="margin-bottom: 12px;">
		<Badge kind="info" outlined>{label}</Badge>
		{#if leg.priceType}
			<span style="font-size: 11.5px; color: var(--muted);">
				{leg.side === 'buy' ? 'Compra' : 'Venda'} {leg.priceType}
			</span>
		{/if}
	</div>

	<div class="field-grid">
		<div class="field">
			<div class="field-label">Lado <span class="req">*</span></div>
			<div class="radio-group">
				<button type="button" class:active={leg.side === 'buy'} class:buy={leg.side === 'buy'} onclick={() => onSideChange('buy')}>Compra</button>
				<button type="button" class:active={leg.side === 'sell'} class:sell={leg.side === 'sell'} onclick={() => onSideChange('sell')}>Venda</button>
			</div>
		</div>

		<div class="field">
			<label class="field-label" for={`${idPrefix}-price-type`}>Tipo de preço <span class="req">*</span></label>
			<select id={`${idPrefix}-price-type`} class="select" bind:value={leg.priceType}>
				<option value="">— Selecione —</option>
				{#each PRICE_TYPES as pt (pt.value)}
					<option value={pt.value}>{pt.label}</option>
				{/each}
			</select>
		</div>

		{#if showAVG}
			<div class="field">
				<label class="field-label" for={`${idPrefix}-month`}>Mês de média <span class="req">*</span></label>
				<select id={`${idPrefix}-month`} class="select" bind:value={leg.monthName}>
					{#each MONTHS_EN as m, i (m)}
						<option value={m}>{MONTHS_PT[i]}</option>
					{/each}
				</select>
			</div>
			<div class="field">
				<label class="field-label" for={`${idPrefix}-year`}>Ano <span class="req">*</span></label>
				<select id={`${idPrefix}-year`} class="select" bind:value={leg.year}>
					{#each YEARS as y (y)}
						<option value={y}>{y}</option>
					{/each}
				</select>
			</div>
		{/if}

		{#if showAVGInter}
			<div class="field">
				<label class="field-label" for={`${idPrefix}-start-date`}>Data início <span class="req">*</span></label>
				<input id={`${idPrefix}-start-date`} class="input" type="date" bind:value={leg.startDate}/>
			</div>
			<div class="field">
				<label class="field-label" for={`${idPrefix}-end-date`}>Data fim <span class="req">*</span></label>
				<input id={`${idPrefix}-end-date`} class="input" type="date" min={leg.startDate} bind:value={leg.endDate}/>
			</div>
		{/if}

		{#if showFix}
			<div class="field">
				<label class="field-label" for={`${idPrefix}-fixing-date`}>Data de fixing</label>
				<input id={`${idPrefix}-fixing-date`} class="input" type="date" readonly={leg.fixingDateInherited} bind:value={leg.fixingDate}/>
				{#if leg.fixingDateInherited}
					<div class="field-help">Herdado da leg variável (oposta)</div>
				{/if}
			</div>
			<div class="field">
				<label class="field-label" for={`${idPrefix}-order-type`}>Tipo de ordem</label>
				<select id={`${idPrefix}-order-type`} class="select" bind:value={leg.orderType}>
					<option value="">—</option>
					{#each ORDER_TYPES as o (o.value)}
						<option value={o.value}>{o.label}</option>
					{/each}
				</select>
			</div>
			{#if leg.orderType && leg.orderType !== 'At Market'}
				<div class="field">
					<label class="field-label" for={`${idPrefix}-validity`}>Validade</label>
					<select id={`${idPrefix}-validity`} class="select" bind:value={leg.orderValidity}>
						{#each VALIDITIES as v (v.value)}
							<option value={v.value}>{v.label}</option>
						{/each}
					</select>
				</div>
			{/if}
			{#if leg.orderType === 'Limit'}
				<div class="field">
					<label class="field-label" for={`${idPrefix}-limit-price`}>Preço limite (USD) <span class="req">*</span></label>
					<div class="input-suffix">
						<input id={`${idPrefix}-limit-price`} class="input" placeholder="2.645,00" bind:value={leg.limitPrice}/>
						<span class="suffix">USD</span>
					</div>
				</div>
			{/if}
		{/if}
	</div>
</div>

