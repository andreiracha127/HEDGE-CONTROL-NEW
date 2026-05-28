import { client } from '$lib/api/client';
import { items, normalizeContract, optionalData, total } from '$lib/alcast/route-data';

export const load = async () => {
	const response = await client.GET('/contracts/hedge', { params: { query: { limit: 200 } } });
	const data = optionalData(response);

	return {
		contracts: items<Record<string, any>>(data).map(normalizeContract),
		total: total(data),
	};
};

