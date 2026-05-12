import { describe, it, expect } from 'vitest';
import {
	cashflowAnalyticPath,
	cashflowProjectionPath,
	cashflowLedgerPath,
	contractsHedgeListPath,
	contractsHedgeDetailPath,
	contractsHedgeStatusPath,
	mtmSnapshotsPath,
	pnlSnapshotsPath,
	STALE_PATH_LITERALS,
} from './paths';

describe('cashflow path builders', () => {
	it('builds /cashflow/analytic with as_of_date', () => {
		const path = cashflowAnalyticPath({ as_of_date: '2026-05-12' });
		expect(path).toBe('/cashflow/analytic?as_of_date=2026-05-12');
		expect(path).not.toMatch(/\/cashflow\/analytics(\b|\?)/);
	});

	it('builds /cashflow/projection with as_of_date', () => {
		const path = cashflowProjectionPath({ as_of_date: '2026-05-12' });
		expect(path).toBe('/cashflow/projection?as_of_date=2026-05-12');
		expect(path).not.toMatch(/\/cashflow\/projections(\b|\?)/);
	});

	it('builds /cashflow/ledger with source_event_id (no date-range params)', () => {
		const path = cashflowLedgerPath({ source_event_id: 'evt-123' });
		expect(path).toBe('/cashflow/ledger?source_event_id=evt-123');
		expect(path).not.toContain('date_from');
		expect(path).not.toContain('date_to');
	});

	it('throws when as_of_date missing for analytic', () => {
		expect(() => cashflowAnalyticPath({ as_of_date: '' })).toThrow(/as_of_date/);
	});

	it('throws when as_of_date missing for projection', () => {
		expect(() => cashflowProjectionPath({ as_of_date: '   ' })).toThrow(/as_of_date/);
	});

	it('throws when source_event_id missing for ledger', () => {
		expect(() => cashflowLedgerPath({ source_event_id: '' })).toThrow(/source_event_id/);
	});
});

describe('hedge contracts path builders', () => {
	it('builds /contracts/hedge list with no params', () => {
		expect(contractsHedgeListPath({})).toBe('/contracts/hedge');
	});

	it('builds /contracts/hedge list with status + limit', () => {
		const path = contractsHedgeListPath({ status: 'active', limit: 100 });
		expect(path).toBe('/contracts/hedge?limit=100&status=active');
		expect(path.startsWith('/contracts/hedge')).toBe(true);
		expect(path).not.toMatch(/^\/contracts\?/);
	});

	it('builds /contracts/hedge/{id} detail path', () => {
		const path = contractsHedgeDetailPath('contract-abc');
		expect(path).toBe('/contracts/hedge/contract-abc');
		expect(path).not.toMatch(/^\/contracts\/contract-abc$/);
	});

	it('builds /contracts/hedge/{id}/status path', () => {
		const path = contractsHedgeStatusPath('contract-abc');
		expect(path).toBe('/contracts/hedge/contract-abc/status');
	});

	it('throws when contract id missing', () => {
		expect(() => contractsHedgeDetailPath('')).toThrow(/contract_id/);
		expect(() => contractsHedgeStatusPath('   ')).toThrow(/contract_id/);
	});
});

describe('MTM / P&L singleton snapshot path builders', () => {
	it('builds /mtm/snapshots with object_type, object_id, as_of_date', () => {
		const path = mtmSnapshotsPath({
			object_type: 'hedge_contract',
			object_id: 'uuid-1',
			as_of_date: '2026-05-12',
		});
		expect(path).toBe(
			'/mtm/snapshots?object_type=hedge_contract&object_id=uuid-1&as_of_date=2026-05-12',
		);
		expect(path).not.toContain('/mtm/snapshots/latest');
	});

	it('throws on any missing MTM parameter', () => {
		expect(() => mtmSnapshotsPath({ object_type: '', object_id: 'x', as_of_date: 'd' })).toThrow(
			/object_type/,
		);
		expect(() => mtmSnapshotsPath({ object_type: 'x', object_id: '', as_of_date: 'd' })).toThrow(
			/object_id/,
		);
		expect(() => mtmSnapshotsPath({ object_type: 'x', object_id: 'y', as_of_date: '' })).toThrow(
			/as_of_date/,
		);
	});

	it('builds /pl/snapshots with entity_type, entity_id, period_start, period_end', () => {
		const path = pnlSnapshotsPath({
			entity_type: 'hedge_contract',
			entity_id: 'uuid-2',
			period_start: '2026-05-01',
			period_end: '2026-05-31',
		});
		expect(path).toBe(
			'/pl/snapshots?entity_type=hedge_contract&entity_id=uuid-2&period_start=2026-05-01&period_end=2026-05-31',
		);
		expect(path).not.toContain('/pl/snapshot/latest');
		expect(path).not.toContain('/pl/snapshots/latest');
	});

	it('throws on any missing P&L parameter', () => {
		expect(() =>
			pnlSnapshotsPath({ entity_type: '', entity_id: 'x', period_start: 's', period_end: 'e' }),
		).toThrow(/entity_type/);
		expect(() =>
			pnlSnapshotsPath({ entity_type: 'x', entity_id: '', period_start: 's', period_end: 'e' }),
		).toThrow(/entity_id/);
		expect(() =>
			pnlSnapshotsPath({ entity_type: 'x', entity_id: 'y', period_start: '', period_end: 'e' }),
		).toThrow(/period_start/);
		expect(() =>
			pnlSnapshotsPath({ entity_type: 'x', entity_id: 'y', period_start: 's', period_end: '' }),
		).toThrow(/period_end/);
	});

	it('does not conflate MTM object_* and P&L entity_* names', () => {
		const mtm = mtmSnapshotsPath({
			object_type: 'hedge_contract',
			object_id: 'a',
			as_of_date: '2026-05-12',
		});
		const pnl = pnlSnapshotsPath({
			entity_type: 'hedge_contract',
			entity_id: 'a',
			period_start: '2026-05-01',
			period_end: '2026-05-31',
		});
		expect(mtm).toContain('object_type=');
		expect(mtm).toContain('object_id=');
		expect(mtm).not.toContain('entity_type=');
		expect(pnl).toContain('entity_type=');
		expect(pnl).toContain('entity_id=');
		expect(pnl).not.toContain('object_type=');
	});
});

describe('STALE_PATH_LITERALS', () => {
	it('covers every stale literal listed in J-A6-01', () => {
		expect(STALE_PATH_LITERALS).toEqual(
			expect.arrayContaining([
				'/cashflow/analytics',
				'/cashflow/projections',
				'/mtm/snapshots/latest',
				'/pl/snapshot/latest',
				'/contracts?',
				'/contracts/${contractId}',
				'/contracts/${contractId}/status',
			]),
		);
		expect(STALE_PATH_LITERALS.length).toBeGreaterThanOrEqual(7);
	});
});
