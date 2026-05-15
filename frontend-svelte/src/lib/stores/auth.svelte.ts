import { goto } from '$app/navigation';

export type UserRole = 'trader' | 'risk_manager' | 'auditor';

interface JwtClaims {
	sub: string;
	name?: string;
	roles?: UserRole[];
	exp?: number;
	iat?: number;
}

const SESSION_CSRF_KEY = 'hedge-control.auth.csrf';
const CSRF_COOKIE_NAME = 'csrf_token';
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
const SESSION_COOKIE_MAX_AGE_MS = 300 * 1000;
const SESSION_COOKIE_REFRESH_LEAD_MS = 60 * 1000;

function decodeJwtPayload(token: string): JwtClaims {
	const parts = token.split('.');
	if (parts.length !== 3) throw new Error('Invalid JWT format');
	const payload = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'));
	return JSON.parse(payload);
}

class AuthStore {
	#token = $state<string | null>(null);
	#claims = $state<JwtClaims | null>(null);
	#csrfToken = $state<string | null>(null);
	#clerkSessionProvider: (() => Promise<string | null>) | null = null;
	#expiryTimer: ReturnType<typeof setTimeout> | null = null;
	#expiryWarningTimer: ReturnType<typeof setTimeout> | null = null;
	#refreshTimer: ReturnType<typeof setTimeout> | null = null;
	#redirecting = false;
	#isRestoring = $state(false);
	#generation = 0;

	readonly isAuthenticated = $derived(this.#claims !== null);
	readonly isRestoring = $derived(this.#isRestoring);
	readonly userRoles = $derived<UserRole[]>(this.#claims?.roles ?? []);
	readonly userName = $derived(this.#claims?.name ?? this.#claims?.sub ?? '');
	// J-A6-04: immutable subject accessor for evidence fields. Never falls back
	// to display name or any other mutable claim. Returns null when no sub is
	// present so callers MUST block the mutation rather than fabricate identity.
	readonly userSub = $derived<string | null>(
		typeof this.#claims?.sub === 'string' && this.#claims.sub.length > 0
			? this.#claims.sub
			: null,
	);
	readonly expiresAt = $derived(this.#claims?.exp ? this.#claims.exp * 1000 : null);

	/** Session expiry warning flag — true when <5min remain */
	showExpiryWarning = $state(false);

	constructor() {
		this.#restoreSession();
	}

	login(token: string) {
		try {
			const claims = decodeJwtPayload(token);
			this.#applySession(null, claims, this.#csrfToken);
		} catch {
			this.logout();
			throw new Error('Invalid token');
		}
	}

	async establishSession(sessionToken: string) {
		let claims: JwtClaims;
		try {
			claims = decodeJwtPayload(sessionToken);
		} catch {
			this.logout();
			throw new Error('Invalid token');
		}

		const response = await fetch(`${API_BASE}/auth/session`, {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({ session_token: sessionToken }),
		});
		if (!response.ok) {
			this.logout();
			throw new Error('Invalid token');
		}
		const body = (await response.json()) as { csrf_token?: unknown };
		const csrf =
			typeof body.csrf_token === 'string' && body.csrf_token.length > 0
				? body.csrf_token
				: this.#readCookie(CSRF_COOKIE_NAME);
		if (!csrf) {
			this.logout();
			throw new Error('Invalid token');
		}

		this.#applySession(null, claims, csrf);
	}

	logout() {
		this.#generation++;
		const csrfToken = this.getCsrfToken();
		if (csrfToken) void this.#clearBackendSession(csrfToken);
		this.#clearTimers();
		this.#clearStoredToken();
		this.#token = null;
		this.#claims = null;
		this.#csrfToken = null;
		this.showExpiryWarning = false;

		if (!this.#redirecting) {
			this.#redirecting = true;
			goto('/login');
		}
	}

	getAuthHeader(): string | null {
		return null;
	}

	getToken(): string | null {
		return this.#token;
	}

	getCsrfToken(): string | null {
		return this.#readCookie(CSRF_COOKIE_NAME) ?? this.#csrfToken;
	}

	hasRole(role: UserRole): boolean {
		return this.userRoles.includes(role);
	}

	hasAnyRole(...roles: UserRole[]): boolean {
		return roles.some((r) => this.userRoles.includes(r));
	}

	// Frontend-only role discriminator for UX guards; backend route gates remain authoritative.
	isTraderOnly(): boolean {
		return this.userRoles.length === 1 && this.userRoles[0] === 'trader';
	}

	setClerkSessionProvider(provider: (() => Promise<string | null>) | null) {
		this.#clerkSessionProvider = provider;
		if (provider && this.#claims && this.getCsrfToken() && typeof fetch !== 'undefined') {
			void this.#refreshBackendSession();
		}
	}

	#setupExpiryTimers(claims: JwtClaims) {
		this.#clearTimers();
		if (!claims.exp) return;

		const now = Date.now();
		const expiresAt = Math.floor(claims.exp * 1000);
		const msUntilExpiry = expiresAt - now;

		if (msUntilExpiry <= 0) {
			this.logout();
			return;
		}

		// Warning 5 min before expiry
		const msUntilWarning = msUntilExpiry - 5 * 60 * 1000;
		if (msUntilWarning > 0) {
			this.#expiryWarningTimer = setTimeout(() => {
				this.showExpiryWarning = true;
			}, msUntilWarning);
		} else {
			this.showExpiryWarning = true;
		}

		// Auto-logout on expiry
		this.#expiryTimer = setTimeout(() => {
			this.logout();
		}, msUntilExpiry);
	}

