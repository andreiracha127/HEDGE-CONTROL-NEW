import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E config for Hedge Control frontend.
 *
 * Tests run against a real docker-compose stack (backend + db + frontend-svelte).
 * Start the stack before running: docker-compose up -d db backend frontend-svelte
 *
 * The BASE_URL env var overrides the default http://localhost:5173.
 */
export default defineConfig({
	testDir: './e2e',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 2 : 0,
	workers: process.env.CI ? '50%' : undefined,
	reporter: process.env.CI ? 'github' : 'html',
	timeout: 30_000,
	expect: {
		timeout: 10_000,
	},

	use: {
		baseURL: process.env.BASE_URL ?? 'http://localhost:5173',
		trace: 'on-first-retry',
		screenshot: 'only-on-failure',
	},

	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'] },
		},
	],
});
