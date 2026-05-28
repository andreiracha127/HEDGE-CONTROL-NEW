import { client } from '$lib/api/client';
import { items, normalizeRfq, normalizeRfqQuote, optionalData, requireData } from '$lib/alcast/route-data';

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
	const ranking = requireData(rankingResult, 'Failed to load RFQ ranking') as Record<string, any>;
	const tradeRanking = (
		rfq.intent === 'SPREAD'
			? optionalData(tradeRankingResult)
			: requireData(tradeRankingResult, 'Failed to load RFQ trade ranking')
	) as Record<string, any> | null;
	const quoteRows = items<Record<string, any>>(requireData(quotesResult, 'Failed to load RFQ quotes'));
	const activeQuotes = quoteRows.filter((quote) => quote.state !== 'rejected');
	const spreadBest = rfq.intent === 'SPREAD' ? (ranking as Record<string, any>).ranking?.[0] : null;
	const tradeRankingRows = Array.isArray(tradeRanking?.ranking) ? tradeRanking.ranking : [];
	const rankedQuoteIds = tradeRankingRows
		.map((entry: Record<string, any>) => entry.quote?.id)
		.filter(Boolean)
		.map(String);
	const bestRankedQuote = spreadBest
		? null
		: tradeRankingRows[0]?.quote as Record<string, any> | undefined;
	const bestQuoteIds = spreadBest
		? [spreadBest.buy_quote?.id, spreadBest.sell_quote?.id].filter(Boolean).map(String)
		: bestRankedQuote?.id
			? [String(bestRankedQuote.id)]
			: [];
	const bestPrice = bestRankedQuote ? Number(bestRankedQuote.fixed_price_value) : null;
	const quoteRank = new Map(rankedQuoteIds.map((id: string, index: number) => [id, index]));
	const rankedQuotes = activeQuotes
		.slice()
		.sort((a, b) => (quoteRank.get(String(a.id)) ?? Number.MAX_SAFE_INTEGER) - (quoteRank.get(String(b.id)) ?? Number.MAX_SAFE_INTEGER));
	const rejectedQuotes = quoteRows.filter((quote) => quote.state === 'rejected');
	const quotes = [...rankedQuotes, ...rejectedQuotes].map((quote) =>
		normalizeRfqQuote(quote, {
			bestQuoteIds,
			bestPrice: Number.isFinite(bestPrice) ? bestPrice : null,
		}),
	);
	const stateEvents = items(requireData(eventsResult, 'Failed to load RFQ state events'));
	const canAwardRfq = Boolean(spreadBest?.buy_quote?.id && spreadBest?.sell_quote?.id) || bestQuoteIds.length > 0;

	return {
		rfq,
		rfqs: [rfq],
		quotes,
		ranking,
		tradeRanking,
		canAwardRfq,
		stateEvents,
	};
};
