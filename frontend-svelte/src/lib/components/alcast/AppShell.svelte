<script lang="ts">
	import type { Snippet } from 'svelte';
	import Sidebar from './Sidebar.svelte';
	import Topbar from './Topbar.svelte';

	type NavBadges = {
		rfqOpen: number | null;
		ordersToday: number | null;
		approvalsPending: number | null;
	};
	type BreadcrumbItem = {
		label: string;
		href?: string;
	};

	let {
		crumbs = [],
		navBadges,
		userName,
		userRoles,
		onLogout,
		children,
	}: {
		crumbs?: BreadcrumbItem[];
		navBadges: NavBadges;
		userName: string;
		userRoles: string[];
		onLogout: () => void | Promise<void>;
		children: Snippet;
	} = $props();

	let sidebarCollapsed = $state(false);

	$effect(() => {
		if (typeof localStorage === 'undefined') return;
		sidebarCollapsed = localStorage.getItem('alcast.sidebarCollapsed') === 'true';
	});

	$effect(() => {
		if (typeof localStorage === 'undefined') return;
		localStorage.setItem('alcast.sidebarCollapsed', String(sidebarCollapsed));
	});
</script>

<div class="app" class:sidebar-collapsed={sidebarCollapsed}>
	<Sidebar
		{navBadges}
		{userName}
		{userRoles}
		{onLogout}
		collapsed={sidebarCollapsed}
	/>
	<div class="main">
		<Topbar
			{crumbs}
			{userRoles}
			sidebarCollapsed={sidebarCollapsed}
			onSidebarToggle={() => (sidebarCollapsed = !sidebarCollapsed)}
		/>
		{@render children()}
	</div>
</div>
