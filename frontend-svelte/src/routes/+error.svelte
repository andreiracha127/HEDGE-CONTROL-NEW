<script lang="ts">
	import { page } from '$app/state';
</script>

<div class="flex h-screen items-center justify-center">
	<div class="text-center">
		<h1 class="text-6xl font-bold text-gray-500">{page.status}</h1>
		<p class="mt-4 text-lg text-gray-500">{page.error?.message ?? 'Algo deu errado'}</p>
		<a href="/" class="mt-6 inline-block rounded bg-blue-50 px-4 py-2 text-sm text-white hover:bg-blue-50-hover">
			Voltar ao início
		</a>
	</div>
</div>
