/**
 * J-A6-10 — manual JWT login gating logic.
 *
 * The flow must remain available in dev/test/local builds and stay
 * disabled in production builds unless the operator explicitly opts
 * in. These tests exercise `resolveRuntimeFlags` against synthetic env
 * snapshots so the gating decision is reproducible without relying on
 * Vite's actual compile-time `import.meta.env`.
 */
import { describe, it, expect } from 'vitest';
import { resolveRuntimeFlags } from './runtime';

describe('resolveRuntimeFlags — manual JWT login gating', () => {
	it('enables manual login when DEV is true', () => {
		const r = resolveRuntimeFlags({ DEV: true, MODE: 'development' });
		expect(r.manualTokenLoginEnabled).toBe(true);
		expect(r.manualTokenLoginReason).toBe('dev-mode');
	});

	it('enables manual login when MODE is development', () => {
		const r = resolveRuntimeFlags({ DEV: false, MODE: 'development' });
		expect(r.manualTokenLoginEnabled).toBe(true);
		expect(r.manualTokenLoginReason).toBe('dev-mode');
	});

	it('enables manual login when MODE is test', () => {
		const r = resolveRuntimeFlags({ DEV: false, MODE: 'test' });
		expect(r.manualTokenLoginEnabled).toBe(true);
	});

	it('disables manual login in production without opt-in', () => {
		const r = resolveRuntimeFlags({ DEV: false, MODE: 'production' });
		expect(r.manualTokenLoginEnabled).toBe(false);
		expect(r.manualTokenLoginReason).toBe('disabled-no-production-login');
	});

	it('disables manual login in staging without opt-in', () => {
		const r = resolveRuntimeFlags({ DEV: false, MODE: 'staging' });
		expect(r.manualTokenLoginEnabled).toBe(false);
	});

	it('re-enables manual login in production when the explicit opt-in flag is "1"', () => {
		const r = resolveRuntimeFlags({
			DEV: false,
			MODE: 'production',
			VITE_ALLOW_MANUAL_TOKEN_LOGIN: '1',
		});
		expect(r.manualTokenLoginEnabled).toBe(true);
		expect(r.manualTokenLoginReason).toBe('explicit-opt-in');
	});

	it('rejects opt-in values other than the literal "1" (no silent truthy coercion)', () => {
		// Guards against accidental enablement via env values like
		// 'true', 'yes', '0', or whitespace. The flag must be exactly '1'.
		for (const v of ['true', 'yes', '0', '', ' 1 ', 'TRUE']) {
			const r = resolveRuntimeFlags({
				DEV: false,
				MODE: 'production',
				VITE_ALLOW_MANUAL_TOKEN_LOGIN: v,
			});
			expect(r.manualTokenLoginEnabled, `value=${JSON.stringify(v)}`).toBe(false);
		}
	});

	it('falls back to production when MODE is absent and DEV is false', () => {
		const r = resolveRuntimeFlags({ DEV: false });
		expect(r.mode).toBe('production');
		expect(r.manualTokenLoginEnabled).toBe(false);
	});

	it('treats absent DEV as development when MODE is development', () => {
		const r = resolveRuntimeFlags({ MODE: 'development' });
		expect(r.manualTokenLoginEnabled).toBe(true);
	});
});
