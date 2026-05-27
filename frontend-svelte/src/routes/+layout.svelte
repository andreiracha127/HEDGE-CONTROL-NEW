<script lang="ts">
	import '../app.css';
	import { authStore } from '$lib/stores/auth.svelte';
	import { wsStore } from '$lib/stores/ws.svelte';
	import { notifications, type Notification } from '$lib/stores/notifications.svelte';
	import { page } from '$app/state';
	import { clerk, initClerk } from '$lib/clerk';
	import AppShell from '$lib/components/alcast/AppShell.svelte';

	let { children, data } = $props();

	$effect(() => {
		if (authStore.isAuthenticated) {
			wsStore.connect();
			void initClerk().catch(() => {
				/* Restored cookie sessions can render before Clerk loads; refresh remains best-effort. */
			});
		} else {
			wsStore.disconnect();
		}
	});

	async function logout() {
		wsStore.disconnect();
		try {
			await initClerk();
			await clerk.signOut();
		} catch {
			/* Local logout must not depend on Clerk CDN availability. */
		} finally {
			authStore.logout();
		}
	}

	function typeColor(type: Notification['type']): string {
		if (type === 'success') return 'badge pos';
		if (type === 'error') return 'badge neg';
		if (type === 'warning') return 'badge warn';
		return 'badge info';
	}

	const crumbs = $derived(crumbsFor(page.url.pathname));
	const navBadges = $derived(data?.navBadges ?? { rfqOpen: null, ordersToday: null, approvalsPending: null });

	function crumbsFor(pathname: string): string[] {
		const segments = pathname.split('/').filter(Boolean);
		if (segments.length === 0) return ['Hedge Control', 'Visão geral'];

		const labels: Record<string, string> = {
			exposures: 'Exposições',
			orders: 'Ordens',
			new: 'Novo',
			rfq: 'RFQ',
			contracts: 'Contratos',
			counterparties: 'Contrapartes',
			cashflow: 'Fluxo de caixa',
			analytics: 'Análise',
			pnl: 'P&L',
			mtm: 'MTM',
			'what-if': 'What-if',
			'market-data': 'Dados de mercado',
			'workflow-approvals': 'Aprovações',
			audit: 'Auditoria',
		};

		return ['Hedge Control', ...segments.map((segment) => labels[segment] ?? segment)];
	}
</script>

{#if authStore.isAuthenticated}
	<AppShell {crumbs} {navBadges} userName={authStore.userName} userRoles={authStore.userRoles} onLogout={logout}>
		{@render children()}
	</AppShell>
{:else}
	{@render children()}
{/if}

{#if authStore.showExpiryWarning}
	<div class="env-badge neg" style="position: fixed; top: 0; left: 0; right: 0; z-index: 50; text-align: center; padding: 8px;">
		Sessão expira em breve - faça login novamente para continuar.
		<button onclick={logout} class="btn-link" style="margin-left: 8px;">Renovar agora</button>
	</div>
{/if}

<div style="position: fixed; bottom: 16px; right: 16px; z-index: 50; display: flex; flex-direction: column; gap: 8px;">
	{#each notifications.items as notification (notification.id)}
		<div class={typeColor(notification.type)} style="padding: 10px 14px; box-shadow: var(--sh-pop);">
			{notification.message}
			<button onclick={() => notifications.remove(notification.id)} class="btn-ghost btn-sm" style="margin-left: 8px;">x</button>
		</div>
	{/each}
</div>
