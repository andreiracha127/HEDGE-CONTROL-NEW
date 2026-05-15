import type { Clerk as ClerkInstance } from '@clerk/clerk-js';
import { authStore } from '$lib/stores/auth.svelte';

declare global {
	interface Window {
		Clerk?: ClerkInstance;
		__clerk_publishable_key?: string;
		__internal_ClerkUICtor?: NonNullable<ClerkLoadOptions['ui']>['ClerkUI'];
	}
}

type ClerkLoadOptions = NonNullable<Parameters<ClerkInstance['load']>[0]>;

// TODO(post-cluster-3): swap from the dev publishable key to pk_live_... for the custom domain.
const PUBLISHABLE_KEY = import.meta.env.VITE_CLERK_PUBLISHABLE_KEY;

export let clerk = undefined as unknown as ClerkInstance;

let loadPromise: Promise<void> | null = null;
let uiLoadPromise: Promise<void> | null = null;
let sdkLoadPromise: Promise<ClerkInstance> | null = null;

function requirePublishableKey(): string {
	if (!PUBLISHABLE_KEY) {
		throw new Error('VITE_CLERK_PUBLISHABLE_KEY missing; auth disabled');
	}
	return PUBLISHABLE_KEY;
}

function clerkFrontendApiFromPublishableKey(publishableKey: string): string {
	const encodedDomain = publishableKey.split('_')[2];
	if (!encodedDomain) {
		throw new Error('VITE_CLERK_PUBLISHABLE_KEY is not a valid Clerk publishable key');
	}

	const domain = atob(encodedDomain).slice(0, -1);
	if (!domain) {
		throw new Error('VITE_CLERK_PUBLISHABLE_KEY does not contain a Clerk Frontend API domain');
	}
	return domain;
}

function loadClerkUi(): Promise<void> {
	if (typeof window === 'undefined' || typeof document === 'undefined') return Promise.resolve();
	if (window.__internal_ClerkUICtor) return Promise.resolve();

	uiLoadPromise ??= new Promise((resolve, reject) => {
		const existingScript = document.getElementById('clerk-ui-bundle') as HTMLScriptElement | null;
		const script = existingScript ?? document.createElement('script');
		const publishableKey = requirePublishableKey();

		script.id = 'clerk-ui-bundle';
		script.src = `https://${clerkFrontendApiFromPublishableKey(publishableKey)}/npm/@clerk/ui@1/dist/ui.browser.js`;
		script.async = true;
		script.crossOrigin = 'anonymous';
		script.onload = () => {
			if (window.__internal_ClerkUICtor) {
				resolve();
				return;
			}
			reject(new Error('Clerk UI bundle loaded without exposing __internal_ClerkUICtor'));
		};
		script.onerror = () => reject(new Error('Failed to load @clerk/ui bundle'));

		if (!existingScript) document.head.appendChild(script);
	});

	return uiLoadPromise;
}

function loadClerkJs(): Promise<ClerkInstance> {
	if (typeof window === 'undefined' || typeof document === 'undefined') {
		return Promise.reject(new Error('ClerkJS can only be loaded in a browser'));
	}
	if (window.Clerk) return Promise.resolve(window.Clerk);

	sdkLoadPromise ??= new Promise((resolve, reject) => {
		const existingScript = document.getElementById('clerk-js-bundle') as HTMLScriptElement | null;
		const script = existingScript ?? document.createElement('script');
		const publishableKey = requirePublishableKey();

		window.__clerk_publishable_key = publishableKey;
		script.id = 'clerk-js-bundle';
		script.src = `https://${clerkFrontendApiFromPublishableKey(publishableKey)}/npm/@clerk/clerk-js@6/dist/clerk.browser.js`;
		script.async = true;
		script.crossOrigin = 'anonymous';
		script.setAttribute('data-clerk-publishable-key', publishableKey);
		script.onload = () => {
			if (window.Clerk) {
				resolve(window.Clerk);
				return;
			}
			reject(new Error('ClerkJS bundle loaded without exposing window.Clerk'));
		};
		script.onerror = () => reject(new Error('Failed to load @clerk/clerk-js bundle'));

		if (!existingScript) document.head.appendChild(script);
	});

	return sdkLoadPromise;
}

export async function initClerk(): Promise<void> {
	loadPromise ??= (async () => {
		await loadClerkUi();
		clerk = await loadClerkJs();
		await clerk.load({
			signInUrl: '/login',
			signUpUrl: '/sign-up',
			ui: { ClerkUI: window.__internal_ClerkUICtor },
		});
	})();
	await loadPromise;
	authStore.setClerkSessionProvider(async () => {
		return (await clerk.session?.getToken({ skipCache: true })) ?? null;
	});
}
