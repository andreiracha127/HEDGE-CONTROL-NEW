import { beforeEach, describe, expect, test, vi } from 'vitest';

const get = vi.fn();

vi.mock('$lib/api/client', () => ({
	client: { GET: get },
}));

describe('audit load', () => {
	beforeEach(() => {
		get.mockReset();
	});

	test('loads audit events from the API', async () => {
		get.mockResolvedValueOnce({ data: { events: [{ event_type: 'rfq.create', entity_id: 'rfq-1', timestamp_utc: '2026-05-27T00:00:00Z' }] } });

		const { load } = await import('./+page');
		const result = await load();

		expect(get).toHaveBeenCalledWith('/audit/events', { params: { query: { limit: 200 } } });
		expect(result.auditLog[0]).toMatchObject({ action: 'rfq.create', detail: 'rfq.create', entity: 'rfq-1', role: 'System', ts: '2026-05-27T00:00:00Z', user: 'Sistema' });
	});

	test('returns an empty log instead of throwing when the auditor endpoint is forbidden', async () => {
		get.mockResolvedValueOnce({ error: { detail: 'Forbidden' } });

		const { load } = await import('./+page');
		const result = await load();

		expect(result.auditLog).toEqual([]);
		expect(result.auditLoadError).toBe('Forbidden');
	});
});

