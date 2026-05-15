import { expect, type Page } from '@playwright/test';

const API_BASE = process.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

function fakeJwt(payload: Record<string, unknown>): string {
	const header = btoa(JSON.stringify({ alg: 'RS256', typ: 'JWT' }));
	const body = btoa(JSON.stringify(payload));
	const sig = btoa('fake-signature');
	return `${header}.${body}.${sig}`;
}

async function seedCookieSession(page: Page, roles: string[]): Promise<void> {
	const clerkToken = fakeJwt({
		sub: 'e2e-test-user',
		name: 'E2E Test User',
		roles,
		exp: Math.floor(Date.now() / 1000) + 3600,
	});
	await page.route(`${API_BASE}/auth/me`, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ actor_sub: 'e2e-test-user', roles }),
		});
	});
	await page.route(`${API_BASE}/auth/refresh`, async (route) => {
		await route.fulfill({
			status: 200,
			contentType: 'application/json',
			body: JSON.stringify({ csrf_token: 'csrf-e2e-refreshed' }),
		});
	});
	await page.route(`${API_BASE}/auth/logout`, async (route) => {
		await route.fulfill({ status: 204, body: '' });
	});
	await page.addInitScript((token) => {
		(window as unknown as { __internal_ClerkUICtor: unknown }).__internal_ClerkUICtor = function ClerkUI() {};
		(window as unknown as { Clerk: unknown }).Clerk = {
			load: async () => undefined,
			session: { getToken: async () => token },
			mountSignIn: () => undefined,
			unmountSignIn: () => undefined,
			mountSignUp: () => undefined,
			unmountSignUp: () => undefined,
			signOut: async () => undefined,
		};
		window.sessionStorage.setItem('hedge-control.auth.csrf', 'csrf-e2e');
		document.cookie = 'csrf_token=csrf-e2e; path=/';
	}, clerkToken);
}

export async function loginAsTrader(page: Page): Promise<void> {
	await seedCookieSession(page, ['trader']);
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 10_000 });
}

export async function loginAsAdmin(page: Page): Promise<void> {
	await seedCookieSession(page, ['trader', 'risk_manager']);
	await page.goto('/');
	await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 10_000 });
}
