<script lang="ts">
	import Icon, { type IconName } from './Icon.svelte';
	import { client } from '$lib/api/client';
	import { searchGlobal, type GlobalSearchGroup } from '$lib/alcast/global-search';

	type BreadcrumbItem = {
		label: string;
		href?: string;
	};

	type BreadcrumbInput = string | BreadcrumbItem;
	type Command = {
		label: string;
		href: string;
		icon: IconName;
		detail: string;
		keywords?: string[];
	};

	let {
		crumbs = [] as BreadcrumbInput[],
		userRoles = [] as string[],
		sidebarCollapsed = false,
		onSidebarToggle,
	}: {
		crumbs?: BreadcrumbInput[];
		userRoles?: string[];
		sidebarCollapsed?: boolean;
		onSidebarToggle?: () => void;
	} = $props();

	const mode = import.meta.env.MODE;
	const envLabel = mode === 'production' ? 'Produção' : mode === 'development' ? 'Desenvolvimento' : 'Homologação';
	const envClass = mode === 'production' ? 'env-badge prod' : 'env-badge';
	let commandOpen = $state(false);
	let searchQuery = $state('');
	let searchOpen = $state(false);
	let searchBusy = $state(false);
	let searchGroups = $state<GlobalSearchGroup[]>([]);

	const canCreateOrders = $derived(userRoles.includes('trader'));
	const canUseRiskWorkflows = $derived(userRoles.includes('risk_manager') || userRoles.includes('auditor'));
	const canUseAnalysis = $derived(userRoles.includes('risk_manager') || userRoles.includes('auditor'));
	const canUseAudit = $derived(userRoles.includes('auditor'));

	function normalizeCrumb(crumb: BreadcrumbInput): BreadcrumbItem {
		return typeof crumb === 'string' ? { label: crumb } : crumb;
	}

	const breadcrumbItems = $derived(crumbs.map(normalizeCrumb));

	const commands = $derived.by((): Command[] => {
		const items: Command[] = [];
		if (canUseRiskWorkflows) items.push({ label: 'Nova RFQ', href: '/rfq/new', icon: 'rfq', detail: 'Originar cotação com contrapartes' });
		if (canCreateOrders) items.push({ label: 'Nova ordem', href: '/orders/new', icon: 'clipboard', detail: 'Registrar fonte comercial da exposição' });
		if (canUseRiskWorkflows) items.push({ label: 'Aprovações', href: '/workflow-approvals', icon: 'shieldCheck', detail: 'Decisões pendentes de governança' });
		if (canUseAudit) items.push({ label: 'Auditoria', href: '/audit', icon: 'doc', detail: 'Ledger imutável e verificação HMAC' });
		if (canUseAnalysis) items.push({ label: 'What-if', href: '/analytics/what-if', icon: 'bolt', detail: 'Cenários de P&L e volume' });
		return items;
	});

	const normalizedQuery = $derived(searchQuery.trim().toLocaleLowerCase('pt-BR'));
	const sidebarToggleLabel = $derived(sidebarCollapsed ? 'Expandir navegação' : 'Recolher navegação');

	$effect(() => {
		if (typeof window === 'undefined') return;
		const handleKeydown = (event: KeyboardEvent) => {
			if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
				event.preventDefault();
				commandOpen = true;
				searchOpen = false;
			}
			if (event.key === 'Escape') {
				commandOpen = false;
				searchOpen = false;
			}
		};
		window.addEventListener('keydown', handleKeydown);
		return () => window.removeEventListener('keydown', handleKeydown);
	});

	$effect(() => {
		const query = normalizedQuery;
		if (query.length < 2) {
			searchGroups = [];
			searchBusy = false;
			return;
		}
		searchBusy = true;
		let cancelled = false;
		const timeout = window.setTimeout(async () => {
			const groups = await searchGlobal(query, {
				get: (path, options) => (client.GET as any)(path, options),
			});
			if (!cancelled) {
				searchGroups = groups;
				searchBusy = false;
			}
		}, 250);
		return () => {
			cancelled = true;
			window.clearTimeout(timeout);
		};
	});
