import { error } from '@sveltejs/kit';

type ApiResult<T = unknown> = {
	data?: T | null;
	error?: { detail?: unknown } | null;
};

export function requireData<T>(result: ApiResult<T>, message: string): T {
	if (result.error) {
		const detail = typeof result.error.detail === 'string' ? `: ${result.error.detail}` : '';
		error(502, `${message}${detail}`);
	}
	if (result.data == null) error(502, message);
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

export function normalizeRfq(row: Record<string, any>): Record<string, any> {
	return {
		...row,
		id: row.rfq_number ?? row.id,
		rfq: row.rfq_number ?? row.id,
		qty: row.quantity_mt ?? row.qty,
		direction: row.direction,
		window: row.delivery_window_start ? datePart(row.delivery_window_start).slice(0, 7) : row.window,
		delivery_start: row.delivery_window_start ?? row.delivery_start,
		delivery_end: row.delivery_window_end ?? row.delivery_end,
		created: row.created_at ?? row.created,
		quotes: row.invitations?.length ?? row.quotes ?? 0,
		best: row.notional_usd_at_best ?? row.best ?? null,
		requester: row.created_by ?? row.requester ?? 'Sistema',
	};
}

export function normalizeOrder(row: Record<string, any>): Record<string, any> {
	return {
		...row,
		rfq: row.rfq_number ?? row.rfq_id ?? row.rfq ?? '—',
		qty: row.quantity_mt ?? row.qty,
		direction: row.order_type === 'SO' ? 'SELL' : 'BUY',
		price: row.avg_entry_price ?? row.price,
		cp: row.counterparty_name ?? row.counterparty_id ?? row.cp ?? '—',
		status: row.status ?? 'filled',
		traded: row.trade_date ?? row.created_at ?? row.traded,
		settlement: row.delivery_date_end ?? row.settlement ?? null,
	};
}

export function normalizeContract(row: Record<string, any>): Record<string, any> {
	return {
		...row,
		qty: row.quantity_mt ?? row.qty,
		type: row.float_pricing_convention ?? row.type ?? 'Forward',
		fixed_leg: row.fixed_leg_side ?? row.fixed_leg ?? 'buy',
		var_leg: row.variable_leg_side ?? row.var_leg ?? 'sell',
		price: row.fixed_price_value ?? row.price,
		cp: row.counterparty_short ?? row.counterparty_name ?? row.counterparty_id ?? row.cp ?? '—',
		settle: row.settlement_date ?? row.prompt_date ?? row.settle,
		mtm: row.mtm_value ?? row.mtm ?? null,
		status: row.status ?? 'active',
	};
}

export function normalizeCounterparty(row: Record<string, any>): Record<string, any> {
	const limit = row.credit_limit_usd ?? row.limit ?? 0;
	const used = row.credit_used_usd ?? row.used ?? 0;
	return {
		...row,
		short: row.short_name ?? row.short ?? row.id,
		rating: row.rating ?? row.risk_rating ?? '—',
		limit,
		used,
		status: row.status ?? (row.is_active === false ? 'suspended' : row.kyc_status === 'review' ? 'review' : 'active'),
	};
}

export function normalizeCashflow(row: Record<string, any>): Record<string, any> {
	return {
		...row,
		date: row.cashflow_date ?? row.price_settlement_date ?? row.date,
		desc: row.description ?? `${row.object_type ?? 'cashflow'} ${row.object_id ?? ''}`.trim(),
		cp: row.counterparty_name ?? row.cp ?? '—',
		commodity: row.commodity ?? '—',
		amount_usd: row.amount_usd,
		direction: numberOrNull(row.amount_usd) != null && numberOrNull(row.amount_usd)! < 0 ? 'out' : 'in',
		status: row.status ?? 'projected',
	};
}

export function normalizeCommodity(row: Record<string, any>): Record<string, any> {
	return {
		...row,
		code: row.symbol ?? row.code ?? '—',
		name: row.name ?? row.symbol ?? row.code ?? '—',
		unit: row.unit ?? 'USD/t',
		last: row.price_usd ?? row.value ?? row.last ?? null,
		prev: row.previous_value ?? row.prev ?? null,
		settlement_date: row.settlement_date,
		provider: row.provider ?? row.source ?? '—',
	};
}

export function normalizeAuditEvent(row: Record<string, any>): Record<string, any> {
	return {
		...row,
		ts: row.timestamp_utc ?? row.ts,
		user: row.actor_subject ?? row.user ?? 'Sistema',
		role: row.actor_role ?? row.role ?? 'System',
		action: row.event_type ?? row.action,
		entity: row.entity_id ?? row.entity,
		detail: row.event_type ?? row.detail ?? '',
	};
}

export function exposureBucketsFrom(data: unknown) {
	const rows = items<Record<string, any>>(data);
	return rows.map((row) => {
		const commercialMt =
			numberOrNull(row.commercial_mt ?? row.commercial_net_mt ?? row.original_tons ?? row.quantity_mt) ?? 0;
		const hedgedMt = numberOrNull(row.hedged_mt ?? row.hedge_mt ?? row.hedged_tons) ?? 0;
		const residualMt =
			numberOrNull(row.residual_mt ?? row.exposure_residual_mt ?? row.open_tons) ??
			Math.max(Math.abs(commercialMt) - hedgedMt, 0);
		const explicitRatio = numberOrNull(row.coverage_ratio ?? row.hedge_ratio ?? row.hedge_coverage_ratio);
		const ratio =
			explicitRatio != null
				? explicitRatio >= 0 && explicitRatio <= 1
					? explicitRatio * 100
					: explicitRatio
				: commercialMt !== 0
					? (hedgedMt / Math.abs(commercialMt)) * 100
					: 0;

		return {
			...row,
			month:
				row.month ??
				row.settlement_month ??
				row.reference_month ??
				datePart(row.delivery_date_start ?? row.delivery_window_start ?? row.as_of_date ?? row.exposure_date),
			commercial_mt: commercialMt,
			hedged_mt: hedgedMt,
			residual_mt: residualMt,
			ratio,
		};
	});
}

