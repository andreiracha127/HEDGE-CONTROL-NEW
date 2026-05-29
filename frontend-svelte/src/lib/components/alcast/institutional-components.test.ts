import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/svelte';
import PageHeader from './PageHeader.svelte';
import EmptyState from './EmptyState.svelte';
import ToastStack from './ToastStack.svelte';
import Topbar from './Topbar.svelte';
import DecisionDossier from './DecisionDossier.svelte';
import ExecutionTimeline from './ExecutionTimeline.svelte';
import type { Notification } from '$lib/stores/notifications.svelte';

vi.mock('$lib/api/client', () => ({
	client: {
		GET: vi.fn(async (path: string) => {
			if (path === '/rfqs') {
				return {
					data: [{ id: 'rfq-1', rfq_number: 'RFQ-2026-001', counterparty_name: 'Marex', state: 'SENT' }],
				};
			}
			return { data: [] };
		}),
	},
}));

describe('institutional foundation components', () => {
	it('renders a page header with eyebrow, title, subtitle, metadata, and actions', () => {
		render(PageHeader, {
			props: {
				eyebrow: 'Trading desk',
				title: 'Laboratório de cenários',
				subtitle: 'Simulações para exposições ativas',
				meta: ['As of 27/05/2026', 'Risk manager'],
				actions: [
					{ label: 'Refresh', icon: 'refresh', variant: 'secondary' },
					{ label: 'Export', icon: 'download', variant: 'primary' },
				],
			},
		});

		expect(screen.getByText('Trading desk')).toBeInTheDocument();
		expect(screen.getByRole('heading', { name: 'Laboratório de cenários' })).toBeInTheDocument();
		expect(screen.getByText('Simulações para exposições ativas')).toBeInTheDocument();
		expect(screen.getByText('As of 27/05/2026')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Refresh/i })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /Export/i })).toBeInTheDocument();
	});

	it('renders an empty state with a primary action', () => {
		render(EmptyState, {
			props: {
				icon: 'doc',
				title: 'No audit events loaded',
				message: 'Adjust filters or refresh the ledger.',
				actionLabel: 'Refresh ledger',
				actionHref: '/audit',
			},
		});

		expect(screen.getByText('No audit events loaded')).toBeInTheDocument();
		expect(screen.getByText('Adjust filters or refresh the ledger.')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /Refresh ledger/i })).toHaveAttribute('href', '/audit');
	});

	it('renders actionable toast notifications and dispatches dismiss', async () => {
		const remove = vi.fn();
		const items: Notification[] = [
			{ id: 'n1', type: 'error', message: 'RFQ award failed' },
			{ id: 'n2', type: 'success', message: 'Audit hash verified' },
		];

		render(ToastStack, { props: { items, onRemove: remove } });

		expect(screen.getByRole('status', { name: /RFQ award failed/i })).toBeInTheDocument();
		expect(screen.getByRole('status', { name: /Audit hash verified/i })).toBeInTheDocument();

		await screen.getAllByRole('button', { name: /Dismiss/i })[0].click();
		expect(remove).toHaveBeenCalledWith('n1');
	});

	it('opens quick actions from the topbar action button', async () => {
		render(Topbar, { props: { crumbs: ['Hedge Control', 'Visão geral'], userRoles: ['trader', 'risk_manager', 'auditor'] } });

		await fireEvent.click(screen.getByRole('button', { name: /Ações rápidas/i }));

		expect(screen.getByRole('dialog', { name: /Ações rápidas/i })).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /Nova RFQ/i })).toHaveAttribute('href', '/rfq/new');
		expect(screen.getByRole('link', { name: /Auditoria/i })).toHaveAttribute('href', '/audit');
	});

	it('keeps the sidebar toggle in the topbar chrome with drawer semantics', async () => {
		const toggle = vi.fn();
		render(Topbar, {
			props: {
				crumbs: [{ label: 'Hedge Control', href: '/' }, { label: 'Visão geral' }],
				userRoles: ['risk_manager'],
				sidebarCollapsed: true,
				onSidebarToggle: toggle,
			},
		});

		const button = screen.getByRole('button', { name: /Expandir navegação/i });
		expect(button).toHaveAttribute('aria-controls', 'primary-navigation');
		expect(button).toHaveAttribute('aria-expanded', 'false');

		await fireEvent.click(button);
		expect(toggle).toHaveBeenCalledTimes(1);
	});

	it('separates global search from quick actions and makes breadcrumbs navigable', async () => {
		render(Topbar, {
			props: {
				crumbs: [
					{ label: 'Hedge Control', href: '/' },
					{ label: 'Análise', href: '/analytics' },
					{ label: 'MTM' },
				],
				userRoles: ['risk_manager'],
			},
		});

		expect(screen.getByRole('link', { name: 'Hedge Control' })).toHaveAttribute('href', '/');
		expect(screen.getByRole('link', { name: 'Análise' })).toHaveAttribute('href', '/analytics');
		expect(screen.getByText('MTM')).toHaveClass('cur');

		const search = screen.getByRole('searchbox', { name: /Busca global/i });
		await fireEvent.focus(search);
		expect(screen.queryByRole('dialog', { name: /Ações rápidas/i })).not.toBeInTheDocument();

		await fireEvent.input(search, { target: { value: 'rfq' } });
		expect(screen.getByRole('region', { name: /Resultados da busca/i })).toBeInTheDocument();
		await waitFor(() => expect(screen.getByRole('link', { name: /RFQ-2026-001/i })).toHaveAttribute('href', '/rfq/rfq-1'));

		await fireEvent.click(screen.getByRole('button', { name: /Ações rápidas/i }));
		expect(screen.getByRole('dialog', { name: /Ações rápidas/i })).toBeInTheDocument();
	});

	it('renders a decision dossier with verdict and governed facts', () => {
		render(DecisionDossier, {
			props: {
				title: 'Dossiê de adjudicação',
				verdict: 'Pronta para adjudicação',
				verdictKind: 'pos',
				items: [
					{ label: 'Melhor cotação', value: '2,645.50' },
					{ label: 'Alçada', value: 'Risk Manager' },
				],
			},
		});

		expect(screen.getByText('Dossiê de adjudicação')).toBeInTheDocument();
		expect(screen.getByText('Pronta para adjudicação')).toBeInTheDocument();
		expect(screen.getByText('Melhor cotação')).toBeInTheDocument();
		expect(screen.getByText('2,645.50')).toBeInTheDocument();
	});

	it('renders an execution timeline with empty-state fallback', () => {
		const { rerender } = render(ExecutionTimeline, {
			props: {
				events: [
					{ label: 'RFQ sent', time: '10:32', actor: 'system', kind: 'info' },
					{ label: 'Quote received', time: '10:41', actor: 'broker', kind: 'pos' },
				],
			},
		});

		expect(screen.getByText('RFQ sent')).toBeInTheDocument();
		expect(screen.getByText('Quote received')).toBeInTheDocument();

		rerender({ events: [], emptyTitle: 'No lifecycle events' });
		expect(screen.getByText('No lifecycle events')).toBeInTheDocument();
	});
});
