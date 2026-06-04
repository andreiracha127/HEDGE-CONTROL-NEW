const HTML_ESCAPE_MAP: Record<string, string> = {
	'&': '&amp;',
	'<': '&lt;',
	'>': '&gt;',
	'"': '&quot;',
	"'": '&#39;',
};

const HTML_ESCAPE_RE = /[&<>"']/g;

/**
 * Escape HTML special characters to prevent XSS in contexts that render HTML
 * (e.g. ECharts tooltip formatters which use innerHTML by default).
 */
export function escapeHtml(str: string): string {
	return str.replace(HTML_ESCAPE_RE, (ch) => HTML_ESCAPE_MAP[ch]);
}
