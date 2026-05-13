<script lang="ts">
	import '../app.css';
	import { authStore } from '$lib/stores/auth.svelte';
	import { wsStore } from '$lib/stores/ws.svelte';
	import { notifications, type Notification } from '$lib/stores/notifications.svelte';
	import { page } from '$app/state';

	let { children } = $props();

	// WS lifecycle: connect when authenticated, disconnect on logout
	$effect(() => {
		if (authStore.isAuthenticated) {
			wsStore.connect();
		} else {
			wsStore.disconnect();
		}
	});

	function wsStatusDot(status: string): string {
		switch (status) {
			case 'authenticated': return 'bg-success';
			case 'open':
			case 'connecting': return 'bg-warning animate-pulse';
			case 'error': return 'bg-danger';
			default: return 'bg-surface-600';
		}
	}

	// J-A6-08/09: orders surface is visible to any authenticated user
	// (read-only reconstructability), while audit is restricted to the
	// `auditor` role both here and at the backend. The role gate is a UX
	// courtesy — the security boundary is the backend's `require_role`
	// check on `/audit/events` and `/audit/events/{id}/verify`.
	const navItems = $derived([
		{ href: '/', label: 'Dashboard', icon: '◉' },
		{ href: '/rfq', label: 'RFQs', icon: '⇄' },
		{ href: '/orders', label: 'Orders', icon: '⊟' },
		{ href: '/exposures', label: 'Exposições', icon: '◧' },
		{ href: '/cashflow', label: 'Cashflow', icon: '⊞' },
		{ href: '/contracts', label: 'Contratos', icon: '◳' },
		{ href: '/counterparties', label: 'Contrapartes', icon: '⊕' },
		{ href: '/analytics/pnl', label: 'Analytics', icon: '◠' },
		{ href: '/market-data', label: 'Market Data', icon: '◆' },
		...(authStore.hasRole('auditor')
			? [{ href: '/audit', label: 'Audit', icon: '⊜' }]
			: []),
	]);

	let sidebarCollapsed = $state(false);

	function isActive(href: string): boolean {
		if (href === '/') return page.url.pathname === '/';
		return page.url.pathname.startsWith(href);
	}

	function typeColor(type: Notification['type']): string {
		switch (type) {
			case 'success': return 'bg-success/90 text-white';
			case 'error': return 'bg-danger/90 text-white';
			case 'warning': return 'bg-warning/90 text-surface-950';
			default: return 'bg-accent/90 text-white';
		}
	}
</script>

<div class="flex h-screen overflow-hidden">
	<!-- Sidebar -->
	{#if authStore.isAuthenticated}
		<nav
			class="flex flex-col border-r border-surface-800 bg-surface-900 transition-[width] duration-200 {sidebarCollapsed ? 'w-14' : 'w-52'}"
		>
			<div class="flex h-12 items-center justify-between border-b border-surface-800 px-3">
				{#if !sidebarCollapsed}
					<span class="text-sm font-semibold text-surface-200">Hedge Control</span>
				{/if}
				<button
					onclick={() => (sidebarCollapsed = !sidebarCollapsed)}
					class="rounded p-1 text-surface-400 hover:bg-surface-800 hover:text-surface-200"
				>
					{sidebarCollapsed ? '→' : '←'}
				</button>
			</div>

			<div class="flex-1 overflow-y-auto py-2">
				{#each navItems as item}
					<a
						href={item.href}
						class="flex items-center gap-3 px-3 py-2 text-sm transition-colors
							{isActive(item.href)
								? 'bg-accent/10 text-accent border-r-2 border-accent'
								: 'text-surface-400 hover:bg-surface-800 hover:text-surface-200'}"
					>
						<span class="text-base">{item.icon}</span>
						{#if !sidebarCollapsed}
							<span>{item.label}</span>
						{/if}
					</a>
				{/each}
			</div>

			<div class="border-t border-surface-800 px-3 py-2">
				<!-- WS connection status -->
				<div class="flex items-center gap-2 mb-1">
					<span class="h-2 w-2 rounded-full {wsStatusDot(wsStore.status)}"></span>
					{#if !sidebarCollapsed}
						<span class="text-xs text-surface-600">
							{wsStore.status === 'authenticated' ? 'Conectado' : wsStore.status === 'connecting' ? 'Conectando...' : wsStore.status === 'error' ? 'Erro WS' : 'Desconectado'}
						</span>
					{/if}
				</div>
				{#if !sidebarCollapsed}
					<div class="text-xs text-surface-500 truncate">{authStore.userName}</div>
					<div class="text-xs text-surface-600">{authStore.userRoles.join(', ')}</div>
				{/if}
				<button
					onclick={() => { wsStore.disconnect(); authStore.logout(); }}
					class="mt-1 w-full rounded px-2 py-1 text-xs text-surface-400 hover:bg-surface-800 hover:text-surface-200"
				>
					{sidebarCollapsed ? '⏻' : 'Sair'}
				</button>
			</div>
		</nav>
	{/if}

	<!-- Main content -->
	<main class="flex-1 overflow-y-auto">
		{@render children()}
	</main>
</div>

<!-- Session expiry warning -->
{#if authStore.showExpiryWarning}
	<div class="fixed top-0 left-0 right-0 z-50 bg-warning px-4 py-2 text-center text-sm font-medium text-surface-950">
		Sessão expira em breve — faça login novamente para continuar.
		<button
			onclick={() => authStore.logout()}
			class="ml-2 underline"
		>
			Renovar agora
		</button>
	</div>
{/if}

<!-- Toast notifications -->
<div class="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
	{#each notifications.items as notification (notification.id)}
		<div class="flex items-center gap-2 rounded-lg px-4 py-2 text-sm shadow-lg {typeColor(notification.type)}">
			<span>{notification.message}</span>
			<button
				onclick={() => notifications.remove(notification.id)}
				class="ml-2 opacity-70 hover:opacity-100"
			>
				✕
			</button>
		</div>
	{/each}
</div>
