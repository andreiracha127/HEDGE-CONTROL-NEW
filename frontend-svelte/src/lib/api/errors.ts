/**
 * Extract a hard-fail-friendly error message from a non-2xx Response.
 *
 * Order: `detail`, `error`, `message`. Strings are returned as-is. Arrays or
 * objects are JSON-serialised as a concise validation summary. If no
 * structured body is available the HTTP status code is reported so the
 * operator always sees a non-empty failure surface.
 */
export async function describeApiError(res: Response): Promise<string> {
	let body: unknown = null;
	try {
		body = await res.clone().json();
	} catch {
		body = null;
	}

	if (body && typeof body === 'object') {
		for (const field of ['detail', 'error', 'message'] as const) {
			const value = (body as Record<string, unknown>)[field];
			const formatted = formatField(value);
			if (formatted) return formatted;
		}
	}

	return `HTTP ${res.status}`;
}

function formatField(value: unknown): string | null {
	if (value == null) return null;
	if (typeof value === 'string') {
		const trimmed = value.trim();
		return trimmed ? trimmed : null;
	}
	if (Array.isArray(value)) {
		if (value.length === 0) return null;
		return summariseValidationArray(value);
	}
	if (typeof value === 'object') {
		try {
			const json = JSON.stringify(value);
			return json && json !== '{}' ? json : null;
		} catch {
			return null;
		}
	}
	return String(value);
}

function summariseValidationArray(items: unknown[]): string {
	const parts: string[] = [];
	for (const item of items) {
		if (typeof item === 'string' && item.trim()) {
			parts.push(item.trim());
			continue;
		}
		if (item && typeof item === 'object') {
			const obj = item as Record<string, unknown>;
			const loc = Array.isArray(obj.loc) ? obj.loc.join('.') : undefined;
			const msg = typeof obj.msg === 'string' ? obj.msg : undefined;
			if (loc && msg) parts.push(`${loc}: ${msg}`);
			else if (msg) parts.push(msg);
			else {
				try {
					parts.push(JSON.stringify(item));
				} catch {
					/* skip */
				}
			}
		}
	}
	return parts.length > 0 ? parts.join('; ') : JSON.stringify(items);
}
