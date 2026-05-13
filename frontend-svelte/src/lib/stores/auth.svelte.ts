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

function decodeJwtPayload(token: string): JwtClaims {
	const parts = token.split('.');
	if (parts.length !== 3) throw new Error('Invalid JWT format');
	const payload = atob(parts[1].replace(/-/g, '+').replace(/_/g, '/'));
	return JSON.parse(payload);
}

class AuthStore {
	#token = $state<string | null>(null);
	#claims = $state<JwtClaims | null>(null);
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
			this.#token = token;
			this.#claims = claims;
			this.showExpiryWarning = false;
			this.#redirecting = false;
			this.#persistToken(token);
			this.#setupExpiryTimers(claims);
		} catch {
			this.logout();
			throw new Error('Invalid token');
		}
	}

	logout() {
		this.#clearTimers();
		this.#clearStoredToken();
		this.#token = null;
		this.#claims = null;
		this.showExpiryWarning = false;

		if (!this.#redirecting) {
			this.#redirecting = true;
			goto('/login');
		}
	}

	getAuthHeader(): string | null {
		return this.#token ? `Bearer ${this.#token}` : null;
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
			this.showExpiryWarning = false;
			this.#redirecting = false;
			this.#setupExpiryTimers(claims);
		} catch {
			this.#clearStoredToken();
		}
	}

	#persistToken(token: string) {
		this.#getStorage()?.setItem(SESSION_TOKEN_KEY, token);
	}

	#clearStoredToken() {
		this.#getStorage()?.removeItem(SESSION_TOKEN_KEY);
	}

	#getStorage(): Storage | null {
		if (typeof sessionStorage === 'undefined') return null;
		return sessionStorage;
	}
}

export const authStore = new AuthStore();
