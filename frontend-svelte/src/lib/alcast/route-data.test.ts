import { describe, expect, it } from 'vitest';
import { exposureBucketsFrom } from './route-data';

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
