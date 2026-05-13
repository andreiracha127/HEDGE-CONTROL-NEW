/**
 * Frontend runtime configuration (J-A6-10).
 *
 * The manual JWT-paste login flow is a developer convenience — it
 * bypasses any production identity provider and decodes the token
 * client-side without a backend exchange. The flow must therefore be
 * gated to development/test/local builds so it cannot be normalised as
 * a production workflow.
 *
 * Gating policy:
 *
 *   - Local / dev / test (`import.meta.env.DEV === true` OR `MODE` is
 *     `development` / `test`): manual login is permitted.
 *   - Any other mode (`production`, `staging`, etc.): manual login is
 *     permitted *only if* the operator opts in via the explicit build
 *     flag `VITE_ALLOW_MANUAL_TOKEN_LOGIN === '1'`. Operators flipping
 *     this flag on are signalling that they understand they are running
 *     a dev-only auth path against a non-dev environment (used for
 *     emergency break-glass or for hosted-preview builds before a real
 *     IdP is wired).
 *
 * The decision is therefore: presence of a documented dev environment
 * OR explicit production opt-in. Absent both, the login route renders a
 * hard-fail configuration message and refuses to accept tokens — the
 * dispatch's explicit "do not silently allow dev-only flow" requirement.
 */

export interface RuntimeFlags {
	manualTokenLoginEnabled: boolean;
	manualTokenLoginReason:
		| 'dev-mode'
		| 'explicit-opt-in'
		| 'disabled-no-production-login';
	mode: string;
}

interface RuntimeEnv {
	DEV?: boolean;
	MODE?: string;
	VITE_ALLOW_MANUAL_TOKEN_LOGIN?: string;
}

export function resolveRuntimeFlags(env: RuntimeEnv): RuntimeFlags {
	const mode = env.MODE ?? (env.DEV ? 'development' : 'production');
	const isDevLikeMode =
		env.DEV === true || mode === 'development' || mode === 'test';
	const explicitOptIn = env.VITE_ALLOW_MANUAL_TOKEN_LOGIN === '1';

	if (isDevLikeMode) {
		return {
			manualTokenLoginEnabled: true,
			manualTokenLoginReason: 'dev-mode',
			mode,
		};
	}
	if (explicitOptIn) {
		return {
			manualTokenLoginEnabled: true,
			manualTokenLoginReason: 'explicit-opt-in',
			mode,
		};
	}
	return {
		manualTokenLoginEnabled: false,
		manualTokenLoginReason: 'disabled-no-production-login',
		mode,
	};
}

// Live snapshot derived from Vite's compile-time env. Re-evaluated per
// import, which is correct: the values are baked at build time, so the
// runtime cannot drift away from the deploy-time configuration.
export const runtimeFlags: RuntimeFlags = resolveRuntimeFlags({
	DEV: import.meta.env.DEV,
	MODE: import.meta.env.MODE,
	VITE_ALLOW_MANUAL_TOKEN_LOGIN: import.meta.env.VITE_ALLOW_MANUAL_TOKEN_LOGIN,
});
