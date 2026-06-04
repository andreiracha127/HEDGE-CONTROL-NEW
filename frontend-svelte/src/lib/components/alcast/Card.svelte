<script lang="ts">
	import type { Snippet } from 'svelte';

	let {
		title,
		sub,
		actions,
		footer,
		noPad = false,
		children,
	}: {
		title?: string | Snippet;
		sub?: string;
		actions?: Snippet;
		footer?: Snippet;
		noPad?: boolean;
		children: Snippet;
	} = $props();

	const titleIsSnippet = $derived(typeof title === 'function');
</script>

<div class="card">
	{#if title || actions}
		<div class="card-head">
			<div>
				{#if title}
					<h3 class="card-title">
						{#if titleIsSnippet}
							{@render (title as Snippet)()}
						{:else}
							{title}
						{/if}
					</h3>
				{/if}
				{#if sub}<div class="card-sub">{sub}</div>{/if}
			</div>
			{#if actions}{@render actions()}{/if}
		</div>
	{/if}
	{#if noPad}
		{@render children()}
	{:else}
		<div class="card-body">{@render children()}</div>
	{/if}
	{#if footer}
		<div class="card-foot">{@render footer()}</div>
	{/if}
</div>


