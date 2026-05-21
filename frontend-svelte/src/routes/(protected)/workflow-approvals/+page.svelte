<script lang="ts">
	import { onMount } from 'svelte';
	import { apiFetch } from '$lib/api/fetch';
	import {
		workflowApprovalGrantPath,
		workflowApprovalRejectPath,
		workflowApprovalsPath,
	} from '$lib/api/paths';
	import { authStore } from '$lib/stores/auth.svelte';

	type ApprovalStatus = 'pending' | 'approved' | 'rejected' | 'expired' | 'consumed' | 'superseded';
	type WorkflowApproval = {
		id: string;
		mutation_type: string;
		status: ApprovalStatus;
		requested_by: string;
		approved_by?: string | null;
		threshold_at_request: string;
		threshold_config_value: string;
		threshold_dimension: string;
		expires_at: string;
	};

	let approvals = $state<WorkflowApproval[]>([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let rejecting = $state<string | null>(null);
	let reasonText = $state('');

	const canAct = $derived(
		authStore.userRoles.includes('risk_manager') || authStore.userRoles.includes('auditor'),
	);

	async function loadApprovals() {
		loading = true;
		error = null;
		try {
			const response = await apiFetch(workflowApprovalsPath({ status: 'pending' }));
			if (!response.ok) throw new Error(`HTTP ${response.status}`);
			approvals = (await response.json()) as WorkflowApproval[];
		} catch (err) {
			error = err instanceof Error ? err.message : 'Load failed';
			approvals = [];
		} finally {
			loading = false;
		}
	}

	async function grant(id: string) {
		const response = await apiFetch(workflowApprovalGrantPath(id), { method: 'POST' });
		if (!response.ok) {
			error = `Grant failed: HTTP ${response.status}`;
			return;
		}
		await loadApprovals();
	}

	async function reject(id: string) {
		const text = reasonText.trim();
		if (text.length < 8) return;
		const response = await apiFetch(workflowApprovalRejectPath(id), {
			method: 'POST',
			body: JSON.stringify({ reason_code: 'other', reason_text: text }),
		});
		if (!response.ok) {
			error = `Reject failed: HTTP ${response.status}`;
			return;
		}
		rejecting = null;
		reasonText = '';
		await loadApprovals();
	}

	onMount(() => {
		void loadApprovals();
	});
</script>

<div class="p-6">
	<div class="flex items-center justify-between gap-4">
		<div>
			<h1 class="text-lg font-semibold text-surface-200">Workflow approvals</h1>
			<p class="mt-1 text-sm text-surface-500">Pending institutional threshold approvals</p>
		</div>
		<button
			class="rounded border border-surface-700 px-3 py-2 text-sm text-surface-200 hover:border-accent/60"
			type="button"
			onclick={loadApprovals}
		>
			Refresh
		</button>
	</div>

	{#if error}
		<div class="mt-4 border border-red-500/40 bg-red-950/30 px-3 py-2 text-sm text-red-200">{error}</div>
	{/if}

	{#if loading}
		<div class="mt-6 text-sm text-surface-500">Loading...</div>
	{:else if approvals.length === 0}
		<div class="mt-6 border border-surface-800 bg-surface-900 p-4 text-sm text-surface-400">
			No pending approvals.
		</div>
	{:else}
		<div class="mt-6 overflow-x-auto border border-surface-800">
			<table class="min-w-full text-left text-sm">
				<thead class="bg-surface-900 text-xs uppercase text-surface-500">
					<tr>
						<th class="px-3 py-2">Mutation</th>
						<th class="px-3 py-2">Threshold</th>
						<th class="px-3 py-2">Requester</th>
						<th class="px-3 py-2">Expires</th>
						<th class="px-3 py-2 text-right">Actions</th>
					</tr>
				</thead>
				<tbody>
					{#each approvals as approval (approval.id)}
						<tr class="border-t border-surface-800">
							<td class="px-3 py-2 text-surface-200">{approval.mutation_type}</td>
							<td class="px-3 py-2 text-surface-300">
								{approval.threshold_at_request} / {approval.threshold_config_value}
							</td>
							<td class="px-3 py-2 text-surface-400">{approval.requested_by}</td>
							<td class="px-3 py-2 text-surface-400">
								{new Date(approval.expires_at).toLocaleString()}
							</td>
							<td class="px-3 py-2">
								{#if canAct}
									<div class="flex justify-end gap-2">
										<button
											class="rounded border border-emerald-600 px-3 py-1 text-emerald-200 hover:bg-emerald-950"
											type="button"
											onclick={() => grant(approval.id)}
										>
											Grant
										</button>
										<button
											class="rounded border border-red-600 px-3 py-1 text-red-200 hover:bg-red-950"
											type="button"
											onclick={() => {
												rejecting = approval.id;
												reasonText = '';
											}}
										>
											Reject
										</button>
									</div>
									{#if rejecting === approval.id}
										<div class="mt-2 flex justify-end gap-2">
											<input
												class="w-64 border border-surface-700 bg-surface-950 px-2 py-1 text-surface-200"
												bind:value={reasonText}
												placeholder="Reason"
											/>
											<button
												class="rounded border border-red-600 px-3 py-1 text-red-200 disabled:opacity-50"
												type="button"
												disabled={reasonText.trim().length < 8}
												onclick={() => reject(approval.id)}
											>
												Send
											</button>
										</div>
									{/if}
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>
