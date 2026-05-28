import { describe, expect, it } from 'vitest';
import {
	exposureBucketsFrom,
	normalizeAuditEvent,
	normalizeCashflow,
	normalizeCommodity,
	normalizeContract,
	normalizeCounterparty,
	normalizeRfq,
	normalizeRfqQuote,
} from './route-data';

describe('exposureBucketsFrom', () => {
	it('normalizes live exposure-list rows into bucket-shaped numeric fields', () => {
		const buckets = exposureBucketsFrom({
			items: [
				{
					settlement_month: '2026-08',
					original_tons: '100.000',
					open_tons: '40.000',
					hedged_tons: '60.000',
				},
			],
		});

		expect(buckets).toEqual([
			expect.objectContaining({
				month: '2026-08',
				commercial_mt: 100,
				hedged_mt: 60,
				residual_mt: 40,
				ratio: 60,
			}),
		]);
	});

	it('converts fractional coverage ratios to display percentages', () => {
		const [bucket] = exposureBucketsFrom({
			items: [{ month: '2026-09', commercial_net_mt: '200.000', hedged_tons: '80.000', hedge_coverage_ratio: '0.4' }],
		});

		expect(bucket.ratio).toBe(40);
	});

	it('aggregates live exposure-list detail rows into one bucket per month', () => {
		const buckets = exposureBucketsFrom({
			items: [
				{ settlement_month: '2026-06', original_tons: '1000', hedged_tons: '250', open_tons: '750' },
				{ settlement_month: '2026-06', original_tons: '500', hedged_tons: '250', open_tons: '250' },
			],
		});

		expect(buckets).toHaveLength(1);
		expect(buckets[0]).toMatchObject({
			month: '2026-06',
			commercial_mt: 1500,
			hedged_mt: 500,
			residual_mt: 1000,
		});
		expect(buckets[0].ratio).toBeCloseTo(33.333, 3);
	});
});

describe('live API row normalizers', () => {
	it('coerces cashflow Decimal strings before UI aggregation', () => {
		expect(normalizeCashflow({ amount_usd: '125.50', cashflow_date: '2026-06-01' })).toMatchObject({
			amount_usd: 125.5,
			direction: 'in',
		});
		expect(normalizeCashflow({ amount_usd: '-10.00', cashflow_date: '2026-06-01' })).toMatchObject({
			amount_usd: -10,
			direction: 'out',
		});
	});

	it('maps projection settlement dates onto the rendered cashflow date field', () => {
		expect(normalizeCashflow({ amount_usd: '25.00', settlement_date: '2026-06-15' })).toMatchObject({
			date: '2026-06-15',
			amount_usd: 25,
		});
	});

	it('keeps missing contract MTM unavailable for the contracts table', () => {
		expect(normalizeContract({ quantity_mt: '100.000', fixed_price_value: '2638.50' })).toMatchObject({
			qty: 100,
			price: 2638.5,
			mtm: null,
		});
	});

	it('preserves live RFQ UUIDs while exposing rfq_number for display', () => {
		expect(normalizeRfq({ id: '1f5a2a6d-2d2c-4637-8277-672a6c2ab100', rfq_number: 'RFQ-2026-0007' })).toMatchObject({
			id: '1f5a2a6d-2d2c-4637-8277-672a6c2ab100',
			rfq: 'RFQ-2026-0007',
		});
	});

	it('preserves live counterparty UUIDs while exposing short_name for display', () => {
		expect(normalizeCounterparty({ id: '4d7a5353-9823-41a5-b63c-13f9a946c4c1', short_name: 'ITAU' })).toMatchObject({
			id: '4d7a5353-9823-41a5-b63c-13f9a946c4c1',
			short: 'ITAU',
		});
	});

	it('does not expose UUIDs, object ids, or Clerk subjects as display fallbacks', () => {
		expect(normalizeCounterparty({ id: '4d7a5353-9823-41a5-b63c-13f9a946c4c1' })).toMatchObject({
			short: 'Contraparte sem nome',
		});
		expect(normalizeCashflow({ object_type: 'cashflow', object_id: 'evt-raw-1', amount_usd: '10.00' })).toMatchObject({
			desc: 'Liquidação projetada',
		});
		expect(normalizeAuditEvent({ actor_subject: 'user_3DlOwTmAbFZHTBxt5NU30jemklp', event_type: 'rfq_sent' })).toMatchObject({
			user: 'Usuário autenticado',
		});
	});

	it('marks non-approved KYC counterparties as unavailable for RFQ selection', () => {
		expect(normalizeCounterparty({ kyc_status: 'pending', is_active: true })).toMatchObject({ status: 'review' });
		expect(normalizeCounterparty({ kyc_status: 'expired', is_active: true })).toMatchObject({ status: 'suspended' });
		expect(normalizeCounterparty({ kyc_status: 'rejected', is_active: true })).toMatchObject({ status: 'suspended' });
		expect(normalizeCounterparty({ kyc_status: 'approved', is_active: true })).toMatchObject({ status: 'active' });
	});

	it('keeps missing previous market prices unavailable instead of fabricating zero', () => {
		expect(normalizeCommodity({ symbol: 'AL-LME', price_usd: '2645.500000' })).toMatchObject({
			code: 'AL-LME',
			last: 2645.5,
			prev: null,
		});
	});

	it('maps RFQQuoteRead fields into table fields with a stable key and best flag', () => {
		expect(
			normalizeRfqQuote(
				{ id: 'q-1', counterparty_id: 'cp-1', fixed_price_value: '2638.50', received_at: '2026-05-27T12:00:00Z', state: 'active' },
				{ bestQuoteId: 'q-1', bestPrice: 2638.5 },
			),
		).toMatchObject({
			id: 'q-1',
			cp: 'Contraparte não informada',
			price: 2638.5,
			spread: 0,
			received: '2026-05-27T12:00:00Z',
			status: 'best',
		});
	});

	it('maps audit detail from payload instead of duplicating event_type', () => {
		expect(
			normalizeAuditEvent({
				event_type: 'rfq_invitation_rejected',
				entity_type: 'rfq',
				entity_id: 'rfq-1',
				timestamp_utc: '2026-05-27T12:00:00Z',
				payload: { detail: 'Counterparty declined quote' },
			}),
		).toMatchObject({
			action: 'Convite recusado',
			entity: 'RFQ · rfq-1',
			detail: 'Counterparty declined quote',
		});
	});
});
