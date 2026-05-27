import { client } from '$lib/api/client';
import { normalizeCounterparty, requireData } from '$lib/alcast/route-data';

export const load = async ({ params }: { params: { id: string } }) => {
	const counterpartyResult = await client.GET('/counterparties/{counterparty_id}', { params: { path: { counterparty_id: params.id } } });

	const counterparty = normalizeCounterparty(requireData(counterpartyResult, 'Failed to load counterparty') as Record<string, any>);

	return {
		counterparties: [counterparty],
		counterparty,
		contracts: [],
	};
};

