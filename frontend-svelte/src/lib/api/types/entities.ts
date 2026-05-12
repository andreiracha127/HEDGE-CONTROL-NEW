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

export interface CashflowAnalyticsEntry {
	id?: string;
	period?: string;
	month?: string;
	commodity?: string;
	net_amount?: number;
	net?: number;
	inflows?: number;
	total_inflows?: number;
	outflows?: number;
	total_outflows?: number;
}

export interface CashflowSummary {
	total_inflows?: number;
	total_outflows?: number;
	net_balance?: number;
}

export interface CashflowProjection {
	id?: string;
	month?: string;
	period?: string;
	projected_inflow?: number;
	inflow?: number;
	projected_outflow?: number;
	outflow?: number;
	net?: number;
	projected_net?: number;
}

export interface CashflowLedgerEntry {
	id?: string;
	date?: string;
	settlement_date?: string;
	contract_reference?: string;
	reference?: string;
	counterparty_name?: string;
	counterparty?: string;
	commodity?: string;
	inflow?: number;
	outflow?: number;
	amount?: number;
	balance?: number;
	running_balance?: number;
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

export interface MarketPrice {
	id?: string;
	date?: string;
	price?: number;
	value?: number;
	change?: number;
}
