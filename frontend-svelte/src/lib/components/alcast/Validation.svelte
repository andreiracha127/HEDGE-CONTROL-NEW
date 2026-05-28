<script lang="ts">
	let {
		ok = false,
		warn = false,
		label,
	}: { ok?: boolean; warn?: boolean; label: string } = $props();

	const color = $derived(warn ? 'var(--orange)' : ok ? 'var(--pos)' : 'var(--neg)');
</script>

<div class="row gap-2" style="font-size: 12.5px;">
	<span style="width: 14px; height: 14px; border-radius: 50%; display: grid; place-items: center; background: {color}; color: #fff; font-size: 10px;">
		{warn ? '!' : '✓'}
	</span>
	<span style="color: var(--ink-2);">{label}</span>
</div>


