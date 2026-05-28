import { beforeEach, describe, expect, test, vi } from 'vitest';

const get = vi.fn();

vi.mock('$lib/api/client', () => ({
	client: { GET: get },
}));

describe('contract detail load', () => {
	beforeEach(() => {
		get.mockReset();
	});

	test('returns the contract with related server payloads', async () => {
		get
			.mockResolvedValueOnce({ data: { id: 'ct-1', quantity_mt: '12.000', fixed_price_value: '2640.00' } })
			.mockResolvedValueOnce({ data: { items: [{ order_id: 'ord-1' }] } })
			.mockResolvedValueOnce({ data: { mtm_value: '10.00' } })
			.mockResolvedValueOnce({ data: { items: [{ amount_usd: '10.00' }] } })
			.mockResolvedValueOnce({ data: { items: [] } });

		const { load } = await import('./+page');
		const result = await load({ params: { id: 'ct-1' } } as never);

		expect(get).toHaveBeenCalledWith('/contracts/hedge/{contract_id}', { params: { path: { contract_id: 'ct-1' } } });
		expect(get).toHaveBeenCalledWith('/mtm/hedge-contracts/{contract_id}', expect.objectContaining({ params: expect.objectContaining({ query: expect.any(Object) }) }));
		expect(result.contracts[0].id).toBe('ct-1');
		expect(result.linkages).toEqual([{ order_id: 'ord-1' }]);
	});
});

