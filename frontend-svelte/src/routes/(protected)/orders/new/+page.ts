import { client } from '$lib/api/client';
import { items, normalizeCounterparty, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const response = await client.GET('/counterparties', { params: { query: { limit: 200 } } });
	const data = requireData(response, 'Failed to load counterparties');

	return {
		counterparties: items<Record<string, any>>(data).map(normalizeCounterparty),
	};
};

