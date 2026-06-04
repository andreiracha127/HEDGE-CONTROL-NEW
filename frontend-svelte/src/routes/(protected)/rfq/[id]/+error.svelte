<script lang="ts">
	import { page } from '$app/state';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
</script>

<div class="page error-surface">
	<EmptyState
		icon="rfq"
		title={`${page.status} · RFQ indisponível`}
		message={page.error?.message ?? 'A solicitação não foi encontrada ou não está acessível para este perfil.'}
		actionLabel="Voltar para RFQs"
		actionHref="/rfq"
	/>
</div>
