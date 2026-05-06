import { test, expect } from '@playwright/test';
import { loginAsAdmin } from './helpers';

test.describe('Login → Dashboard flow', () => {
	test('redirects unauthenticated users to /login', async ({ page }) => {
		await page.goto('/');
		await expect(page).toHaveURL(/\/login/);
	});

	test('shows login page with JWT token input', async ({ page }) => {
		await page.goto('/login');
		await expect(page.locator('h1')).toContainText('Hedge Control');
		await expect(page.locator('#token')).toBeVisible();
		await expect(page.locator('button[type="submit"]')).toBeVisible();
	});

	test('rejects invalid token format', async ({ page }) => {
		await page.goto('/login');
		await page.locator('#token').fill('not-a-jwt');
		await page.locator('button[type="submit"]').click();
		// Should stay on login page (invalid token doesn't navigate)
		await expect(page).toHaveURL(/\/login/);
	});

	test('authenticates with valid dev token and reaches dashboard', async ({ page }) => {
		await loginAsAdmin(page);
		// Dashboard should show key elements
		await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 10_000 });
		await expect(page.getByRole('link', { name: /RFQs Gerenciar cotações/ })).toBeVisible();
	});

	test('navigates between sections after login', async ({ page }) => {
		await loginAsAdmin(page);

		// Navigate to contracts
		await page.locator('a[href="/contracts"]').first().click();
		await expect(page).toHaveURL(/\/contracts/);
		await expect(page.getByRole('heading', { name: 'Contratos' })).toBeVisible();

		// Navigate to exposures
		await page.locator('a[href="/exposures"]').first().click();
		await expect(page).toHaveURL(/\/exposures/);
	});
});
