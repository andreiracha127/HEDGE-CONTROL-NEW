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
		let signUpMounted = false;
		let unsubscribe: (() => void) | undefined;

		void (async () => {
			try {
				await initClerk();
				if (!active) return;

				clerk.mountSignUp(mountEl, {
					path: '/sign-up',
					routing: 'path',
					forceRedirectUrl: '/',
					fallbackRedirectUrl: '/',
					signInForceRedirectUrl: '/',
					signInFallbackRedirectUrl: '/',
					signInUrl: '/login',
				});
				signUpMounted = true;
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
			if (signUpMounted && mountEl) clerk.unmountSignUp(mountEl);
		};
	});
</script>

<svelte:head>
	<title>Sign up | Hedge Control</title>
</svelte:head>

<main class="auth-screen">
	<section class="auth-panel">
		<div class="auth-brand">
			<div class="auth-mark">HC</div>
			<div>
				<h1>Hedge Control</h1>
				<p>Institutional hedge operations terminal</p>
			</div>
		</div>
		<div class="auth-strip">
			<span>Tenant onboarding</span>
			<span>Role-bound access</span>
			<span>Audit-ready</span>
		</div>
		<div class="auth-card">
			<div bind:this={mountEl}></div>
			{#if error}
				<p class="auth-error">
					{error}
				</p>
			{/if}
		</div>
	</section>
</main>
