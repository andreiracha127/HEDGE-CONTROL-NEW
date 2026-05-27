import { client } from '$lib/api/client';
import { items, normalizeCounterparty, normalizeOrder, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const [counterpartiesResponse, ordersResponse] = await Promise.all([
		client.GET('/counterparties', { params: { query: { limit: 200 } } }),
		client.GET('/orders', { params: { query: { limit: 200 } } }),
	]);
	const counterpartyData = requireData(counterpartiesResponse, 'Failed to load counterparties');
	const orderData = requireData(ordersResponse, 'Failed to load orders');

	return {
		counterparties: items<Record<string, any>>(counterpartyData).map(normalizeCounterparty),
		orders: items<Record<string, any>>(orderData).map(normalizeOrder),
	};
};
