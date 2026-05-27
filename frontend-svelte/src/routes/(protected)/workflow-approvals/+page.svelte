<script lang="ts">
	import { invalidateAll } from '$app/navigation';
	import { client } from '$lib/api/client';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import Card from '$lib/components/alcast/Card.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import Kpi from '$lib/components/alcast/Kpi.svelte';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';

	type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired' | 'consumed' | 'superseded';
	type Approval = {
		id: string;
		mutation_type: string;
		status: ApprovalStatus;
		requested_by: string;
		approved_by?: string | null;
		threshold_at_request: string;
		threshold_config_value: string;
		threshold_dimension: string;
		expires_at: string;
		created_at: string;
	};

	let { data } = $props();
	const approvals = $derived((data.approvals ?? []) as Approval[]);
	const pendingApprovals = $derived(approvals.filter((approval) => approval.status === 'pending'));
	const expiringSoon = $derived(
		pendingApprovals.filter((approval) => {
			const expiresAt = Date.parse(approval.expires_at);
			return Number.isFinite(expiresAt) && expiresAt - Date.now() <= 24 * 60 * 60 * 1000;
		}).length,
	);
	const highestThreshold = $derived(
		pendingApprovals.reduce((max, approval) => {
			const value = Number(approval.threshold_at_request);
			return Number.isFinite(value) ? Math.max(max, value) : max;
		}, 0),
	);
	const canAct = $derived(authStore.hasAnyRole('risk_manager', 'auditor'));

	let acting = $state<string | null>(null);
	let rejecting = $state<string | null>(null);
	let reasonText = $state('');

	function badgeKind(status: ApprovalStatus): 'pos' | 'neg' | 'warn' | 'info' | 'neutral' {
		if (status === 'approved' || status === 'consumed') return 'pos';
		if (status === 'rejected' || status === 'expired') return 'neg';
		if (status === 'pending') return 'warn';
		return 'neutral';
	}

	function barColor(approval: Approval): string {
		if (approval.status === 'approved' || approval.status === 'consumed') return 'var(--pos)';
		if (approval.status === 'rejected' || approval.status === 'expired') return 'var(--neg)';
		return 'var(--orange)';
	}

	function mutationLabel(value: string): string {
		const labels: Record<string, string> = {
			deal_create: 'Criacao de contrato',
			deal_award: 'Award de RFQ',
			hedge_contract_settle: 'Liquidacao de contrato',
		};
		return labels[value] ?? value;
	}

	function thresholdLabel(value: string): string {
		const labels: Record<string, string> = {
			notional_usd: 'Notional',
			settlement_amount_usd: 'Settlement',
		};
		return labels[value] ?? value;
	}

	function money(value: string | number): string {
		const amount = Number(value);
		if (!Number.isFinite(amount)) return '—';
		return amount.toLocaleString('pt-BR', {
			style: 'currency',
			currency: 'USD',
			maximumFractionDigits: 0,
		});
	}

	function dateTime(value: string): string {
		const date = new Date(value);
		if (Number.isNaN(date.getTime())) return '—';
		return date.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
	}

	function errorDetail(detail: unknown): string {
		return typeof detail === 'string' ? detail : 'erro desconhecido';
	}

	async function grant(id: string) {
		acting = id;
		const { error: apiError } = await client.POST('/workflow-approvals/{approval_id}/grant', {
			params: { path: { approval_id: id } },
		});
		acting = null;
		if (apiError) {
			notifications.error(`Falha ao aprovar: ${errorDetail(apiError.detail)}`);
			return;
		}
		notifications.success('Aprovacao concedida');
		await invalidateAll();
	}

	async function reject(id: string) {
		const text = reasonText.trim();
		if (text.length < 8) {
			notifications.warning('Informe uma justificativa com pelo menos 8 caracteres.');
			return;
		}

		acting = id;
		const { error: apiError } = await client.POST('/workflow-approvals/{approval_id}/reject', {
			params: { path: { approval_id: id } },
			body: { reason_code: 'other', reason_text: text },
		});
		acting = null;
		if (apiError) {
			notifications.error(`Falha ao rejeitar: ${errorDetail(apiError.detail)}`);
			return;
		}
		rejecting = null;
		reasonText = '';
		notifications.success('Aprovacao rejeitada');
		await invalidateAll();
	}
