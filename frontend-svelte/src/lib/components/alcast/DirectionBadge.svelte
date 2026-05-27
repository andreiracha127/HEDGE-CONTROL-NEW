<script lang="ts">
	import Badge from './Badge.svelte';

	let { dir }: { dir: string } = $props();
	const lower = $derived(dir.toLowerCase());
</script>

{#if lower === 'buy'}
	<Badge kind="pos">COMPRA</Badge>
{:else if lower === 'sell'}
	<Badge kind="neg">VENDA</Badge>
{:else}
	<Badge kind="neutral">{dir}</Badge>
{/if}


