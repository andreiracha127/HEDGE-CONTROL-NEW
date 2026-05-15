import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

const logoutMock = vi.fn();
const getCsrfTokenMock = vi.fn(() => 'csrf-1');

vi.mock('$lib/stores/auth.svelte', () => ({
	authStore: {
		getCsrfToken: getCsrfTokenMock,
		logout: logoutMock,
	},
}));

describe('apiFetch', () => {
	beforeEach(() => {
		vi.resetModules();
		logoutMock.mockReset();
		getCsrfTokenMock.mockReturnValue('csrf-1');
	});

	afterEach(() => {
		vi.unstubAllGlobals();
	});

	it('uses cookie credentials and CSRF header for mutating requests', async () => {
		const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
		vi.stubGlobal('fetch', fetchMock);
		const { apiFetch } = await import('./fetch');

		await apiFetch('/orders/sales', { method: 'POST', body: '{}' });

		const [, init] = fetchMock.mock.calls[0];
		const headers = init.headers as Headers;
		expect(init.credentials).toBe('include');
		expect(headers.get('X-CSRF-Token')).toBe('csrf-1');
		expect(headers.has('Authorization')).toBe(false);
	});

	it('uses cookie credentials without CSRF for read requests', async () => {
		const fetchMock = vi.fn().mockResolvedValue(new Response('{}', { status: 200 }));
		vi.stubGlobal('fetch', fetchMock);
		const { apiFetch } = await import('./fetch');

		await apiFetch('/orders');

		const [, init] = fetchMock.mock.calls[0];
		const headers = init.headers as Headers;
		expect(init.credentials).toBe('include');
		expect(headers.has('X-CSRF-Token')).toBe(false);
		expect(headers.has('Authorization')).toBe(false);
	});
});
