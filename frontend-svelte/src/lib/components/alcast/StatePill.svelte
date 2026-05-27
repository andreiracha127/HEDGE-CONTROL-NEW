<script lang="ts">
	import Badge from './Badge.svelte';

	let { state }: { state: string } = $props();

	type StateMapKind = 'neutral' | 'pos' | 'neg' | 'warn' | 'info';

	const STATE_MAP: Record<string, { kind: StateMapKind; label: string }> = {
		CREATED: { kind: 'neutral', label: 'Criada' },
		SENT: { kind: 'info', label: 'Enviada' },
		QUOTED: { kind: 'pos', label: 'Cotada' },
		AWARDED: { kind: 'pos', label: 'Adjudicada' },
		CANCELLED: { kind: 'neutral', label: 'Cancelada' },
		filled: { kind: 'pos', label: 'Liquidada' },
		partial: { kind: 'warn', label: 'Parcial' },
		cancelled: { kind: 'neutral', label: 'Cancelada' },
		pending: { kind: 'warn', label: 'Pendente' },
		active: { kind: 'pos', label: 'Ativo' },
		maturing: { kind: 'warn', label: 'Vencendo' },
		settled: { kind: 'neutral', label: 'Liquidado' },
		review: { kind: 'warn', label: 'Em análise' },
		projected: { kind: 'info', label: 'Projetado' },
		confirmed: { kind: 'pos', label: 'Confirmado' },
		suspended: { kind: 'neg', label: 'Suspenso' },
	};

	function stateLabel(value: string): { kind: StateMapKind; label: string } {
		return STATE_MAP[value] ?? { kind: 'neutral', label: value };
	}

	const entry = $derived(stateLabel(state));
</script>

<Badge kind={entry.kind} dot>{entry.label}</Badge>


