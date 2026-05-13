<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatDate, formatQuantityMT, formatPrice } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { ordersListPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import type { OrderRead } from '$lib/api/types/entities';

	// J-A6-08: read-only orders surface. The page exists so auditors and
	// risk managers can reconstruct exposure source records — mutations
	// (create/archive/link) are intentionally out of scope for PR-A6-4.

	type ViewState = 'loading' | 'ready' | 'error';

	let orders = $state<OrderRead[]>([]);
	let nextCursor = $state<string | null>(null);
	let viewState = $state<ViewState>('loading');
	let viewError = $state<string>('');
	let abortController: AbortController;

	async function loadOrders(signal?: AbortSignal) {
		viewState = 'loading';
		try {
			const res = await apiFetch(ordersListPath({ limit: 50 }), { signal });
			if (res.ok) {
				const body = await res.json();
				orders = Array.isArray(body?.items) ? body.items : [];
				nextCursor = typeof body?.next_cursor === 'string' ? body.next_cursor : null;
				viewState = 'ready';
			} else {
				orders = [];
				viewState = 'error';
				viewError = await describeApiError(res);
				notifications.error(`Orders: ${viewError}`);
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			orders = [];
			viewState = 'error';
			viewError = e instanceof Error ? e.message : 'Erro de conexão';
			notifications.error('Erro ao carregar orders');
		}
	}

	function orderTypeLabel(t: OrderRead['order_type']): string {
		return t === 'SO' ? 'Sales Order' : 'Purchase Order';
	}

	function orderTypeColor(t: OrderRead['order_type']): string {
		return t === 'SO' ? 'text-success' : 'text-accent';
	}

	onMount(() => {
		abortController = new AbortController();
		loadOrders(abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });
</script>

<div class="p-6">
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-lg font-semibold text-surface-200">Orders</h1>
			<p class="mt-1 text-xs text-surface-500">
				Registros canônicos de pedidos (SO/PO) — fonte das exposições. Somente leitura.
			</p>
		</div>
	</div>

	{#if viewState === 'loading'}
		<div class="mt-4 text-surface-500">Carregando...</div>
	{:else if viewState === 'error'}
		<div
			class="mt-4 rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
			data-testid="orders-error"
		>
			Erro ao carregar orders: {viewError}
		</div>
	{:else if orders.length === 0}
		<div class="mt-4 text-surface-500" data-testid="orders-empty">Nenhuma order cadastrada</div>
	{:else}
		<div class="mt-4 overflow-x-auto rounded border border-surface-800" data-testid="orders-table">
			<table class="w-full text-sm">
				<thead>
					<tr class="border-b border-surface-800 bg-surface-900 text-left text-xs text-surface-500">
						<th class="px-3 py-2">Tipo</th>
						<th class="px-3 py-2">Commodity</th>
						<th class="px-3 py-2">Qty (MT)</th>
						<th class="px-3 py-2">Pricing</th>
						<th class="px-3 py-2">Preço (USD/MT)</th>
						<th class="px-3 py-2">Contraparte</th>
						<th class="px-3 py-2">Entrega</th>
						<th class="px-3 py-2">Criado</th>
						<th class="px-3 py-2"></th>
					</tr>
				</thead>
				<tbody>
					{#each orders as order (order.id)}
						<tr class="border-b border-surface-800/50 hover:bg-surface-900/30">
							<td class="px-3 py-2 text-xs font-semibold {orderTypeColor(order.order_type)}">
								{orderTypeLabel(order.order_type)}
							</td>
							<td class="px-3 py-2 text-surface-200">{order.commodity}</td>
							<td class="px-3 py-2 tabular-nums text-surface-200" data-testid="orders-quantity">
								{formatQuantityMT(order.quantity_mt)}
							</td>
							<td class="px-3 py-2 text-xs text-surface-400">
								{order.price_type}{order.pricing_convention ? ` · ${order.pricing_convention}` : ''}
							</td>
							<td class="px-3 py-2 tabular-nums text-surface-200">
								{order.avg_entry_price != null
									? formatPrice(order.avg_entry_price, `${order.currency}/MT`)
									: '—'}
							</td>
							<td class="px-3 py-2 text-surface-300 text-xs">
								{order.counterparty_name ?? '—'}
							</td>
							<td class="px-3 py-2 text-xs text-surface-400">
								{order.delivery_date_start ? formatDate(order.delivery_date_start) : '—'}
								{#if order.delivery_date_end} → {formatDate(order.delivery_date_end)}{/if}
							</td>
							<td class="px-3 py-2 text-xs text-surface-500">{formatDate(order.created_at)}</td>
							<td class="px-3 py-2">
								<a
									href={`/orders/${order.id}`}
									data-testid="orders-detail-link"
									class="text-xs text-accent hover:underline"
								>
									Detalhe →
								</a>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>

		{#if nextCursor}
			<p class="mt-3 text-xs text-surface-500" data-testid="orders-next-cursor">
				Cursor de próxima página disponível (paginação cursor-based, não implementada nesta wave).
			</p>
		{/if}
	{/if}
</div>
