import { describe, expect, it } from 'vitest';
import { resolveApiBaseUrl, resolveWebSocketUrl } from './base';

describe('API base URL resolution', () => {
	it('keeps loopback API cookies first-party by matching the browser host', () => {
		expect(resolveApiBaseUrl('http://localhost:8000', 'http://127.0.0.1:5173/')).toBe(
			'http://127.0.0.1:8000',
		);
		expect(resolveApiBaseUrl('http://127.0.0.1:8000', 'http://localhost:5173/')).toBe(
			'http://localhost:8000',
		);
	});

	it('does not rewrite non-loopback API hosts', () => {
		expect(resolveApiBaseUrl('https://api.example.com', 'http://127.0.0.1:5173/')).toBe(
			'https://api.example.com',
		);
	});

	it('derives the websocket URL from the normalized API base', () => {
		expect(resolveWebSocketUrl('http://localhost:8000', 'http://127.0.0.1:5173/')).toBe(
			'ws://127.0.0.1:8000/ws',
		);
	});
});
