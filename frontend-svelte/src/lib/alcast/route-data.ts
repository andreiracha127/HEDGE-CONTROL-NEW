import { error } from '@sveltejs/kit';
import {
	actionLabel,
	displayActor,
	entityDisplayName,
	safeBusinessText,
	sourceLabel,
} from './presentation';

type ApiResult<T = unknown> = {
	data?: T | null;
	error?: { detail?: unknown; status?: number; statusCode?: number } | null;
	response?: { status?: number } | null;
};

export function requireData<T>(result: ApiResult<T>, message: string): T {
	if (result.error) {
		error(result.response?.status ?? result.error.status ?? result.error.statusCode ?? 502, message);
	}
	if (result.data == null) error(result.response?.status ?? 502, message);
	return result.data;
}

export function optionalData<T>(result: ApiResult<T> | null | undefined): T | null {
	if (!result || result.error || result.data == null) return null;
	return result.data;
}

export function items<T = Record<string, unknown>>(data: unknown): T[] {
	if (Array.isArray(data)) return data as T[];
	if (data && typeof data === 'object') {
		const record = data as { items?: T[]; events?: T[]; cashflow_items?: T[] };
		return record.items ?? record.events ?? record.cashflow_items ?? [];
	}
	return [];
}

export function total(data: unknown): number {
	if (data && typeof data === 'object' && 'total' in data && typeof (data as { total?: unknown }).total === 'number') {
		return (data as { total: number }).total;
	}
	return items(data).length;
}

const numberOrNull = (value: unknown): number | null => {
	if (value == null || value === '') return null;
	const parsed = Number(value);
	return Number.isFinite(parsed) ? parsed : null;
};

const datePart = (value: unknown): string => (typeof value === 'string' ? value.slice(0, 10) : '');
const monthPart = (value: unknown): string => (typeof value === 'string' ? value.slice(0, 7) : '');

function signedExposureAmount(row: Record<string, any>, value: number): number {
	const direction = String(row.direction ?? row.exposure_direction ?? row.side ?? '').toLowerCase();
	if (['long', 'buy', 'purchase', 'po'].includes(direction)) return -Math.abs(value);
	if (['short', 'sell', 'sales', 'so'].includes(direction)) return Math.abs(value);
	return value;
}

export function canonicalCommodityCode(value: unknown): string {
	const raw = String(value ?? '').trim().toUpperCase();
	if (raw === 'ALUMINIUM' || raw === 'ALUMINUM' || raw === 'AL-LME' || raw === 'LME_ALUMINUM') return 'ALUMINUM';
	if (raw === 'COPPER' || raw === 'CU-LME' || raw === 'LME_COPPER') return 'COPPER';
	if (raw === 'ZINC' || raw === 'ZN-LME' || raw === 'LME_ZINC') return 'ZINC';
	if (raw === 'NICKEL' || raw === 'NI-LME' || raw === 'LME_NICKEL') return 'NICKEL';
	if (raw === 'USD/BRL') return 'USDBRL';
	return raw || '—';
}

export function displayCommodityCode(value: unknown): string {
	const canonical = canonicalCommodityCode(value);
	if (canonical === 'ALUMINUM') return 'AL-LME';
	if (canonical === 'COPPER') return 'CU-LME';
	if (canonical === 'ZINC') return 'ZN-LME';
	if (canonical === 'NICKEL') return 'NI-LME';
	return canonical;
}

export function normalizeRfq(row: Record<string, any>): Record<string, any> {
	return {
		...row,
		id: row.id,
		rfq: safeBusinessText(row.rfq_number, 'RFQ sem número'),
		qty: row.quantity_mt ?? row.qty,
		direction: row.direction,
		window: row.delivery_window_start ? datePart(row.delivery_window_start).slice(0, 7) : row.window,
		delivery_start: row.delivery_window_start ?? row.delivery_start,
		delivery_end: row.delivery_window_end ?? row.delivery_end,
		created: row.created_at ?? row.created,
		quotes: row.quote_count ?? row.quotes ?? row.submitted_quote_count ?? 0,
		requester: displayActor(row.created_by ?? row.requester, 'Sistema'),
	};
}

export function normalizeRfqQuote(
	row: Record<string, any>,
	options: { bestQuoteId?: string | null; bestQuoteIds?: string[]; bestPrice?: number | null } = {},
): Record<string, any> {
	const price = numberOrNull(row.fixed_price_value ?? row.price);
	const bestPrice = options.bestPrice ?? null;
	const quoteId = String(row.id);
	const isBest =
		(options.bestQuoteIds != null && options.bestQuoteIds.includes(quoteId)) ||
		(options.bestQuoteId != null && quoteId === options.bestQuoteId);
	const status =
		isBest
			? 'best'
			: row.state === 'rejected'
				? 'rejected'
				: row.state ?? row.status ?? 'quoted';

	return {
		...row,
		cp: entityDisplayName(row, 'Contraparte não informada'),
		price,
		spread: price != null && bestPrice != null ? price - bestPrice : null,
		received: row.received_at ?? row.created_at ?? row.received,
		valid: row.valid_until ?? row.valid ?? null,
		status,
	};
}

