/**
 * J-A6-03 — runtime validators for /pl/snapshots and /mtm/snapshots.
 *
 * The acceptance criteria for PR-A6-3 require that missing required
 * Decimal/identifier fields surface as malformed responses instead of
 * silently rendering as zero. True backend zero values (`"0"`, `"0.000"`,
 * `0`) are valid Decimal serialisations and must pass through.
 */
import { describe, it, expect } from 'vitest';
import {
	validatePnlSnapshot,
	validateMtmSnapshot,
} from './analytics-response-shape';

const VALID_PNL = {
	id: '11111111-1111-1111-1111-111111111111',
	entity_type: 'hedge_contract',
	entity_id: '22222222-2222-2222-2222-222222222222',
	period_start: '2026-01-01',
	period_end: '2026-01-31',
	realized_pl: '1234.56',
	unrealized_mtm: '-987.65',
	created_at: '2026-02-01T12:00:00Z',
	correlation_id: 'corr-1',
};

const VALID_MTM = {
	id: '33333333-3333-3333-3333-333333333333',
	object_type: 'hedge_contract',
	object_id: '44444444-4444-4444-4444-444444444444',
	as_of_date: '2026-05-12',
	quantity_mt: '100.000',
	entry_price: '2380.123456',
	price_d1: '2390.654321',
	mtm_value: '1053.21',
	correlation_id: 'corr-2',
	created_at: '2026-05-12T18:00:00Z',
};

describe('validatePnlSnapshot', () => {
	it('accepts a fully populated snapshot', () => {
		const result = validatePnlSnapshot(VALID_PNL);
		expect(result.ok).toBe(true);
		if (result.ok) expect(result.value.realized_pl).toBe('1234.56');
	});

	it('accepts true backend zero values for realized_pl / unrealized_mtm', () => {
		// `"0"` is a valid Decimal serialisation — must not be treated as
		// missing data.
		const zero = { ...VALID_PNL, realized_pl: '0', unrealized_mtm: '0.00' };
		const result = validatePnlSnapshot(zero);
		expect(result.ok).toBe(true);
	});

	it('permits correlation_id to be null (schema: string | null)', () => {
		const result = validatePnlSnapshot({ ...VALID_PNL, correlation_id: null });
		expect(result.ok).toBe(true);
	});

	it.each([
		['realized_pl'],
		['unrealized_mtm'],
		['period_start'],
		['period_end'],
		['id'],
		['entity_type'],
		['entity_id'],
		['created_at'],
	])('rejects missing required field %s', (field) => {
		const body = { ...VALID_PNL };
		delete (body as Record<string, unknown>)[field];
		const result = validatePnlSnapshot(body);
		expect(result.ok).toBe(false);
		if (!result.ok) expect(result.missing).toContain(field);
	});

	it.each([
		['realized_pl'],
		['unrealized_mtm'],
		['period_start'],
		['period_end'],
	])('rejects null on non-nullable required field %s', (field) => {
		const body = { ...VALID_PNL, [field]: null };
		const result = validatePnlSnapshot(body);
		expect(result.ok).toBe(false);
		if (!result.ok) expect(result.missing).toContain(field);
	});

	it('rejects an inverted period window (period_start > period_end)', () => {
		const inverted = {
			...VALID_PNL,
			period_start: '2026-03-01',
			period_end: '2026-01-31',
		};
		const result = validatePnlSnapshot(inverted);
		expect(result.ok).toBe(false);
		if (!result.ok) {
			expect(result.missing.some((m) => m.includes('period_start'))).toBe(true);
		}
	});

	it('rejects non-object payloads', () => {
		expect(validatePnlSnapshot(null).ok).toBe(false);
		expect(validatePnlSnapshot(undefined).ok).toBe(false);
		expect(validatePnlSnapshot('oops').ok).toBe(false);
		expect(validatePnlSnapshot(42).ok).toBe(false);
	});
});

describe('validateMtmSnapshot', () => {
	it('accepts a fully populated snapshot', () => {
		const result = validateMtmSnapshot(VALID_MTM);
		expect(result.ok).toBe(true);
		if (result.ok) expect(result.value.mtm_value).toBe('1053.21');
	});

	it('accepts true backend zero values for mtm_value / entry_price / price_d1', () => {
		const zero = {
			...VALID_MTM,
			mtm_value: '0',
			entry_price: '0.000000',
			price_d1: '0',
		};
		const result = validateMtmSnapshot(zero);
		expect(result.ok).toBe(true);
	});

	it.each([
		['mtm_value'],
		['as_of_date'],
		['object_id'],
		['object_type'],
		['quantity_mt'],
		['entry_price'],
		['price_d1'],
		['id'],
		['created_at'],
	])('rejects missing required field %s', (field) => {
		const body = { ...VALID_MTM };
		delete (body as Record<string, unknown>)[field];
		const result = validateMtmSnapshot(body);
		expect(result.ok).toBe(false);
		if (!result.ok) expect(result.missing).toContain(field);
	});

	it('rejects null correlation_id — MTM schema does not permit null', () => {
		// Per generated `schema.d.ts`:
		//   MTMSnapshotResponse.correlation_id: string  ← not nullable
		const result = validateMtmSnapshot({ ...VALID_MTM, correlation_id: null });
		expect(result.ok).toBe(false);
		if (!result.ok) expect(result.missing).toContain('correlation_id');
	});

	it('rejects null on non-nullable economic fields', () => {
		const result = validateMtmSnapshot({ ...VALID_MTM, mtm_value: null });
		expect(result.ok).toBe(false);
		if (!result.ok) expect(result.missing).toContain('mtm_value');
	});

	it('rejects non-object payloads', () => {
		expect(validateMtmSnapshot(null).ok).toBe(false);
		expect(validateMtmSnapshot([]).ok).toBe(false);
	});
});
