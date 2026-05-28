import { client } from '$lib/api/client';
import { items, normalizeCashflow, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const asOfDate = new Date().toISOString().slice(0, 10);
	const projectionResult = await client.GET('/cashflow/projection', { params: { query: { as_of_date: asOfDate } } });
	const projection = requireData(projectionResult, 'Failed to load cashflow projection');

	return {
		projection,
		cashflow: items<Record<string, any>>(projection).map(normalizeCashflow),
	};
};

