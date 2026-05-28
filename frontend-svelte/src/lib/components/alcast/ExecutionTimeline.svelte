<script lang="ts">
	import EmptyState from './EmptyState.svelte';

	export type TimelineKind = 'pos' | 'neg' | 'warn' | 'info' | 'neutral';
	export type TimelineEvent = {
		label: string;
		time?: string;
		actor?: string;
		kind?: TimelineKind;
	};

	let {
		events = [],
		emptyTitle = 'Sem eventos registrados',
	}: {
		events?: TimelineEvent[];
		emptyTitle?: string;
	} = $props();
</script>

{#if events.length}
	<div class="execution-timeline">
		{#each events as event, i (`${event.label}-${event.time ?? i}`)}
			<div class="execution-step {event.kind ?? 'neutral'}">
				<div class="execution-dot"></div>
				<div>
					<div class="execution-label">{event.label}</div>
					<div class="execution-meta">
						{event.time ?? '—'}{#if event.actor} · {event.actor}{/if}
					</div>
				</div>
			</div>
		{/each}
	</div>
{:else}
	<EmptyState icon="doc" title={emptyTitle} message="A trilha será preenchida quando houver transições ou ações auditáveis." />
{/if}
