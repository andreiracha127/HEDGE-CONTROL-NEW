import { type Page } from '@playwright/test';

/**
 * Generate a fake JWT token for dev-mode authentication.
 * The backend ignores JWT validation when JWT_ISSUER is empty.
 * The frontend only decodes the payload (no signature verification).
 */
export function createDevToken(overrides: {
	sub?: string;
	name?: string;
	roles?: string[];
	exp?: number;
} = {}): string {
	const header = { alg: 'RS256', typ: 'JWT' };
	const payload = {
		sub: overrides.sub ?? 'e2e-test-user',
		name: overrides.name ?? 'E2E Tester',
		roles: overrides.roles ?? ['trader', 'risk_manager'],
		iat: Math.floor(Date.now() / 1000),
		exp: overrides.exp ?? Math.floor(Date.now() / 1000) + 3600,
	};

	const encode = (obj: object) =>
		Buffer.from(JSON.stringify(obj))
			.toString('base64url');

	return `${encode(header)}.${encode(payload)}.fake-signature`;
}

/**
 * Log in via the login page UI with a dev JWT token.
 */
export async function loginAsTrader(page: Page): Promise<void> {
	const token = createDevToken({ roles: ['trader'] });
	await page.goto('/login');
	await page.locator('#token').fill(token);
	await page.locator('button[type="submit"]').click();
	await page.waitForURL('/', { timeout: 5000 });
}

/**
 * Log in with all roles (trader + risk_manager + auditor).
 */
export async function loginAsAdmin(page: Page): Promise<void> {
	const token = createDevToken();
	await page.goto('/login');
	await page.locator('#token').fill(token);
	await page.locator('button[type="submit"]').click();
	await page.waitForURL('/', { timeout: 5000 });
}
