<script lang="ts">
	import Icon from './Icon.svelte';

	let { crumbs = [] as string[] }: { crumbs?: string[] } = $props();

	const mode = import.meta.env.MODE;
	const envLabel = mode === 'production' ? 'Produção' : mode === 'development' ? 'Desenvolvimento' : 'Homologação';
	const envClass = mode === 'production' ? 'env-badge prod' : 'env-badge';
	let commandOpen = $state(false);

	const commands = [
		{ label: 'Nova RFQ', href: '/rfq/new', icon: 'rfq' as const, detail: 'Originar cotação com contrapartes' },
		{ label: 'Nova ordem', href: '/orders/new', icon: 'clipboard' as const, detail: 'Registrar fonte comercial da exposição' },
		{ label: 'Aprovações', href: '/workflow-approvals', icon: 'shieldCheck' as const, detail: 'Decisões maker-checker pendentes' },
		{ label: 'Auditoria', href: '/audit', icon: 'doc' as const, detail: 'Ledger imutável e verificação HMAC' },
		{ label: 'What-if', href: '/analytics/what-if', icon: 'bolt' as const, detail: 'Stress tests de P&L e volume' },
	];
</script>

<header class="topbar">
	<div class="crumbs">
		{#each crumbs as crumb, i (i)}
			{#if i > 0}<span class="sep">/</span>{/if}
			<span class:cur={i === crumbs.length - 1}>{crumb}</span>
		{/each}
	</div>

	<button type="button" class="topbar-search command-trigger" aria-label="Buscar no command center" onclick={() => (commandOpen = true)}>
		<Icon name="search"/>
		<span>Buscar contraparte, contrato, RFQ...</span>
		<kbd>Ctrl K</kbd>
	</button>

	<div class="topbar-actions">
		<span class={envClass}>{envLabel}</span>
		<button type="button" class="icon-btn" aria-label="Atualizar">
			<Icon name="refresh"/>
		</button>
		<button type="button" class="icon-btn" aria-label="Notificações">
			<Icon name="bell"/>
			<span class="dot"></span>
		</button>
	</div>
</header>

{#if commandOpen}
	<button type="button" class="command-scrim" aria-label="Fechar command center" onclick={() => (commandOpen = false)}></button>
	<div class="command-panel" role="dialog" aria-label="Command center">
		<div class="command-head">
			<div>
				<div class="head-eyebrow">Command center</div>
				<div class="command-title">Navegação institucional</div>
			</div>
			<button type="button" class="toast-dismiss" aria-label="Fechar command center" onclick={() => (commandOpen = false)}>x</button>
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

