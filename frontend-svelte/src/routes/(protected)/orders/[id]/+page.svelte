<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatDate, formatQuantityMT, formatPrice } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { orderDetailPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import type { OrderRead } from '$lib/api/types/entities';

	// J-A6-08: read-only order detail surface. Shows enough canonical
	// fields for an auditor to reconstruct the exposure source record.

	type ViewState = 'loading' | 'ready' | 'error';

	let order = $state<OrderRead | null>(null);
	let viewState = $state<ViewState>('loading');
	let viewError = $state<string>('');
	let abortController: AbortController;

	const orderId = $derived(page.params.id ?? '');

	async function loadOrder(id: string, signal?: AbortSignal) {
		viewState = 'loading';
		try {
			const res = await apiFetch(orderDetailPath(id), { signal });
			if (res.ok) {
				order = await res.json();
				viewState = 'ready';
			} else {
				order = null;
				viewState = 'error';
				viewError = await describeApiError(res);
				notifications.error(`Order ${id}: ${viewError}`);
			}
		} catch (e) {
			if (e instanceof DOMException && e.name === 'AbortError') return;
			order = null;
			viewState = 'error';
			viewError = e instanceof Error ? e.message : 'Erro de conexão';
			notifications.error('Erro ao carregar order');
		}
	}

	onMount(() => {
		abortController = new AbortController();
		if (orderId) loadOrder(orderId, abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });
</script>

<div class="p-6 max-w-4xl">
	<div class="flex items-center gap-3">
		<a href="/orders" class="text-surface-500 hover:text-surface-300">← Voltar</a>
		<h1 class="text-lg font-semibold text-surface-200">Order</h1>
		{#if order}
			<span class="font-mono text-xs text-surface-500">{order.id}</span>
		{/if}
	</div>

	{#if viewState === 'loading'}
		<div class="mt-4 text-surface-500">Carregando...</div>
	{:else if viewState === 'error'}
		<div
			class="mt-4 rounded border border-danger/40 bg-danger/10 px-3 py-2 text-sm text-danger"
			data-testid="order-detail-error"
		>
			Erro ao carregar order: {viewError}
		</div>
	{:else if order}
		<div class="mt-4 grid grid-cols-2 gap-3" data-testid="order-detail">
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Tipo</div>
				<div class="text-sm font-semibold text-surface-200">
					{order.order_type === 'SO' ? 'Sales Order' : 'Purchase Order'}
				</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Commodity</div>
				<div class="text-sm font-semibold text-surface-200">{order.commodity}</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Quantidade (MT)</div>
				<div class="text-sm font-semibold tabular-nums text-surface-200" data-testid="order-detail-quantity">
					{formatQuantityMT(order.quantity_mt)}
				</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Pricing</div>
				<div class="text-sm text-surface-200">
					{order.price_type}{order.pricing_convention ? ` · ${order.pricing_convention}` : ''}
				</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Preço médio</div>
				<div class="text-sm tabular-nums text-surface-200">
					{order.avg_entry_price != null
						? formatPrice(order.avg_entry_price, `${order.currency}/MT`)
						: '—'}
				</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Moeda</div>
				<div class="text-sm text-surface-200">{order.currency}</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Contraparte</div>
				<div class="text-sm text-surface-200">{order.counterparty_name ?? '—'}</div>
				{#if order.counterparty_id}
					<div class="font-mono text-xs text-surface-500">{order.counterparty_id}</div>
				{/if}
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3">
				<div class="text-xs text-surface-500">Pagamento</div>
				<div class="text-sm text-surface-200">
					{order.payment_terms_days != null ? `${order.payment_terms_days} dias` : '—'}
				</div>
			</div>
			<div class="rounded border border-surface-800 bg-surface-900 p-3 col-span-2">
				<div class="text-xs text-surface-500">Janela de entrega</div>
				<div class="text-sm text-surface-200">
					{order.delivery_date_start ? formatDate(order.delivery_date_start) : '—'}
					{#if order.delivery_date_end} → {formatDate(order.delivery_date_end)}{/if}
					{#if order.delivery_terms} · <span class="text-surface-400">{order.delivery_terms}</span>{/if}
				</div>
			</div>
			{#if order.reference_month}
				<div class="rounded border border-surface-800 bg-surface-900 p-3">
					<div class="text-xs text-surface-500">Mês de referência (AVG)</div>
					<div class="text-sm text-surface-200">{order.reference_month}</div>
				</div>
			{/if}
			{#if order.fixing_date}
				<div class="rounded border border-surface-800 bg-surface-900 p-3">
					<div class="text-xs text-surface-500">Fixing (C2R)</div>
					<div class="text-sm text-surface-200">{formatDate(order.fixing_date)}</div>
				</div>
			{/if}
			{#if order.observation_date_start}
				<div class="rounded border border-surface-800 bg-surface-900 p-3 col-span-2">
					<div class="text-xs text-surface-500">Janela de observação (AVGInter)</div>
					<div class="text-sm text-surface-200">
						{formatDate(order.observation_date_start)}
						{#if order.observation_date_end} → {formatDate(order.observation_date_end)}{/if}
					</div>
				</div>
			{/if}
			{#if order.notes}
				<div class="rounded border border-surface-800 bg-surface-900 p-3 col-span-2">
					<div class="text-xs text-surface-500">Notas</div>
					<pre class="mt-1 whitespace-pre-wrap text-sm text-surface-300">{order.notes}</pre>
				</div>
			{/if}
			<div class="rounded border border-surface-800 bg-surface-900 p-3 col-span-2 text-xs text-surface-500">
				Criado em {formatDate(order.created_at)}
				{#if order.deleted_at} · <span class="text-warning">Arquivado em {formatDate(order.deleted_at)}</span>{/if}
			</div>
		</div>
	{/if}
</div>
