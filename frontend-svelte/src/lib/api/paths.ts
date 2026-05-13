/**
 * Typed contract path builders for routed pages.
 *
 * Each helper returns the canonical path from `docs/api/openapi_v1.json`.
 * Required query parameters are enforced at the type level; the helpers throw
 * if a caller passes an empty value, so a missing parameter cannot silently
 * become a 422 backend request.
 *
 * STALE_PATH_LITERALS is consumed by `paths.drift.test.ts` to fail the build
 * when the literals repaired in PR-A6-1 reappear under `frontend-svelte/src`.
 */

function requireParam(value: string | null | undefined, name: string): string {
	const trimmed = (value ?? '').trim();
	if (!trimmed) {
		throw new Error(`Missing required parameter: ${name}`);
	}
	return trimmed;
}

// ─── Cashflow ───────────────────────────────────────────────────────────

export function cashflowAnalyticPath(params: { as_of_date: string }): string {
	const qs = new URLSearchParams({ as_of_date: requireParam(params.as_of_date, 'as_of_date') });
	return `/cashflow/analytic?${qs}`;
}

export function cashflowProjectionPath(params: { as_of_date: string }): string {
	const qs = new URLSearchParams({ as_of_date: requireParam(params.as_of_date, 'as_of_date') });
	return `/cashflow/projection?${qs}`;
}

export function cashflowLedgerPath(params: { source_event_id: string }): string {
	const qs = new URLSearchParams({
		source_event_id: requireParam(params.source_event_id, 'source_event_id'),
	});
	return `/cashflow/ledger?${qs}`;
}

// ─── Hedge Contracts ────────────────────────────────────────────────────

export function contractsHedgeListPath(params: {
	status?: string;
	limit?: number;
}): string {
	const qs = new URLSearchParams();
	if (params.limit != null) qs.set('limit', String(params.limit));
	if (params.status) qs.set('status', params.status);
	const tail = qs.toString();
	return tail ? `/contracts/hedge?${tail}` : '/contracts/hedge';
}

export function contractsHedgeDetailPath(contractId: string): string {
	return `/contracts/hedge/${requireParam(contractId, 'contract_id')}`;
}

export function contractsHedgeStatusPath(contractId: string): string {
	return `/contracts/hedge/${requireParam(contractId, 'contract_id')}/status`;
}

// ─── MTM / P&L Snapshots ────────────────────────────────────────────────

export function mtmSnapshotsPath(params: {
	object_type: string;
	object_id: string;
	as_of_date: string;
}): string {
	const qs = new URLSearchParams({
		object_type: requireParam(params.object_type, 'object_type'),
		object_id: requireParam(params.object_id, 'object_id'),
		as_of_date: requireParam(params.as_of_date, 'as_of_date'),
	});
	return `/mtm/snapshots?${qs}`;
}

export function pnlSnapshotsPath(params: {
	entity_type: string;
	entity_id: string;
	period_start: string;
	period_end: string;
}): string {
	const qs = new URLSearchParams({
		entity_type: requireParam(params.entity_type, 'entity_type'),
		entity_id: requireParam(params.entity_id, 'entity_id'),
		period_start: requireParam(params.period_start, 'period_start'),
		period_end: requireParam(params.period_end, 'period_end'),
	});
	return `/pl/snapshots?${qs}`;
}

// ─── Orders (read-only) ─────────────────────────────────────────────────
//
// `/orders` returns `OrderListResponse` with cursor pagination.
// `/orders/{order_id}` returns a single `OrderRead`. PR-A6-4 surfaces
// only the read endpoints — purchase/sales/archive mutations stay out of
// scope.

export function ordersListPath(params: {
	cursor?: string | null;
	limit?: number;
} = {}): string {
	const qs = new URLSearchParams();
	if (params.limit != null) qs.set('limit', String(params.limit));
	if (params.cursor) qs.set('cursor', params.cursor);
	const tail = qs.toString();
	return tail ? `/orders?${tail}` : '/orders';
}

export function orderDetailPath(orderId: string): string {
	return `/orders/${requireParam(orderId, 'order_id')}`;
}

// ─── Audit (read-only + verify) ─────────────────────────────────────────
//
// `/audit/events` returns `AuditEventListResponse` with optional filters
// + cursor pagination. `/audit/events/{event_id}/verify` returns
// `AuditVerifyResponse { valid, detail, event_id }`.

export function auditEventsPath(params: {
	entity_type?: string | null;
	entity_id?: string | null;
	start?: string | null;
	end?: string | null;
	cursor?: string | null;
	limit?: number;
} = {}): string {
	const qs = new URLSearchParams();
	if (params.limit != null) qs.set('limit', String(params.limit));
	if (params.entity_type) qs.set('entity_type', params.entity_type);
	if (params.entity_id) qs.set('entity_id', params.entity_id);
	if (params.start) qs.set('start', params.start);
	if (params.end) qs.set('end', params.end);
	if (params.cursor) qs.set('cursor', params.cursor);
	const tail = qs.toString();
	return tail ? `/audit/events?${tail}` : '/audit/events';
}

export function auditEventVerifyPath(eventId: string): string {
	return `/audit/events/${requireParam(eventId, 'event_id')}/verify`;
}

// ─── Drift guard literals ───────────────────────────────────────────────
//
// Stale path literals retired by PR-A6-1. The drift guard test
// (`paths.drift.test.ts`) scans `frontend-svelte/src` and fails if any of
// these reappear. Listed as raw substrings so a partial/templated reuse such
// as `/cashflow/projections` or `/mtm/snapshots/latest` is still caught.
export const STALE_PATH_LITERALS: readonly string[] = [
	'/cashflow/analytics',
	'/cashflow/projections',
	'/mtm/snapshots/latest',
	'/pl/snapshot/latest',
	'/contracts?',
	'/contracts/${contractId}',
	'/contracts/${contractId}/status',
];
