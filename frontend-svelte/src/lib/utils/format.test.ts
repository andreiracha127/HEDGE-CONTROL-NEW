import { describe, it, expect } from 'vitest';
import {
	formatDate,
	formatNumber,
	formatQuantityMT,
	formatPrice,
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
		expect(stateColor('AWARDED')).toContain('success');
	});

	it('returns fallback for unknown state', () => {
		expect(stateColor('UNKNOWN')).toContain('surface');
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
		expect(directionColor('BUY')).toBe('text-success');
		expect(directionColor('SELL')).toBe('text-danger');
	});
});
