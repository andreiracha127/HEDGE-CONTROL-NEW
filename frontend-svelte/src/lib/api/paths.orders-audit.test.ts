/**
 * J-A6-08 + J-A6-09 — path helpers for the read-only orders and audit
 * surfaces.
 */
import { describe, it, expect } from 'vitest';
import {
	ordersListPath,
	orderDetailPath,
	auditEventsPath,
	auditEventVerifyPath,
} from './paths';

describe('ordersListPath', () => {
	it('returns /orders with no query when no params supplied', () => {
		expect(ordersListPath()).toBe('/orders');
	});

	it('serialises limit and cursor when supplied', () => {
		const path = ordersListPath({ limit: 50, cursor: 'abc' });
		expect(path).toBe('/orders?limit=50&cursor=abc');
	});

	it('omits null/empty cursor', () => {
		const path = ordersListPath({ limit: 25, cursor: null });
		expect(path).toBe('/orders?limit=25');
	});
});

describe('orderDetailPath', () => {
	it('returns /orders/{id} for a valid id', () => {
		expect(orderDetailPath('order-1')).toBe('/orders/order-1');
	});

	it('throws on empty/whitespace order_id', () => {
		expect(() => orderDetailPath('')).toThrow(/order_id/);
		expect(() => orderDetailPath('   ')).toThrow(/order_id/);
	});
});

describe('auditEventsPath', () => {
	it('returns /audit/events with no query when no params supplied', () => {
		expect(auditEventsPath()).toBe('/audit/events');
	});

	it('serialises entity_type, entity_id, start, end, limit', () => {
		const path = auditEventsPath({
			entity_type: 'rfq',
			entity_id: 'uuid-1',
			start: '2026-01-01',
			end: '2026-01-31',
			limit: 50,
		});
		expect(path).toBe(
			'/audit/events?limit=50&entity_type=rfq&entity_id=uuid-1&start=2026-01-01&end=2026-01-31',
		);
	});

	it('drops null/empty filters', () => {
		const path = auditEventsPath({
			entity_type: null,
			entity_id: '',
			start: null,
			limit: 10,
		});
		expect(path).toBe('/audit/events?limit=10');
	});
});

describe('auditEventVerifyPath', () => {
	it('returns /audit/events/{id}/verify', () => {
		expect(auditEventVerifyPath('ev-1')).toBe('/audit/events/ev-1/verify');
	});

	it('throws on empty event_id', () => {
		expect(() => auditEventVerifyPath('')).toThrow(/event_id/);
	});
});
