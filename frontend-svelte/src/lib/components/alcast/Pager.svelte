<script lang="ts">
	import Icon from './Icon.svelte';

	let {
		from = 1,
		to = 10,
		total = 47,
	}: { from?: number; to?: number; total?: number } = $props();
</script>

<div class="pager">
	<div>Mostrando {from}-{to} de {total}</div>
	<div class="ctrls">
		<button type="button" class="pg-btn"><Icon name="arrowLeft"/></button>
		<button type="button" class="pg-btn active">1</button>
		<button type="button" class="pg-btn">2</button>
		<button type="button" class="pg-btn">3</button>
		<button type="button" class="pg-btn"><Icon name="arrowRight"/></button>
	</div>
</div>


