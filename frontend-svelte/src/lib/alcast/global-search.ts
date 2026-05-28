import type { IconName } from '$lib/components/alcast/Icon.svelte';
import { displayCommodityCode, items, normalizeContract, normalizeOrder, normalizeRfq } from './route-data';
import { entityDisplayName, safeBusinessText, stateBadge } from './presentation';

export type GlobalSearchItem = {
	label: string;
	detail: string;
	href: string;
	icon: IconName;
};

export type GlobalSearchGroup = {
	label: string;
	items: GlobalSearchItem[];
};

type SearchClient = {
	get: (path: string, options?: unknown) => Promise<{ data?: unknown; error?: unknown }>;
};

const LIMIT = 8;

function searchStateLabel(value: unknown, fallback = 'Em análise'): string {
	const label = stateBadge(value).label;
	return label === 'Indisponível' || label === 'Não classificado' ? fallback : label;
}

function includesQuery(...values: unknown[]): (query: string) => boolean {
	const haystack = values
		.map((value) => safeBusinessText(value, ''))
		.filter(Boolean)
		.join(' ')
		.toLocaleLowerCase('pt-BR');
	return (query: string) => haystack.includes(query);
}

async function readGroup(
	client: SearchClient,
	path: string,
	options: unknown,
	mapper: (row: Record<string, any>) => GlobalSearchItem | null,
	query: string,
): Promise<GlobalSearchItem[]> {
	try {
		const result = await client.get(path, options);
		if (result.error) return [];
		return items<Record<string, any>>(result.data)
			.map(mapper)
			.filter((item): item is GlobalSearchItem => item != null)
			.filter((item) => includesQuery(item.label, item.detail)(query))
			.slice(0, LIMIT);
	} catch {
		return [];
	}
}

export async function searchGlobal(query: string, client: SearchClient): Promise<GlobalSearchGroup[]> {
	const normalized = query.trim().toLocaleLowerCase('pt-BR');
	if (normalized.length < 2) return [];

	const [counterparties, contracts, rfqs, orders] = await Promise.all([
		readGroup(
			client,
			'/counterparties',
			{ params: { query: { limit: 100 } } },
			(row) => {
				const label = entityDisplayName(row, 'Contraparte sem nome');
				if (!row.id) return null;
				return {
					label,
					detail: `Contraparte · ${searchStateLabel(row.status)}`,
					href: `/counterparties/${row.id}`,
					icon: 'users',
				};
			},
			normalized,
		),
		readGroup(
			client,
			'/contracts/hedge',
			{ params: { query: { limit: 100 } } },
			(row) => {
				const contract = normalizeContract(row);
				if (!row.id) return null;
				return {
					label: safeBusinessText(row.contract_number ?? row.reference, `Contrato ${displayCommodityCode(row.commodity)}`),
					detail: `${safeBusinessText(contract.cp, 'Contraparte não informada')} · ${stateBadge(contract.status).label}`,
					href: `/contracts/${row.id}`,
					icon: 'fileSign',
				};
			},
			normalized,
		),
		readGroup(
			client,
			'/rfqs',
			{ params: { query: { limit: 100 } } },
			(row) => {
				const rfq = normalizeRfq(row);
				if (!row.id) return null;
				return {
					label: safeBusinessText(rfq.rfq, 'RFQ sem número'),
					detail: `${entityDisplayName(row, 'Contraparte não informada')} · ${stateBadge(row.state).label}`,
					href: `/rfq/${row.id}`,
					icon: 'rfq',
				};
			},
			normalized,
		),
		readGroup(
			client,
			'/orders',
			{ params: { query: { limit: 100 } } },
			(row) => {
				const order = normalizeOrder(row);
				if (!row.id) return null;
				return {
					label: safeBusinessText(row.order_number, `Ordem ${safeBusinessText(row.id, '') || 'sem número'}`),
					detail: `${safeBusinessText(order.cp, 'Contraparte não informada')} · ${stateBadge(order.status).label}`,
					href: `/orders/${row.id}`,
					icon: 'clipboard',
				};
			},
			normalized,
		),
	]);

	return [
		{ label: 'Contrapartes', items: counterparties },
		{ label: 'Contratos', items: contracts },
		{ label: 'RFQs', items: rfqs },
		{ label: 'Ordens', items: orders },
	].filter((group) => group.items.length > 0);
}
