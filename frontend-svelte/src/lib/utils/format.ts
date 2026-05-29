const dateFormatter = new Intl.DateTimeFormat('pt-BR', {
	dateStyle: 'short',
	timeStyle: 'short',
});

const numberFormatter = new Intl.NumberFormat('pt-BR', {
	minimumFractionDigits: 2,
	maximumFractionDigits: 2,
});

// Decimal-safe formatter for backend NUMERIC(_, scale) values that arrive as
// strings over the API. Routing through ``Number()`` would lose precision
// for values whose total significant digits exceed IEEE-754's ~15-17
// (e.g. 100000000000.000001 vs 100000000000.000002 collapse to the same
// JS number even though the backend NUMERIC(18, 6) ranks/awards them
// differently). Format the integer part via Intl.NumberFormat on a BigInt
// (loss-free) and concatenate the fractional digits as a string.
//
// Currently used for:
//   - MT quantities (NUMERIC(_, 3), see migrations 025/033)
//   - prices       (NUMERIC(18, 6), see migrations 025/033)
const intGroupingFormatter = new Intl.NumberFormat('pt-BR');

function formatDecimalString(
	input: number | string,
	scale: number,
): string | null {
	let s: string;
	if (typeof input === 'number') {
		if (!Number.isFinite(input)) return null;
		s = input.toFixed(scale);
	} else {
		s = input.trim();
		// If it isn't a plain decimal string, fall back to a Number parse
		// (covers scientific notation, but also caps at IEEE-754 precision —
		// the backend serializes NUMERIC values in plain form so this branch
		// is only a defensive fallback).
		if (!/^-?\d+(?:\.\d+)?$/.test(s)) {
			const n = Number(s);
			if (!Number.isFinite(n)) return null;
			s = n.toFixed(scale);
		}
	}

	const negative = s.startsWith('-');
	const abs = negative ? s.slice(1) : s;
	const dot = abs.indexOf('.');
	const intPart = dot === -1 ? abs : abs.slice(0, dot);
	const fracRaw = dot === -1 ? '' : abs.slice(dot + 1);
	const fracPart = fracRaw.padEnd(scale, '0').slice(0, scale);

	const intFormatted = intGroupingFormatter.format(BigInt(intPart || '0'));
	return (negative ? '-' : '') + intFormatted + ',' + fracPart;
}

const integerFormatter = new Intl.NumberFormat('pt-BR', {
	maximumFractionDigits: 0,
});

export function formatDate(iso: string | null | undefined): string {
	if (!iso) return '—';
	return dateFormatter.format(new Date(iso));
}

// Whole-number pt-BR display (e.g. aggregated tonnage, counts). For
// precision-critical backend NUMERIC(_, 3) quantities use ``formatQuantityMT``.
export function formatInteger(value: number | string | null | undefined): string {
	if (value == null) return '—';
	const n = typeof value === 'string' ? Number(value) : value;
	if (!Number.isFinite(n)) return '—';
	return integerFormatter.format(n);
}

// Fixed-precision pt-BR display where the digit count is decided by the caller
// (e.g. per-instrument price precision). Number-based — for precision-critical
// price strings use ``formatPrice`` (6 decimals, BigInt-safe).
export function formatDecimal(
	value: number | string | null | undefined,
	digits: number,
): string {
	if (value == null) return '—';
	const n = typeof value === 'string' ? Number(value) : value;
	if (!Number.isFinite(n)) return '—';
	return new Intl.NumberFormat('pt-BR', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits,
	}).format(n);
}

// Signed pt-BR integer: positive values gain an explicit ``+`` prefix so deltas
// read unambiguously (e.g. MTM moves). Negative values keep their ``-``.
export function formatSignedInteger(
	value: number | string | null | undefined,
): string {
	if (value == null) return '—';
	const n = typeof value === 'string' ? Number(value) : value;
	if (!Number.isFinite(n)) return '—';
	return (n >= 0 ? '+' : '-') + integerFormatter.format(Math.abs(n));
}

// USD amount with pt-BR grouping. ``signed`` prefixes ``+``/``-`` (for deltas);
// unsigned preserves a native ``-`` for negatives.
export function formatUSD(
	value: number | string | null | undefined,
	options: { signed?: boolean; digits?: number } = {},
): string {
	if (value == null) return '—';
	const n = typeof value === 'string' ? Number(value) : value;
	if (!Number.isFinite(n)) return '—';
	const { signed = false, digits = 0 } = options;
	const fmt = new Intl.NumberFormat('pt-BR', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits,
	});
	if (signed) return `${n >= 0 ? '+' : '-'}US$ ${fmt.format(Math.abs(n))}`;
	return `US$ ${fmt.format(n)}`;
}

// Percentage display in pt-BR (comma decimal). Input is the already-computed
// percentage value (e.g. 73.5 → "73,5%").
export function formatPercent(
	value: number | string | null | undefined,
	digits = 2,
	options: { signed?: boolean } = {},
): string {
	if (value == null) return '—';
	const n = typeof value === 'string' ? Number(value) : value;
	if (!Number.isFinite(n)) return '—';
	const body = new Intl.NumberFormat('pt-BR', {
		minimumFractionDigits: digits,
		maximumFractionDigits: digits,
	}).format(options.signed ? Math.abs(n) : n);
	if (options.signed) return `${n >= 0 ? '+' : '-'}${body}%`;
	return `${body}%`;
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
	return formatDecimalString(value, 3) ?? '—';
}

export function formatPrice(
	value: number | string | null | undefined,
	unit?: string,
): string {
	if (value == null) return '—';
	const formatted = formatDecimalString(value, 6);
	if (formatted == null) return '—';
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
	CREATED: 'badge neutral',
	SENT: 'badge info',
	QUOTED: 'badge warn',
	AWARDED: 'badge pos',
	CLOSED: 'badge neutral',
};

export function stateLabel(state: string | undefined): string {
	if (!state) return '—';
	return STATE_LABELS[state] ?? state;
}

export function stateColor(state: string | undefined): string {
	if (!state) return 'badge neutral';
	return STATE_COLORS[state] ?? 'badge neutral';
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
	if (!direction) return 'muted';
	return direction === 'BUY' ? 'badge pos' : 'badge neg';
}
