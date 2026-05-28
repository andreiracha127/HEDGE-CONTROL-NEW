<script lang="ts">
	let { history = [] }: { history?: { mtm_value?: number | null; mtm?: number | null }[] } = $props();

	const W = 720;
	const H = 120;

	const data = $derived.by(() => {
		const points = history
			.map((row) => Number(row.mtm_value ?? row.mtm))
			.filter((value) => Number.isFinite(value));
		if (points.length < 2) return null;
		const min = Math.min(...points);
		const max = Math.max(...points);
		const range = max - min || 1;
		const step = W / Math.max(1, points.length - 1);
		const pathStr = points
			.map((p, i) => `${i * step},${H - ((p - min) / range) * (H - 4) - 2}`)
			.join(' L ');
		const zeroY = H - ((0 - min) / range) * (H - 4) - 2;
		return { pathStr, zeroY, last: points[points.length - 1] };
	});
</script>

{#if data}
	<svg width="100%" height={H} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
		<line x1="0" y1={data.zeroY} x2={W} y2={data.zeroY} stroke="var(--line)" stroke-dasharray="2,3" />
		<path
			d={`M 0,${data.zeroY} L ${data.pathStr} L ${W},${data.zeroY} Z`}
			opacity="0.6"
			style="fill: {data.last >= 0 ? 'var(--pos-soft)' : 'var(--neg-soft)'};"
		/>
		<path
			d={`M ${data.pathStr}`}
			fill="none"
			stroke={data.last >= 0 ? 'var(--pos)' : 'var(--neg)'}
			stroke-width="1.8"
		/>
	</svg>
{/if}


