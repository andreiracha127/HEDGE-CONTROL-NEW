<script lang="ts">
	let {
		points,
		color = 'var(--navy-2)',
		width = 80,
		height = 24,
		fill = false,
	}: {
		points: number[];
		color?: string;
		width?: number;
		height?: number;
		fill?: boolean;
	} = $props();

	const path = $derived.by(() => {
		if (!points || points.length === 0) return { line: '', closed: '' };
		const min = Math.min(...points);
		const max = Math.max(...points);
		const range = max - min || 1;
		const step = width / Math.max(1, points.length - 1);
		const pts = points.map((p, i) => [
			i * step,
			height - ((p - min) / range) * (height - 2) - 1,
		]);
		const d = 'M ' + pts.map((p) => p.join(',')).join(' L ');
		return { line: d, closed: `${d} L ${width},${height} L 0,${height} Z` };
	});
</script>

{#if points && points.length > 0}
	<svg {width} {height} class="kpi-spark">
		{#if fill}
			<path d={path.closed} opacity="0.18" style="fill: {color};" />
		{/if}
		<path d={path.line} fill="none" stroke={color} stroke-width="1.5" stroke-linejoin="round" />
	</svg>
{/if}


