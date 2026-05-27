import { client } from '$lib/api/client';
import { items, normalizeContract, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const contractsResult = await client.GET('/contracts/hedge', { params: { query: { limit: 200 } } });
	const contracts = items<Record<string, any>>(requireData(contractsResult, 'Failed to load contracts')).map(normalizeContract);

	return {
		contracts,
	};
};

