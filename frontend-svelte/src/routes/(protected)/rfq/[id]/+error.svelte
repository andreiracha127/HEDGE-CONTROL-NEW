<script lang="ts">
	import { page } from '$app/state';
</script>

<div class="flex h-full items-center justify-center">
	<div class="text-center">
		<h1 class="text-4xl font-bold text-gray-500">{page.status}</h1>
		<p class="mt-2 text-gray-500">{page.error?.message ?? 'RFQ não encontrada'}</p>
		<a href="/rfq" class="mt-4 inline-block text-sm text-blue-700 hover:underline">← Voltar para RFQs</a>
	</div>
</div>
