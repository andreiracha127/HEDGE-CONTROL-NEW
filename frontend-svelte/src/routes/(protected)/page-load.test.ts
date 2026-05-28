import { beforeEach, describe, expect, test, vi } from 'vitest';

const get = vi.fn();
let isAuthenticated = true;
let isRestoring = false;

vi.mock('$lib/api/client', () => ({
	client: { GET: get },
}));

vi.mock('$lib/stores/auth.svelte', () => ({
	authStore: {
		get isAuthenticated() {
			return isAuthenticated;
		},
		get isRestoring() {
			return isRestoring;
		},
		whenRestored: async () => {
			if (isRestoring) {
				isRestoring = false;
				isAuthenticated = true;
			}
		},
	},
}));

describe('dashboard load', () => {
	beforeEach(() => {
		get.mockReset();
		isAuthenticated = true;
		isRestoring = false;
	});

	test('returns flat dashboard data from API responses', async () => {
		get
			.mockResolvedValueOnce({ data: { commercial_net_mt: '10.000', hedge_coverage_ratio: '0.5' } })
			.mockResolvedValueOnce({
				data: {
					items: [
						{
							settlement_month: '2026-06',
							commercial_mt: '1000',
							hedged_mt: '500',
						},
					],
				},
			})
			.mockResolvedValueOnce({ data: { items: [{ id: 'rfq-1' }], total: 1 } })
			.mockResolvedValueOnce({ data: [{ symbol: 'AL-LME', value: '2645.50' }] });

		const { load } = await import('./+page');
		const result = await load();

		expect(get).not.toHaveBeenCalledWith('/pl/snapshots', expect.anything());
		expect(get).toHaveBeenCalledWith('/exposures/list', { params: { query: { limit: 200 } } });
		expect(result.rfqs[0]).toMatchObject({ id: 'rfq-1', rfq: 'RFQ sem número' });
		expect(result.commodities[0]).toMatchObject({ code: 'AL-LME', last: 2645.5, prev: null, provider: 'Fonte indisponível' });
		expect((result.globalExposure as any).commercial_net_mt).toBe('10.000');
		expect(result.exposureBuckets).toMatchObject([{ month: '2026-06', commercial_mt: 1000, hedged_mt: 500, ratio: 50 }]);
	});

	test('degrades to empty dashboard collections when API data is unavailable', async () => {
		get
			.mockResolvedValueOnce({ error: { detail: 'missing table' } })
			.mockResolvedValueOnce({ error: { detail: 'missing table' } })
			.mockResolvedValueOnce({ error: { detail: 'missing table' } })
			.mockResolvedValueOnce({ error: { detail: 'missing table' } });

		const { load } = await import('./+page');
		const result = await load();

		expect(result.globalExposure).toBeNull();
		expect(result.rfqs).toEqual([]);
		expect(result.commodities).toEqual([]);
		expect(result.exposureBuckets).toEqual([]);
	});

	test('does not call protected APIs while the session is unauthenticated', async () => {
		isAuthenticated = false;
		isRestoring = false;

		const { load } = await import('./+page');
		const result = await load();

		expect(get).not.toHaveBeenCalled();
		expect(result.globalExposure).toBeNull();
		expect(result.rfqs).toEqual([]);
		expect(result.commodities).toEqual([]);
		expect(result.exposureBuckets).toEqual([]);
	});

	test('waits for session restoration before short-circuiting the dashboard', async () => {
		isAuthenticated = false;
		isRestoring = true;
		get
			.mockResolvedValueOnce({ data: { commercial_net_mt: '10.000' } })
			.mockResolvedValueOnce({ data: { items: [] } })
			.mockResolvedValueOnce({ data: { items: [], total: 0 } })
			.mockResolvedValueOnce({ data: [] });

		const { load } = await import('./+page');
		const result = await load();

		expect(get).toHaveBeenCalledWith('/exposures/global');
		expect((result.globalExposure as any).commercial_net_mt).toBe('10.000');
	});
});
