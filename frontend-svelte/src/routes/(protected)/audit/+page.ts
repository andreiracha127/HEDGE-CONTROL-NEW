import { client } from '$lib/api/client';
import { items, normalizeAuditEvent, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const response = await client.GET('/audit/events', { params: { query: { limit: 200 } } });
	const data = requireData(response, 'Failed to load audit events');

	return {
		auditLog: items<Record<string, any>>(data).map(normalizeAuditEvent),
	};
};

