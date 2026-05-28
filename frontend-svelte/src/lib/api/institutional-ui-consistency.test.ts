import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';

function read(relativeUrl: string): string {
	return readFileSync(new URL(relativeUrl, import.meta.url), 'utf8');
}

describe('institutional UI consistency', () => {
	it('keeps high-value routes on the Alcast institutional design system', () => {
		const routeFiles = [
			'../../routes/(protected)/analytics/what-if/+page.svelte',
			'../../routes/(protected)/orders/[id]/+page.svelte',
			'../../routes/(public)/login/+page.svelte',
			'../../routes/(public)/sign-up/+page.svelte',
			'../../routes/+error.svelte',
			'../../routes/(protected)/rfq/[id]/+error.svelte',
		];

		for (const routeFile of routeFiles) {
			const source = read(routeFile);
			expect(source, routeFile).not.toMatch(/\b(?:text|bg|border)-gray-\d{2,3}\b/);
			expect(source, routeFile).not.toMatch(/\brounded\s+border\s+border-gray-\d{2,3}\b/);
		}
	});

	it('uses shared institutional shell components for headers, empty states, and notifications', () => {
		expect(read('../../routes/(protected)/analytics/what-if/+page.svelte')).toContain('PageHeader');
		expect(read('../../routes/(protected)/orders/[id]/+page.svelte')).toContain('PageHeader');
		expect(read('../../routes/(protected)/orders/[id]/+page.svelte')).toContain('EmptyState');
		expect(read('../../routes/+layout.svelte')).toContain('ToastStack');
		expect(read('../../routes/+layout.svelte')).not.toContain('notifications.items as notification');
	});

	it('keeps the shell usable on compact institutional workstations', () => {
		const css = read('../../app.css');
		expect(css).toContain('@media (max-width: 760px)');
		expect(css).toContain('.app { grid-template-columns: 1fr; }');
		expect(css).toContain('.sidebar { position: static; height: auto; }');
		expect(css).toContain('.detail-grid { grid-template-columns: 1fr; }');
		expect(css).toContain('.topbar { flex-wrap: wrap; height: auto; }');
	});

	it('keeps public auth panels within narrow mobile viewports', () => {
		const css = read('../../app.css');
		expect(css).toContain('.auth-panel { width: min(460px, calc(100vw - 32px));');
		expect(css).toContain('.auth-card, .auth-card > * { max-width: 100%; min-width: 0; }');
	});

	it('keeps audit ledger counts live instead of hardcoded', () => {
		const auditPage = read('../../routes/(protected)/audit/+page.svelte');
		expect(auditPage).toContain('PageHeader');
		expect(auditPage).toContain('EmptyState');
		expect(auditPage).not.toContain('1.247 eventos');
		expect(auditPage).not.toContain('total={1247}');
	});

	it('turns RFQ detail into an institutional award cockpit', () => {
		const rfqDetail = read('../../routes/(protected)/rfq/[id]/+page.svelte');
		expect(rfqDetail).toContain('PageHeader');
		expect(rfqDetail).toContain('DecisionDossier');
		expect(rfqDetail).toContain('ExecutionTimeline');
		expect(rfqDetail).toContain('quote-ladder');
		expect(rfqDetail).toContain('EmptyState');
		expect(rfqDetail).not.toContain('class="page-head"');
	});

	it('turns approvals into decision dossiers instead of generic action cards', () => {
		const approvals = read('../../routes/(protected)/workflow-approvals/+page.svelte');
		expect(approvals).toContain('PageHeader');
		expect(approvals).toContain('DecisionDossier');
		expect(approvals).toContain('EmptyState');
		expect(approvals).toContain('approval-decision-card');
		expect(approvals).not.toContain('class="page-head"');
		expect(approvals).not.toContain('Sem ação</button>');
	});

	it('turns contract detail into a settlement readiness cockpit', () => {
		const contractDetail = read('../../routes/(protected)/contracts/[id]/+page.svelte');
		expect(contractDetail).toContain('PageHeader');
		expect(contractDetail).toContain('DecisionDossier');
		expect(contractDetail).toContain('ExecutionTimeline');
		expect(contractDetail).toContain('settlement-readiness');
		expect(contractDetail).not.toContain('class="page-head"');
	});

	it('turns the protected overview into a risk command center', () => {
		const overview = read('../../routes/(protected)/+page.svelte');
		expect(overview).toContain('PageHeader');
		expect(overview).toContain('DecisionDossier');
		expect(overview).toContain('EmptyState');
		expect(overview).toContain('risk-command-center');
		expect(overview).not.toContain('class="page-head"');
		expect(overview).not.toContain('Sem atividade recente');
	});

	it('turns core operational lists into institutional blotters', () => {
		const blotters = [
			'../../routes/(protected)/rfq/+page.svelte',
			'../../routes/(protected)/orders/+page.svelte',
			'../../routes/(protected)/contracts/+page.svelte',
		];

		for (const routeFile of blotters) {
			const source = read(routeFile);
			expect(source, routeFile).toContain('PageHeader');
			expect(source, routeFile).toContain('EmptyState');
			expect(source, routeFile).toContain('institutional-blotter');
			expect(source, routeFile).not.toContain('class="page-head"');
			expect(source, routeFile).not.toContain('class="tbl-empty"');
		}
	});

	it('turns monitoring surfaces into institutional control panels', () => {
		const monitoringRoutes = [
			'../../routes/(protected)/cashflow/+page.svelte',
			'../../routes/(protected)/exposures/+page.svelte',
			'../../routes/(protected)/market-data/+page.svelte',
		];

		for (const routeFile of monitoringRoutes) {
			const source = read(routeFile);
			expect(source, routeFile).toContain('PageHeader');
			expect(source, routeFile).toContain('EmptyState');
			expect(source, routeFile).toContain('institutional-monitoring');
			expect(source, routeFile).not.toContain('class="page-head"');
			expect(source, routeFile).not.toContain('class="tbl-empty"');
		}
	});

	it('turns MTM and P&L analytics into institutional analytics surfaces', () => {
		const analyticsRoutes = [
			'../../routes/(protected)/analytics/mtm/+page.svelte',
			'../../routes/(protected)/analytics/pnl/+page.svelte',
		];

		for (const routeFile of analyticsRoutes) {
			const source = read(routeFile);
			expect(source, routeFile).toContain('PageHeader');
			expect(source, routeFile).toContain('EmptyState');
			expect(source, routeFile).toContain('institutional-analytics');
			expect(source, routeFile).not.toContain('class="page-head"');
			expect(source, routeFile).not.toContain('class="tbl-empty"');
			expect(source, routeFile).not.toContain('Sem deals no período');
			expect(source, routeFile).not.toContain('Sem contribuintes financeiros no período');
		}
	});

	it('turns counterparty list and onboarding into institutional relationship surfaces', () => {
		const counterpartyRoutes = [
			'../../routes/(protected)/counterparties/+page.svelte',
			'../../routes/(protected)/counterparties/new/+page.svelte',
		];

		for (const routeFile of counterpartyRoutes) {
			const source = read(routeFile);
			expect(source, routeFile).toContain('PageHeader');
			expect(source, routeFile).toContain('institutional-counterparty');
			expect(source, routeFile).not.toContain('class="page-head"');
		}

		expect(read('../../routes/(protected)/counterparties/+page.svelte')).toContain('EmptyState');
		expect(read('../../routes/(protected)/counterparties/+page.svelte')).not.toContain('class="tbl-empty"');
		expect(read('../../routes/(protected)/counterparties/new/+page.svelte')).toContain('DecisionDossier');
	});

	it('turns create and relationship detail workflows into institutional operating rooms', () => {
		const operatingRoutes = [
			'../../routes/(protected)/orders/new/+page.svelte',
			'../../routes/(protected)/rfq/new/+page.svelte',
			'../../routes/(protected)/counterparties/[id]/+page.svelte',
		];

		for (const routeFile of operatingRoutes) {
			const source = read(routeFile);
			expect(source, routeFile).toContain('PageHeader');
			expect(source, routeFile).toContain('DecisionDossier');
			expect(source, routeFile).not.toContain('class="page-head"');
		}

		expect(read('../../routes/(protected)/orders/new/+page.svelte')).toContain('institutional-order-entry');
		expect(read('../../routes/(protected)/rfq/new/+page.svelte')).toContain('institutional-rfq-entry');
		expect(read('../../routes/(protected)/counterparties/[id]/+page.svelte')).toContain('institutional-counterparty-detail');
	});

	it('uses institutional empty states in critical detail surfaces', () => {
		const detailRoutes = [
			'../../routes/(protected)/rfq/[id]/+page.svelte',
			'../../routes/(protected)/contracts/[id]/+page.svelte',
			'../../routes/(protected)/counterparties/[id]/+page.svelte',
		];

		for (const routeFile of detailRoutes) {
			const source = read(routeFile);
			expect(source, routeFile).toContain('EmptyState');
			expect(source, routeFile).not.toContain('class="tbl-empty"');
		}
	});
});
