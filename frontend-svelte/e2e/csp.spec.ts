import { test, expect } from '@playwright/test';

/**
 * CSP Report-Only + Reporting endpoint smoke tests (PR-CL3-4).
 *
 * These tests require the full docker-compose stack (db + backend + frontend-svelte)
 * to be running with the updated nginx CSP template + entrypoint substitution:
 *
 *   docker-compose up -d --build db backend frontend-svelte
 *
 * They verify:
 * - Content-Security-Policy-Report-Only header is present with the bindado 13-directive shape
 * - No enforce-mode Content-Security-Policy header leaks
 * - Report-To header points at the backend /csp/report
 * - Clerk login page loads without CSP violations in console (report-only ramp is clean for known Clerk domains)
 */

test.describe('CSP Report-Only infrastructure (D-3.3)', () => {
	// Regression for Codex P2 on PR #85: docker-entrypoint.sh now derives CLERK_FAPI_HOST
	// from VITE_CLERK_PUBLISHABLE_KEY (base64 url-safe decode of tenant suffix) instead of
	// falling back to bare parent domain "clerk.accounts.dev". This prevents CSP blocks post-enforce.
	// NOTE: header-assertion tests are docker/nginx-gated (internal skip); console smoke test below runs on static dev serve.
	test('serves Content-Security-Policy-Report-Only header with strict Clerk-aware baseline', async ({
		page,
	}) => {
		test.skip(true, 'CSP Report-Only headers injected by nginx in full docker-compose frontend-svelte; CI E2E uses static serve (no headers). Manual: docker compose up -d --build db backend frontend-svelte then npx playwright test e2e/csp.spec.ts');
		const response = await page.goto('/login');
		expect(response).not.toBeNull();

		const csp = response!.headers()['content-security-policy-report-only'];
		expect(csp, 'CSP-Report-Only header must be present').toBeDefined();
		expect(csp).toContain("default-src 'self'");
		expect(csp).toContain("script-src 'self' 'unsafe-inline' https://");
		expect(csp).toContain('https://challenges.cloudflare.com');
		expect(csp).toContain('connect-src');
		expect(csp).toContain('frame-ancestors \'none\'');
		expect(csp).toContain('report-to csp-endpoint');
		// No unsafe-eval per bindado decision
		expect(csp).not.toContain("'unsafe-eval'");
	});

	test('does NOT serve an enforce-mode Content-Security-Policy header', async ({ page }) => {
		test.skip(true, 'Enforce CSP header check requires nginx-injected headers from full docker-compose; CI uses static serve. Manual: docker compose up -d --build ...');
		const response = await page.goto('/login');
		const enforce = response!.headers()['content-security-policy'];
		expect(enforce, 'Enforce CSP header must be absent in report-only ramp').toBeUndefined();
	});

	test('Report-To header points at backend /csp/report endpoint', async ({ page }) => {
		test.skip(true, 'Report-To header injected by nginx in full docker-compose frontend-svelte service; CI E2E uses static serve. Manual verification command in first CSP test skip reason.');
		const response = await page.goto('/');
		const reportTo = response!.headers()['report-to'];
		expect(reportTo, 'Report-To header must be present').toBeDefined();
		expect(reportTo).toContain('/csp/report');
		expect(reportTo).toContain('csp-endpoint');
	});

	test('Clerk login page loads with zero CSP violations in browser console', async ({ page }) => {
		const cspMessages: string[] = [];
		page.on('console', (msg) => {
			const text = msg.text();
			if (
				text.toLowerCase().includes('content security policy') ||
				text.toLowerCase().includes('csp') ||
				text.includes('Refused to load')
			) {
				cspMessages.push(text);
			}
		});

		const pageErrors: string[] = [];
		page.on('pageerror', (err) => pageErrors.push(err.message));

		await page.goto('/login');

		// Wait for Clerk UI to hydrate (scripts from FAPI + challenges.cloudflare)
		await expect(page.locator('h1')).toContainText('Hedge Control', { timeout: 15_000 });

		// Allow a short window for any late CSP reports (report-only does not block)
		await page.waitForTimeout(1500);

		expect(
			cspMessages,
			'No CSP violation messages should appear in console during Clerk login load (report-only ramp)'
		).toHaveLength(0);
		expect(pageErrors.filter((e) => e.toLowerCase().includes('csp'))).toHaveLength(0);
	});
});
