<script lang="ts">
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';

	interface Approval {
		urgent?: boolean;
		approved?: boolean;
		id: string;
		title: string;
		desc: string;
		requestor: string;
		when: string;
		policy: string;
	}

	const items: Approval[] = [
		{
			urgent: true,
			id: 'APR-2026-0098',
			title: 'Ordem fora da alçada do trader',
			desc: 'ORD-2026-0420 · AL-LME 2.500t buy @ 2.638,50 · JPM · Notional US$ 6,6 M (acima do limite trader US$ 5 M)',
			requestor: 'M. Santos · Trader',
			when: 'aguardando há 1h 42min',
			policy: 'Política Hedge §4.2',
		},
		{
			id: 'APR-2026-0097',
			title: 'Novo limite de contraparte',
			desc: 'Aumento de US$ 6,5 M → US$ 9,0 M · Citi Brasil · revisão semestral',
			requestor: 'L. Ferreira · Risco',
			when: 'aguardando há 12h',
			policy: 'Política Crédito §8.1',
		},
		{
			approved: true,
			id: 'APR-2026-0096',
			title: 'Contrato CT-2026-0118',
			desc: 'AL-LME 1.500t buy · ITAU · Notional US$ 3,9 M',
			requestor: 'A. Costa · Aprovador',
			when: 'aprovada ontem 17:55',
			policy: 'Política Hedge §4.1',
		},
	];

	function barColor(a: Approval): string {
		if (a.urgent) return 'var(--neg)';
		if (a.approved) return 'var(--pos)';
		return 'var(--orange)';
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Aprovações</h1>
			<div class="page-sub">Workflow de aprovações pendentes · 2 itens aguardando você</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary">Histórico</button>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Aguardando você" value="2"   delta="SLA médio 2h · 1 vencendo" deltaKind="neg"/>
		<Kpi label="Aprovadas (mês)"  value="38"  delta="taxa de aprovação 95 %"     deltaKind="pos"/>
		<Kpi label="Tempo médio"      value="01:18" unit="h:m" delta="−00:24 vs mês anterior" deltaKind="pos"/>
		<Kpi label="Rejeições"        value="2"   delta="motivo: fora de alçada"/>
	</div>

	<div class="stack gap-3">
		{#each items as a (a.id)}
			<div class="card" style="padding: 18px; display: grid; grid-template-columns: 4px 1fr auto; gap: 16px; align-items: center;">
				<div style="align-self: stretch; background: {barColor(a)}; border-radius: 2px;"></div>
				<div>
					<div class="row gap-3" style="margin-bottom: 4px;">
						{#if a.urgent}
							<Badge kind="neg" dot>SLA vencendo</Badge>
						{:else if a.approved}
							<Badge kind="pos" dot>Aprovado</Badge>
						{:else}
							<Badge kind="warn" dot>Pendente</Badge>
						{/if}
						<span class="mono" style="font-size: 11px; color: var(--muted);">{a.id}</span>
						<span style="font-size: 11px; color: var(--muted);">· {a.policy}</span>
					</div>
					<div style="font-size: 14px; font-weight: 500; margin-bottom: 4px;">{a.title}</div>
					<div style="font-size: 12.5px; color: var(--ink-3);">{a.desc}</div>
					<div style="font-size: 11.5px; color: var(--muted); margin-top: 6px;">{a.requestor} · {a.when}</div>
				</div>
				<div class="row gap-2">
					{#if !a.approved}
						<button type="button" class="btn btn-secondary">Ver detalhes</button>
						<button type="button" class="btn btn-danger">Rejeitar</button>
						<button type="button" class="btn btn-primary"><Icon name="shieldCheck"/>Aprovar</button>
					{:else}
						<button type="button" class="btn btn-secondary">Ver registro</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>
