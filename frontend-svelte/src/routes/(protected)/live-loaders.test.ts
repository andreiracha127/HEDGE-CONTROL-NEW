import { beforeEach, describe, expect, test, vi } from 'vitest';

const get = vi.fn();

vi.mock('$lib/api/client', () => ({
	client: { GET: get },
}));

describe('protected live-data loaders', () => {
	beforeEach(() => {
		get.mockReset();
	});

	test('loads exposures from list, net, and hedge-task endpoints without prototype rows', async () => {
		get
			.mockResolvedValueOnce({ data: { items: [] } })
			.mockResolvedValueOnce({ data: { items: [] } })
			.mockResolvedValueOnce({ data: { items: [] } });

		const { load } = await import('./exposures/+page');
		const result = await load();

		expect(get).toHaveBeenCalledWith('/exposures/list', { params: { query: { limit: 200 } } });
		expect(get).toHaveBeenCalledWith('/exposures/net');
		expect(get).toHaveBeenCalledWith('/exposures/tasks');
		expect(result.exposureRows).toEqual([]);
		expect(result.exposureBuckets).toEqual([]);
		expect(result.netExposure).toEqual({ items: [] });
		expect(result.tasks).toEqual({ items: [] });
	});

	test('loads market data only from the Westmetall cash-settlement endpoint', async () => {
		get.mockResolvedValueOnce({ data: [] });

		const { load } = await import('./market-data/+page');
		const result = await load();

		expect(get).toHaveBeenCalledTimes(1);
		expect(get).toHaveBeenCalledWith('/market-data/westmetall/aluminum/cash-settlement/prices', {
			params: { query: { limit: 90 } },
		});
		expect(result.commodities).toEqual([]);
	});

	test('loads MTM analytics from hedge contracts without scenario or price fallbacks', async () => {
		get.mockResolvedValueOnce({ data: { items: [] } });

		const { load } = await import('./analytics/mtm/+page');
		const result = await load();

		expect(get).toHaveBeenCalledTimes(1);
		expect(get).toHaveBeenCalledWith('/contracts/hedge', { params: { query: { limit: 200 } } });
		expect(result.contracts).toEqual([]);
	});
});
