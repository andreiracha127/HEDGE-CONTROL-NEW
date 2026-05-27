/**
 * Institutional RFQ create flow regression guard.
 *
 * The create page must keep the bank/broker-ready text builder controls:
 * trade type, LME price-type nomenclature, directional templates, and
 * bilingual preview text from `/rfqs/preview-text`. These are source-scan
 * assertions because the page currently has no component-level harness.
 */
// @vitest-environment node
// @ts-nocheck
import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const RFQ_NEW = resolve(
	process.cwd(),
	'src',
	'routes',
	'(protected)',
	'rfq',
	'new',
	'+page.svelte',
);

function readRfqNew(): string {
	return readFileSync(RFQ_NEW, 'utf8');
}

describe('RFQ create page — institutional bank/broker text model', () => {
	const source = readRfqNew();

	it('exposes the institutional trade model controls and LME price-type names', () => {
		expect(source).toMatch(/tradeType\s*=\s*\$state<['"][^>]*Swap[^>]*Forward/);
		expect(source).toContain('<option value="Swap">Swap</option>');
		expect(source).toContain('<option value="Forward">Forward</option>');
		expect(source).toContain('<option value="AVG">AVG</option>');
		expect(source).toContain('<option value="AVGInter">AVG Period</option>');
		expect(source).toContain('<option value="Fix">Fix</option>');
		expect(source).toContain('<option value="C2R">C2R</option>');
	});

	it('offers the expected bank-facing templates for common hedge intents', () => {
		expect(source).toMatch(/function\s+applyTemplate\s*\(/);
		expect(source).toContain("template: 'queda' | 'alta' | 'spread'");
		expect(source).toContain('Protecao de Queda');
		expect(source).toContain('Protecao de Alta');
		expect(source).toContain('Spread: Buy AVG + Sell AVG');
		expect(source).toContain('>Queda<');
		expect(source).toContain('>Alta<');
		expect(source).toContain('>Spread<');
	});

	it('sends the preview endpoint the RFQ engine leg payload instead of the simplified create payload', () => {
		const previewBlock = source.match(/async function loadPreview\(\)[\s\S]*?apiFetch\('\/rfqs\/preview-text'[\s\S]*?\}\);/);
		expect(previewBlock, 'loadPreview preview endpoint block must be present').toBeTruthy();
		expect(previewBlock![0]).toContain('trade_type: tradeType');
		expect(previewBlock![0]).toContain('leg1: buildLegPayload(trade.leg1)');
		expect(previewBlock![0]).toContain('company_header: companyLabel');
		expect(previewBlock![0]).toContain('body.leg2 = buildLegPayload(trade.leg2)');
		expect(previewBlock![0]).not.toContain('commodity,');
		expect(previewBlock![0]).not.toContain('intent,');
	});

	it('renders bilingual text preview and copy/share actions for bank and broker workflows', () => {
		expect(source).toMatch(/previewTextEn\s*=\s*\$state/);
		expect(source).toMatch(/previewTextPt\s*=\s*\$state/);
		expect(source).toContain('data.text_en');
		expect(source).toContain('data.text_pt');
		expect(source).toContain('English (LME)');
		expect(source).toContain('Portugues (Banco)');
		expect(source).toContain('Copiar EN');
		expect(source).toContain('Copiar PT');
		expect(source).toContain('whatsappShareUrl()');
	});

	it('keeps legacy RFQ ergonomics for dates, fixing inheritance, and side pairing', () => {
		expect(source).toMatch(/function\s+setLegSide\s*\(/);
		expect(source).toMatch(/function\s+oppositeSide\s*\(/);
		expect(source).toContain("trade[otherLeg].side = oppositeSide(side)");
		expect(source).toMatch(/function\s+syncFixingDatesFromVariableLeg\s*\(/);
		expect(source).toMatch(/function\s+lastBusinessDayOfMonthIso\s*\(/);
		expect(source).toContain("fixedLeg.fixingDate = lastBusinessDayOfMonthIso(variableLeg.year, monthIndex)");
		expect(source).toContain("fixedLeg.fixingDate = variableLeg.endDate");
		expect(source).toMatch(/function\s+isPastAverageMonth\s*\(/);
		expect(source).toContain('hidden={isPastAverageMonth(m, trade.leg1.year)}');
		expect(source).toContain('hidden={isPastAverageMonth(m, trade.leg2.year)}');
		expect(source).toContain('min={todayIso}');
		expect(source).toContain('readonly={isFixingDateInherited(trade.leg1)}');
		expect(source).toContain('readonly={isFixingDateInherited(trade.leg2)}');
	});

	it('does not duplicate RFQ composition fields in the setup section', () => {
		expect(source).not.toMatch(/let\s+direction\s*=\s*\$state/);
		expect(source).not.toMatch(/let\s+deliveryStart\s*=\s*\$state/);
		expect(source).not.toMatch(/let\s+deliveryEnd\s*=\s*\$state/);
		expect(source).not.toContain('id="direction"');
		expect(source).not.toContain('for="direction"');
		expect(source).not.toContain('Settlement Inicio');
		expect(source).not.toContain('Settlement Fim');
		expect(source).toMatch(/function\s+deriveRfqDirection\s*\(/);
		expect(source).toMatch(/function\s+deriveDeliveryWindow\s*\(/);
		expect(source).toContain('const deliveryWindow = deriveDeliveryWindow(trades[0])');
		expect(source).toContain('direction: deriveRfqDirection(trades[0])');
		expect(source).toContain('delivery_window_start: deliveryWindow.start');
		expect(source).toContain('delivery_window_end: deliveryWindow.end');
	});
});
