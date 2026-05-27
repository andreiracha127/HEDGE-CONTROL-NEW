import { client } from '$lib/api/client';
import { items, normalizeContract, normalizeCounterparty, requireData } from '$lib/alcast/route-data';

export const load = async ({ params }: { params: { id: string } }) => {
	const contractId = params.id;
	const asOfDate = new Date().toISOString().slice(0, 10);
	const [contractResult, linkagesResult, mtmResult, cashflowResult, counterpartiesResult] = await Promise.all([
		client.GET('/contracts/hedge/{contract_id}', { params: { path: { contract_id: contractId } } }),
		client.GET('/contracts/hedge/{contract_id}/linkages', { params: { path: { contract_id: contractId } } }),
		client.GET('/mtm/hedge-contracts/{contract_id}', { params: { path: { contract_id: contractId }, query: { as_of_date: asOfDate } } }),
		client.GET('/cashflow/ledger/hedge-contracts/{contract_id}', { params: { path: { contract_id: contractId } } }),
		client.GET('/counterparties', { params: { query: { limit: 200 } } }),
	]);

	const contract = normalizeContract(requireData(contractResult, 'Failed to load contract') as Record<string, any>);
	const linkages = items(requireData(linkagesResult, 'Failed to load contract linkages'));
	const mtm = requireData(mtmResult, 'Failed to load contract MTM');
	const cashflow = items(requireData(cashflowResult, 'Failed to load contract cashflow'));
	const counterparties = items<Record<string, any>>(requireData(counterpartiesResult, 'Failed to load counterparties')).map(normalizeCounterparty);
	const enrichedContract: Record<string, any> = {
		...contract,
		mtm: (mtm as Record<string, any>).mtm_value ?? contract.mtm,
	};

	return {
		contract: enrichedContract,
		contracts: [enrichedContract],
		linkages,
		mtm,
		cashflow,
		counterparties,
	};
};

