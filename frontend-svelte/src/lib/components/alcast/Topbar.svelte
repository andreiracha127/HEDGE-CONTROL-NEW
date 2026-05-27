<script lang="ts">
	import Icon from './Icon.svelte';

	let { crumbs = [] as string[] }: { crumbs?: string[] } = $props();

	const mode = import.meta.env.MODE;
	const envLabel = mode === 'production' ? 'Produção' : mode === 'development' ? 'Desenvolvimento' : 'Homologação';
	const envClass = mode === 'production' ? 'env-badge prod' : 'env-badge';
</script>

<header class="topbar">
	<div class="crumbs">
		{#each crumbs as crumb, i (i)}
			{#if i > 0}<span class="sep">/</span>{/if}
			<span class:cur={i === crumbs.length - 1}>{crumb}</span>
		{/each}
	</div>

	<div class="topbar-search">
		<Icon name="search"/>
		<input
			type="search"
			placeholder="Buscar contraparte, contrato, RFQ..."
			disabled
			title="Busca global disponível na próxima wave"
		/>
	</div>

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


