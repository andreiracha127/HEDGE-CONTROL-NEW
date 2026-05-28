import { test, expect } from '@playwright/test';
import { loginAsTrader, loginAsAdmin } from './helpers';

test.describe('Contracts', () => {
	test.beforeEach(async ({ page }) => {
		await loginAsTrader(page);
	});

	test('contract list page loads', async ({ page }) => {
		await page.goto('/contracts');
		await expect(page.getByRole('heading', { name: 'Contratos' })).toBeVisible();
	});

	test('contract list shows filter controls', async ({ page }) => {
		await page.goto('/contracts');
		await expect(page.getByRole('button', { name: /Ativos/ })).toBeVisible();
		await expect(page.getByRole('button', { name: /Vencendo/ })).toBeVisible();
		await expect(page.getByRole('button', { name: /Liquidados/ })).toBeVisible();
		await expect(page.getByRole('button', { name: 'Commodity' })).toBeVisible();
	});

	test('clicking a contract row navigates to detail', async ({ page }) => {
		await page.goto('/contracts');
		const firstRow = page.locator('tbody tr').first();
		if (await firstRow.isVisible({ timeout: 5000 }).catch(() => false)) {
			await firstRow.click();
			await expect(page).toHaveURL(/\/contracts\/[a-f0-9-]+/);
			// Detail page should show reference
			await expect(page.locator('text=Detalhes')).toBeVisible();
			await expect(page.locator('text=Legs')).toBeVisible();
		}
	});

	test('contract detail shows status transition buttons for trader', async ({ page }) => {
		await page.goto('/contracts');
		const firstRow = page.locator('tbody tr').first();
		if (await firstRow.isVisible({ timeout: 5000 }).catch(() => false)) {
			await firstRow.click();
			await page.waitForURL(/\/contracts\/[a-f0-9-]+/);
			// Active contracts should show transition buttons
			const statusBadge = page.locator('span:has-text("Ativo")');
			if (await statusBadge.isVisible().catch(() => false)) {
				await expect(page.locator('button:has-text("Liquidar")')).toBeVisible();
				await expect(page.locator('button:has-text("Cancelar")')).toBeVisible();
			}
		}
	});
});
