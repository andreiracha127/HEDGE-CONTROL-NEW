import { describe, expect, it, vi } from 'vitest';
import { searchGlobal } from './global-search';

describe('global institutional search', () => {
	it('returns grouped business results from existing list endpoints', async () => {
		const get = vi.fn(async (path: string) => {
			if (path === '/counterparties') {
				return { data: { items: [{ id: 'cp-1', legal_name: 'Marex Spectron', short_name: 'Marex' }] } };
			}
			if (path === '/contracts/hedge') {
				return { data: { items: [{ id: 'ct-1', counterparty_name: 'Marex Spectron', commodity: 'ALUMINUM' }] } };
			}
			if (path === '/rfqs') {
				return { data: { items: [{ id: 'rfq-1', rfq_number: 'RFQ-2026-0001', state: 'SENT', counterparty_name: 'Marex Spectron' }] } };
			}
			if (path === '/orders') {
				return { data: { items: [{ id: 'ord-1', order_type: 'SO', counterparty_name: 'Marex Spectron' }] } };
			}
			return { data: { items: [] } };
		});

		const results = await searchGlobal('marex', { get });

		expect(get).toHaveBeenCalledWith('/counterparties', expect.anything());
		expect(results.map((group) => group.label)).toEqual(['Contrapartes', 'Contratos', 'RFQs', 'Ordens']);
		expect(results[0].items[0]).toMatchObject({ label: 'Marex Spectron', href: '/counterparties/cp-1' });
		expect(results[0].items[0].detail).toBe('Contraparte · Em análise');
		expect(results.flatMap((group) => group.items).map((item) => item.detail).join(' ')).not.toMatch(/state=|\/rfqs|backend|payload/i);
	});

	it('survives partial endpoint failures and returns the successful groups', async () => {
		const get = vi.fn(async (path: string) => {
			if (path === '/rfqs') throw new Error('network');
			if (path === '/counterparties') return { data: { items: [{ id: 'cp-1', short_name: 'Itau BBA' }] } };
			return { data: { items: [] } };
		});

		const results = await searchGlobal('itau', { get });

		expect(results).toHaveLength(1);
		expect(results[0]).toMatchObject({ label: 'Contrapartes' });
	});
});
