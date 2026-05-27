import { client } from '$lib/api/client';
import { exposureBucketsFrom, items, normalizeCommodity, normalizeRfq, optionalData } from '$lib/alcast/route-data';

export const load = async () => {
	const [globalExposureResult, exposureListResult, rfqsResult, marketResult] = await Promise.allSettled([
		client.GET('/exposures/global'),
		client.GET('/exposures/list', { params: { query: { limit: 200 } } }),
		client.GET('/rfqs', { params: { query: { state: 'SENT', limit: 5 } } }),
		client.GET('/market-data/westmetall/aluminum/cash-settlement/prices', { params: { query: { limit: 2 } } }),
	]);

	const globalExposure = optionalData(globalExposureResult.status === 'fulfilled' ? globalExposureResult.value : null);
	const exposureList = optionalData(exposureListResult.status === 'fulfilled' ? exposureListResult.value : null);
	const rfqsData = optionalData(rfqsResult.status === 'fulfilled' ? rfqsResult.value : null);
	const marketData = optionalData(marketResult.status === 'fulfilled' ? marketResult.value : null);

	return {
		globalExposure,
		rfqs: items<Record<string, any>>(rfqsData).map(normalizeRfq),
		commodities: items<Record<string, any>>(marketData).map(normalizeCommodity),
		exposureBuckets: exposureBucketsFrom(exposureList),
	};
};

