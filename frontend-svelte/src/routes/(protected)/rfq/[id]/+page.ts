import { client } from '$lib/api/client';
import { items, normalizeRfq, requireData } from '$lib/alcast/route-data';

export const load = async ({ params }: { params: { id: string } }) => {
	const rfqId = params.id;
	const [rfqResult, quotesResult, rankingResult, eventsResult] = await Promise.all([
		client.GET('/rfqs/{rfq_id}', { params: { path: { rfq_id: rfqId } } }),
		client.GET('/rfqs/{rfq_id}/quotes', { params: { path: { rfq_id: rfqId } } }),
		client.GET('/rfqs/{rfq_id}/ranking', { params: { path: { rfq_id: rfqId } } }),
		client.GET('/rfqs/{rfq_id}/state-events', { params: { path: { rfq_id: rfqId } } }),
	]);

	const rfq = normalizeRfq(requireData(rfqResult, 'Failed to load RFQ') as Record<string, any>);
	const quotes = items<Record<string, any>>(requireData(quotesResult, 'Failed to load RFQ quotes'));
	const ranking = requireData(rankingResult, 'Failed to load RFQ ranking');
	const stateEvents = items(requireData(eventsResult, 'Failed to load RFQ state events'));

	return {
		rfq,
		rfqs: [rfq],
		quotes,
		ranking,
		stateEvents,
	};
};

