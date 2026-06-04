import { client } from '$lib/api/client';
import { requireData } from '$lib/alcast/route-data';

export const load = async () => {
	const snapshotDate = new Date().toISOString().slice(0, 10);
	const response = await client.POST('/deals/pnl-breakdown', {
		body: {
			deal_ids: [],
			snapshot_date: snapshotDate,
		},
	});
	const pnl = requireData(response, 'Failed to load P&L');

	return {
		pnl,
		snapshotDate,
	};
};