export function normalizeOrder(row: Record<string, any>): Record<string, any> {
	return {
		...row,
		rfq: safeBusinessText(row.rfq_number ?? row.rfq, 'Sem RFQ vinculada'),
		qty: row.quantity_mt ?? row.qty,
		direction: row.order_type === 'SO' ? 'SELL' : 'BUY',
		price: row.avg_entry_price ?? row.price,
		cp: entityDisplayName(row, 'Contraparte não informada'),
		status: safeBusinessText(row.status, 'pending'),
		traded: row.trade_date ?? row.created_at ?? row.traded,
		settlement: row.delivery_date_end ?? row.settlement ?? null,
	};
}

export function normalizeContract(row: Record<string, any>): Record<string, any> {
	return {
		...row,
		qty: numberOrNull(row.quantity_mt ?? row.qty),
		type: row.float_pricing_convention ?? row.type ?? '—',
		fixed_leg: row.fixed_leg_side ?? row.fixed_leg ?? null,
		var_leg: row.variable_leg_side ?? row.var_leg ?? null,
		price: numberOrNull(row.fixed_price_value ?? row.price),
		cp: entityDisplayName(row, 'Contraparte não informada'),
		settle: row.settlement_date ?? row.prompt_date ?? row.settle,
		mtm: numberOrNull(row.mtm_value ?? row.mtm),
		status: safeBusinessText(row.status, 'pending'),
	};
}

export function normalizeCounterparty(row: Record<string, any>): Record<string, any> {
	const limit = numberOrNull(row.credit_limit_usd ?? row.limit) ?? 0;
	const used = numberOrNull(row.credit_used_usd ?? row.used) ?? 0;
	const kycStatus = row.kyc_status;
	const status =
		row.status ??
		(row.is_active === false
			? 'suspended'
			: kycStatus === 'pending' || kycStatus === 'review'
				? 'review'
				: kycStatus === 'expired' || kycStatus === 'rejected'
					? 'suspended'
					: 'active');
	return {
		...row,
		short: entityDisplayName(row, 'Contraparte sem nome'),
		rating: row.rating ?? row.risk_rating ?? '—',
		limit,
		used,
		status,
	};
}

export function normalizeCashflow(row: Record<string, any>): Record<string, any> {
	const amountUsd = numberOrNull(row.amount_usd) ?? 0;
	return {
		...row,
		date: row.cashflow_date ?? row.price_settlement_date ?? row.settlement_date ?? row.date,
		desc: safeBusinessText(row.description, 'Liquidação projetada'),
		cp: entityDisplayName(row, 'Contraparte não informada'),
		commodity: safeBusinessText(row.commodity, 'Commodity não informada'),
		amount_usd: amountUsd,
		direction: amountUsd < 0 ? 'out' : 'in',
		status: safeBusinessText(row.status, 'projected'),
	};
}

export function normalizeCommodity(row: Record<string, any>): Record<string, any> {
	const code = row.symbol ?? row.code ?? '—';
	return {
		...row,
		code: displayCommodityCode(code),
		canonical_code: canonicalCommodityCode(code),
		name: row.name ?? row.symbol ?? row.code ?? '—',
		unit: row.unit ?? 'USD/t',
		last: numberOrNull(row.price_usd ?? row.value ?? row.last),
		prev: numberOrNull(row.previous_value ?? row.prev),
		settlement_date: row.settlement_date,
		provider: sourceLabel(row.provider ?? row.source),
	};
}

export function normalizeAuditEvent(row: Record<string, any>): Record<string, any> {
	const payload = row.payload && typeof row.payload === 'object' ? (row.payload as Record<string, any>) : {};
	return {
		...row,
		ts: row.timestamp_utc ?? row.ts,
		user: displayActor(row.user ?? row.actor_subject, 'Sistema'),
		role: safeBusinessText(row.actor_role ?? row.role, 'Perfil operacional'),
		action: actionLabel(row.event_type ?? row.action),
		entity: safeBusinessText(row.entity ?? row.entity_name, 'Registro operacional'),
		detail: safeBusinessText(payload.detail ?? payload.reason ?? row.detail ?? row.description, 'Evento registrado'),
	};
}

