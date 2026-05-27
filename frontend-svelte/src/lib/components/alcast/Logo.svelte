<script lang="ts">
	let { size = 26 }: { size?: number } = $props();
</script>

<svg width={size} height={size} viewBox="0 0 32 32" class="logo-mark">
	<rect x="0" y="0" width="32" height="32" rx="6" fill="var(--orange)"/>
	<path d="M8 22 L14 8 L16 8 L18 12 L13 12 L11 16 L21 16 L18 22 Z" fill="#fff"/>
</svg>


