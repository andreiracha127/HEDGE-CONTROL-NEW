<script lang="ts">
	import type { Snippet } from 'svelte';

	type Kind = 'neutral' | 'pos' | 'neg' | 'warn' | 'info';

	let {
		kind = 'neutral',
		dot = false,
		outlined = false,
		children,
	}: {
		kind?: Kind;
		dot?: boolean;
		outlined?: boolean;
		children: Snippet;
	} = $props();
</script>

<span class="badge {kind}" class:outlined>
	{#if dot}<span class="dot"></span>{/if}{@render children()}
</span>


