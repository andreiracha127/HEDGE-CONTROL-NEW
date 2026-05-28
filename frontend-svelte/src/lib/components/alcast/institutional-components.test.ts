import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/svelte';
import PageHeader from './PageHeader.svelte';
import EmptyState from './EmptyState.svelte';
import ToastStack from './ToastStack.svelte';
import Topbar from './Topbar.svelte';
import DecisionDossier from './DecisionDossier.svelte';
import ExecutionTimeline from './ExecutionTimeline.svelte';
import type { Notification } from '$lib/stores/notifications.svelte';

describe('institutional foundation components', () => {
	it('renders a page header with eyebrow, title, subtitle, metadata, and actions', () => {
		render(PageHeader, {
			props: {
				eyebrow: 'Trading desk',
				title: 'Scenario lab',
				subtitle: 'Stress tests for active exposures',
				meta: ['As of 27/05/2026', 'Risk manager'],
				actions: [
					{ label: 'Refresh', icon: 'refresh', variant: 'secondary' },
					{ label: 'Export', icon: 'download', variant: 'primary' },
				],
			},
		});

		expect(screen.getByText('Trading desk')).toBeInTheDocument();
		expect(screen.getByRole('heading', { name: 'Scenario lab' })).toBeInTheDocument();
		expect(screen.getByText('Stress tests for active exposures')).toBeInTheDocument();
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

	it('opens a command center from the topbar search trigger', async () => {
		render(Topbar, { props: { crumbs: ['Hedge Control', 'Visão geral'] } });

		await fireEvent.click(screen.getByRole('button', { name: /Buscar/i }));

		expect(screen.getByRole('dialog', { name: /Command center/i })).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /Nova RFQ/i })).toHaveAttribute('href', '/rfq/new');
		expect(screen.getByRole('link', { name: /Auditoria/i })).toHaveAttribute('href', '/audit');
	});

	it('renders a decision dossier with verdict and governed facts', () => {
		render(DecisionDossier, {
			props: {
				title: 'Award dossier',
				verdict: 'Ready to award',
				verdictKind: 'pos',
				items: [
					{ label: 'Best quote', value: '2,645.50' },
					{ label: 'Maker-checker', value: 'Risk Manager' },
				],
			},
		});

		expect(screen.getByText('Award dossier')).toBeInTheDocument();
		expect(screen.getByText('Ready to award')).toBeInTheDocument();
		expect(screen.getByText('Best quote')).toBeInTheDocument();
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
