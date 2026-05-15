import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock import.meta.env
vi.stubEnv('VITE_API_BASE_URL', 'http://localhost:8000');

/**
 * Minimal mock WebSocket for unit tests.
 */
let mockWsInstance: MockWebSocket | undefined;

class MockWebSocket {
	static CONNECTING = 0;
	static OPEN = 1;
	static CLOSING = 2;
	static CLOSED = 3;

	readyState = MockWebSocket.OPEN;
	onopen: ((ev: Event) => void) | null = null;
	onclose: ((ev: CloseEvent) => void) | null = null;
	onmessage: ((ev: MessageEvent) => void) | null = null;
	onerror: ((ev: Event) => void) | null = null;

	sent: string[] = [];
	closeCode?: number;

	constructor(public url: string) {
		mockWsInstance = this;
		setTimeout(() => this.onopen?.(new Event('open')), 0);
	}

	send(data: string) {
		this.sent.push(data);
	}

	close(code?: number) {
		this.closeCode = code;
		this.readyState = MockWebSocket.CLOSED;
		setTimeout(() => {
			this.onclose?.(new CloseEvent('close', { code: code ?? 1000 }));
		}, 0);
	}

	simulateMessage(data: unknown) {
		this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(data) }));
	}

	simulateClose(code = 1000) {
		this.readyState = MockWebSocket.CLOSED;
		this.onclose?.(new CloseEvent('close', { code }));
	}

	simulateError() {
		this.onerror?.(new Event('error'));
		this.readyState = MockWebSocket.CLOSED;
		this.onclose?.(new CloseEvent('close', { code: 1006 }));
	}
}

// Stub WebSocket globally before any module loads
vi.stubGlobal('WebSocket', MockWebSocket);

// Mock dependencies at top level (hoisted)
vi.mock('./auth.svelte', () => ({
	authStore: {
		getAuthHeader: vi.fn(() => 'Bearer fake-token'),
		getToken: vi.fn(() => 'fake-token'),
		getCsrfToken: vi.fn(() => 'csrf-token'),
		isAuthenticated: true,
	},
}));

vi.mock('./notifications.svelte', () => ({
	notifications: {
		warning: vi.fn(() => 'notif-id'),
		error: vi.fn(() => 'notif-id'),
		remove: vi.fn(),
	},
}));

