<script lang="ts">
	import type { Notification } from '$lib/stores/notifications.svelte';
	import Icon from './Icon.svelte';

	let {
		items = [],
		onRemove,
	}: {
		items: Notification[];
		onRemove: (id: string) => void;
	} = $props();

	function toastClass(type: Notification['type']): string {
		return `toast toast-${type}`;
	}

	function iconName(type: Notification['type']) {
		if (type === 'success') return 'shieldCheck';
		if (type === 'error') return 'info';
		if (type === 'warning') return 'bolt';
		return 'bell';
	}
</script>

<div class="toast-stack" aria-live="polite" aria-relevant="additions removals">
	{#each items as notification (notification.id)}
		<div class={toastClass(notification.type)} role="status" aria-label={notification.message}>
			<div class="toast-icon"><Icon name={iconName(notification.type)}/></div>
			<div class="toast-body">
				<div class="toast-kicker">{notification.type}</div>
				<div class="toast-message">{notification.message}</div>
			</div>
			<button
				type="button"
				class="toast-dismiss"
				aria-label={`Dismiss ${notification.message}`}
				onclick={() => onRemove(notification.id)}
			>
				x
			</button>
		</div>
	{/each}
</div>
