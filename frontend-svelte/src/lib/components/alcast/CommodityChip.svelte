<script lang="ts">
	let { code }: { code: string } = $props();

	const COLORS: Record<string, string> = {
		'AL-LME': '#7E8AA6',
		'CU-LME': '#C2825F',
		'ZN-LME': '#6FA89C',
		'NI-LME': '#8A86A6',
		USDBRL: '#1E5C36',
	};

	const color = $derived(COLORS[code] ?? '#8E94A0');
</script>

<span class="row gap-2" style="font-weight: 500;">
	<span style="width: 8px; height: 8px; border-radius: 2px; background: {color}; display: inline-block;"></span>
	{code}
</span>


