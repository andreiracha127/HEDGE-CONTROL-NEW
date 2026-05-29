const DEFAULT_API_BASE_URL = 'http://localhost:8000';

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1']);

function trimTrailingSlash(value: string): string {
	return value.endsWith('/') ? value.slice(0, -1) : value;
}

function browserHostname(browserHref?: string): string | null {
	const href = browserHref ?? globalThis.location?.href;
	if (!href) return null;
	try {
		return new URL(href).hostname;
	} catch {
		return null;
	}
}

export function resolveApiBaseUrl(
	configuredBaseUrl: string = DEFAULT_API_BASE_URL,
	browserHref?: string,
): string {
	try {
		const apiUrl = new URL(configuredBaseUrl);
		const host = browserHostname(browserHref);
		if (host && LOOPBACK_HOSTS.has(host) && LOOPBACK_HOSTS.has(apiUrl.hostname)) {
			apiUrl.hostname = host;
		}
		return trimTrailingSlash(apiUrl.toString());
	} catch {
		return trimTrailingSlash(configuredBaseUrl);
	}
}

export function resolveWebSocketUrl(
	configuredBaseUrl: string = DEFAULT_API_BASE_URL,
	browserHref?: string,
): string {
	const apiBase = resolveApiBaseUrl(configuredBaseUrl, browserHref);
	return `${apiBase.replace(/^http/i, 'ws')}/ws`;
}

export const API_BASE = resolveApiBaseUrl(import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL);
export const WS_URL = resolveWebSocketUrl(import.meta.env.VITE_API_BASE_URL ?? DEFAULT_API_BASE_URL);
