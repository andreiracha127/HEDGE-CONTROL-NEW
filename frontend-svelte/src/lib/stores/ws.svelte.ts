import { authStore } from './auth.svelte';
import { notifications } from './notifications.svelte';
import {
	isWsEvent,
	isControlMessage,
	type WsEvent,
	type WsEventType,
	type WsEventMap,
} from '$lib/api/types/ws-events';

export type WsStatus = 'closed' | 'connecting' | 'open' | 'authenticated' | 'error';

type EventHandler<T extends WsEventType = WsEventType> = (event: WsEventMap[T]) => void;

const RECONNECT_BASE_MS = 1000;
const RECONNECT_CAP_MS = 30000;
const MAX_RECONNECT_ATTEMPTS = 10;
const DEGRADATION_DELAY_MS = 5000;
const POLL_INTERVAL_MS = 5000;

class WsStore {
	status = $state<WsStatus>('closed');
	isPollingFallback = $state(false);

	#ws: WebSocket | null = null;
	#handlers = new Map<WsEventType, Set<EventHandler>>();
	#subscriptions = new Map<string, { topic: string; id: string }>();
	#pendingSubscriptions: Array<{ topic: string; id: string }> = [];
	#reconnectAttempts = 0;
	#reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	#degradationTimer: ReturnType<typeof setTimeout> | null = null;
	#pollingTimers = new Map<string, ReturnType<typeof setInterval>>();
	#pollingCallbacks = new Map<string, () => void>();
	#pollingNotificationId: string | null = null;
	#intentionalClose = false;

