import { describe, it, expect } from 'vitest';
import {
	formatDate,
	formatNumber,
	formatQuantityMT,
	formatCurrency,
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

	it('returns dash for null/undefined and non-finite input', () => {
		expect(formatQuantityMT(null)).toBe('—');
		expect(formatQuantityMT(undefined)).toBe('—');
		expect(formatQuantityMT('not-a-number')).toBe('—');
	});
});

describe('formatCurrency', () => {
	it('appends unit when provided', () => {
		const result = formatCurrency(1000, 'USD/MT');
		expect(result).toContain('USD/MT');
	});

	it('omits unit when not provided', () => {
		const result = formatCurrency(1000);
		expect(result).not.toContain('USD');
	});

	it('returns dash for null', () => {
		expect(formatCurrency(null)).toBe('—');
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
