import { client } from '$lib/api/client';
import { exposureBucketsFrom, requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const [listResult, netResult, tasksResult] = await Promise.all([
		client.GET('/exposures/list', { params: { query: { limit: 200 } } }),
		client.GET('/exposures/net'),
		client.GET('/exposures/tasks'),
	]);

	const exposureList = requireData(listResult, 'Failed to load exposures');
	const netExposure = requireData(netResult, 'Failed to load net exposure');
	const tasks = requireData(tasksResult, 'Failed to load exposure tasks');

	return {
		exposureBuckets: exposureBucketsFrom(exposureList),
		netExposure,
		tasks,
	};
};

