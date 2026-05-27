<script lang="ts">
	import Logo from './Logo.svelte';
	import Icon, { type IconName } from './Icon.svelte';
	import { page } from '$app/state';

	type NavBadges = {
		rfqOpen: number | null;
		ordersToday: number | null;
		approvalsPending: number | null;
	};

	interface NavItem {
		key: string;
		label: string;
		icon: IconName;
		badge: string | null;
		href: string;
	}

	let {
		navBadges,
		userName,
		userRoles,
		onLogout,
	}: {
		navBadges: NavBadges;
		userName: string;
		userRoles: string[];
		onLogout: () => void | Promise<void>;
	} = $props();

	const roleLabels: Record<string, string> = {
		auditor: 'Auditor',
		risk_manager: 'Risk manager',
		trader: 'Trader',
	};

	const displayRole = $derived.by(() => {
		for (const role of ['auditor', 'risk_manager', 'trader']) {
			if (userRoles.includes(role)) return roleLabels[role];
		}
		return 'Unknown';
	});

	const initials = $derived(
		userName
			.split(/\s+/)
			.filter(Boolean)
			.slice(0, 2)
			.map((part) => part[0]?.toUpperCase())
			.join('') || 'HC',
	);

	const nav = $derived<{ label: string; items: NavItem[] }[]>([
		{
			label: 'Operação',
			items: [
				{ key: 'dashboard', label: 'Visão geral', icon: 'home', badge: null, href: '/' },
				{ key: 'exposures', label: 'Exposições', icon: 'layers', badge: null, href: '/exposures' },
				{ key: 'orders', label: 'Ordens', icon: 'clipboard', badge: navBadges.ordersToday !== null ? String(navBadges.ordersToday) : null, href: '/orders' },
				{ key: 'rfq', label: 'RFQ', icon: 'rfq', badge: navBadges.rfqOpen !== null ? String(navBadges.rfqOpen) : null, href: '/rfq' },
				{ key: 'contracts', label: 'Contratos', icon: 'fileSign', badge: null, href: '/contracts' },
				{ key: 'counterparties', label: 'Contrapartes', icon: 'users', badge: null, href: '/counterparties' },
			],
		},
		{
			label: 'Análise',
			items: [
				{ key: 'cashflow', label: 'Fluxo de caixa', icon: 'coins', badge: null, href: '/cashflow' },
				{ key: 'pnl', label: 'P&L', icon: 'chart', badge: null, href: '/analytics/pnl' },
				{ key: 'mtm', label: 'MTM e cenário', icon: 'scale', badge: null, href: '/analytics/mtm' },
				{ key: 'whatif', label: 'What-if', icon: 'bolt', badge: null, href: '/analytics/what-if' },
				{ key: 'market', label: 'Dados de mercado', icon: 'globe', badge: null, href: '/market-data' },
			],
		},
		{
			label: 'Governança',
			items: [
				{ key: 'approvals', label: 'Aprovações', icon: 'shieldCheck', badge: navBadges.approvalsPending !== null ? String(navBadges.approvalsPending) : null, href: '/workflow-approvals' },
				...(userRoles.includes('auditor')
					? [{ key: 'audit', label: 'Auditoria', icon: 'doc' as IconName, badge: null, href: '/audit' }]
					: []),
			],
		},
	]);

	function isActive(href: string): boolean {
		const path = page.url.pathname;
		if (href === '/') return path === '/';
		return path.startsWith(href);
	}
</script>

<aside class="sidebar">
	<div class="sidebar-brand">
		<Logo size={26}/>
		<div>
			<div class="sidebar-brand-name">Alcast Hedge</div>
			<div class="sidebar-brand-sub">Hedge Control Platform</div>
		</div>
	</div>

	{#each nav as section (section.label)}
		<div class="sidebar-section">
			<div class="sidebar-section-label">{section.label}</div>
			<nav class="sidebar-nav">
				{#each section.items as item (item.key)}
					<a class="sb-item" class:active={isActive(item.href)} href={item.href} data-label={item.label}>
						<Icon name={item.icon}/>
						<span>{item.label}</span>
						{#if item.badge}
							<span class="sb-pill">{item.badge}</span>
						{/if}
					</a>
				{/each}
			</nav>
		</div>
	{/each}

	<div class="sb-foot">
		<div class="sb-foot-avatar">{initials}</div>
		<div style="min-width: 0;">
			<div class="sb-foot-name">{userName}</div>
			<div class="sb-foot-role">{displayRole}</div>
			<button type="button" class="btn-link tiny" onclick={onLogout}>Sair</button>
		</div>
	</div>
</aside>


