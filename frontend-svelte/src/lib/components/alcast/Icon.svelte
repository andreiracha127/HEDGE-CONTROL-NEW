<script lang="ts">
	export type IconName =
		| 'home' | 'layers' | 'clipboard' | 'rfq' | 'fileSign' | 'users'
		| 'coins' | 'chart' | 'scale' | 'globe' | 'shieldCheck' | 'bell'
		| 'search' | 'plus' | 'chevronDown' | 'chevronRight' | 'filter'
		| 'download' | 'refresh' | 'more' | 'up' | 'down' | 'settings'
		| 'bolt' | 'externalLink' | 'arrowLeft' | 'arrowRight' | 'menu' | 'lock'
		| 'info' | 'doc';

	let { name }: { name: IconName } = $props();
</script>

{#if name === 'home'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M10 20v-6h4v6"/></svg>
{:else if name === 'layers'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/><path d="M3 17l9 5 9-5"/></svg>
{:else if name === 'clipboard'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="5" width="12" height="16" rx="1.5"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 11h6M9 14h6M9 17h3"/></svg>
{:else if name === 'rfq'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h10l4 4v12H5z"/><path d="M15 4v4h4"/><path d="M9 12l2 2 4-4"/></svg>
{:else if name === 'fileSign'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h10l4 4v12H5z"/><path d="M15 4v4h4"/><path d="M8 14l2 2 5-5"/></svg>
{:else if name === 'users'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="9" r="3.2"/><path d="M3 20c.6-3.2 3-5 6-5s5.4 1.8 6 5"/><circle cx="17" cy="8" r="2.5"/><path d="M16 14c2 0 4 1 4.5 3.5"/></svg>
{:else if name === 'coins'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><ellipse cx="8" cy="8" rx="5" ry="2.5"/><path d="M3 8v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5V8"/><ellipse cx="16" cy="14" rx="5" ry="2.5"/><path d="M11 14v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5v-4"/></svg>
{:else if name === 'chart'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 4v16h16"/><path d="M7 14l3-3 3 3 5-7"/></svg>
{:else if name === 'scale'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M5 21h14"/><path d="M6 7l-3 6h6z"/><path d="M18 7l3 6h-6z"/><path d="M5 7h14"/></svg>
{:else if name === 'globe'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c2.5 3 4 6 4 9s-1.5 6-4 9c-2.5-3-4-6-4-9s1.5-6 4-9z"/></svg>
{:else if name === 'shieldCheck'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l8 3v6c0 4.5-3.2 8.4-8 9-4.8-.6-8-4.5-8-9V6z"/><path d="M9 12l2 2 4-4"/></svg>
{:else if name === 'bell'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9a6 6 0 1112 0c0 5 2 6 2 6H4s2-1 2-6z"/><path d="M10 19a2 2 0 004 0"/></svg>
{:else if name === 'search'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="6"/><path d="M16 16l4 4"/></svg>
{:else if name === 'plus'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>
{:else if name === 'chevronDown'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 9l6 6 6-6"/></svg>
{:else if name === 'chevronRight'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M9 6l6 6-6 6"/></svg>
{:else if name === 'filter'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5h18l-7 9v6l-4-2v-4z"/></svg>
{:else if name === 'download'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v12"/><path d="M7 11l5 5 5-5"/><path d="M5 20h14"/></svg>
{:else if name === 'refresh'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12a9 9 0 0115-6.7L21 8"/><path d="M21 4v4h-4"/><path d="M21 12a9 9 0 01-15 6.7L3 16"/><path d="M3 20v-4h4"/></svg>
{:else if name === 'more'}
	<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="6" cy="12" r="1.5"/><circle cx="12" cy="12" r="1.5"/><circle cx="18" cy="12" r="1.5"/></svg>
{:else if name === 'up'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M7 14l5-5 5 5"/></svg>
{:else if name === 'down'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M7 10l5 5 5-5"/></svg>
{:else if name === 'settings'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 01-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 010-4h.1a1.7 1.7 0 001.5-1 1.7 1.7 0 00-.3-1.8L4.2 7a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 014 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9c.6.4 1 1 1 1.7"/></svg>
{:else if name === 'bolt'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M13 3L4 14h7l-1 7 9-11h-7z"/></svg>
{:else if name === 'externalLink'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6"/><path d="M20 4l-8 8"/><path d="M19 13v6H5V5h6"/></svg>
{:else if name === 'arrowLeft'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/><path d="M9 12h12"/></svg>
{:else if name === 'arrowRight'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/><path d="M15 12H3"/></svg>
{:else if name === 'menu'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/></svg>
{:else if name === 'lock'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11V7a4 4 0 018 0v4"/></svg>
{:else if name === 'info'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8v.5"/></svg>
{:else if name === 'doc'}
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4h9l5 5v11H5z"/><path d="M14 4v5h5"/></svg>
{/if}

