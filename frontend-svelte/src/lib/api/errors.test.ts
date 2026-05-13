import { describe, it, expect } from 'vitest';
import { describeApiError } from './errors';

function makeResponse(status: number, body: unknown): Response {
	return new Response(typeof body === 'string' ? body : JSON.stringify(body), {
		status,
		headers: { 'Content-Type': 'application/json' },
	});
}

describe('describeApiError', () => {
	it('extracts a plain-string `detail`', async () => {
		const res = makeResponse(409, { detail: 'Transição não permitida' });
		expect(await describeApiError(res)).toBe('Transição não permitida');
	});

	it('extracts `error` when `detail` absent', async () => {
		const res = makeResponse(500, { error: 'internal_server_error' });
		expect(await describeApiError(res)).toBe('internal_server_error');
	});

	it('extracts `message` when other fields absent', async () => {
		const res = makeResponse(400, { message: 'bad payload' });
		expect(await describeApiError(res)).toBe('bad payload');
	});

	it('summarises a FastAPI-style validation array on `detail`', async () => {
		const res = makeResponse(422, {
			detail: [
				{ loc: ['query', 'as_of_date'], msg: 'field required', type: 'missing' },
				{ loc: ['query', 'object_id'], msg: 'value is not a valid uuid', type: 'value_error' },
			],
		});
		const out = await describeApiError(res);
		expect(out).toContain('query.as_of_date: field required');
		expect(out).toContain('query.object_id: value is not a valid uuid');
		expect(out).toContain(';');
	});

	it('falls back to HTTP status when body has no structured fields', async () => {
		const res = makeResponse(503, '<html>service down</html>');
		expect(await describeApiError(res)).toBe('HTTP 503');
	});

	it('falls back to HTTP status when body is not JSON', async () => {
		const res = new Response('not json', {
			status: 500,
			headers: { 'Content-Type': 'text/plain' },
		});
		expect(await describeApiError(res)).toBe('HTTP 500');
	});

	it('skips empty / whitespace string fields', async () => {
		const res = makeResponse(400, { detail: '   ', error: '', message: 'fallback msg' });
		expect(await describeApiError(res)).toBe('fallback msg');
	});

	it('serialises an object-shaped detail when no string available', async () => {
		const res = makeResponse(400, { detail: { code: 'X', hint: 'try again' } });
		const out = await describeApiError(res);
		expect(out).toContain('code');
		expect(out).toContain('hint');
	});
});
