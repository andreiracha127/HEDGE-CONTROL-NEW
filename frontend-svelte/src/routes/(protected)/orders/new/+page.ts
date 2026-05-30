import { client } from '$lib/api/client';
import { items, normalizeCounterparty, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	// Orders reference commercial_partners (customers/suppliers) after W1, NOT hedge
	// counterparties (brokers/banks). The /counterparties endpoint is hedge-only and
	// returns an empty list to traders, so the order form must source the selectable
	// customer/supplier here. Both kinds are loaded; the form filters by order kind.
	const response = await client.GET('/commercial-partners', {
		params: { query: { limit: 200 } },
	});
	const data = requireData(response, 'Failed to load commercial partners');

	return {
		counterparties: items<Record<string, any>>(data).map(normalizeCounterparty),
	};
};

