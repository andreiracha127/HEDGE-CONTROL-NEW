import { client } from '$lib/api/client';
import { items, normalizeRfq, normalizeRfqQuote, requireData } from '$lib/alcast/route-data';

export const load = async ({ params }: { params: { id: string } }) => {
	const rfqId = params.id;
	const [rfqResult, quotesResult, rankingResult, tradeRankingResult, eventsResult] = await Promise.all([
		client.GET('/rfqs/{rfq_id}', { params: { path: { rfq_id: rfqId } } }),
		client.GET('/rfqs/{rfq_id}/quotes', { params: { path: { rfq_id: rfqId } } }),
		client.GET('/rfqs/{rfq_id}/ranking', { params: { path: { rfq_id: rfqId } } }),
		client.GET('/rfqs/{rfq_id}/trade-ranking', { params: { path: { rfq_id: rfqId } } }),
		client.GET('/rfqs/{rfq_id}/state-events', { params: { path: { rfq_id: rfqId } } }),
	]);

	const rfq = normalizeRfq(requireData(rfqResult, 'Failed to load RFQ') as Record<string, any>);
	const ranking = requireData(rankingResult, 'Failed to load RFQ ranking');
	const tradeRanking = requireData(tradeRankingResult, 'Failed to load RFQ trade ranking') as Record<string, any>;
	const quoteRows = items<Record<string, any>>(requireData(quotesResult, 'Failed to load RFQ quotes'));
	const activeQuotes = quoteRows.filter((quote) => quote.state !== 'rejected');
	const spreadBest = rfq.intent === 'SPREAD' ? (ranking as Record<string, any>).ranking?.[0] : null;
	const bestRankedQuote = spreadBest
		? null
		: (tradeRanking.ranking?.[0]?.quote as Record<string, any> | undefined) ??
			activeQuotes
				.slice()
				.sort((a, b) => {
					const left = Number(a.fixed_price_value);
					const right = Number(b.fixed_price_value);
					return rfq.direction === 'SELL' ? right - left : left - right;
				})[0];
	const bestQuoteIds = spreadBest
		? [spreadBest.buy_quote?.id, spreadBest.sell_quote?.id].filter(Boolean).map(String)
		: bestRankedQuote?.id
			? [String(bestRankedQuote.id)]
			: [];
	const bestPrice = bestRankedQuote ? Number(bestRankedQuote.fixed_price_value) : null;
	const quotes = quoteRows.map((quote) =>
		normalizeRfqQuote(quote, {
			bestQuoteIds,
			bestPrice: Number.isFinite(bestPrice) ? bestPrice : null,
		}),
	);
	const stateEvents = items(requireData(eventsResult, 'Failed to load RFQ state events'));

	return {
		rfq,
		rfqs: [rfq],
		quotes,
		ranking,
		tradeRanking,
		stateEvents,
	};
};

