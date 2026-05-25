import { expect, test } from '@playwright/test';
import { bootstrapPersona, expectBackendHealthy } from './_personas';

test('risk manager journey verifies live backend availability without route mocks', async ({
	page,
	request,
}) => {
	await expectBackendHealthy(request);
	await bootstrapPersona(page, 'risk_manager');
	await page.goto('/contracts');
	await expect(page).toHaveURL(/\/contracts/);
	await expect(page.locator('body')).toBeVisible();
});
