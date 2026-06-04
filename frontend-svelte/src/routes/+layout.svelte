<script lang="ts">
	import '../app.css';
	import { authStore } from '$lib/stores/auth.svelte';
	import { wsStore } from '$lib/stores/ws.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { page } from '$app/state';
	import { clerk, initClerk } from '$lib/clerk';
	import AppShell from '$lib/components/alcast/AppShell.svelte';
	import ToastStack from '$lib/components/alcast/ToastStack.svelte';

	type BreadcrumbItem = {
		label: string;
		href?: string;
	};

	let { children, data } = $props();
	let clerkDisplayName = $state<string | null>(null);

	$effect(() => {
		if (authStore.isAuthenticated) {
			wsStore.connect();
			void initClerk().catch(() => {
				/* Restored cookie sessions can render before Clerk loads; refresh remains best-effort. */
			}).then(() => {
				try {
					clerkDisplayName = nameFromClerkUser(clerk.user);
				} catch {
					clerkDisplayName = null;
				}
			});
		} else {
			clerkDisplayName = null;
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

	const crumbs = $derived(crumbsFor(page.url.pathname));
	const navBadges = $derived(data?.navBadges ?? { rfqOpen: null, ordersToday: null, approvalsPending: null });
	const displayUserName = $derived(safeDisplayName(clerkDisplayName ?? authStore.userName));

	function nameFromClerkUser(user: typeof clerk.user): string | null {
		const fullName = user?.fullName?.trim();
		if (fullName) return fullName;
		const joined = [user?.firstName, user?.lastName].filter(Boolean).join(' ').trim();
		if (joined) return joined;
		return user?.primaryEmailAddress?.emailAddress ?? null;
	}

	function safeDisplayName(value: string): string {
		const trimmed = value.trim();
		if (!trimmed || /^user_[A-Za-z0-9]+$/.test(trimmed)) return 'Usuário autenticado';
		return trimmed;
	}

	function crumbsFor(pathname: string): BreadcrumbItem[] {
		const segments = pathname.split('/').filter(Boolean);
		if (segments.length === 0) return [{ label: 'Hedge Control', href: '/' }, { label: 'Visão geral' }];

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

		const hrefBySegment: Record<string, string> = {
			exposures: '/exposures',
			orders: '/orders',
			rfq: '/rfq',
			contracts: '/contracts',
			counterparties: '/counterparties',
			cashflow: '/cashflow',
			analytics: '/analytics/pnl',
			pnl: '/analytics/pnl',
			mtm: '/analytics/mtm',
			'what-if': '/analytics/what-if',
			'market-data': '/market-data',
			'workflow-approvals': '/workflow-approvals',
			audit: '/audit',
		};

		return [
			{ label: 'Hedge Control', href: '/' },
			...segments.map((segment, index) => {
				const isCurrent = index === segments.length - 1;
				return {
					label: labels[segment] ?? segment,
					href: isCurrent ? undefined : hrefBySegment[segment],
				};
			}),
		];
	}
</script>

{#if authStore.isAuthenticated}
	<AppShell {crumbs} {navBadges} userName={displayUserName} userRoles={authStore.userRoles} onLogout={logout}>
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

<ToastStack items={notifications.items} onRemove={(id) => notifications.remove(id)}/>
