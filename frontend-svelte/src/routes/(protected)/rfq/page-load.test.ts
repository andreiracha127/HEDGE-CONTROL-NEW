import { beforeEach, describe, expect, test, vi } from 'vitest';

const get = vi.fn();

vi.mock('$lib/api/client', () => ({
	client: { GET: get },
}));

describe('rfq list load', () => {
	beforeEach(() => {
		get.mockReset();
	});

	test('loads rfqs and keeps the selected tab', async () => {
		get.mockResolvedValueOnce({ data: { items: [{ id: 'rfq-1', quantity_mt: '1.000', state: 'SENT' }], total: 1 } });

		const { load } = await import('./+page');
		const result = await load({ url: new URL('http://localhost/rfq?tab=SENT') } as never);

		expect(get).toHaveBeenCalledWith('/rfqs', { params: { query: { state: 'SENT', limit: 200 } } });
		expect(result.tab).toBe('SENT');
		expect(result.rfqs[0]).toMatchObject({ id: 'rfq-1', rfq: 'rfq-1', qty: '1.000', state: 'SENT' });
	});
});

