import { client } from '$lib/api/client';
import { exposureBucketsFrom, items, normalizeCommodity, normalizeRfq, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const [globalExposureResult, exposureListResult, rfqsResult, marketResult] = await Promise.all([
		client.GET('/exposures/global'),
		client.GET('/exposures/list', { params: { query: { limit: 200 } } }),
		client.GET('/rfqs', { params: { query: { state: 'SENT', limit: 5 } } }),
		client.GET('/market-data/westmetall/aluminum/cash-settlement/prices', { params: { query: { limit: 2 } } }),
	]);

	const globalExposure = requireData(globalExposureResult, 'Failed to load global exposure');
	const exposureList = requireData(exposureListResult, 'Failed to load exposure buckets');
	const rfqsData = requireData(rfqsResult, 'Failed to load RFQs');
	const marketData = requireData(marketResult, 'Failed to load market data');

	return {
		globalExposure,
		rfqs: items<Record<string, any>>(rfqsData).map(normalizeRfq),
		commodities: items<Record<string, any>>(marketData).map(normalizeCommodity),
		exposureBuckets: exposureBucketsFrom(exposureList),
	};
};

