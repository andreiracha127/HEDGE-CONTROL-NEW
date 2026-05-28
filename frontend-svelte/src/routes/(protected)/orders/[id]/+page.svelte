<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { page } from '$app/state';
	import { notifications } from '$lib/stores/notifications.svelte';
	import { formatDate, formatQuantityMT, formatPrice } from '$lib/utils/format';
	import { apiFetch } from '$lib/api/fetch';
	import { orderDetailPath } from '$lib/api/paths';
	import { describeApiError } from '$lib/api/errors';
	import Card from '$lib/components/alcast/Card.svelte';
	import Badge from '$lib/components/alcast/Badge.svelte';
	import EmptyState from '$lib/components/alcast/EmptyState.svelte';
	import PageHeader from '$lib/components/alcast/PageHeader.svelte';
	import type { OrderRead } from '$lib/api/types/entities';

	type ViewState = 'loading' | 'ready' | 'error';

	let order = $state<OrderRead | null>(null);
	let viewState = $state<ViewState>('loading');
	let viewError = $state<string>('');
	let abortController: AbortController;

	const orderId = $derived(page.params.id ?? '');
	const orderTypeLabel = $derived(order?.order_type === 'SO' ? 'Sales Order' : 'Purchase Order');
	const headerMeta = $derived([
		order?.commodity ?? 'Commodity pendente',
		order ? `${formatQuantityMT(order.quantity_mt)} MT` : 'Quantidade pendente',
		order?.counterparty_name ?? 'Contraparte não vinculada',
	]);

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

	function retry() {
		if (orderId) loadOrder(orderId, abortController?.signal);
	}

	onMount(() => {
		abortController = new AbortController();
		if (orderId) loadOrder(orderId, abortController.signal);
	});

	onDestroy(() => { abortController?.abort(); });
</script>

<div class="page">
	<PageHeader
		eyebrow="Fonte de exposição"
		title={order ? orderTypeLabel : 'Order'}
		subtitle={order ? `Registro canônico ${order.id}` : `Carregando ${orderId}`}
		meta={headerMeta}
		actions={[
			{ label: 'Voltar', icon: 'arrowLeft', variant: 'secondary', href: '/orders' },
			{ label: 'Recarregar', icon: 'refresh', variant: 'secondary', onclick: retry },
		]}
	/>

	{#if viewState === 'loading'}
		<Card>
			<EmptyState icon="refresh" title="Carregando order" message="Buscando o registro canônico e seus campos auditáveis." />
		</Card>
	{:else if viewState === 'error'}
		<Card>
			<EmptyState
				icon="info"
				title="Erro ao carregar order"
				message={viewError}
				actionLabel="Tentar novamente"
				onAction={retry}
			/>
		</Card>
	{:else if order}
		<div class="detail-grid" data-testid="order-detail">
			<div class="stack gap-4">
				<Card title="Termos comerciais" sub="Campos originais usados para reconstruir a exposição">
					<dl class="kv" style="grid-template-columns: 180px 1fr 180px 1fr;">
						<dt>Tipo</dt><dd><Badge kind={order.order_type === 'SO' ? 'pos' : 'info'}>{orderTypeLabel}</Badge></dd>
						<dt>Commodity</dt><dd>{order.commodity}</dd>
						<dt>Quantidade</dt><dd class="tabular strong" data-testid="order-detail-quantity">{formatQuantityMT(order.quantity_mt)} MT</dd>
						<dt>Moeda</dt><dd>{order.currency}</dd>
						<dt>Pricing</dt><dd>{order.price_type}{order.pricing_convention ? ` · ${order.pricing_convention}` : ''}</dd>
						<dt>Preço médio</dt>
						<dd class="tabular">
							{order.avg_entry_price != null ? formatPrice(order.avg_entry_price, `${order.currency}/MT`) : '—'}
						</dd>
						<dt>Contraparte</dt><dd>{order.counterparty_name ?? '—'}</dd>
						<dt>ID contraparte</dt><dd class="mono">{order.counterparty_id ?? '—'}</dd>
						<dt>Pagamento</dt><dd>{order.payment_terms_days != null ? `${order.payment_terms_days} dias` : '—'}</dd>
						<dt>Criado em</dt><dd>{formatDate(order.created_at)}</dd>
					</dl>
				</Card>

				<Card title="Janela de entrega" sub="Período operacional que alimenta o cálculo de exposição">
					<dl class="kv">
						<dt>Início</dt><dd>{order.delivery_date_start ? formatDate(order.delivery_date_start) : '—'}</dd>
						<dt>Fim</dt><dd>{order.delivery_date_end ? formatDate(order.delivery_date_end) : '—'}</dd>
						<dt>Termos</dt><dd>{order.delivery_terms ?? '—'}</dd>
						<dt>Reference month</dt><dd>{order.reference_month ?? '—'}</dd>
						<dt>Fixing</dt><dd>{order.fixing_date ? formatDate(order.fixing_date) : '—'}</dd>
					</dl>
				</Card>

				{#if order.observation_date_start || order.observation_date_end}
					<Card title="Janela de observação">
						<dl class="kv">
							<dt>Início</dt><dd>{formatDate(order.observation_date_start)}</dd>
							<dt>Fim</dt><dd>{formatDate(order.observation_date_end)}</dd>
						</dl>
					</Card>
				{/if}
			</div>

			<div class="stack gap-4">
				<Card title="Governança">
					<dl class="kv">
						<dt>Origem</dt><dd>Order book</dd>
						<dt>Status</dt><dd><Badge kind={order.deleted_at ? 'warn' : 'pos'} dot>{order.deleted_at ? 'Arquivada' : 'Ativa'}</Badge></dd>
						<dt>Arquivada em</dt><dd>{order.deleted_at ? formatDate(order.deleted_at) : '—'}</dd>
					</dl>
				</Card>

				<Card title="Notas internas">
					{#if order.notes}
						<pre class="notes-block">{order.notes}</pre>
					{:else}
						<EmptyState
							icon="doc"
							title="Sem notas"
							message="Nenhuma observação interna foi registrada para esta order."
						/>
					{/if}
				</Card>
			</div>
		</div>
	{/if}
</div>
