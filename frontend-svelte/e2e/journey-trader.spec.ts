import { expect, test } from '@playwright/test';
import { bootstrapPersona, expectBackendHealthy } from './_personas';

test('trader journey reaches the live app shell without backend mocks', async ({ page, request }) => {
	await expectBackendHealthy(request);
	await bootstrapPersona(page, 'trader');
	await page.goto('/login');
	await expect(page).toHaveURL(/\/login/);
	await expect(page.locator('body')).toBeVisible();
});
