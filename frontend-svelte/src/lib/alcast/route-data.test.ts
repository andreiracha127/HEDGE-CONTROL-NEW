import { describe, expect, it } from 'vitest';
import { exposureBucketsFrom, normalizeCashflow, normalizeCommodity, normalizeRfqQuote } from './route-data';

describe('exposureBucketsFrom', () => {
	it('normalizes live exposure-list rows into bucket-shaped numeric fields', () => {
		const buckets = exposureBucketsFrom({
			items: [
				{
					settlement_month: '2026-08',
					original_tons: '100.000',
					open_tons: '40.000',
					hedged_tons: '60.000',
				},
			],
		});

		expect(buckets).toEqual([
			expect.objectContaining({
				month: '2026-08',
				commercial_mt: 100,
				hedged_mt: 60,
				residual_mt: 40,
				ratio: 60,
			}),
		]);
	});

	it('converts fractional coverage ratios to display percentages', () => {
		const [bucket] = exposureBucketsFrom({
			items: [{ month: '2026-09', commercial_net_mt: '200.000', hedged_tons: '80.000', hedge_coverage_ratio: '0.4' }],
		});

		expect(bucket.ratio).toBe(40);
	});
});

describe('live API row normalizers', () => {
	it('coerces cashflow Decimal strings before UI aggregation', () => {
		expect(normalizeCashflow({ amount_usd: '125.50', cashflow_date: '2026-06-01' })).toMatchObject({
			amount_usd: 125.5,
			direction: 'in',
		});
		expect(normalizeCashflow({ amount_usd: '-10.00', cashflow_date: '2026-06-01' })).toMatchObject({
			amount_usd: -10,
			direction: 'out',
		});
	});

	it('keeps missing previous market prices unavailable instead of fabricating zero', () => {
		expect(normalizeCommodity({ symbol: 'AL-LME', price_usd: '2645.500000' })).toMatchObject({
			code: 'AL-LME',
			last: 2645.5,
			prev: null,
		});
	});

	it('maps RFQQuoteRead fields into table fields with a stable key and best flag', () => {
		expect(
			normalizeRfqQuote(
				{ id: 'q-1', counterparty_id: 'cp-1', fixed_price_value: '2638.50', received_at: '2026-05-27T12:00:00Z', state: 'active' },
				{ bestQuoteId: 'q-1', bestPrice: 2638.5 },
			),
		).toMatchObject({
			id: 'q-1',
			cp: 'cp-1',
			price: 2638.5,
			spread: 0,
			received: '2026-05-27T12:00:00Z',
			status: 'best',
		});
	});
});
