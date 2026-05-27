import { client } from '$lib/api/client';
import { exposureBucketsFrom, items, normalizeCommodity, normalizeRfq, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const [globalExposureResult, plResult, rfqsResult, marketResult] = await Promise.all([
		client.GET('/exposures/global'),
		client.GET('/pl/snapshots', {
			params: {
				query: {
					entity_type: 'portfolio',
					entity_id: 'global',
					period_start: new Date().toISOString().slice(0, 8) + '01',
					period_end: new Date().toISOString().slice(0, 10),
				},
			},
		}),
		client.GET('/rfqs', { params: { query: { state: 'SENT', limit: 5 } } }),
		client.GET('/market-data/westmetall/aluminum/cash-settlement/prices', { params: { query: { limit: 2 } } }),
	]);

	const globalExposure = requireData(globalExposureResult, 'Failed to load global exposure');
	const plSnapshot = requireData(plResult, 'Failed to load P&L snapshot');
	const rfqsData = requireData(rfqsResult, 'Failed to load RFQs');
	const marketData = requireData(marketResult, 'Failed to load market data');

	return {
		globalExposure,
		plSnapshot,
		rfqs: items<Record<string, any>>(rfqsData).map(normalizeRfq),
		commodities: items<Record<string, any>>(marketData).map(normalizeCommodity),
		exposureBuckets: exposureBucketsFrom(globalExposure),
	};
};

