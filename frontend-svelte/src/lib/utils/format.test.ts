import { describe, it, expect } from 'vitest';
import {
	formatDate,
	formatNumber,
	formatQuantityMT,
	formatPrice,
	formatInteger,
	formatDecimal,
	formatSignedInteger,
	formatUSD,
	formatPercent,
	stateLabel,
	stateColor,
	intentLabel,
	directionLabel,
	directionColor,
} from './format';

describe('formatDate', () => {
	it('formats ISO date string in pt-BR', () => {
		const result = formatDate('2026-03-15T14:30:00Z');
		// pt-BR format: dd/mm/yyyy, hh:mm
		expect(result).toMatch(/\d{2}\/\d{2}\/\d{4}/);
	});

	it('returns dash for null/undefined', () => {
		expect(formatDate(null)).toBe('—');
		expect(formatDate(undefined)).toBe('—');
	});
});

describe('formatNumber', () => {
	it('formats number with 2 decimal places', () => {
		const result = formatNumber(1234.5);
		// pt-BR uses comma for decimals: "1.234,50"
		expect(result).toContain('234');
		expect(result).toMatch(/,50$/);
	});

	it('returns dash for null/undefined', () => {
		expect(formatNumber(null)).toBe('—');
		expect(formatNumber(undefined)).toBe('—');
	});
});

describe('formatQuantityMT', () => {
	it('preserves three fractional digits for backend NUMERIC(_, 3) values', () => {
		// "1.234" must NOT be truncated to "1,23" — it represents 1.234 MT.
		expect(formatQuantityMT('1.234')).toMatch(/,234$/);
		expect(formatQuantityMT(1.234)).toMatch(/,234$/);
	});

	it('pads integer values to three decimals', () => {
		expect(formatQuantityMT(100)).toMatch(/,000$/);
	});

	it('rounds half-up beyond three decimals (Intl default)', () => {
		expect(formatQuantityMT('1.2345')).toMatch(/,23[45]$/);
	});

	it('preserves precision for large-magnitude decimal strings', () => {
		// Same IEEE-754 collapse risk as price fields, applied to MT scale.
		const a = formatQuantityMT('100000000000.001');
		const b = formatQuantityMT('100000000000.002');
		expect(a).not.toBe(b);
		expect(a).toMatch(/,001$/);
		expect(b).toMatch(/,002$/);
	});

	it('returns dash for null/undefined and non-finite input', () => {
		expect(formatQuantityMT(null)).toBe('—');
		expect(formatQuantityMT(undefined)).toBe('—');
		expect(formatQuantityMT('not-a-number')).toBe('—');
	});
});

describe('formatPrice', () => {
	it('preserves six fractional digits for backend NUMERIC(18, 6) values', () => {
		// 100.000001 vs 100.000002 must render distinctly — the backend
		// ranks/awards on these and the UI must not collapse them.
		expect(formatPrice('100.000001')).toMatch(/,000001$/);
		expect(formatPrice('100.000002')).toMatch(/,000002$/);
		expect(formatPrice(100.000001)).not.toBe(formatPrice(100.000002));
	});

	it('preserves precision for large-magnitude decimal strings beyond IEEE-754', () => {
		// 12-digit integer + 6-decimal fraction = 18 significant digits,
		// which exceeds JS Number precision (~15-17 sig digits). A string
		// that round-trips through Number would collapse these two values.
		// The decimal-safe formatter must render them distinctly.
		const a = formatPrice('100000000000.000001');
		const b = formatPrice('100000000000.000002');
		expect(a).not.toBe(b);
		expect(a).toMatch(/,000001$/);
		expect(b).toMatch(/,000002$/);
	});

	it('groups thousands with pt-BR separator for large integer parts', () => {
		expect(formatPrice('1234567.123456')).toBe('1.234.567,123456');
	});

	it('handles negative decimal strings without losing precision', () => {
		expect(formatPrice('-100000000000.000001')).toMatch(/^-/);
		expect(formatPrice('-100000000000.000001')).toMatch(/,000001$/);
	});

	it('pads integer values to six decimals', () => {
		expect(formatPrice(1000)).toMatch(/,000000$/);
	});

	it('appends unit when provided', () => {
		const result = formatPrice(1000, 'USD/MT');
		expect(result).toContain('USD/MT');
	});

	it('omits unit when not provided', () => {
		const result = formatPrice(1000);
		expect(result).not.toContain('USD');
	});

	it('returns dash for null/undefined and non-finite input', () => {
		expect(formatPrice(null)).toBe('—');
		expect(formatPrice(undefined)).toBe('—');
		expect(formatPrice('not-a-number')).toBe('—');
	});
});

