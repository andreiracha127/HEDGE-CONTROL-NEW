<script lang="ts">
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { runtimeFlags } from '$lib/config/runtime';

	let token = $state('');
	let loading = $state(false);

	// J-A6-10: the manual JWT paste flow is a developer convenience.
	// `runtimeFlags.manualTokenLoginEnabled` is true only when the build
	// runs in dev/test mode OR when the operator has opted in via the
	// explicit `VITE_ALLOW_MANUAL_TOKEN_LOGIN=1` build flag. In a
	// production build without that opt-in, the page renders a
	// hard-fail configuration message and refuses to accept tokens —
	// no silent dev-only flow.
	const manualLoginEnabled = runtimeFlags.manualTokenLoginEnabled;

	$effect(() => {
		if (authStore.isAuthenticated) {
			goto('/');
		}
	});

	async function handleLogin(e: SubmitEvent) {
		e.preventDefault();
		if (!manualLoginEnabled) {
			notifications.error(
				'Login manual desabilitado nesta build. Configure um provedor de identidade.',
			);
			return;
		}
		loading = true;
		try {
			await authStore.establishSession(token.trim());
			goto('/');
		} catch {
			notifications.error('Token inválido. Verifique e tente novamente.');
		} finally {
			loading = false;
		}
	}
</script>

<div class="flex h-screen items-center justify-center bg-surface-950">
	<div class="w-full max-w-md rounded-lg border border-surface-800 bg-surface-900 p-8">
		<h1 class="text-xl font-semibold text-surface-200">Hedge Control</h1>

		{#if !manualLoginEnabled}
			<!--
				J-A6-10 hard-fail surface. Mode is `production` (or any
				non-dev/non-test mode) and the operator has not opted in
				via VITE_ALLOW_MANUAL_TOKEN_LOGIN=1. The page does not
				render the paste form so the dev-only flow cannot be
				normalised as production login.
			-->
			<div
				class="mt-4 rounded border border-danger/40 bg-danger/10 px-3 py-3 text-sm text-danger"
				data-testid="login-config-error"
			>
				<p class="font-semibold">Configuração de login ausente</p>
				<p class="mt-1 text-xs text-danger/80">
					Esta build está em modo <code data-testid="login-config-mode">{runtimeFlags.mode}</code> e
					não tem um provedor de identidade configurado. O login manual por token foi gated
					(J-A6-10) e não está disponível.
				</p>
				<p class="mt-2 text-xs text-surface-500">
					Para habilitar autenticação manual em ambientes não-dev (uso emergencial), faça o
					build com <code>VITE_ALLOW_MANUAL_TOKEN_LOGIN=1</code>.
				</p>
			</div>
		{:else}
			<p class="mt-1 text-sm text-surface-500">Cole seu token JWT para acessar a plataforma.</p>

			<form onsubmit={handleLogin} class="mt-6 space-y-4" data-testid="login-manual-form">
				<div>
					<label for="token" class="block text-sm font-medium text-surface-400">JWT Token</label>
					<textarea
						id="token"
						bind:value={token}
						rows={4}
						class="mt-1 w-full rounded-md border border-surface-700 bg-surface-800 px-3 py-2 text-sm text-surface-200 placeholder-surface-600 focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent font-mono"
						placeholder="eyJhbGciOiJSUzI1NiIs..."
						required
					></textarea>
				</div>

				<button
					type="submit"
					disabled={loading || !token.trim()}
					data-testid="login-submit-button"
					class="w-full rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed"
				>
					{loading ? 'Validando...' : 'Entrar'}
				</button>
			</form>

			<p
				class="mt-4 text-xs text-surface-600 text-center"
				data-testid="login-dev-banner"
				data-login-reason={runtimeFlags.manualTokenLoginReason}
			>
				{#if runtimeFlags.manualTokenLoginReason === 'dev-mode'}
					Modo {runtimeFlags.mode} — autenticação via token manual habilitada.
				{:else}
					Build não-dev com <code>VITE_ALLOW_MANUAL_TOKEN_LOGIN=1</code> — login manual liberado
					por opt-in explícito.
				{/if}
			</p>
		{/if}
	</div>
</div>
