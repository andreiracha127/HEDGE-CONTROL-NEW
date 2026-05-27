import { client } from '$lib/api/client';
import { items, normalizeRfq, optionalData, total } from '$lib/alcast/route-data';

export const load = async ({ url }: { url: URL }) => {
	const tab = url.searchParams.get('tab') ?? 'all';
	const query = tab === 'all' ? { limit: 200 } : { state: tab, limit: 200 };
	const response = await client.GET('/rfqs', { params: { query } });
	const data = optionalData(response);

	return {
		rfqs: items<Record<string, any>>(data).map(normalizeRfq),
		total: total(data),
		tab,
	};
};