describe('formatInteger', () => {
	it('groups thousands with pt-BR separator and no decimals', () => {
		expect(formatInteger(1500)).toBe('1.500');
		expect(formatInteger(1234567)).toBe('1.234.567');
	});

	it('rounds to whole numbers', () => {
		expect(formatInteger(1499.6)).toBe('1.500');
	});

	it('returns dash for null/undefined and non-finite input', () => {
		expect(formatInteger(null)).toBe('—');
		expect(formatInteger(undefined)).toBe('—');
		expect(formatInteger('not-a-number')).toBe('—');
	});
});

describe('formatDecimal', () => {
	it('formats with the caller-supplied digit count in pt-BR', () => {
		expect(formatDecimal(2631, 2)).toBe('2.631,00');
		expect(formatDecimal(5.4321, 4)).toBe('5,4321');
	});

	it('returns dash for null/undefined and non-finite input', () => {
		expect(formatDecimal(null, 2)).toBe('—');
		expect(formatDecimal('not-a-number', 2)).toBe('—');
	});
});

describe('formatSignedInteger', () => {
	it('prefixes positive values with + and negatives with -', () => {
		expect(formatSignedInteger(1234)).toBe('+1.234');
		expect(formatSignedInteger(-1234)).toBe('-1.234');
		expect(formatSignedInteger(0)).toBe('+0');
	});

	it('returns dash for null/undefined', () => {
		expect(formatSignedInteger(null)).toBe('—');
	});
});

describe('formatUSD', () => {
	it('renders unsigned USD with pt-BR grouping', () => {
		expect(formatUSD(1234567)).toBe('US$ 1.234.567');
	});

	it('renders signed USD with explicit +/- on the absolute value', () => {
		expect(formatUSD(1234, { signed: true })).toBe('+US$ 1.234');
		expect(formatUSD(-1234, { signed: true })).toBe('-US$ 1.234');
	});

	it('honours the digits option', () => {
		expect(formatUSD(1234.5, { digits: 2 })).toBe('US$ 1.234,50');
	});

	it('returns dash for null/undefined and non-finite input', () => {
		expect(formatUSD(null)).toBe('—');
		expect(formatUSD('not-a-number')).toBe('—');
	});
});

describe('formatPercent', () => {
	it('renders pt-BR percentage with comma decimal', () => {
		expect(formatPercent(73.5, 1)).toBe('73,5%');
		expect(formatPercent(2.5)).toBe('2,50%');
	});

	it('supports signed mode for deltas', () => {
		expect(formatPercent(2.5, 2, { signed: true })).toBe('+2,50%');
		expect(formatPercent(-2.5, 2, { signed: true })).toBe('-2,50%');
	});

	it('returns dash for null/undefined and non-finite input', () => {
		expect(formatPercent(null)).toBe('—');
		expect(formatPercent('not-a-number')).toBe('—');
	});
});

describe('stateLabel', () => {
	it('maps known states to PT-BR', () => {
		expect(stateLabel('CREATED')).toBe('Criado');
		expect(stateLabel('SENT')).toBe('Enviado');
		expect(stateLabel('QUOTED')).toBe('Cotado');
		expect(stateLabel('AWARDED')).toBe('Premiado');
		expect(stateLabel('CLOSED')).toBe('Fechado');
	});

	it('falls back to raw string for unknown state', () => {
		expect(stateLabel('UNKNOWN')).toBe('UNKNOWN');
	});
});

describe('stateColor', () => {
	it('returns color class for known states', () => {
		expect(stateColor('AWARDED')).toBe('badge pos');
	});

	it('returns fallback for unknown state', () => {
		expect(stateColor('UNKNOWN')).toBe('badge neutral');
	});
});

describe('intentLabel', () => {
	it('maps known intents to PT-BR', () => {
		expect(intentLabel('COMMERCIAL_HEDGE')).toBe('Hedge Comercial');
		expect(intentLabel('GLOBAL_POSITION')).toBe('Posição Global');
		expect(intentLabel('SPREAD')).toBe('Spread');
	});

	it('falls back for unknown intent', () => {
		expect(intentLabel('CUSTOM')).toBe('CUSTOM');
	});
});

describe('directionLabel', () => {
	it('maps BUY/SELL to PT-BR', () => {
		expect(directionLabel('BUY')).toBe('Compra');
		expect(directionLabel('SELL')).toBe('Venda');
	});
});

describe('directionColor', () => {
	it('returns correct color classes', () => {
		expect(directionColor('BUY')).toBe('badge pos');
		expect(directionColor('SELL')).toBe('badge neg');
	});
});
