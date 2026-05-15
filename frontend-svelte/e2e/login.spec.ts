import { test, expect } from '@playwright/test';
import { loginAsAdmin } from './helpers';

test.describe('Login -> Dashboard flow', () => {
	test('redirects unauthenticated users to /login', async ({ page }) => {
		await page.goto('/');
		await expect(page).toHaveURL(/\/login/);
	});

	test('shows the Clerk-mounted login page without the retired token form', async ({ page }) => {
		const pageErrors: string[] = [];
		page.on('pageerror', (error) => pageErrors.push(error.message));

		await page.goto('/login');
		await expect(page.locator('h1')).toContainText('Hedge Control');
		await expect(page.locator('#token')).toHaveCount(0);
		await expect(page.locator('[data-testid="login-manual-form"]')).toHaveCount(0);
		await expect
			.poll(() => pageErrors, { timeout: 3_000 })
			.not.toContain('Clerk was not loaded with Ui components');
	});

	test('hydrates a valid backend cookie session before protected routing', async ({ page }) => {
		await loginAsAdmin(page);
		await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 10_000 });
		await page.reload();
		await expect(page.getByRole('heading', { name: 'Dashboard' })).toBeVisible({ timeout: 10_000 });
	});

	test('navigates between sections after cookie-session hydration', async ({ page }) => {
		await loginAsAdmin(page);

		await page.locator('a[href="/contracts"]').first().click();
		await expect(page).toHaveURL(/\/contracts/);
		await expect(page.getByRole('heading', { name: 'Contratos' })).toBeVisible();

		await page.locator('a[href="/exposures"]').first().click();
		await expect(page).toHaveURL(/\/exposures/);
	});
});