	#setupSessionRefresh(claims: JwtClaims, csrfToken: string | null) {
		if (!csrfToken || typeof fetch === 'undefined') return;
		const refreshDelay = SESSION_COOKIE_MAX_AGE_MS - SESSION_COOKIE_REFRESH_LEAD_MS;
		if (claims.exp && Math.floor(claims.exp * 1000) - Date.now() <= refreshDelay) return;

		this.#refreshTimer = setTimeout(() => {
			void this.#refreshBackendSession();
		}, refreshDelay);
	}

	#clearTimers() {
		if (this.#expiryTimer) clearTimeout(this.#expiryTimer);
		if (this.#expiryWarningTimer) clearTimeout(this.#expiryWarningTimer);
		if (this.#refreshTimer) clearTimeout(this.#refreshTimer);
		this.#expiryTimer = null;
		this.#expiryWarningTimer = null;
		this.#refreshTimer = null;
	}

	#restoreSession() {
		this.#csrfToken =
			this.#getStorage()?.getItem(SESSION_CSRF_KEY) ?? this.#readCookie(CSRF_COOKIE_NAME);
		if (!this.#csrfToken) return;
		this.#isRestoring = true;
		void this.#restoreBackendIdentity();
	}

	#applySession(token: string | null, claims: JwtClaims, csrfToken: string | null) {
		this.#generation++;
		this.#token = token;
		this.#claims = claims;
		this.#csrfToken = csrfToken;
		this.showExpiryWarning = false;
		this.#redirecting = false;
		this.#persistSessionState();
		this.#setupExpiryTimers(claims);
		this.#setupSessionRefresh(claims, csrfToken);
	}

	#persistSessionState() {
		if (this.#csrfToken) this.#getStorage()?.setItem(SESSION_CSRF_KEY, this.#csrfToken);
	}

	#clearStoredToken() {
		this.#getStorage()?.removeItem('hedge-control.auth.token');
		this.#getStorage()?.removeItem(SESSION_CSRF_KEY);
	}

	async #clearBackendSession(csrfToken: string) {
		if (typeof fetch === 'undefined') return;
		try {
			await fetch(`${API_BASE}/auth/logout`, {
				method: 'POST',
				credentials: 'include',
				keepalive: true,
				headers: { 'X-CSRF-Token': csrfToken },
			});
		} catch {
			// Local logout must still clear client state if the network is unavailable.
		}
	}

	async #restoreBackendIdentity() {
		if (typeof fetch === 'undefined') {
			this.#isRestoring = false;
			return;
		}
		const csrf = this.getCsrfToken();
		if (!csrf) {
			this.#clearStoredToken();
			this.#isRestoring = false;
			return;
		}
		try {
			const response = await fetch(`${API_BASE}/auth/me`, {
				credentials: 'include',
			});
			if (!response.ok) {
				this.#clearStoredToken();
				this.#isRestoring = false;
				return;
			}

			const body = (await response.json()) as { actor_sub?: unknown; roles?: unknown };
			if (typeof body.actor_sub !== 'string' || body.actor_sub.length === 0) {
				this.#clearStoredToken();
				this.#isRestoring = false;
				return;
			}

			// Backend auth validates roles first; this is defense-in-depth for malformed responses.
			const roles = Array.isArray(body.roles)
				? body.roles.filter((role): role is UserRole =>
						['trader', 'risk_manager', 'auditor'].includes(String(role)),
					)
				: [];
			this.#applySession(null, { sub: body.actor_sub, roles }, csrf);
			await this.#refreshBackendSession();
		} catch {
			this.#clearStoredToken();
		} finally {
			this.#isRestoring = false;
		}
	}

	async #refreshBackendSession() {
		if (typeof fetch === 'undefined' || !this.#claims) return;
		const generation = this.#generation;
		const token = (await this.#clerkSessionProvider?.()) ?? this.#token;
		const csrfToken = this.getCsrfToken();
		if (!csrfToken) {
			this.logout();
			return;
		}

		try {
			const response = await fetch(`${API_BASE}/auth/refresh`, {
				method: 'POST',
				credentials: 'include',
				headers: {
					'Content-Type': 'application/json',
					'X-CSRF-Token': csrfToken,
				},
				body: JSON.stringify(token ? { session_token: token } : {}),
			});
			if (this.#generation !== generation) return;
			if (!response.ok) {
				this.logout();
				return;
			}

			const body = (await response.json()) as { csrf_token?: unknown };
			const nextCsrf =
				typeof body.csrf_token === 'string' && body.csrf_token.length > 0
					? body.csrf_token
					: this.#readCookie(CSRF_COOKIE_NAME);
			if (!nextCsrf) {
				this.logout();
				return;
			}

			this.#applySession(null, token ? decodeJwtPayload(token) : this.#claims, nextCsrf);
		} catch {
			this.logout();
		}
	}

	#getStorage(): Storage | null {
		if (typeof sessionStorage === 'undefined') return null;
		return sessionStorage;
	}

	#readCookie(name: string): string | null {
		if (typeof document === 'undefined') return null;
		const prefix = `${name}=`;
		const cookie = document.cookie
			.split(';')
			.map((part) => part.trim())
			.find((part) => part.startsWith(prefix));
		return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : null;
	}
}

// Imported as `$lib/stores/auth.svelte`; SvelteKit resolves this runes module from auth.svelte.ts.
export const authStore = new AuthStore();
