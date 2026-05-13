/**
 * J-A6-11 — frontend MT quantity precision matches backend MTQuantity
 * (NUMERIC scale 3, see `backend/app/core/precision.py`).
 *
 * The submitted form value must remain a decimal *string* so neither
 * `Number()` coercion nor IEEE-754 representation truncates trailing
 * digits before the request leaves the browser.
 */
import { describe, it, expect } from 'vitest';
import { validateMtQuantity } from './quantity';

describe('validateMtQuantity', () => {
	it('accepts three-decimal quantities exactly as typed', () => {
		const r = validateMtQuantity('123.456');
		expect(r.ok).toBe(true);
		if (r.ok) expect(r.canonical).toBe('123.456');
	});

	it('accepts integer, one-decimal and two-decimal quantities', () => {
		for (const v of ['100', '100.5', '100.50']) {
			const r = validateMtQuantity(v);
			expect(r.ok).toBe(true);
			if (r.ok) expect(r.canonical).toBe(v);
		}
	});

	it('rejects four or more decimal places with a precision-specific error', () => {
		const r = validateMtQuantity('123.4567');
		expect(r.ok).toBe(false);
		if (!r.ok) expect(r.reason).toMatch(/3 casas decimais/);
	});

	it('rejects empty / whitespace input as required', () => {
		expect(validateMtQuantity('').ok).toBe(false);
		expect(validateMtQuantity('   ').ok).toBe(false);
		expect(validateMtQuantity(null).ok).toBe(false);
		expect(validateMtQuantity(undefined).ok).toBe(false);
	});

	it('rejects zero and negative quantities (no trades on zero MT)', () => {
		expect(validateMtQuantity('0').ok).toBe(false);
		expect(validateMtQuantity('0.000').ok).toBe(false);
		expect(validateMtQuantity('-1').ok).toBe(false);
	});

	it('rejects non-numeric input', () => {
		for (const v of ['abc', '1,5', '1.5.5', '1e3', '+5', '5 MT']) {
			expect(validateMtQuantity(v).ok).toBe(false);
		}
	});

	it('preserves the literal user input as the canonical payload value', () => {
		// `123.000` MT and `123` MT must serialise differently — Decimal
		// scale carries trading-desk semantics (signalled precision).
		const padded = validateMtQuantity('123.000');
		expect(padded.ok).toBe(true);
		if (padded.ok) expect(padded.canonical).toBe('123.000');
		const bare = validateMtQuantity('123');
		expect(bare.ok).toBe(true);
		if (bare.ok) expect(bare.canonical).toBe('123');
	});
});
