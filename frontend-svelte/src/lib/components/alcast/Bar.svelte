<script lang="ts">
	type Kind = 'pos' | 'neg' | 'warn' | 'neutral';

	let { pct, kind = 'pos' }: { pct: number; kind?: Kind } = $props();

	const clamped = $derived(Math.min(100, Math.max(0, pct)));
</script>

<div class="bar">
	<div class="fill {kind}" style="width: {clamped}%;"></div>
</div>


