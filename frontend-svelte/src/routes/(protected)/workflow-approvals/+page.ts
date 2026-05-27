import { client } from '$lib/api/client';
import { items, requireData, total } from '$lib/alcast/route-data';

export const load = async () => {
	const response = await client.GET('/workflow-approvals', {
		params: { query: { status: 'pending', limit: 50 } },
	});
	const data = requireData(response, 'Failed to load workflow approvals');

	return {
		approvals: items<Record<string, any>>(data),
		total: total(data),
	};
};
