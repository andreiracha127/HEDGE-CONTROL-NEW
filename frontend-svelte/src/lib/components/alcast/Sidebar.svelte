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
		collapsed = false,
	}: {
		navBadges: NavBadges;
		userName: string;
		userRoles: string[];
		onLogout: () => void | Promise<void>;
		collapsed?: boolean;
	} = $props();

	const roleLabels: Record<string, string> = {
		auditor: 'Auditor',
		risk_manager: 'Risk manager',
		trader: 'Trader',
	};

	function isRawSubject(value: string): boolean {
		return /^user_[A-Za-z0-9]+$/.test(value.trim());
	}

	const safeUserName = $derived(
		userName.trim().length > 0 && !isRawSubject(userName) ? userName.trim() : 'Usuário autenticado',
	);

	const displayRole = $derived.by(() => {
		for (const role of ['auditor', 'risk_manager', 'trader']) {
			if (userRoles.includes(role)) return roleLabels[role];
		}
		return 'Perfil pendente';
	});
	const canUseAnalysis = $derived(userRoles.includes('risk_manager') || userRoles.includes('auditor'));
	const canUseRiskWorkflows = $derived(userRoles.includes('risk_manager') || userRoles.includes('auditor'));

	const initials = $derived(
		safeUserName
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
				...(canUseAnalysis ? [{ key: 'exposures', label: 'Exposições', icon: 'layers' as IconName, badge: null, href: '/exposures' }] : []),
				{ key: 'orders', label: 'Ordens', icon: 'clipboard', badge: navBadges.ordersToday !== null ? String(navBadges.ordersToday) : null, href: '/orders' },
				...(canUseRiskWorkflows ? [
					{ key: 'rfq', label: 'RFQ', icon: 'rfq' as IconName, badge: navBadges.rfqOpen !== null ? String(navBadges.rfqOpen) : null, href: '/rfq' },
					{ key: 'contracts', label: 'Contratos', icon: 'fileSign' as IconName, badge: null, href: '/contracts' },
				] : []),
				{ key: 'counterparties', label: 'Contrapartes', icon: 'users', badge: null, href: '/counterparties' },
			],
		},
		{
			label: 'Análise',
			items: canUseAnalysis
				? [
					{ key: 'cashflow', label: 'Fluxo de caixa', icon: 'coins', badge: null, href: '/cashflow' },
					{ key: 'pnl', label: 'P&L', icon: 'chart', badge: null, href: '/analytics/pnl' },
					{ key: 'mtm', label: 'MTM e cenário', icon: 'scale', badge: null, href: '/analytics/mtm' },
					{ key: 'whatif', label: 'What-if', icon: 'bolt', badge: null, href: '/analytics/what-if' },
					{ key: 'market', label: 'Dados de mercado', icon: 'globe', badge: null, href: '/market-data' },
				]
				: [],
		},
		{
			label: 'Governança',
			items: [
				...(canUseRiskWorkflows ? [
				{ key: 'approvals', label: 'Aprovações', icon: 'shieldCheck' as IconName, badge: navBadges.approvalsPending !== null ? String(navBadges.approvalsPending) : null, href: '/workflow-approvals' },
				] : []),
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

<aside id="primary-navigation" class="sidebar" class:collapsed={collapsed} aria-label="Navegação principal">
	<div class="sidebar-brand">
		<Logo size={26}/>
		<div class="sidebar-brand-copy">
			<div class="sidebar-brand-name">Alcast Hedge</div>
			<div class="sidebar-brand-sub">Hedge Control Platform</div>
		</div>
	</div>

	{#each nav as section (section.label)}
		{#if section.items.length > 0}
		<div class="sidebar-section">
			<div class="sidebar-section-label">{section.label}</div>
			<nav class="sidebar-nav">
				{#each section.items as item (item.key)}
					<a class="sb-item" class:active={isActive(item.href)} href={item.href} data-label={item.label} title={collapsed ? item.label : undefined}>
						<Icon name={item.icon}/>
						<span>{item.label}</span>
						{#if item.badge}
							<span class="sb-pill">{item.badge}</span>
						{/if}
					</a>
				{/each}
			</nav>
		</div>
		{/if}
	{/each}

	<div class="sb-foot">
		<div class="sb-foot-avatar">{initials}</div>
		<div class="sb-foot-meta">
			<div class="sb-foot-name">{safeUserName}</div>
			<div class="sb-foot-role">{displayRole}</div>
			<button type="button" class="btn-link tiny" onclick={onLogout}>Sair</button>
		</div>
	</div>
</aside>