	connect() {
		if (this.#ws && this.status !== 'closed' && this.status !== 'error') return;

		const token = authStore.getToken();
		if (!token && !authStore.isAuthenticated) return;

		this.#intentionalClose = false;
		this.status = 'connecting';

		const baseUrl = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000';
		const wsUrl = baseUrl.replace(/^http/, 'ws') + '/ws';

		try {
			this.#ws = new WebSocket(wsUrl);
		} catch {
			this.status = 'error';
			this.#scheduleReconnect();
			return;
		}

		this.#ws.onopen = () => {
			this.status = 'open';
			this.#reconnectAttempts = 0;
			// First-message auth
			const rawToken = authStore.getToken() ?? '';
			const csrfToken = rawToken ? null : authStore.getCsrfToken();
			this.#send({
				action: 'authenticate',
				token: rawToken,
				...(csrfToken ? { csrf_token: csrfToken } : {}),
			});
		};

		this.#ws.onmessage = (event) => {
			this.#handleMessage(event.data);
		};

		this.#ws.onclose = (event) => {
			this.#ws = null;
			if (this.#intentionalClose) {
				this.status = 'closed';
				return;
			}
			this.status = 'closed';
			this.#onDisconnect();
			this.#scheduleReconnect();
		};

		this.#ws.onerror = () => {
			// onclose will fire after onerror
			this.status = 'error';
		};
	}

	disconnect() {
		this.#intentionalClose = true;
		this.#clearReconnect();
		this.#clearDegradation();
		this.#stopPollingFallback();
		if (this.#ws) {
			this.#ws.close(1000);
			this.#ws = null;
		}
		this.status = 'closed';
	}

	subscribe(topic: string, id: string): () => void {
		const key = `${topic}:${id}`;
		this.#subscriptions.set(key, { topic, id });

		if (this.status === 'authenticated') {
			this.#send({ action: 'subscribe', topic, id });
		} else {
			this.#pendingSubscriptions.push({ topic, id });
		}

		return () => {
			this.#subscriptions.delete(key);
			if (this.status === 'authenticated') {
				this.#send({ action: 'unsubscribe', topic, id });
			}
			// Stop polling for this subscription if active
			this.#stopPollingForKey(key);
		};
	}

	on<T extends WsEventType>(eventType: T, handler: (event: WsEventMap[T]) => void): () => void {
		if (!this.#handlers.has(eventType)) {
			this.#handlers.set(eventType, new Set());
		}
		const handlers = this.#handlers.get(eventType)!;
		handlers.add(handler as EventHandler);

		return () => {
			handlers.delete(handler as EventHandler);
			if (handlers.size === 0) this.#handlers.delete(eventType);
		};
	}

	/**
	 * Register a polling callback for a subscription key.
	 * Called during polling fallback mode at POLL_INTERVAL_MS.
	 */
	registerPollingCallback(topic: string, id: string, callback: () => void) {
		const key = `${topic}:${id}`;
		this.#pollingCallbacks.set(key, callback);
	}

	unregisterPollingCallback(topic: string, id: string) {
		const key = `${topic}:${id}`;
		this.#pollingCallbacks.delete(key);
	}

	// ─── Private ──────────────────────────────────────────────────────────

	#send(data: Record<string, unknown>) {
		if (this.#ws?.readyState === WebSocket.OPEN) {
			this.#ws.send(JSON.stringify(data));
		}
	}

	#handleMessage(raw: string) {
		let parsed: unknown;
		try {
			parsed = JSON.parse(raw);
		} catch {
			return;
		}

		// Control messages (auth_ack, subscription_ack, etc.)
		if (isControlMessage(parsed)) {
			if (parsed.type === 'auth_ack') {
				this.status = 'authenticated';
				this.#flushPendingSubscriptions();
				this.#onReconnect();
			} else if (parsed.type === 'subscription_error') {
				notifications.warning(`WS subscription error: ${parsed.reason}`);
			}
			return;
		}

		// Domain events — only dispatch after auth handshake is complete
		if (isWsEvent(parsed)) {
			if (this.status !== 'authenticated') return;
			const handlers = this.#handlers.get(parsed.event as WsEventType);
			if (handlers) {
				for (const handler of handlers) {
					try {
						handler(parsed as never);
					} catch (e) {
						console.error('WS event handler error:', e);
					}
				}
			}
		}
	}

	#flushPendingSubscriptions() {
		// Re-subscribe all active subscriptions (for reconnect)
		for (const { topic, id } of this.#subscriptions.values()) {
			this.#send({ action: 'subscribe', topic, id });
		}
		// Flush buffered subscriptions
		for (const sub of this.#pendingSubscriptions) {
			this.#send({ action: 'subscribe', topic: sub.topic, id: sub.id });
		}
		this.#pendingSubscriptions = [];
	}

	#scheduleReconnect() {
		if (this.#intentionalClose) return;
		if (this.#reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
			notifications.error('Conexão WebSocket perdida. Clique para reconectar.', 0);
			return;
		}
		const delay = Math.min(
			RECONNECT_BASE_MS * Math.pow(2, this.#reconnectAttempts),
			RECONNECT_CAP_MS
		);
		this.#reconnectAttempts++;
		this.#reconnectTimer = setTimeout(() => this.connect(), delay);
	}

	#clearReconnect() {
		if (this.#reconnectTimer) {
			clearTimeout(this.#reconnectTimer);
			this.#reconnectTimer = null;
		}
		this.#reconnectAttempts = 0;
	}

	// ─── Graceful Degradation: Polling Fallback ──────────────────────────

	#onDisconnect() {
		this.#clearDegradation();
		this.#degradationTimer = setTimeout(() => {
			this.#startPollingFallback();
		}, DEGRADATION_DELAY_MS);
	}

	#onReconnect() {
		this.#clearDegradation();
		this.#stopPollingFallback();
		if (this.#pollingNotificationId) {
			notifications.remove(this.#pollingNotificationId);
			this.#pollingNotificationId = null;
		}
	}

	#clearDegradation() {
		if (this.#degradationTimer) {
			clearTimeout(this.#degradationTimer);
			this.#degradationTimer = null;
		}
	}

	#startPollingFallback() {
		if (this.isPollingFallback) return;
		this.isPollingFallback = true;
		this.#pollingNotificationId = notifications.warning('Real-time indisponível — atualizando via polling.', 0);

		for (const [key, { topic, id }] of this.#subscriptions) {
			const callback = this.#pollingCallbacks.get(key);
			if (callback) {
				// Initial immediate poll
				callback();
				// Then interval
				this.#pollingTimers.set(key, setInterval(callback, POLL_INTERVAL_MS));
			}
		}
	}

	#stopPollingFallback() {
		if (!this.isPollingFallback) return;
		this.isPollingFallback = false;
		for (const timer of this.#pollingTimers.values()) {
			clearInterval(timer);
		}
		this.#pollingTimers.clear();
	}

	#stopPollingForKey(key: string) {
		const timer = this.#pollingTimers.get(key);
		if (timer) {
			clearInterval(timer);
			this.#pollingTimers.delete(key);
		}
	}
}

export const wsStore = new WsStore();
