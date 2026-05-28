<script lang="ts">
	import Icon from './Icon.svelte';

	let {
		from = 0,
		to = 0,
		total = 0,
		hasPrevious = false,
		hasNext = false,
		onPrevious,
		onNext,
	}: {
		from?: number;
		to?: number;
		total?: number;
		hasPrevious?: boolean;
		hasNext?: boolean;
		onPrevious?: () => void | Promise<void>;
		onNext?: () => void | Promise<void>;
	} = $props();
</script>

<div class="pager">
	<div>Mostrando {from}-{to} de {total}</div>
	<div class="ctrls">
		<button type="button" class="pg-btn" disabled={!hasPrevious} onclick={onPrevious} aria-label="Página anterior"><Icon name="arrowLeft"/></button>
		<button type="button" class="pg-btn active">1</button>
		<button type="button" class="pg-btn" disabled={!hasNext} onclick={onNext} aria-label="Próxima página"><Icon name="arrowRight"/></button>
	</div>
</div>


