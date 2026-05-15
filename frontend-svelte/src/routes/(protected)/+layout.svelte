<script lang="ts">
	import { goto } from '$app/navigation';
	import { authStore } from '$lib/stores/auth.svelte';

	let { children } = $props();

	$effect(() => {
		if (!authStore.isAuthenticated && !authStore.isRestoring) {
			goto('/login');
		}
	});
</script>

{#if authStore.isAuthenticated}
	{@render children()}
{/if}
