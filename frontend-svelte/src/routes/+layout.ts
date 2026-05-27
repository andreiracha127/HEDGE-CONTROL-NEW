import { client } from '$lib/api/client';

const safeCount = (result: PromiseSettledResult<{ data?: unknown }>): number | null => {
	if (result.status !== 'fulfilled' || !result.value.data) return null;
	const data = result.value.data as { total?: number; items?: unknown[] };
	const total = data.total ?? data.items?.length ?? null;
	return total && total > 0 ? total : null;
};

export const load = async () => {
	const [rfqs, orders, approvals] = await Promise.allSettled([
		client.GET('/rfqs', { params: { query: { state: 'SENT', limit: 1 } } }),
		client.GET('/orders', { params: { query: { limit: 1 } } }),
		client.GET('/workflow-approvals', { params: { query: { status: 'pending', limit: 1 } } }),
	]);

	return {
		navBadges: {
			rfqOpen: safeCount(rfqs),
			ordersToday: safeCount(orders),
			approvalsPending: safeCount(approvals),
		},
	};
};
