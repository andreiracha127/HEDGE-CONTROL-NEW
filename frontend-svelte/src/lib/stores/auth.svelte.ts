import { goto } from '$app/navigation';

export type UserRole = 'trader' | 'risk_manager' | 'auditor';

interface JwtClaims {
	sub: string;
	name?: string;
	roles?: UserRole[];
	exp?: number;
	iat?: number;
}

const SESSION_TOKEN_KEY = 'hedge-control.auth.token';
const SESSION_CSRF_KEY = 'hedge-control.auth.csrf';
const CSRF_COOKIE_NAME = 'csrf_token';
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';

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
	#expiryTimer: ReturnType<typeof setTimeout> | null = null;
	#expiryWarningTimer: ReturnType<typeof setTimeout> | null = null;
	#redirecting = false;

	readonly isAuthenticated = $derived(this.#token !== null);
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
			this.#applySession(token, claims, this.#csrfToken);
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

		this.#applySession(sessionToken, claims, csrf);
	}

	logout() {
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
		return this.#token ? `Bearer ${this.#token}` : null;
	}

	getCsrfToken(): string | null {
		return this.#csrfToken ?? this.#readCookie(CSRF_COOKIE_NAME);
	}

	hasRole(role: UserRole): boolean {
		return this.userRoles.includes(role);
	}

	hasAnyRole(...roles: UserRole[]): boolean {
		return roles.some((r) => this.userRoles.includes(r));
	}

	#setupExpiryTimers(claims: JwtClaims) {
		this.#clearTimers();
		if (!claims.exp) return;

		const now = Date.now();
		const expiresAt = claims.exp * 1000;
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

	#clearTimers() {
		if (this.#expiryTimer) clearTimeout(this.#expiryTimer);
		if (this.#expiryWarningTimer) clearTimeout(this.#expiryWarningTimer);
		this.#expiryTimer = null;
		this.#expiryWarningTimer = null;
	}

	#restoreSession() {
		const token = this.#getStorage()?.getItem(SESSION_TOKEN_KEY);
		if (!token) return;

		try {
			const claims = decodeJwtPayload(token);
			if (claims.exp && claims.exp * 1000 <= Date.now()) {
				this.#clearStoredToken();
				return;
			}

			this.#token = token;
			this.#claims = claims;
			this.#csrfToken =
				this.#getStorage()?.getItem(SESSION_CSRF_KEY) ?? this.#readCookie(CSRF_COOKIE_NAME);
			this.showExpiryWarning = false;
			this.#redirecting = false;
			this.#setupExpiryTimers(claims);
		} catch {
			this.#clearStoredToken();
		}
	}

	#applySession(token: string, claims: JwtClaims, csrfToken: string | null) {
		this.#token = token;
		this.#claims = claims;
		this.#csrfToken = csrfToken;
		this.showExpiryWarning = false;
		this.#redirecting = false;
		this.#persistToken(token);
		this.#setupExpiryTimers(claims);
	}

	#persistToken(token: string) {
		this.#getStorage()?.setItem(SESSION_TOKEN_KEY, token);
		if (this.#csrfToken) this.#getStorage()?.setItem(SESSION_CSRF_KEY, this.#csrfToken);
	}

	#clearStoredToken() {
		this.#getStorage()?.removeItem(SESSION_TOKEN_KEY);
		this.#getStorage()?.removeItem(SESSION_CSRF_KEY);
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

export const authStore = new AuthStore();
