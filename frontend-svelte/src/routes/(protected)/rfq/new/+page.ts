import { client } from '$lib/api/client';
import { items, normalizeCounterparty, normalizeOrder, optionalData } from '$lib/alcast/route-data';

export const load = async () => {
	const [counterpartiesResponse, ordersResponse] = await Promise.all([
		client.GET('/counterparties', { params: { query: { limit: 200 } } }),
		client.GET('/orders', { params: { query: { limit: 200 } } }),
	]);
	const counterpartyData = optionalData(counterpartiesResponse);
	const orderData = optionalData(ordersResponse);

	return {
		counterparties: items<Record<string, any>>(counterpartyData).map(normalizeCounterparty),
		orders: items<Record<string, any>>(orderData).map(normalizeOrder),
	};
};
