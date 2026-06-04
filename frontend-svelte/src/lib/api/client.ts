import createClient from 'openapi-fetch';
import type { paths } from './schema';
import { authStore } from '$lib/stores/auth.svelte';
import { API_BASE } from './base';

const MUTATING_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE']);

export const client = createClient<paths>({
	baseUrl: API_BASE,
	fetch: (request: Request) => fetch(request, { credentials: 'include' }),
});

client.use({
	async onRequest({ request }) {
		const csrf = authStore.getCsrfToken();
		if (MUTATING_METHODS.has(request.method.toUpperCase()) && csrf) {
			request.headers.set('X-CSRF-Token', csrf);
		}
		return request;
	},
	async onResponse({ response }) {
		if (response.status === 401) {
			authStore.logout();
		}
		return response;
	},
});
