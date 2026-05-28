<script lang="ts">
	import Icon, { type IconName } from './Icon.svelte';

	type HeaderAction = {
		label: string;
		icon?: IconName;
		variant?: 'primary' | 'secondary' | 'accent' | 'danger' | 'ghost';
		href?: string;
		disabled?: boolean;
		testId?: string;
		onclick?: () => void | Promise<void>;
	};

	let {
		eyebrow,
		title,
		subtitle,
		meta = [],
		actions = [],
	}: {
		eyebrow?: string;
		title: string;
		subtitle?: string;
		meta?: string[];
		actions?: HeaderAction[];
	} = $props();

	function actionClass(variant: HeaderAction['variant'] = 'secondary'): string {
		return `btn btn-${variant}`;
	}
</script>

<div class="page-head institutional-head">
	<div class="institutional-head-copy">
		{#if eyebrow}
			<div class="head-eyebrow">{eyebrow}</div>
		{/if}
		<h1 class="page-title">{title}</h1>
		{#if subtitle}
			<div class="page-sub">{subtitle}</div>
		{/if}
		{#if meta.length}
			<div class="head-meta">
				{#each meta as item, i (item)}
					{#if i > 0}<span class="head-meta-sep"></span>{/if}
					<span>{item}</span>
				{/each}
			</div>
		{/if}
	</div>
	{#if actions.length}
		<div class="page-actions">
			{#each actions as action (action.label)}
				{#if action.href}
					<a class={actionClass(action.variant)} href={action.href} aria-disabled={action.disabled} data-testid={action.testId}>
						{#if action.icon}<Icon name={action.icon}/>{/if}
						{action.label}
					</a>
				{:else}
					<button type="button" class={actionClass(action.variant)} disabled={action.disabled} onclick={action.onclick} data-testid={action.testId}>
						{#if action.icon}<Icon name={action.icon}/>{/if}
						{action.label}
					</button>
				{/if}
			{/each}
		</div>
	{/if}
</div>