describe('WsStore', () => {
	let wsStore: typeof import('./ws.svelte').wsStore;
	let authStoreMock: {
		getAuthHeader: ReturnType<typeof vi.fn>;
		getToken: ReturnType<typeof vi.fn>;
		getCsrfToken: ReturnType<typeof vi.fn>;
		isAuthenticated: boolean;
	};

	beforeEach(async () => {
		vi.useFakeTimers();
		mockWsInstance = undefined;

		vi.resetModules();
		// Re-import after module reset to get fresh singleton
		const authMod = await import('./auth.svelte');
		authStoreMock = authMod.authStore as unknown as typeof authStoreMock;
		authStoreMock.getAuthHeader.mockReturnValue('Bearer fake-token');
		authStoreMock.getToken.mockReturnValue('fake-token');
		authStoreMock.getCsrfToken.mockReturnValue('csrf-token');
		authStoreMock.isAuthenticated = true;

		const mod = await import('./ws.svelte');
		wsStore = mod.wsStore;
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	function connectAndAuth() {
		wsStore.connect();
		vi.advanceTimersByTime(1); // trigger onopen setTimeout
		expect(mockWsInstance).toBeDefined();
		mockWsInstance!.simulateMessage({ type: 'auth_ack', user: 'test-user' });
	}

	describe('connect', () => {
		it('creates WebSocket with correct URL', () => {
			wsStore.connect();
			expect(mockWsInstance).toBeDefined();
			expect(mockWsInstance!.url).toBe('ws://localhost:8000/ws');
		});

		it('transitions to connecting then open', () => {
			wsStore.connect();
			expect(wsStore.status).toBe('connecting');
			vi.advanceTimersByTime(1);
			expect(wsStore.status).toBe('open');
		});

		it('sends auth message on open', () => {
			wsStore.connect();
			vi.advanceTimersByTime(1);
			expect(mockWsInstance!.sent).toHaveLength(1);
			const msg = JSON.parse(mockWsInstance!.sent[0]);
			expect(msg).toEqual({ action: 'authenticate', token: 'fake-token' });
		});

		it('transitions to authenticated on auth_ack', () => {
			connectAndAuth();
			expect(wsStore.status).toBe('authenticated');
		});

		it('does not connect without auth token', () => {
			authStoreMock.getAuthHeader.mockReturnValue(null);
			authStoreMock.getToken.mockReturnValue(null);
			authStoreMock.isAuthenticated = false;
			wsStore.connect();
			expect(wsStore.status).toBe('closed');
			expect(mockWsInstance).toBeUndefined();
		});

		it('connects with cookie-backed auth when no raw JWT is available', () => {
			authStoreMock.getAuthHeader.mockReturnValue(null);
			authStoreMock.getToken.mockReturnValue(null);
			authStoreMock.isAuthenticated = true;

			wsStore.connect();
			vi.advanceTimersByTime(1);

			expect(mockWsInstance).toBeDefined();
			const msg = JSON.parse(mockWsInstance!.sent[0]);
			expect(msg).toEqual({ action: 'authenticate', token: '', csrf_token: 'csrf-token' });
		});

		it('uses cookie-backed auth for the post-Clerk session state where AuthStore discards the JWT', () => {
			authStoreMock.getAuthHeader.mockReturnValue(null);
			authStoreMock.getToken.mockReturnValue(null);
			authStoreMock.getCsrfToken.mockReturnValue('csrf-after-establish-session');
			authStoreMock.isAuthenticated = true;

			wsStore.connect();
			vi.advanceTimersByTime(1);

			const msg = JSON.parse(mockWsInstance!.sent[0]);
			expect(msg).toEqual({
				action: 'authenticate',
				token: '',
				csrf_token: 'csrf-after-establish-session',
			});
			expect(authStoreMock.getToken).toHaveBeenCalled();
		});
	});

	describe('disconnect', () => {
		it('closes WebSocket and sets status to closed', () => {
			connectAndAuth();
			wsStore.disconnect();
			expect(wsStore.status).toBe('closed');
			expect(mockWsInstance!.closeCode).toBe(1000);
		});

		it('does not trigger reconnect after intentional close', () => {
			connectAndAuth();
			wsStore.disconnect();
			vi.advanceTimersByTime(60000);
			expect(wsStore.status).toBe('closed');
		});
	});

	describe('subscribe', () => {
		it('sends subscribe message when authenticated', () => {
			connectAndAuth();
			const unsub = wsStore.subscribe('rfq', 'uuid-1');

			const subMsg = JSON.parse(mockWsInstance!.sent[mockWsInstance!.sent.length - 1]);
			expect(subMsg).toEqual({ action: 'subscribe', topic: 'rfq', id: 'uuid-1' });
			unsub();
		});

		it('buffers subscription when not yet authenticated', () => {
			wsStore.connect();
			vi.advanceTimersByTime(1); // open but not auth'd

			const sentBefore = mockWsInstance!.sent.length;
			wsStore.subscribe('rfq', 'uuid-2');

			// No new message sent (buffered)
			expect(mockWsInstance!.sent.length).toBe(sentBefore);

			// Auth ack flushes pending
			mockWsInstance!.simulateMessage({ type: 'auth_ack', user: 'test-user' });

			const flushed = mockWsInstance!.sent.slice(sentBefore).map((s) => JSON.parse(s));
			expect(flushed).toContainEqual({ action: 'subscribe', topic: 'rfq', id: 'uuid-2' });
		});

		it('unsubscribe sends message and cleans up', () => {
			connectAndAuth();
			const unsub = wsStore.subscribe('rfq', 'uuid-1');
			unsub();

			const lastMsg = JSON.parse(mockWsInstance!.sent[mockWsInstance!.sent.length - 1]);
			expect(lastMsg).toEqual({ action: 'unsubscribe', topic: 'rfq', id: 'uuid-1' });
		});
	});

	describe('event handling', () => {
		it('dispatches typed events to registered handlers', () => {
			connectAndAuth();
			const handler = vi.fn();
			const off = wsStore.on('quote_received', handler);

			mockWsInstance!.simulateMessage({
				event: 'quote_received',
				rfq_id: 'rfq-1',
				data: { quote_id: 'q1', counterparty_id: 'cp1', fixed_price_value: 100, fixed_price_unit: 'USD/MT', float_pricing_convention: 'LME', received_at: '2026-01-01' },
				timestamp: '2026-01-01T00:00:00Z',
				seq: 1,
			});

			expect(handler).toHaveBeenCalledTimes(1);
			expect(handler.mock.calls[0][0].event).toBe('quote_received');
			off();
		});

		it('does not dispatch to unregistered handlers', () => {
			connectAndAuth();
			const handler = vi.fn();
			const off = wsStore.on('quote_received', handler);
			off();

			mockWsInstance!.simulateMessage({
				event: 'quote_received',
				rfq_id: 'rfq-1',
				data: { quote_id: 'q1', counterparty_id: 'cp1', fixed_price_value: 100, fixed_price_unit: 'USD/MT', float_pricing_convention: 'LME', received_at: '2026-01-01' },
				timestamp: '2026-01-01T00:00:00Z',
				seq: 1,
			});

			expect(handler).not.toHaveBeenCalled();
		});

		it('drops domain events before auth_ack', () => {
			wsStore.connect();
			vi.advanceTimersByTime(1); // open but not authenticated

			const handler = vi.fn();
			wsStore.on('quote_received', handler);

			mockWsInstance!.simulateMessage({
				event: 'quote_received',
				rfq_id: 'rfq-1',
				data: { quote_id: 'q1', counterparty_id: 'cp1', fixed_price_value: 100, fixed_price_unit: 'USD/MT', float_pricing_convention: 'LME', received_at: '2026-01-01' },
				timestamp: '2026-01-01T00:00:00Z',
				seq: 1,
			});

			expect(handler).not.toHaveBeenCalled();

			// After auth, events should dispatch normally
			mockWsInstance!.simulateMessage({ type: 'auth_ack', user: 'test-user' });
			mockWsInstance!.simulateMessage({
				event: 'quote_received',
				rfq_id: 'rfq-1',
				data: { quote_id: 'q1', counterparty_id: 'cp1', fixed_price_value: 100, fixed_price_unit: 'USD/MT', float_pricing_convention: 'LME', received_at: '2026-01-01' },
				timestamp: '2026-01-01T00:00:00Z',
				seq: 2,
			});

			expect(handler).toHaveBeenCalledTimes(1);
		});

		it('ignores malformed JSON messages', () => {
			connectAndAuth();
			mockWsInstance!.onmessage?.(new MessageEvent('message', { data: '{not json}' }));
			expect(wsStore.status).toBe('authenticated');
		});
	});

	describe('reconnection', () => {
		it('schedules reconnect on unexpected close', () => {
			connectAndAuth();
			mockWsInstance!.simulateClose(1006);

			expect(wsStore.status).toBe('closed');
			// After 1s (base delay), should try to reconnect → connecting → open (mock auto-fires onopen)
			vi.advanceTimersByTime(1001);
			// Status should be open (mock WS fires onopen immediately via setTimeout)
			expect(wsStore.status).toBe('open');
			// New WS instance should exist
			expect(mockWsInstance).toBeDefined();
			// Auth message should have been sent again
			const lastSent = JSON.parse(mockWsInstance!.sent[mockWsInstance!.sent.length - 1]);
			expect(lastSent.action).toBe('authenticate');
		});

		it('does not reconnect after intentional disconnect', () => {
			connectAndAuth();
			wsStore.disconnect();
			vi.advanceTimersByTime(60000);
			expect(wsStore.status).toBe('closed');
		});
	});

	describe('polling fallback', () => {
		it('activates polling after degradation delay when WS stays down', () => {
			connectAndAuth();

			const pollCb = vi.fn();
			wsStore.registerPollingCallback('rfq', 'uuid-1', pollCb);
			wsStore.subscribe('rfq', 'uuid-1');

			// Simulate disconnect
			mockWsInstance!.simulateClose(1006);

			expect(wsStore.isPollingFallback).toBe(false);

			// Advance past reconnect (1s) + degradation delay (5s)
			// The reconnect will create a new WS that also fails
			vi.advanceTimersByTime(1001); // first reconnect fires
			// New WS instance created, simulate it also failing
			mockWsInstance!.simulateError();

			// Now advance past degradation delay from first disconnect
			vi.advanceTimersByTime(5000);

			expect(wsStore.isPollingFallback).toBe(true);
			expect(pollCb).toHaveBeenCalled();
		});

		it('dismisses polling notification on reconnect', async () => {
			const notifMod = await import('./notifications.svelte');
			const notifMock = notifMod.notifications as unknown as {
				warning: ReturnType<typeof vi.fn>;
				remove: ReturnType<typeof vi.fn>;
			};
			notifMock.warning.mockReturnValue('poll-notif-123');

			connectAndAuth();

			const pollCb = vi.fn();
			wsStore.registerPollingCallback('rfq', 'uuid-1', pollCb);
			wsStore.subscribe('rfq', 'uuid-1');

			// Disconnect and enter polling fallback
			mockWsInstance!.simulateClose(1006);
			vi.advanceTimersByTime(1001); // reconnect fires
			mockWsInstance!.simulateError(); // reconnect fails
			vi.advanceTimersByTime(5000); // degradation timer

			expect(wsStore.isPollingFallback).toBe(true);
			expect(notifMock.warning).toHaveBeenCalledWith(
				'Real-time indisponível — atualizando via polling.',
				0
			);

			// Now reconnect succeeds
			vi.advanceTimersByTime(2001); // next reconnect attempt
			vi.advanceTimersByTime(1); // onopen setTimeout
			mockWsInstance!.simulateMessage({ type: 'auth_ack', user: 'test-user' });

			expect(wsStore.isPollingFallback).toBe(false);
			expect(notifMock.remove).toHaveBeenCalledWith('poll-notif-123');
		});

		it('stops polling on intentional disconnect', () => {
			connectAndAuth();
			wsStore.disconnect();
			expect(wsStore.isPollingFallback).toBe(false);
		});
	});
});
