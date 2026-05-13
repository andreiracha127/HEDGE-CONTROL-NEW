/**
 * Provisional domain entity interfaces.
 *
 * These types capture the fields actually accessed in route-page templates.
 * Optional fields are used liberally because API response shapes may vary
 * between endpoints or evolve over time. When the OpenAPI spec stabilises,
 * replace these with the generated `schema.d.ts` types.
 *
 * TODO 012 — created to eliminate pervasive `any` in route pages.
 */

// ─── RFQ ────────────────────────────────────────────────────────────────

export interface RfqInvitation {
	id: string;
	recipient_name?: string;
	recipient_phone?: string;
	send_status?: string;
}

export interface Rfq {
	id: string;
	rfq_number?: string;
	state: string;
	commodity?: string;
	quantity_mt?: number;
	direction?: string;
	intent?: string;
	created_at?: string;
	invitations?: RfqInvitation[];
	quotes?: RfqQuote[];
}

export interface RfqQuote {
	id: string;
	counterparty_id?: string;
	fixed_price_value?: number;
	fixed_price_unit?: string;
	float_pricing_convention?: string;
	received_at?: string;
	created_at?: string;
	_isNew?: boolean;
}

export interface RfqRankingEntry {
	counterparty_id?: string;
	counterparty_name?: string;
	score?: number;
	fixed_price_value?: number;
	fixed_price_unit?: string;
}

export interface RfqRanking {
	ranking?: RfqRankingEntry[];
}

export interface RfqStateEvent {
	id: string;
	from_state?: string;
	to_state?: string;
	user_id?: string;
	reason?: string;
	event_timestamp?: string;
	created_contract_ids?: string;
}

// ─── Exposures ──────────────────────────────────────────────────────────

export interface Exposure {
	id?: string;
	commodity?: string;
	settlement_month?: string;
	source_type?: string;
	quantity_mt?: number;
	direction?: string;
	hedge_status?: string;
	net_exposure_mt?: number;
}

export interface NetExposure {
	gross_exposure_mt?: number;
	net_exposure_mt?: number;
	hedge_ratio?: number | null;
	open_positions?: number;
}

export interface HedgeTask {
	id?: string;
	exposure_id?: string;
	commodity?: string;
	action?: string;
	recommendation?: string;
	quantity_mt?: number;
	settlement_month?: string;
}

// ─── Cashflow ───────────────────────────────────────────────────────────
//
// Aligned with the canonical OpenAPI shapes in `schema.d.ts`. Decimal
// columns (amount_usd, mtm_value, price_*, quantity_mt, totals) are
// serialised as strings; the format helpers (`formatNumber`,
// `formatPrice`, `formatQuantityMT`) preserve that precision when given
// the raw string.

/** Mirror of `components["schemas"]["CashFlowItem"]` (analytic items). */
export interface CashFlowItem {
	amount_usd: string;
	mtm_value: string;
	object_id: string;
	object_type: string;
	settlement_date: string;
	price_settlement_date?: string | null;
	price_source?: string | null;
	price_symbol?: string | null;
	price_value?: string | null;
}

/** Mirror of `components["schemas"]["CashFlowAnalyticResponse"]`. */
export interface CashFlowAnalyticResponse {
	as_of_date: string;
	cashflow_items: CashFlowItem[];
	total_net_cashflow: string;
}

/** Mirror of `components["schemas"]["CashFlowProjectionItem"]`. */
export interface CashFlowProjectionItem {
	amount_usd: string;
	commodity: string;
	counterparty: string;
	deal_id?: string | null;
	instrument_id: string;
	instrument_type: string;
	price_per_mt: string;
	price_source: string;
	quantity_mt: string;
	reference: string;
	settlement_date: string;
}

/** Mirror of `components["schemas"]["CashFlowProjectionSummary"]`. */
export interface CashFlowProjectionSummary {
	instrument_count: number;
	net_cashflow: string;
	total_inflows: string;
	total_outflows: string;
}

/** Mirror of `components["schemas"]["CashFlowProjectionResponse"]`. */
export interface CashFlowProjectionResponse {
	as_of_date: string;
	items: CashFlowProjectionItem[];
	summary: CashFlowProjectionSummary;
}

/** Mirror of `components["schemas"]["CashFlowLedgerEntryRead"]`. */
export interface CashFlowLedgerEntry {
	id: string;
	hedge_contract_id: string;
	leg_id: string;
	cashflow_date: string;
	created_at: string;
	currency: string;
	direction: string;
	amount: string;
	source_event_id: string | null;
	source_event_type: string;
	price_settlement_date?: string | null;
	price_source?: string | null;
	price_symbol?: string | null;
	price_value?: string | null;
}

// ─── Contracts ──────────────────────────────────────────────────────────

export interface Contract {
	id: string;
	reference?: string;
	commodity?: string;
	quantity_mt?: number;
	fixed_price_value?: number;
	fixed_price_unit?: string;
	counterparty_name?: string;
	counterparty_id?: string;
	status?: string;
	trade_date?: string;
	created_at?: string;
	classification?: string;
	fixed_leg_side?: string;
	variable_leg_side?: string;
	float_pricing_convention?: string;
	source_type?: string;
}

