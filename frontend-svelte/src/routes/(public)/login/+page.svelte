<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { clerk, initClerk } from '$lib/clerk';
	import { authStore } from '$lib/stores/auth.svelte';

	type SessionLike = {
		getToken: () => Promise<string | null>;
	};

	let mountEl: HTMLDivElement;
	let error = $state<string | null>(null);

	$effect(() => {
		if (authStore.isAuthenticated) {
			goto('/');
		}
	});

	async function establishBackendSession(session: SessionLike | null | undefined) {
		const token = await session?.getToken();
		if (!token) return;
		try {
			await authStore.establishSession(token);
			goto('/');
		} catch {
			error = 'Não foi possível estabelecer a sessão.';
		}
	}

	onMount(() => {
		let active = true;
		let signInMounted = false;
		let unsubscribe: (() => void) | undefined;

		void (async () => {
			try {
				await initClerk();
				if (!active) return;

				clerk.mountSignIn(mountEl, {
					path: '/login',
					routing: 'path',
					forceRedirectUrl: '/',
					fallbackRedirectUrl: '/',
					signUpForceRedirectUrl: '/',
					signUpFallbackRedirectUrl: '/',
					signUpUrl: '/sign-up',
				});
				signInMounted = true;
				unsubscribe = clerk.addListener(({ session }) => {
					void establishBackendSession(session);
				});
				void establishBackendSession(clerk.session);
			} catch {
				if (active) error = 'Configuração de Clerk ausente.';
			}
		})();

		return () => {
			active = false;
			unsubscribe?.();
			if (signInMounted && mountEl) clerk.unmountSignIn(mountEl);
		};
	});
</script>

<svelte:head>
	<title>Login | Hedge Control</title>
</svelte:head>

<main class="flex min-h-screen items-center justify-center bg-surface-950 px-4 py-8">
	<section class="w-full max-w-md">
		<h1 class="mb-6 text-xl font-semibold text-surface-200">Hedge Control</h1>
		<div bind:this={mountEl}></div>
		{#if error}
			<p class="mt-4 rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger">
				{error}
			</p>
		{/if}
	</section>
</main>
