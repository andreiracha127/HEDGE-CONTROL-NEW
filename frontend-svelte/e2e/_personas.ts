import type { APIRequestContext, Page } from '@playwright/test';

export type Persona = 'trader' | 'risk_manager' | 'auditor';

export const API_BASE = process.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

function fakeJwt(payload: Record<string, unknown>): string {
	const header = Buffer.from(JSON.stringify({ alg: 'RS256', typ: 'JWT' })).toString('base64url');
	const body = Buffer.from(JSON.stringify(payload)).toString('base64url');
	const sig = Buffer.from('e2e-signature').toString('base64url');
	return `${header}.${body}.${sig}`;
}

export async function bootstrapPersona(page: Page, persona: Persona): Promise<void> {
	const token = fakeJwt({
		sub: `e2e-${persona}`,
		roles: [persona],
		exp: Math.floor(Date.now() / 1000) + 300,
	});
	await page.addInitScript(
		({ csrf, sessionToken }) => {
			window.sessionStorage.setItem('hedge-control.auth.csrf', csrf);
			window.sessionStorage.setItem('hedge-control.auth.token', sessionToken);
			document.cookie = `csrf_token=${csrf}; path=/`;
		},
		{ csrf: 'test-csrf-token', sessionToken: token },
	);
}

export async function expectBackendHealthy(request: APIRequestContext): Promise<void> {
	const response = await request.get(`${API_BASE}/health`);
	if (!response.ok()) {
		throw new Error(`backend health failed: ${response.status()} ${await response.text()}`);
	}
}
