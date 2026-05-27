import { client } from '$lib/api/client';
import { items, normalizeContract, requireData, total } from '$lib/alcast/route-data';

export const load = async () => {
	const response = await client.GET('/contracts/hedge', { params: { query: { limit: 200 } } });
	const data = requireData(response, 'Failed to load contracts');

	return {
		contracts: items<Record<string, any>>(data).map(normalizeContract),
		total: total(data),
	};
};

