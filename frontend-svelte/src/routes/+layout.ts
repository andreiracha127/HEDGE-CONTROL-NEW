import { client } from '$lib/api/client';
import { authStore } from '$lib/stores/auth.svelte';

export const ssr = false;

type ListEnvelope = {
	total?: number | null;
	items?: unknown[];
	next_cursor?: string | null;
};

type ListResult = {
	data?: unknown;
	error?: unknown;
};

const safeBadge = (count: number): number | null => (count > 0 ? count : null);

const countList = async (fetchPage: (cursor?: string) => Promise<ListResult>): Promise<number | null> => {
	let cursor: string | undefined;
	let count = 0;
	for (let page = 0; page < 20; page += 1) {
		const result = await fetchPage(cursor);
		if (result.error || !result.data) return safeBadge(count);
		const data = result.data as ListEnvelope;
		if (typeof data.total === 'number') return safeBadge(data.total);
		count += data.items?.length ?? 0;
		cursor = data.next_cursor ?? undefined;
		if (!cursor) break;
	}
	return safeBadge(count);
};

export const load = async () => {
	if (!authStore.isAuthenticated) {
		return {
			navBadges: {
				rfqOpen: null,
				ordersToday: null,
				approvalsPending: null,
			},
		};
	}

	const [rfqOpen, ordersToday, approvalsPending] = await Promise.all([
		countList((cursor) => client.GET('/rfqs', { params: { query: { state: 'SENT', limit: 200, cursor } } })),
		countList((cursor) => client.GET('/orders', { params: { query: { limit: 200, cursor } } })),
		countList((cursor) => client.GET('/workflow-approvals', { params: { query: { status: 'pending', limit: 200, cursor } } })),
	]);

	return {
		navBadges: {
			rfqOpen,
			ordersToday,
			approvalsPending,
		},
	};
};
