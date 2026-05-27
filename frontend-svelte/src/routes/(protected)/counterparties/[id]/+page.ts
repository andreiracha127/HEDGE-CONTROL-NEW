import { client } from '$lib/api/client';
import { items, normalizeContract, normalizeCounterparty, requireData } from '$lib/alcast/route-data';

export const load = async ({ params }: { params: { id: string } }) => {
	const [counterpartyResult, contractsResult] = await Promise.all([
		client.GET('/counterparties/{counterparty_id}', { params: { path: { counterparty_id: params.id } } }),
		client.GET('/contracts/hedge', { params: { query: { limit: 200 } } }),
	]);

	const counterparty = normalizeCounterparty(requireData(counterpartyResult, 'Failed to load counterparty') as Record<string, any>);
	const contracts = items<Record<string, any>>(requireData(contractsResult, 'Failed to load counterparty contracts')).map(normalizeContract);

	return {
		counterparties: [counterparty],
		counterparty,
		contracts,
	};
};

