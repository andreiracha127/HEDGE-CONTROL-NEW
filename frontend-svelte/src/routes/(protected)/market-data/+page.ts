import { client } from '$lib/api/client';
import { items, normalizeCommodity, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const response = await client.GET('/market-data/westmetall/aluminum/cash-settlement/prices', { params: { query: { limit: 90 } } });
	const data = requireData(response, 'Failed to load market data');

	return {
		commodities: items<Record<string, any>>(data).map(normalizeCommodity),
	};
};

