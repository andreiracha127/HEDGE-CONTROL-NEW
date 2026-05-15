import { expect, type Page } from '@playwright/test';

const API_BASE = process.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

async function seedCookieSession(page: Page, roles: string[]): Promise<void> {
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
	await page.addInitScript(() => {
		window.sessionStorage.setItem('hedge-control.auth.csrf', 'csrf-e2e');
		document.cookie = 'csrf_token=csrf-e2e; path=/';
	});
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
