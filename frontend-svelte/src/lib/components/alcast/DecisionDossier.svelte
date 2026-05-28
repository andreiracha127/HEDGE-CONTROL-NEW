<script lang="ts">
	import Badge from './Badge.svelte';

	export type DossierKind = 'pos' | 'neg' | 'warn' | 'info' | 'neutral';
	export type DossierItem = {
		label: string;
		value: string | number | null | undefined;
		kind?: DossierKind;
	};

	let {
		title,
		verdict,
		verdictKind = 'neutral',
		items = [],
	}: {
		title: string;
		verdict?: string;
		verdictKind?: DossierKind;
		items?: DossierItem[];
	} = $props();
</script>

<section class="decision-dossier">
	<div class="decision-dossier-head">
		<div class="card-title">{title}</div>
		{#if verdict}
			<Badge kind={verdictKind} dot>{verdict}</Badge>
		{/if}
	</div>
	<dl class="decision-dossier-list">
		{#each items as item (item.label)}
			<div>
				<dt>{item.label}</dt>
				<dd class:tabular={typeof item.value === 'number'}>
					{item.value ?? '—'}
				</dd>
			</div>
		{/each}
	</dl>
</section>
