<script lang="ts">
	import type { Snippet } from 'svelte';

	type Side = 'top' | 'bottom' | 'left';

	let {
		side = 'top',
		width = 240,
		children,
	}: {
		side?: Side;
		width?: number;
		children: Snippet;
	} = $props();

	let open = $state(false);
	let root: HTMLSpanElement | undefined = $state();

	function onDocumentClick(e: MouseEvent) {
		if (!root) return;
		if (!root.contains(e.target as Node)) open = false;
	}

	$effect(() => {
		if (!open) return;
		document.addEventListener('click', onDocumentClick);
		return () => document.removeEventListener('click', onDocumentClick);
	});

	function toggle(e: MouseEvent) {
		e.stopPropagation();
		open = !open;
	}
</script>

<span bind:this={root} class="tip" class:open>
	<button
		type="button"
		class="tip-icon"
		aria-label="Mais informações"
		aria-expanded={open}
		onclick={toggle}
	>i</button>
	<span class="tip-pop" data-side={side} style="width: {width}px;" role="tooltip">
		{@render children()}
	</span>
</span>


