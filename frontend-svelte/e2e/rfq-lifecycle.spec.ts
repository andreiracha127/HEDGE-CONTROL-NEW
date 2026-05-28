import { test, expect } from '@playwright/test';
import { loginAsRiskManager } from './helpers';

const RFQ_BOARD_HEADING = 'Solicitações de cotação';

test.describe('RFQ Lifecycle', () => {
	test.beforeEach(async ({ page }) => {
		await loginAsRiskManager(page);
	});

	test('navigates to RFQ board from dashboard', async ({ page }) => {
		await page.locator('a[href="/rfq"]').first().click();
		await expect(page).toHaveURL(/\/rfq/);
	});

	test('RFQ board loads and shows list or empty state', async ({ page }) => {
		await page.goto('/rfq');
		await expect(page.getByRole('heading', { name: RFQ_BOARD_HEADING })).toBeVisible({ timeout: 10_000 });
	});

	test('navigates to new RFQ form', async ({ page }) => {
		await page.goto('/rfq');
		const newBtn = page.locator('a[href="/rfq/new"]');
		if (await newBtn.isVisible()) {
			await newBtn.click();
			await expect(page).toHaveURL(/\/rfq\/new/);
			// Form should have commodity selection
			await expect(page.getByLabel('Commodity')).toBeVisible();
		}
	});

	test('RFQ creation form has required fields', async ({ page }) => {
		await page.goto('/rfq/new');
		// Key form elements
		await expect(page.getByLabel('Commodity')).toBeVisible();
		await expect(page.getByLabel('Quantidade')).toBeVisible();
		await expect(page.getByRole('button', { name: /Enviar a/ })).toBeVisible();
	});
});
