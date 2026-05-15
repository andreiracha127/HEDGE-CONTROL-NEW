/**
 * J-A6-08 / J-A6-09 — static invariants for the read-only
 * orders + audit surfaces.
 *
 * Mirrors the source-scan pattern used by `page-contracts.test.ts` and
 * `rfq-evidence-integrity.test.ts`.
 */
// @vitest-environment node
// @ts-nocheck — Node-only source-scan; matches existing convention.
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const ROUTES = resolve(process.cwd(), 'src', 'routes');
const SRC = resolve(process.cwd(), 'src');

function read(rel: string): string {
	return readFileSync(resolve(ROUTES, rel), 'utf8');
}

describe('orders list page — J-A6-08 reconstructability surface', () => {
	const source = read('(protected)/orders/+page.svelte');

	it('exists and calls the canonical /orders list endpoint via ordersListPath', () => {
		expect(source).toContain('ordersListPath');
		expect(source).toContain("import { ordersListPath } from '$lib/api/paths'");
	});

	it('renders canonical OrderRead fields (id, quantity_mt, order_type, commodity)', () => {
		expect(source).toMatch(/order\.id/);
		expect(source).toMatch(/order\.quantity_mt/);
		expect(source).toMatch(/order\.order_type/);
		expect(source).toMatch(/order\.commodity/);
	});

	it('renders MT quantity via formatQuantityMT (three-decimal preservation)', () => {
		expect(source).toMatch(/formatQuantityMT\(order\.quantity_mt\)/);
	});

	it('links each row to the /orders/{id} detail view', () => {
		expect(source).toMatch(/href=\{`\/orders\/\$\{order\.id\}`\}/);
		expect(source).toContain('data-testid="orders-detail-link"');
	});

	it('does not introduce order mutation UI (J-A6-08 read-only scope)', () => {
		// Order create/archive/link mutations are out of scope per
		// dispatch §8 — guard against accidental scope creep by ruling
		// out any non-GET apiFetch on order endpoints.
		expect(source).not.toMatch(/method\s*:\s*['"](POST|PUT|DELETE|PATCH)['"]/);
		// And the specific create paths must not appear as fetch literals.
		expect(source).not.toMatch(/apiFetch\([^)]*\/orders\/purchase/);
		expect(source).not.toMatch(/apiFetch\([^)]*\/orders\/sales/);
		expect(source).not.toMatch(/apiFetch\([^)]*\/orders\/links/);
		expect(source).not.toMatch(/apiFetch\([^)]*\/orders\/[^\s)'"`]*\/archive/);
	});
});

describe('order detail page — J-A6-08 reconstructability surface', () => {
	const source = read('(protected)/orders/[id]/+page.svelte');

	it('exists and calls /orders/{id} via orderDetailPath', () => {
		expect(source).toContain('orderDetailPath');
		expect(source).toContain("import { orderDetailPath } from '$lib/api/paths'");
	});

	it('reads the {id} param via SvelteKit page.params', () => {
		expect(source).toContain('page.params.id');
	});

	it('renders MT quantity via formatQuantityMT', () => {
		expect(source).toMatch(/formatQuantityMT\(order\.quantity_mt\)/);
	});

	it('does not introduce order mutation UI (read-only scope)', () => {
		expect(source).not.toMatch(/apiFetch\([^)]*method\s*:\s*['"]POST/);
		expect(source).not.toMatch(/apiFetch\([^)]*method\s*:\s*['"]PUT/);
		expect(source).not.toMatch(/apiFetch\([^)]*method\s*:\s*['"]DELETE/);
		expect(source).not.toMatch(/apiFetch\([^)]*method\s*:\s*['"]PATCH/);
	});
});

describe('audit events page — J-A6-09 reconstructability surface', () => {
	const source = read('(protected)/audit/+page.svelte');

	it('exists and calls /audit/events + /audit/events/{id}/verify via the typed helpers', () => {
		expect(source).toContain('auditEventsPath');
		expect(source).toContain('auditEventVerifyPath');
		expect(source).toContain(
			"import { auditEventsPath, auditEventVerifyPath } from '$lib/api/paths'",
		);
	});

	it('gates the page UI behind the auditor role', () => {
		// The auditor role check must be present in this file. Backend
		// `require_role("auditor")` is the security boundary; this is
		// a UX courtesy that hides the route for unauthorised users.
		expect(source).toMatch(/hasRole\(\s*['"]auditor['"]\s*\)/);
		expect(source).toContain('data-testid="audit-forbidden"');
	});

	it('renders the verify action with distinct valid/invalid/unverifiable status states', () => {
		expect(source).toMatch(/verifyEvent\(/);
		expect(source).toMatch(/['"]valid['"]/);
		expect(source).toMatch(/['"]invalid['"]/);
		expect(source).toMatch(/['"]unverifiable['"]/);
		expect(source).toContain('data-testid="audit-verify-button"');
	});

	it('does not allow audit mutations (no PUT/POST/DELETE/PATCH on /audit endpoints)', () => {
		// /audit/events is GET-only; verify is GET-only on the backend.
		// Frontend must not synthesise mutation calls.
		expect(source).not.toMatch(/method\s*:\s*['"](POST|PUT|DELETE|PATCH)['"]/);
	});
});

describe('layout — J-A6-08/09 navigation visibility', () => {
	const source = readFileSync(resolve(ROUTES, '+layout.svelte'), 'utf8');

	it('always lists /orders in the protected nav (visible to any authenticated user)', () => {
		expect(source).toMatch(/href:\s*['"]\/orders['"]/);
	});

	it('only lists /audit in the nav when authStore.hasRole(\'auditor\') is true', () => {
		// The nav array must spread the /audit entry from a hasRole
		// ternary so non-auditors (risk_manager, trader) never see the
		// link. Asserted as a structural match — the spread `...(... ?
		// [{href:'/audit',...}] : [])` must appear in the source — not
		// as an index-order heuristic that breaks if `/audit` is later
		// referenced anywhere else in the file.
		expect(source).toMatch(
			/\.\.\.\(\s*authStore\.hasRole\(\s*['"]auditor['"]\s*\)[\s\S]*?href:\s*['"]\/audit['"][\s\S]*?\)/,
		);
		// And it must NOT appear as an unconditional flat array entry.
		expect(source).not.toMatch(
			/\{\s*href:\s*['"]\/audit['"][^}]*\}\s*,\s*(?!\s*\])/,
		);
	});
});

describe('login page — Clerk SDK surface', () => {
	const source = readFileSync(
		resolve(ROUTES, '(public)', 'login', '+page.svelte'),
		'utf8',
	);
	const rootLayoutSource = readFileSync(resolve(ROUTES, '+layout.svelte'), 'utf8');
	const clerkSource = readFileSync(resolve(SRC, 'lib', 'clerk.ts'), 'utf8');

	it('mounts Clerk SignIn and routes the session through authStore.establishSession', () => {
		expect(source).toContain('clerk.mountSignIn');
		expect(source).toContain('authStore.establishSession');
		expect(source).not.toMatch(/fetch\([^)]*\/auth\/session/);
	});

	it('loads the Clerk UI bundle before mounting prebuilt components', () => {
		expect(clerkSource).toContain('@clerk/clerk-js@6/dist/clerk.browser.js');
		expect(clerkSource).toContain('@clerk/ui@1/dist/ui.browser.js');
		expect(clerkSource).toContain('__internal_ClerkUICtor');
		expect(clerkSource).toMatch(/ui:\s*\{\s*ClerkUI:/);
	});

	it('initializes Clerk on restored authenticated layouts so cookie sessions can refresh', () => {
		expect(rootLayoutSource).toContain('if (authStore.isAuthenticated)');
		expect(rootLayoutSource).toContain('void initClerk().catch');
	});

	it('does not retain the retired manual token form', () => {
		expect(source).not.toContain('login-manual-form');
		expect(source).not.toContain('login-config-error');
		expect(source).not.toContain('manual' + 'TokenLoginEnabled');
		expect(source).not.toContain('VITE_ALLOW_' + 'MANUAL_TOKEN_LOGIN');
		expect(source).not.toContain('runtimeFlags');
	});
});

describe('sign-up page — Clerk SDK surface', () => {
	const source = readFileSync(
		resolve(ROUTES, '(public)', 'sign-up', '+page.svelte'),
		'utf8',
	);

	it('mounts Clerk SignUp and routes the session through authStore.establishSession', () => {
		expect(source).toContain('clerk.mountSignUp');
		expect(source).toContain('authStore.establishSession');
		expect(source).not.toMatch(/fetch\([^)]*\/auth\/session/);
	});
});

describe('runtime config', () => {
	const cfg = readFileSync(resolve(SRC, 'lib', 'config', 'runtime.ts'), 'utf8');

	it('does not retain the retired manual-token build flag', () => {
		expect(cfg).not.toContain('VITE_ALLOW_' + 'MANUAL_TOKEN_LOGIN');
		expect(cfg).not.toContain('manual' + 'TokenLoginEnabled');
		expect(cfg).not.toContain('manual' + 'TokenLoginReason');
		expect(cfg).not.toMatch(/process\.env/);
	});
});
