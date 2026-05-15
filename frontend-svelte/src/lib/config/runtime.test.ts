import { describe, it, expect } from 'vitest';
import { resolveRuntimeFlags } from './runtime';

describe('resolveRuntimeFlags', () => {
	it('returns mode without the retired manual-token login flag in development', () => {
		const r = resolveRuntimeFlags({ DEV: true, MODE: 'development' });
		expect(r).toEqual({ mode: 'development' });
		expect(r).not.toHaveProperty('manual' + 'TokenLoginEnabled');
		expect(r).not.toHaveProperty('manual' + 'TokenLoginReason');
	});

	it('ignores the retired manual-token opt-in flag', () => {
		const r = resolveRuntimeFlags({
			DEV: false,
			MODE: 'production',
			['VITE_ALLOW_' + 'MANUAL_TOKEN_LOGIN']: '1',
		});
		expect(r).toEqual({ mode: 'production' });
		expect(r).not.toHaveProperty('manual' + 'TokenLoginEnabled');
	});

	it('falls back to production when MODE is absent and DEV is false', () => {
		const r = resolveRuntimeFlags({ DEV: false });
		expect(r.mode).toBe('production');
	});
});
