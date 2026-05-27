<script lang="ts">
	import type { Snippet } from 'svelte';
	import Sidebar from './Sidebar.svelte';
	import Topbar from './Topbar.svelte';

	type NavBadges = {
		rfqOpen: number | null;
		ordersToday: number | null;
		approvalsPending: number | null;
	};

	let {
		crumbs = [],
		navBadges,
		userName,
		userRoles,
		onLogout,
		children,
	}: {
		crumbs?: string[];
		navBadges: NavBadges;
		userName: string;
		userRoles: string[];
		onLogout: () => void | Promise<void>;
		children: Snippet;
	} = $props();
</script>

<div class="app">
	<Sidebar {navBadges} {userName} {userRoles} {onLogout}/>
	<div class="main">
		<Topbar {crumbs}/>
		{@render children()}
	</div>
</div>


