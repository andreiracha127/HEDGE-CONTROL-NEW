<script lang="ts">
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import Icon from '$lib/components/alcast/Icon.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	import Pager from '$lib/components/alcast/Pager.svelte';
	import { client } from '$lib/api/client';
	import { authStore } from '$lib/stores/auth.svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	let { data } = $props();
	const auditLog = $derived(data.auditLog);
	const auditLoadError = $derived(data.auditLoadError);
	const auditTotal = $derived(auditLog.length);
	const activeUsers = $derived(new Set(auditLog.map((event: Record<string, unknown>) => String(event.user ?? '')).filter(Boolean)).size);
	type VerifyStatus = 'valid' | 'invalid' | 'unverifiable';
	let verifyResults = $state<Record<string, VerifyStatus>>({});

	type RoleKind = 'neutral' | 'pos' | 'neg' | 'warn' | 'info';

	function roleKind(role: string): RoleKind {
		if (role === 'System') return 'neutral';
		if (role === 'Risco') return 'info';
		if (role === 'Aprovador') return 'warn';
		if (role === 'Trader') return 'pos';
		return 'neutral';
	}

	function fmtChecksum(value: unknown): string {
		if (typeof value !== 'string' || !value.trim()) return '—';
		const checksum = value.trim();
		return checksum.length > 18 ? `${checksum.slice(0, 12)}…${checksum.slice(-6)}` : checksum;
	}

	function verifyStatus(result: { valid?: boolean; detail?: string } | null | undefined): VerifyStatus {
		if (result?.valid === true) return 'valid';
		if (result?.valid === false) {
			const detail = result.detail?.toLowerCase() ?? '';
			return detail.includes('without a signature') || detail.includes('missing signature') || detail.includes('no signature')
				? 'unverifiable'
				: 'invalid';
		}
		return 'unverifiable';
	}

	async function verifyEvent(eventId: string) {
		const { data: result, error: apiError } = await client.GET('/audit/events/{event_id}/verify', {
			params: { path: { event_id: eventId } },
		});
		if (apiError) {
			verifyResults = { ...verifyResults, [eventId]: 'unverifiable' };
			notifications.error(`Falha ao verificar evento: ${apiError.detail ?? 'erro desconhecido'}`);
			return;
		}
		verifyResults = { ...verifyResults, [eventId]: verifyStatus(result) };
	}
</script>

<div class="page">
	{#if !authStore.hasRole('auditor')}
		<Card>
			<div data-testid="audit-forbidden">
				<EmptyState
					icon="lock"
					title="Acesso restrito a auditoria"
					message="Somente auditores podem consultar o ledger imutável e verificar assinaturas."
				/>
			</div>
		</Card>
	{:else}
	<PageHeader
		eyebrow="Governança"
		title="Auditoria"
		subtitle="Trilha imutável de eventos · retenção 7 anos · CVM-compliant"
		meta={[`${auditTotal} evento${auditTotal === 1 ? '' : 's'}`, `${activeUsers} usuário${activeUsers === 1 ? '' : 's'} ativo${activeUsers === 1 ? '' : 's'}`]}
		actions={[
			{ label: 'Exportar trilha (CSV)', icon: 'download', variant: 'secondary' },
		]}
	/>

	<Card noPad>
		<div class="tbl-tools">
			<button type="button" class="chip"><Icon name="filter"/>Período · hoje</button>
			<button type="button" class="chip"><Icon name="filter"/>Usuário · todos</button>
			<button type="button" class="chip"><Icon name="filter"/>Ação · todas</button>
			<button type="button" class="chip"><Icon name="filter"/>Entidade</button>
			<div class="sp"></div>
			<span style="font-size: 11.5px; color: var(--muted);">{auditTotal} evento{auditTotal === 1 ? '' : 's'} · {activeUsers} usuário{activeUsers === 1 ? '' : 's'} ativo{activeUsers === 1 ? '' : 's'}</span>
		</div>
		{#if auditLoadError}
			<div class="badge warn" style="margin: 12px 18px;">Falha ao carregar eventos: {auditLoadError}</div>
		{/if}
		{#if auditLog.length === 0}
			<EmptyState
				icon="doc"
				title="Nenhum evento carregado"
				message="Ajuste filtros, confirme permissão de auditoria ou recarregue a trilha."
			/>
		{:else}
		<table class="tbl">
			<thead>
				<tr>
					<th style="width: 160px;">Timestamp</th>
					<th>Usuário</th>
					<th>Papel</th>
					<th>Ação</th>
					<th>Entidade</th>
					<th>Detalhe</th>
					<th>Hash</th>
					<th>Verificação</th>
				</tr>
			</thead>
			<tbody>
				{#each auditLog as e, i (i)}
					{@const eventId = e.id ?? e.entity ?? String(i)}
					<tr>
						<td class="mono tabular" style="font-size: 12px; color: var(--ink-3);">{e.ts}</td>
						<td class="strong">{e.user}</td>
						<td><Badge kind={roleKind(e.role)}>{e.role}</Badge></td>
						<td class="mono" style="font-size: 12px;">{e.action}</td>
						<td class="mono">{e.entity}</td>
						<td style="color: var(--ink-3);">{e.detail}</td>
						<td class="mono" style="font-size: 11px; color: var(--muted-2);">{fmtChecksum(e.checksum)}</td>
						<td>
							<button
								type="button"
								data-testid="audit-verify-button"
								class="btn btn-secondary btn-sm"
								onclick={() => verifyEvent(eventId)}
							>
								{verifyResults[eventId] ?? 'unverifiable'}
							</button>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
		<Pager from={1} to={Math.min(10, auditTotal)} total={auditTotal}/>
		{/if}
	</Card>
	{/if}
</div>
