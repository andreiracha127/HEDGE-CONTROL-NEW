import { client } from '$lib/api/client';
import { items, normalizeOrder, requireData, total } from '$lib/alcast/route-data';

export const load = async () => {
	const response = await client.GET('/orders', { params: { query: { limit: 200 } } });
	const data = requireData(response, 'Failed to load orders');

	return {
		orders: items<Record<string, any>>(data).map(normalizeOrder),
		total: total(data),
	};
};

