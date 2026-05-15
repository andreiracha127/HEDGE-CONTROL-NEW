import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Helper: create a fake JWT with given payload
function fakeJwt(payload: Record<string, unknown>): string {
	const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
	const body = btoa(JSON.stringify(payload));
	const sig = btoa('fake-signature');
	return `${header}.${body}.${sig}`;
}

async function waitForRestoreToSettle(authStore: { isRestoring: boolean }, fetchMock: ReturnType<typeof vi.fn>) {
	for (let i = 0; i < 25; i++) {
		if (!authStore.isRestoring && fetchMock.mock.calls.length >= 2) return;
		await Promise.resolve();
	}
}

async function waitForRefreshBody(fetchMock: ReturnType<typeof vi.fn>, body: string) {
	for (let i = 0; i < 25; i++) {
		if (fetchMock.mock.calls.some((call) => call[1]?.body === body)) return;
		await Promise.resolve();
	}
}

async function waitForCsrfToken(authStore: { getCsrfToken: () => string | null }, token: string) {
	for (let i = 0; i < 25; i++) {
		if (authStore.getCsrfToken() === token) return;
		await Promise.resolve();
	}
}

describe('AuthStore', () => {
	let authStore: typeof import('./auth.svelte').authStore;
	let gotoMock: ReturnType<typeof vi.fn>;

	beforeEach(async () => {
		vi.useFakeTimers();
		sessionStorage.clear();
		vi.resetModules();
		// Import fresh goto mock (same instance that auth.svelte will use)
		const navMod = await import('$app/navigation');
		gotoMock = navMod.goto as ReturnType<typeof vi.fn>;
		gotoMock.mockReset();
		const mod = await import('./auth.svelte');
		authStore = mod.authStore;
	});

	afterEach(() => {
		sessionStorage.clear();
		document.cookie = 'csrf_token=; Max-Age=0; path=/';
		vi.useRealTimers();
		vi.unstubAllGlobals();
	});

	describe('login', () => {
		it('sets authenticated state from valid JWT', () => {
			const token = fakeJwt({
				sub: 'user-1',
				name: 'Test User',
				roles: ['trader', 'risk_manager'],
				exp: Math.floor(Date.now() / 1000) + 3600,
			});

			authStore.login(token);

			expect(authStore.isAuthenticated).toBe(true);
			expect(authStore.userName).toBe('Test User');
			expect(authStore.userRoles).toEqual(['trader', 'risk_manager']);
		});

		it('falls back to sub when name is missing', () => {
			const token = fakeJwt({ sub: 'user-1', exp: Math.floor(Date.now() / 1000) + 3600 });
			authStore.login(token);
			expect(authStore.userName).toBe('user-1');
		});

		it('throws on invalid JWT format', () => {
			expect(() => authStore.login('not-a-jwt')).toThrow('Invalid token');
			expect(authStore.isAuthenticated).toBe(false);
		});

		it('throws on malformed base64 payload', () => {
			expect(() => authStore.login('a.!!!.c')).toThrow('Invalid token');
		});

		it('does not restore plaintext JWTs from legacy session storage', async () => {
			const jwt = fakeJwt({ sub: 'user-1', roles: ['trader'], exp: Math.floor(Date.now() / 1000) + 3600 });
			const legacyKey = 'hedge-control.auth.' + 'token';
			sessionStorage.setItem(legacyKey, jwt);

			vi.resetModules();
			const mod = await import('./auth.svelte');

			expect(mod.authStore.isAuthenticated).toBe(false);
			expect(mod.authStore.getAuthHeader()).toBeNull();
		});

		it('restores identity from the httpOnly cookie session and refreshes without a plaintext JWT', async () => {
			const fetchMock = vi
				.fn()
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ actor_sub: 'user-1', roles: ['trader'] }), {
						status: 200,
						headers: { 'Content-Type': 'application/json' },
					}),
				)
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ csrf_token: 'csrf-new' }), {
						status: 200,
						headers: { 'Content-Type': 'application/json' },
					}),
				);
			sessionStorage.setItem('hedge-control.auth.csrf', 'csrf-old');
			vi.stubGlobal('fetch', fetchMock);

			vi.resetModules();
			const mod = await import('./auth.svelte');
			await waitForRestoreToSettle(mod.authStore, fetchMock);

			expect(fetchMock).toHaveBeenCalledWith(
				'http://localhost:8000/auth/me',
				expect.objectContaining({
					credentials: 'include',
				}),
			);
			expect(mod.authStore.isAuthenticated).toBe(true);
			expect(mod.authStore.isRestoring).toBe(false);
			expect(mod.authStore.userSub).toBe('user-1');
			expect(mod.authStore.userRoles).toEqual(['trader']);
			expect(mod.authStore.getAuthHeader()).toBeNull();
			// Restored sessions have no plaintext JWT in memory; immediate refresh uses the httpOnly cookie.
			expect(fetchMock).toHaveBeenLastCalledWith(
				'http://localhost:8000/auth/refresh',
				expect.objectContaining({
					method: 'POST',
					credentials: 'include',
					headers: {
						'Content-Type': 'application/json',
						'X-CSRF-Token': 'csrf-old',
					},
					body: JSON.stringify({}),
				}),
			);
			expect(mod.authStore.getCsrfToken()).toBe('csrf-new');
		});

		it('exchanges pasted JWT for httpOnly cookies and stores CSRF token', async () => {
			const token = fakeJwt({
				sub: 'user-1',
				name: 'Test User',
				roles: ['trader'],
				exp: Math.floor(Date.now() / 1000) + 3600,
			});
			const fetchMock = vi.fn().mockResolvedValue(
				new Response(JSON.stringify({ csrf_token: 'csrf-1' }), {
					status: 200,
					headers: { 'Content-Type': 'application/json' },
				}),
			);
			vi.stubGlobal('fetch', fetchMock);

			await authStore.establishSession(token);

			expect(fetchMock).toHaveBeenCalledWith(
				'http://localhost:8000/auth/session',
				expect.objectContaining({
					method: 'POST',
					credentials: 'include',
					body: JSON.stringify({ session_token: token }),
				}),
			);
			expect(authStore.isAuthenticated).toBe(true);
			expect(authStore.userName).toBe('Test User');
			expect(authStore.getCsrfToken()).toBe('csrf-1');
			expect(authStore.getAuthHeader()).toBeNull();
			expect(authStore.getToken()).toBeNull();
		});

		it('prefers the current CSRF cookie over cached session state', async () => {
			const token = fakeJwt({ sub: 'user-1', roles: ['trader'], exp: Math.floor(Date.now() / 1000) + 3600 });
			const fetchMock = vi.fn().mockResolvedValue(
				new Response(JSON.stringify({ csrf_token: 'csrf-old' }), {
					status: 200,
					headers: { 'Content-Type': 'application/json' },
				}),
			);
			vi.stubGlobal('fetch', fetchMock);

			await authStore.establishSession(token);
			document.cookie = 'csrf_token=csrf-fresh';

			expect(authStore.getCsrfToken()).toBe('csrf-fresh');
		});

		it('refreshes the backend cookie session with a fresh Clerk token before the short cookie expires', async () => {
			const token = fakeJwt({
				sub: 'user-1',
				name: 'Test User',
				roles: ['trader'],
				exp: Math.floor(Date.now() / 1000) + 3600,
			});
			const freshToken = fakeJwt({
				sub: 'user-1',
				name: 'Test User',
				roles: ['trader'],
				exp: Math.floor(Date.now() / 1000) + 7200,
			});
			const fetchMock = vi
				.fn()
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ csrf_token: 'csrf-1' }), {
						status: 200,
						headers: { 'Content-Type': 'application/json' },
					}),
				)
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ csrf_token: 'csrf-2' }), {
						status: 200,
						headers: { 'Content-Type': 'application/json' },
					}),
				);
			vi.stubGlobal('fetch', fetchMock);

			authStore.setClerkSessionProvider(vi.fn().mockResolvedValue(freshToken));
			await authStore.establishSession(token);
			await vi.advanceTimersByTimeAsync(4 * 60 * 1000);

			expect(fetchMock).toHaveBeenLastCalledWith(
				'http://localhost:8000/auth/refresh',
				expect.objectContaining({
					method: 'POST',
					credentials: 'include',
					headers: {
						'Content-Type': 'application/json',
						'X-CSRF-Token': 'csrf-1',
					},
					body: JSON.stringify({ session_token: freshToken }),
				}),
			);
			expect(authStore.isAuthenticated).toBe(true);
			expect(authStore.getCsrfToken()).toBe('csrf-2');
			expect(authStore.getToken()).toBeNull();
		});

		it('uses backend session lifetime instead of short Clerk token expiry', async () => {
			const shortClerkToken = fakeJwt({
				sub: 'user-1',
				name: 'Test User',
				roles: ['trader'],
				exp: Math.floor(Date.now() / 1000) + 60,
			});
			const fetchMock = vi
				.fn()
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ csrf_token: 'csrf-1' }), {
						status: 200,
						headers: { 'Content-Type': 'application/json' },
					}),
				)
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ csrf_token: 'csrf-2' }), {
						status: 200,
						headers: { 'Content-Type': 'application/json' },
					}),
				);
			vi.stubGlobal('fetch', fetchMock);

			await authStore.establishSession(shortClerkToken);
			await vi.advanceTimersByTimeAsync(61 * 1000);

			expect(authStore.isAuthenticated).toBe(true);
			expect(gotoMock).not.toHaveBeenCalled();

			await vi.advanceTimersByTimeAsync(3 * 60 * 1000);
			expect(fetchMock).toHaveBeenLastCalledWith(
				'http://localhost:8000/auth/refresh',
				expect.objectContaining({
					method: 'POST',
					body: JSON.stringify({}),
				}),
			);
			expect(authStore.getCsrfToken()).toBe('csrf-2');
		});

		it('refreshes the backend cookie before the short Clerk token in that cookie expires', async () => {
			const shortClerkToken = fakeJwt({
				sub: 'user-1',
				name: 'Test User',
				roles: ['trader'],
				exp: Math.floor(Date.now() / 1000) + 60,
			});
			const freshClerkToken = fakeJwt({
				sub: 'user-1',
				name: 'Test User',
				roles: ['trader'],
				exp: Math.floor(Date.now() / 1000) + 3600,
			});
			const fetchMock = vi
				.fn()
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ csrf_token: 'csrf-1' }), {
						status: 200,
						headers: { 'Content-Type': 'application/json' },
					}),
				)
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ csrf_token: 'csrf-2' }), {
						status: 200,
						headers: { 'Content-Type': 'application/json' },
					}),
				);
			vi.stubGlobal('fetch', fetchMock);

			authStore.setClerkSessionProvider(vi.fn().mockResolvedValue(freshClerkToken));
			await authStore.establishSession(shortClerkToken);
			await vi.advanceTimersByTimeAsync(45 * 1000);

			expect(fetchMock).toHaveBeenLastCalledWith(
				'http://localhost:8000/auth/refresh',
				expect.objectContaining({
					method: 'POST',
					body: JSON.stringify({ session_token: freshClerkToken }),
				}),
			);
			expect(authStore.isAuthenticated).toBe(true);
			expect(authStore.getCsrfToken()).toBe('csrf-2');
		});

		it('refreshes restored cookie sessions with the Clerk provider token instead of early-returning', async () => {
			const freshToken = fakeJwt({
				sub: 'user-1',
				name: 'Test User',
				roles: ['trader'],
				exp: Math.floor(Date.now() / 1000) + 7200,
			});
			const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
				if (url.endsWith('/auth/me')) {
					return Promise.resolve(
						new Response(JSON.stringify({ actor_sub: 'user-1', roles: ['trader'] }), {
							status: 200,
							headers: { 'Content-Type': 'application/json' },
						}),
					);
				}
				if (url.endsWith('/auth/refresh')) {
					const hasClerkToken = init?.body === JSON.stringify({ session_token: freshToken });
					return Promise.resolve(
						new Response(JSON.stringify({ csrf_token: hasClerkToken ? 'csrf-newer' : 'csrf-new' }), {
							status: 200,
							headers: { 'Content-Type': 'application/json' },
						}),
					);
				}
				return Promise.resolve(new Response(null, { status: 404 }));
			});
			sessionStorage.setItem('hedge-control.auth.csrf', 'csrf-old');
			vi.stubGlobal('fetch', fetchMock);

			vi.resetModules();
			const mod = await import('./auth.svelte');
			mod.authStore.setClerkSessionProvider(vi.fn().mockResolvedValue(freshToken));
			await waitForRestoreToSettle(mod.authStore, fetchMock);
			await waitForRefreshBody(fetchMock, JSON.stringify({ session_token: freshToken }));
			await waitForCsrfToken(mod.authStore, 'csrf-newer');

			expect(fetchMock).toHaveBeenCalledWith(
				'http://localhost:8000/auth/refresh',
				expect.objectContaining({
					method: 'POST',
					credentials: 'include',
					body: JSON.stringify({ session_token: freshToken }),
				}),
			);
			expect(mod.authStore.getCsrfToken()).toBe('csrf-newer');
		});
	});

	describe('logout', () => {
		it('clears auth state and redirects to /login', () => {
			const token = fakeJwt({ sub: 'user-1', exp: Math.floor(Date.now() / 1000) + 3600 });
			authStore.login(token);
			authStore.logout();

			expect(authStore.isAuthenticated).toBe(false);
			expect(authStore.userName).toBe('');
			expect(authStore.userRoles).toEqual([]);
			expect(gotoMock).toHaveBeenCalledWith('/login');
		});

		it('single-flight: multiple logouts only redirect once', () => {
			const token = fakeJwt({ sub: 'user-1', exp: Math.floor(Date.now() / 1000) + 3600 });
			authStore.login(token);
			authStore.logout();
			authStore.logout();
			authStore.logout();

			expect(gotoMock).toHaveBeenCalledTimes(1);
		});

		it('calls backend logout to clear httpOnly cookies when CSRF is available', async () => {
			const token = fakeJwt({ sub: 'user-1', exp: Math.floor(Date.now() / 1000) + 3600 });
			const fetchMock = vi
				.fn()
				.mockResolvedValueOnce(
					new Response(JSON.stringify({ csrf_token: 'csrf-1' }), {
						status: 200,
						headers: { 'Content-Type': 'application/json' },
					}),
				)
				.mockResolvedValueOnce(new Response('{}', { status: 200 }));
			vi.stubGlobal('fetch', fetchMock);
			await authStore.establishSession(token);

			authStore.logout();

			expect(fetchMock).toHaveBeenLastCalledWith(
				'http://localhost:8000/auth/logout',
				expect.objectContaining({
					method: 'POST',
					credentials: 'include',
					keepalive: true,
					headers: { 'X-CSRF-Token': 'csrf-1' },
				}),
			);
		});
	});

	describe('userSub (J-A6-04)', () => {
		it('returns the JWT sub claim when present', () => {
			const token = fakeJwt({
				sub: 'user-1',
				name: 'Test User',
				exp: Math.floor(Date.now() / 1000) + 3600,
			});
			authStore.login(token);
			expect(authStore.userSub).toBe('user-1');
		});

		it('does NOT fall back to display name when sub is missing', () => {
			const token = fakeJwt({
				name: 'Test User',
				exp: Math.floor(Date.now() / 1000) + 3600,
			});
			authStore.login(token);
			// userName falls back to '' (no sub, no name accessor mismatch),
			// but userSub must be null so callers hard-fail rather than
			// fabricate identity from a mutable claim.
			expect(authStore.userSub).toBeNull();
		});

		it('returns null when sub is empty string', () => {
			const token = fakeJwt({ sub: '', exp: Math.floor(Date.now() / 1000) + 3600 });
			authStore.login(token);
			expect(authStore.userSub).toBeNull();
		});

		it('returns null before login', () => {
			expect(authStore.userSub).toBeNull();
		});

		it('returns null after logout', () => {
			const token = fakeJwt({ sub: 'user-1', exp: Math.floor(Date.now() / 1000) + 3600 });
			authStore.login(token);
			authStore.logout();
			expect(authStore.userSub).toBeNull();
		});
	});

	describe('roles', () => {
		it('hasRole returns true for matching role', () => {
			const token = fakeJwt({ sub: 'u', roles: ['trader'], exp: Math.floor(Date.now() / 1000) + 3600 });
			authStore.login(token);
			expect(authStore.hasRole('trader')).toBe(true);
			expect(authStore.hasRole('auditor')).toBe(false);
		});

		it('hasAnyRole checks multiple roles', () => {
			const token = fakeJwt({ sub: 'u', roles: ['auditor'], exp: Math.floor(Date.now() / 1000) + 3600 });
			authStore.login(token);
			expect(authStore.hasAnyRole('trader', 'auditor')).toBe(true);
			expect(authStore.hasAnyRole('trader', 'risk_manager')).toBe(false);
		});

		it('rejects auditor mixed with other human roles', () => {
			const token = fakeJwt({
				sub: 'auditor-mixed',
				roles: ['auditor', 'trader'],
				exp: Math.floor(Date.now() / 1000) + 3600,
			});
			expect(() => authStore.login(token)).toThrow('Invalid token');
			expect(authStore.isAuthenticated).toBe(false);
		});

		it('isTraderOnly is true only for the single trader role', () => {
			authStore.login(fakeJwt({ sub: 'u1', roles: ['trader'], exp: Math.floor(Date.now() / 1000) + 3600 }));
			expect(authStore.isTraderOnly()).toBe(true);

			authStore.login(fakeJwt({ sub: 'u2', roles: ['trader', 'risk_manager'], exp: Math.floor(Date.now() / 1000) + 3600 }));
			expect(authStore.isTraderOnly()).toBe(false);

			authStore.login(fakeJwt({ sub: 'u3', roles: ['auditor'], exp: Math.floor(Date.now() / 1000) + 3600 }));
			expect(authStore.isTraderOnly()).toBe(false);
		});

		it('defaults to empty roles when not in JWT', () => {
			const token = fakeJwt({ sub: 'u', exp: Math.floor(Date.now() / 1000) + 3600 });
			authStore.login(token);
			expect(authStore.userRoles).toEqual([]);
		});
	});

	describe('getAuthHeader', () => {
		it('does not expose Bearer tokens after authentication', () => {
			const token = fakeJwt({ sub: 'u', exp: Math.floor(Date.now() / 1000) + 3600 });
			authStore.login(token);
			expect(authStore.getAuthHeader()).toBeNull();
			expect(authStore.getToken()).toBeNull();
		});

		it('returns null when not authenticated', () => {
			expect(authStore.getAuthHeader()).toBeNull();
			expect(authStore.getToken()).toBeNull();
		});
	});

	describe('expiry timers', () => {
		it('shows warning 5min before expiry', () => {
			const expInSec = Math.floor(Date.now() / 1000) + 600; // 10 min from now
			const token = fakeJwt({ sub: 'u', exp: expInSec });
			authStore.login(token);

			expect(authStore.showExpiryWarning).toBe(false);

			// Advance 5min + 1ms — should now be <5min remaining
			vi.advanceTimersByTime(5 * 60 * 1000 + 1);
			expect(authStore.showExpiryWarning).toBe(true);
		});

		it('shows warning immediately when <5min remain', () => {
			const expInSec = Math.floor(Date.now() / 1000) + 120; // 2min from now
			const token = fakeJwt({ sub: 'u', exp: expInSec });
			authStore.login(token);

			expect(authStore.showExpiryWarning).toBe(true);
		});

		it('auto-logouts on token expiry', () => {
			const expInSec = Math.floor(Date.now() / 1000) + 60; // 1min from now
			const token = fakeJwt({ sub: 'u', exp: expInSec });
			authStore.login(token);

			vi.advanceTimersByTime(60 * 1000 + 1);
			expect(authStore.isAuthenticated).toBe(false);
			expect(gotoMock).toHaveBeenCalledWith('/login');
		});

		it('logouts immediately for expired token', () => {
			const expInSec = Math.floor(Date.now() / 1000) - 10; // already expired
			const token = fakeJwt({ sub: 'u', exp: expInSec });
			authStore.login(token);
			expect(authStore.isAuthenticated).toBe(false);
		});

		it('does not set timers when exp is absent', () => {
			const token = fakeJwt({ sub: 'u' });
			authStore.login(token);
			expect(authStore.isAuthenticated).toBe(true);
			expect(authStore.expiresAt).toBeNull();
		});
	});
});
