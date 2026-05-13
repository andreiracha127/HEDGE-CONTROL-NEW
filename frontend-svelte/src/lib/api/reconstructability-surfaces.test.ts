/**
 * J-A6-08 / J-A6-09 / J-A6-10 — static invariants for the read-only
 * orders + audit surfaces and the gated manual JWT login.
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
		// The nav array spread must depend on hasRole('auditor') so
		// non-auditors (e.g. risk_manager, trader) do not see the link.
		expect(source).toMatch(/hasRole\(\s*['"]auditor['"]\s*\)/);
		expect(source).toMatch(/href:\s*['"]\/audit['"]/);
		// The unconditional listing pattern would be a flat array entry
		// outside the ternary spread — guard against that.
		const idxAudit = source.indexOf("href: '/audit'");
		const idxRole = source.indexOf("hasRole('auditor')");
		expect(idxAudit, '/audit href should appear after the hasRole check').toBeGreaterThan(idxRole);
	});
});

describe('login page — J-A6-10 dev-login gating', () => {
	const source = readFileSync(
		resolve(ROUTES, '(public)', 'login', '+page.svelte'),
		'utf8',
	);

	it('imports the runtime-flags helper and gates the paste form on manualTokenLoginEnabled', () => {
		expect(source).toContain("import { runtimeFlags } from '$lib/config/runtime'");
		expect(source).toMatch(/manualTokenLoginEnabled/);
	});

	it('renders an explicit configuration error when manual login is disabled', () => {
		expect(source).toContain('data-testid="login-config-error"');
		expect(source).toMatch(/\{:else\}/);
	});

	it('refuses submission when manual login is disabled even if the form is somehow reached', () => {
		// Even though the form is hidden behind {#if manualLoginEnabled},
		// handleLogin guards against the disabled case explicitly. Belt
		// and braces: the dispatch's "do not silently allow dev-only
		// flow" rule must not depend on the {#if} alone.
		expect(source).toMatch(/!manualLoginEnabled[\s\S]*?notifications\.error/);
	});

	it('only shows the dev banner inside the enabled branch', () => {
		expect(source).toContain('data-testid="login-dev-banner"');
		// Banner copy must reflect the reason (dev-mode vs explicit-opt-in)
		expect(source).toMatch(/manualTokenLoginReason/);
	});
});

describe('runtime config — J-A6-10 build-flag location', () => {
	const cfg = readFileSync(resolve(SRC, 'lib', 'config', 'runtime.ts'), 'utf8');

	it('reads only Vite-prefixed env vars (no server secrets leak)', () => {
		// All compile-time env reads must be VITE_ prefixed; the gating
		// flag itself follows that convention.
		expect(cfg).toMatch(/VITE_ALLOW_MANUAL_TOKEN_LOGIN/);
		expect(cfg).not.toMatch(/process\.env/);
	});
});
