const dateFormatter = new Intl.DateTimeFormat('pt-BR', {
	dateStyle: 'short',
	timeStyle: 'short',
});

const numberFormatter = new Intl.NumberFormat('pt-BR', {
	minimumFractionDigits: 2,
	maximumFractionDigits: 2,
});

// MT quantities are persisted as NUMERIC(_, 3) on the backend (migrations
// 025/033). Rendering them through ``numberFormatter`` would silently round
// values like 1.234 to 1,23, misrepresenting RFQ/contract size — use this
// formatter instead for any *_mt quantity field.
const mtFormatter = new Intl.NumberFormat('pt-BR', {
	minimumFractionDigits: 3,
	maximumFractionDigits: 3,
});

// Quote/contract prices are persisted as NUMERIC(18, 6) on the backend
// (migrations 025/033). Rendering them through ``numberFormatter`` would
// collapse e.g. 100.000001 and 100.000002 to the same 100,00, even though
// the backend ranks and awards them differently. Use this formatter
// instead for any fixed_price_value / quote price field.
const priceFormatter = new Intl.NumberFormat('pt-BR', {
	minimumFractionDigits: 6,
	maximumFractionDigits: 6,
});

export function formatDate(iso: string | null | undefined): string {
	if (!iso) return '—';
	return dateFormatter.format(new Date(iso));
}

// Decimal-typed economic columns serialize as strings over the API.
// Coerce-on-read at these boundary helpers rather than at every call site.
// NOTE: ``formatNumber`` is for plain 2-decimal numbers. For *_mt quantity
// fields use ``formatQuantityMT`` (3 decimals); for price fields use
// ``formatPrice`` (6 decimals). Routing those through ``formatNumber``
// silently truncates real backend precision.
export function formatNumber(value: number | string | null | undefined): string {
	if (value == null) return '—';
	const n = typeof value === 'string' ? Number(value) : value;
	if (!Number.isFinite(n)) return '—';
	return numberFormatter.format(n);
}

export function formatQuantityMT(value: number | string | null | undefined): string {
	if (value == null) return '—';
	const n = typeof value === 'string' ? Number(value) : value;
	if (!Number.isFinite(n)) return '—';
	return mtFormatter.format(n);
}

export function formatPrice(
	value: number | string | null | undefined,
	unit?: string,
): string {
	if (value == null) return '—';
	const n = typeof value === 'string' ? Number(value) : value;
	if (!Number.isFinite(n)) return '—';
	const formatted = priceFormatter.format(n);
	return unit ? `${formatted} ${unit}` : formatted;
}

const STATE_LABELS: Record<string, string> = {
	CREATED: 'Criado',
	SENT: 'Enviado',
	QUOTED: 'Cotado',
	AWARDED: 'Premiado',
	CLOSED: 'Fechado',
};

const STATE_COLORS: Record<string, string> = {
	CREATED: 'bg-surface-600 text-surface-200',
	SENT: 'bg-accent/20 text-accent',
	QUOTED: 'bg-warning/20 text-warning',
	AWARDED: 'bg-success/20 text-success',
	CLOSED: 'bg-surface-700 text-surface-400',
};

export function stateLabel(state: string | undefined): string {
	if (!state) return '—';
	return STATE_LABELS[state] ?? state;
}

export function stateColor(state: string | undefined): string {
	if (!state) return 'bg-surface-700 text-surface-400';
	return STATE_COLORS[state] ?? 'bg-surface-700 text-surface-400';
}

const INTENT_LABELS: Record<string, string> = {
	COMMERCIAL_HEDGE: 'Hedge Comercial',
	GLOBAL_POSITION: 'Posição Global',
	SPREAD: 'Spread',
};

export function intentLabel(intent: string | undefined): string {
	if (!intent) return '—';
	return INTENT_LABELS[intent] ?? intent;
}

export function directionLabel(direction: string | undefined): string {
	if (!direction) return '—';
	return direction === 'BUY' ? 'Compra' : 'Venda';
}

export function directionColor(direction: string | undefined): string {
	if (!direction) return 'text-surface-400';
	return direction === 'BUY' ? 'text-success' : 'text-danger';
}
