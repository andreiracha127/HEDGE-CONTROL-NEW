<script lang="ts">
	import { authStore } from '$lib/stores/auth.svelte';
</script>

<div class="p-6">
	<h1 class="text-lg font-semibold text-surface-200">Dashboard</h1>
	<p class="mt-1 text-sm text-surface-500">Bem-vindo, {authStore.userName}</p>

	<div class="mt-6 grid grid-cols-3 gap-4">
		<a href="/rfq" class="rounded-lg border border-surface-800 bg-surface-900 p-4 hover:border-accent/50 transition-colors">
			<div class="text-sm font-medium text-surface-300">RFQs</div>
			<div class="mt-1 text-xs text-surface-500">Gerenciar cotações</div>
		</a>

		<a href="/exposures" class="rounded-lg border border-surface-800 bg-surface-900 p-4 hover:border-accent/50 transition-colors">
			<div class="text-sm font-medium text-surface-300">Exposições</div>
			<div class="mt-1 text-xs text-surface-500">Visualizar posições</div>
		</a>

		<a href="/analytics/pnl" class="rounded-lg border border-surface-800 bg-surface-900 p-4 hover:border-accent/50 transition-colors">
			<div class="text-sm font-medium text-surface-300">Analytics</div>
			<div class="mt-1 text-xs text-surface-500">P&L e cenários</div>
		</a>

		<a href="/workflow-approvals" class="rounded-lg border border-surface-800 bg-surface-900 p-4 hover:border-accent/50 transition-colors">
			<div class="text-sm font-medium text-surface-300">Approvals</div>
			<div class="mt-1 text-xs text-surface-500">Aprovações pendentes</div>
		</a>
	</div>
</div>
