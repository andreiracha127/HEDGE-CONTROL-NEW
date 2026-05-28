<script lang="ts">
	import { page } from '$app/state';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
</script>

<div class="page error-surface">
	<EmptyState
		icon="info"
		title={`${page.status} · Falha ao carregar a superfície`}
		message={page.error?.message ?? 'Algo deu errado no carregamento desta área operacional.'}
		actionLabel="Voltar ao início"
		actionHref="/"
	/>
</div>
