import { beforeEach, describe, expect, test, vi } from 'vitest';

const get = vi.fn();

vi.mock('$lib/api/client', () => ({
	client: { GET: get },
}));

describe('dashboard load', () => {
	beforeEach(() => {
		get.mockReset();
	});

	test('returns flat dashboard data from API responses', async () => {
		get
			.mockResolvedValueOnce({ data: { commercial_net_mt: '10.000', hedge_coverage_ratio: '0.5' } })
			.mockResolvedValueOnce({ data: { realized_pl: '100', unrealized_mtm: '50' } })
			.mockResolvedValueOnce({ data: { items: [{ id: 'rfq-1' }], total: 1 } })
			.mockResolvedValueOnce({ data: [{ symbol: 'AL-LME', value: '2645.50' }] });

		const { load } = await import('./+page');
		const result = await load();

		expect(result.rfqs[0]).toMatchObject({ id: 'rfq-1', rfq: 'rfq-1' });
		expect(result.commodities[0]).toMatchObject({ code: 'AL-LME', last: 2645.5, prev: null, provider: '—' });
		expect((result.globalExposure as any).commercial_net_mt).toBe('10.000');
	});
});