// ─── Counterparties ─────────────────────────────────────────────────────

export interface Counterparty {
	id: string;
	name?: string;
	short_name?: string;
	type?: string;
	whatsapp_phone?: string;
	phone?: string;
	kyc_status?: string;
	sanctions_status?: string;
}

// ─── Analytics: P&L ─────────────────────────────────────────────────────
//
// Mirror of `components["schemas"]["PLSnapshotResponse"]` from the
// generated `schema.d.ts`. `/pl/snapshots` returns a single snapshot
// (scalar fields), not a collection — `realized_pl` and `unrealized_mtm`
// are Decimal-as-string per the FastAPI Decimal serialization contract.

export interface PnlSnapshot {
	id: string;
	correlation_id: string | null;
	created_at: string;
	entity_id: string;
	entity_type: string;
	period_start: string;
	period_end: string;
	inputs_hash?: string | null;
	realized_pl: string;
	unrealized_mtm: string;
	price_references?: Array<Record<string, unknown>> | null;
}

// ─── Analytics: MTM ─────────────────────────────────────────────────────
//
// Mirror of `components["schemas"]["MTMSnapshotResponse"]`. `/mtm/snapshots`
// returns a single snapshot — `mtm_value`, `entry_price`, `price_d1`, and
// `quantity_mt` are Decimal-as-string. `MTMObjectType` is "hedge_contract"
// or "order".

export interface MtmSnapshot {
	id: string;
	correlation_id: string;
	created_at: string;
	as_of_date: string;
	object_id: string;
	object_type: 'hedge_contract' | 'order';
	mtm_value: string;
	entry_price: string;
	price_d1: string;
	quantity_mt: string;
	inputs_hash?: string | null;
	price_settlement_date?: string | null;
	price_source?: string | null;
	price_symbol?: string | null;
}

// ─── Analytics: What-If ─────────────────────────────────────────────────

export interface WhatIfResult {
	base?: Record<string, number>;
	scenario?: Record<string, number>;
	base_pnl?: number;
	base_total?: number;
	scenario_pnl?: number;
	scenario_total?: number;
	delta?: number;
	impact?: number;
}

// ─── Market Data ────────────────────────────────────────────────────────
//
// Mirror of `components["schemas"]["CashSettlementPriceRead"]` from the
// generated `schema.d.ts`. `price_usd` is a Decimal serialised as a
// string (NUMERIC(18, 6) per migrations 025/033), so the table display
// must route through `formatPrice` to preserve six fractional digits.
// The legacy `price` / `value` / `change` / `date` fields never existed
// on this endpoint; the prior shape used `?? 0` defaults that silently
// rendered missing prices as zero (J-A6-06).

export interface MarketPrice {
	id: string;
	settlement_date: string;
	price_usd: string;
	source: string;
	source_url: string;
	symbol: string;
	html_sha256: string;
	created_at: string;
	fetched_at: string;
}

// ─── Orders (read-only PR-A6-4) ─────────────────────────────────────────
//
// Mirror of `components["schemas"]["OrderRead"]` and `OrderListResponse`.
// Decimal columns (`quantity_mt`, `avg_entry_price`) arrive as strings;
// pass them through `formatQuantityMT` / `formatPrice` rather than
// `Number()`.

export type OrderType = 'SO' | 'PO';
export type PriceType = 'fixed' | 'variable';
export type OrderPricingConvention = 'AVG' | 'AVGInter' | 'C2R';

export interface OrderRead {
	id: string;
	order_type: OrderType;
	commodity: string;
	quantity_mt: string;
	price_type: PriceType;
	pricing_convention?: OrderPricingConvention | null;
	pricing_type?: string | null;
	avg_entry_price?: string | null;
	currency: string;
	counterparty_id?: string | null;
	counterparty_name?: string | null;
	reference_month?: string | null;
	fixing_date?: string | null;
	delivery_date_start?: string | null;
	delivery_date_end?: string | null;
	delivery_terms?: string | null;
	observation_date_start?: string | null;
	observation_date_end?: string | null;
	payment_terms_days?: number | null;
	notes?: string | null;
	deleted_at?: string | null;
	created_at: string;
}

export interface OrderListResponse {
	items: OrderRead[];
	next_cursor?: string | null;
}

// ─── Audit Events (read + verify PR-A6-4) ───────────────────────────────
//
// Mirror of `components["schemas"]["AuditEventRead"]`,
// `AuditEventListResponse`, and `AuditVerifyResponse`. The signed `payload`
// is intentionally `unknown` — auditors inspect raw evidence via the
// detail view rather than typed property access.

export interface AuditEventRead {
	id: string;
	entity_type: string;
	entity_id: string;
	event_type: string;
	timestamp_utc: string;
	checksum: string;
	signature?: string | null;
	payload: unknown;
}

export interface AuditEventListResponse {
	events?: AuditEventRead[];
	next_cursor?: string | null;
}

export interface AuditVerifyResponse {
	event_id: string;
	valid: boolean;
	detail: string;
}
