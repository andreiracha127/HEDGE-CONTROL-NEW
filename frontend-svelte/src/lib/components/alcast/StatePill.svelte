<script lang="ts">
	import Badge from './Badge.svelte';
	import { stateBadge } from '$lib/alcast/presentation';

	let { state }: { state: string } = $props();
	const entry = $derived(stateBadge(state));
</script>

<Badge kind={entry.kind} dot>{entry.label}</Badge>