function normalizedExposureRows(data: unknown): Record<string, any>[] {
	const rows = items<Record<string, any>>(data);
	return rows.map((row) => {
		const rawCommercialMt =
			numberOrNull(row.commercial_mt ?? row.commercial_net_mt ?? row.original_tons ?? row.quantity_mt) ?? 0;
		const commercialMt = signedExposureAmount(row, rawCommercialMt);
		const commercialActiveMt =
			numberOrNull(row.commercial_active_mt) ?? (commercialMt > 0 ? commercialMt : 0);
		const commercialPassiveMt =
			numberOrNull(row.commercial_passive_mt) ?? (commercialMt < 0 ? Math.abs(commercialMt) : 0);
		const hedgedMt = numberOrNull(row.hedged_mt ?? row.hedge_mt ?? row.hedged_tons) ?? 0;
		const loadedResidualMt = numberOrNull(row.residual_mt ?? row.exposure_residual_mt ?? row.open_tons);
		const residualMt = loadedResidualMt != null ? Math.abs(loadedResidualMt) : Math.max(Math.abs(commercialMt) - hedgedMt, 0);
		const explicitRatio = numberOrNull(row.coverage_ratio ?? row.hedge_ratio ?? row.hedge_coverage_ratio);
		const ratio =
			explicitRatio != null
				? explicitRatio >= 0 && explicitRatio <= 1
					? explicitRatio * 100
					: explicitRatio
				: commercialMt !== 0
					? (hedgedMt / Math.abs(commercialMt)) * 100
					: 0;
		const commodity = canonicalCommodityCode(row.commodity ?? row.product_code ?? row.asset);

		return {
			...row,
			commodity,
			commodity_display: displayCommodityCode(commodity),
			month:
				row.month ??
				row.settlement_month ??
				row.reference_month ??
				monthPart(row.delivery_date_start ?? row.delivery_window_start ?? row.as_of_date ?? row.exposure_date),
			commercial_mt: commercialMt,
			commercial_active_mt: commercialActiveMt,
			commercial_passive_mt: commercialPassiveMt,
			hedged_mt: hedgedMt,
			residual_mt: residualMt,
			mtm_delta_usd: numberOrNull(row.mtm_delta_usd ?? row.mtm_change_usd ?? row.delta_mtm_usd),
			ratio,
		};
	});
}

export function exposureBucketsFrom(data: unknown) {
	const normalized = normalizedExposureRows(data);
	const byMonth = new Map<string, Record<string, any>>();
	for (const bucket of normalized) {
		const key = bucket.month || '—';
		const existing = byMonth.get(key);
		if (!existing) {
			byMonth.set(key, { ...bucket, month: key });
			continue;
		}
		existing.commercial_active_mt += bucket.commercial_active_mt;
		existing.commercial_passive_mt += bucket.commercial_passive_mt;
		existing.commercial_mt += bucket.commercial_mt;
		existing.hedged_mt += bucket.hedged_mt;
		existing.residual_mt += bucket.residual_mt;
		existing.ratio =
			existing.commercial_mt !== 0
				? (existing.hedged_mt / Math.abs(existing.commercial_mt)) * 100
				: 0;
	}
	return Array.from(byMonth.values());
}

export function exposureCommodityRowsFrom(data: unknown) {
	const byCommodity = new Map<string, Record<string, any>>();
	for (const row of normalizedExposureRows(data)) {
		const key = row.commodity;
		const existing = byCommodity.get(key);
		if (!existing) {
			byCommodity.set(key, {
				code: row.commodity_display,
				commodity: key,
				commercial_mt: row.commercial_mt,
				commercial_active_mt: row.commercial_active_mt,
				commercial_passive_mt: row.commercial_passive_mt,
				hedged_mt: row.hedged_mt,
				residual_mt: row.residual_mt,
				mtm_delta_usd: row.mtm_delta_usd,
				pct: row.ratio,
			});
			continue;
		}
		existing.commercial_mt += row.commercial_mt;
		existing.commercial_active_mt += row.commercial_active_mt;
		existing.commercial_passive_mt += row.commercial_passive_mt;
		existing.hedged_mt += row.hedged_mt;
		existing.residual_mt += row.residual_mt;
		if (row.mtm_delta_usd != null) {
			existing.mtm_delta_usd = (existing.mtm_delta_usd ?? 0) + row.mtm_delta_usd;
		}
		existing.pct =
			existing.commercial_mt !== 0
				? (existing.hedged_mt / Math.abs(existing.commercial_mt)) * 100
				: 0;
	}
	return Array.from(byCommodity.values()).sort((a, b) => Math.abs(b.commercial_mt) - Math.abs(a.commercial_mt));
}