</script>

<div class="page">
	<div class="page-head">
		<div>
			<h1 class="page-title">Aprovações</h1>
			<div class="page-sub">Workflow de aprovações pendentes · {pendingApprovals.length} item{pendingApprovals.length === 1 ? '' : 's'} aguardando ação</div>
		</div>
		<div class="page-actions">
			<button type="button" class="btn btn-secondary" onclick={() => invalidateAll()}><Icon name="refresh"/>Atualizar</button>
		</div>
	</div>

	<div class="kpi-row cols-4" style="margin-bottom: 16px;">
		<Kpi label="Pendentes" value={String(pendingApprovals.length)} delta={`${expiringSoon} vencendo em 24h`} deltaKind={expiringSoon > 0 ? 'neg' : 'flat'}/>
		<Kpi label="Maior alçada" value={money(highestThreshold)} delta="limite solicitado"/>
		<Kpi label="Carregadas" value={String(approvals.length)} delta="endpoint /workflow-approvals"/>
		<Kpi label="Permissão" value={canAct ? 'Ativa' : 'Restrita'} delta="risk_manager ou auditor" deltaKind={canAct ? 'pos' : 'neg'}/>
	</div>

	{#if approvals.length === 0}
		<Card>
			<div style="font-size: 13px; color: var(--muted);">Nenhuma aprovação pendente.</div>
		</Card>
	{:else}
		<div class="stack gap-3">
			{#each approvals as approval (approval.id)}
				<div class="card" style="padding: 18px; display: grid; grid-template-columns: 4px 1fr auto; gap: 16px; align-items: center;">
					<div style="align-self: stretch; background: {barColor(approval)}; border-radius: 2px;"></div>
					<div>
						<div class="row gap-3" style="margin-bottom: 4px;">
							<Badge kind={badgeKind(approval.status)} dot>{approval.status}</Badge>
							<span class="mono" style="font-size: 11px; color: var(--muted);">{approval.id}</span>
							<span style="font-size: 11px; color: var(--muted);">· {thresholdLabel(approval.threshold_dimension)}</span>
						</div>
						<div style="font-size: 14px; font-weight: 500; margin-bottom: 4px;">{mutationLabel(approval.mutation_type)}</div>
						<div style="font-size: 12.5px; color: var(--ink-3);">
							{money(approval.threshold_at_request)} solicitado · limite {money(approval.threshold_config_value)}
						</div>
						<div style="font-size: 11.5px; color: var(--muted); margin-top: 6px;">
							Solicitado por {approval.requested_by} · expira {dateTime(approval.expires_at)}
						</div>
						{#if rejecting === approval.id}
							<div class="row gap-2" style="margin-top: 10px;">
								<input
									class="input"
									style="max-width: 420px;"
									bind:value={reasonText}
									placeholder="Justificativa da rejeição"
									aria-label="Justificativa da rejeição"
								/>
								<button type="button" class="btn btn-danger btn-sm" disabled={acting === approval.id} onclick={() => reject(approval.id)}>
									Confirmar rejeição
								</button>
							</div>
						{/if}
					</div>
					<div class="row gap-2">
						{#if approval.status === 'pending' && canAct}
							<button
								type="button"
								class="btn btn-danger"
								disabled={acting === approval.id}
								onclick={() => {
									rejecting = rejecting === approval.id ? null : approval.id;
									reasonText = '';
								}}
							>
								Rejeitar
							</button>
							<button type="button" class="btn btn-primary" disabled={acting === approval.id} onclick={() => grant(approval.id)}>
								<Icon name="shieldCheck"/>{acting === approval.id ? 'Processando...' : 'Aprovar'}
							</button>
						{:else}
							<button type="button" class="btn btn-secondary" disabled>Sem ação</button>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}
</div>