</script>

<header class="topbar">
	{#if onSidebarToggle}
		<button
			type="button"
			class="icon-btn topbar-menu-toggle"
			aria-label={sidebarToggleLabel}
			title={sidebarToggleLabel}
			aria-controls="primary-navigation"
			aria-expanded={sidebarCollapsed ? 'false' : 'true'}
			onclick={() => onSidebarToggle?.()}
		>
			<Icon name="menu"/>
		</button>
	{/if}

	<nav class="crumbs" aria-label="Breadcrumb">
		{#each breadcrumbItems as crumb, i (i)}
			{#if i > 0}<span class="sep">/</span>{/if}
			{#if crumb.href && i < breadcrumbItems.length - 1}
				<a href={crumb.href}>{crumb.label}</a>
			{:else}
				<span class:cur={i === breadcrumbItems.length - 1}>{crumb.label}</span>
			{/if}
		{/each}
	</nav>

	<form class="topbar-search" role="search" onsubmit={(event) => event.preventDefault()}>
		<Icon name="search"/>
		<input
			type="search"
			aria-label="Busca global"
			placeholder="Buscar contraparte, contrato, RFQ..."
			bind:value={searchQuery}
			onfocus={() => (searchOpen = true)}
			onkeydown={(event) => {
				if (event.key === 'Escape') searchOpen = false;
			}}
		/>
	</form>

	<div class="topbar-actions">
		<span class={envClass}>{envLabel}</span>
		<button type="button" class="icon-btn" aria-label="Ações rápidas" title="Ações rápidas (Ctrl K)" onclick={() => (commandOpen = true)}>
			<Icon name="bolt"/>
		</button>
		<button type="button" class="icon-btn" aria-label="Atualizar">
			<Icon name="refresh"/>
		</button>
		<button type="button" class="icon-btn" aria-label="Notificações">
			<Icon name="bell"/>
			<span class="dot"></span>
		</button>
	</div>
</header>

{#if searchOpen && normalizedQuery.length >= 2}
	<div class="search-panel" role="region" aria-label="Resultados da busca">
		{#if searchBusy}
			<div class="search-empty">Buscando registros...</div>
		{:else if searchGroups.length > 0}
			{#each searchGroups as group (group.label)}
				<div class="search-group-label">{group.label}</div>
				{#each group.items as result (result.href)}
					<a class="command-item" href={result.href} onclick={() => (searchOpen = false)}>
						<span class="command-icon"><Icon name={result.icon}/></span>
						<span>
							<span class="command-label">{result.label}</span>
							<span class="command-detail">{result.detail}</span>
						</span>
						<Icon name="chevronRight"/>
					</a>
				{/each}
			{/each}
		{:else}
			<div class="search-empty">Nenhum resultado para "{searchQuery.trim()}".</div>
		{/if}
	</div>
{/if}

{#if commandOpen}
	<button type="button" class="command-scrim" aria-label="Fechar ações rápidas" onclick={() => (commandOpen = false)}></button>
	<div class="command-panel" role="dialog" aria-label="Ações rápidas">
		<div class="command-head">
			<div>
				<div class="head-eyebrow">Ações rápidas</div>
				<div class="command-title">Atalhos operacionais</div>
			</div>
			<button type="button" class="toast-dismiss" aria-label="Fechar ações rápidas" onclick={() => (commandOpen = false)}>x</button>
		</div>
		<div class="command-list">
			{#each commands as command (command.href)}
				<a class="command-item" href={command.href} onclick={() => (commandOpen = false)}>
					<span class="command-icon"><Icon name={command.icon}/></span>
					<span>
						<span class="command-label">{command.label}</span>
						<span class="command-detail">{command.detail}</span>
					</span>
					<Icon name="chevronRight"/>
				</a>
			{/each}
		</div>
	</div>
{/if}
