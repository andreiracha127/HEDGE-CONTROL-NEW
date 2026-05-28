<script lang="ts">
	import Icon, { type IconName } from './Icon.svelte';

	let {
		icon = 'info',
		title,
		message,
		actionLabel,
		actionHref,
		onAction,
	}: {
		icon?: IconName;
		title: string;
		message?: string;
		actionLabel?: string;
		actionHref?: string;
		onAction?: () => void | Promise<void>;
	} = $props();
</script>

<div class="empty-state">
	<div class="empty-state-icon">
		<Icon name={icon}/>
	</div>
	<div>
		<div class="empty-state-title">{title}</div>
		{#if message}
			<div class="empty-state-message">{message}</div>
		{/if}
	</div>
	{#if actionLabel}
		{#if actionHref}
			<a class="btn btn-secondary btn-sm" href={actionHref}>{actionLabel}</a>
		{:else}
			<button type="button" class="btn btn-secondary btn-sm" onclick={onAction}>{actionLabel}</button>
		{/if}
	{/if}
</div>
