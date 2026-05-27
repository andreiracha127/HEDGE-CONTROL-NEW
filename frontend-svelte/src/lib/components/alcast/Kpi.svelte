<script lang="ts">
	import Sparkline from './Sparkline.svelte';

	type DeltaKind = 'pos' | 'neg' | 'flat';

	let {
		label,
		value,
		unit,
		delta,
		deltaKind = 'flat',
		spark,
		sparkColor = 'var(--navy-2)',
	}: {
		label: string;
		value: string;
		unit?: string;
		delta?: string;
		deltaKind?: DeltaKind;
		spark?: number[];
		sparkColor?: string;
	} = $props();
</script>

<div class="kpi">
	<div class="kpi-label">{label}</div>
	<div class="kpi-value">
		{value}{#if unit}<span class="unit">{unit}</span>{/if}
	</div>
	{#if delta}
		<div class="kpi-delta {deltaKind}">
			{#if deltaKind === 'pos'}▲ {:else if deltaKind === 'neg'}▼ {/if}{delta}
		</div>
	{/if}
	{#if spark}
		<Sparkline points={spark} color={sparkColor} fill={true} />
	{/if}
</div>


