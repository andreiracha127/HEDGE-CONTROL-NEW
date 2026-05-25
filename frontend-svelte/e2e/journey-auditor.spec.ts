import { expect, test } from '@playwright/test';
import { bootstrapPersona, expectBackendHealthy } from './_personas';

test('auditor journey reaches the audit route shell without route mocks', async ({ page, request }) => {
	await expectBackendHealthy(request);
	await bootstrapPersona(page, 'auditor');
	await page.goto('/audit');
	await expect(page.locator('body')).toBeVisible();
});
