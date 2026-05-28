/**
 * Alcast Hedge preview mock data — copied from
 * design-prototypes/hedge-control/project/mock.js. This is the design tool's
 * mocked dataset for the /preview route only. Real backend integration happens
 * when the design-port is promoted into the production protected routes.
 */

export interface Commodity {
	code: string;
	name: string;
	unit: string;
	last: number;
	prev: number;
}

export interface ExposureBucket {
	month: string;
	commercial_mt: number;
	hedged_mt: number;
	residual_mt: number;
	ratio: number;
}

export interface Counterparty {
	id: string;
	name: string;
	short: string;
	rating: string;
	limit: number;
	used: number;
	status: 'active' | 'review' | 'suspended';
}

export interface Rfq {
	id: string;
	commodity: string;
	qty: number;
	direction: 'BUY' | 'SELL';
	intent: 'COMMERCIAL_HEDGE' | 'GLOBAL_POSITION' | 'SPREAD';
	window: string;
	delivery_start: string;
	delivery_end: string;
	state: 'CREATED' | 'SENT' | 'QUOTED' | 'AWARDED' | 'CANCELLED';
	created: string;
	quotes: number;
	best: number | null;
	requester: string;
}

export interface Order {
	id: string;
	rfq: string;
	commodity: string;
	qty: number;
	direction: 'BUY' | 'SELL';
	price: number;
	cp: string;
	status: 'filled' | 'partial' | 'cancelled' | 'pending';
	traded: string;
	settlement: string | null;
}

export interface Contract {
	id: string;
	commodity: string;
	qty: number;
	type: 'Forward' | 'NDF' | 'Swap' | 'Asian Forward';
	fixed_leg: 'buy' | 'sell';
	var_leg: 'buy' | 'sell';
	price: number;
	cp: string;
	settle: string;
	mtm: number;
	status: 'active' | 'maturing' | 'settled' | 'cancelled';
}

export interface Cashflow {
	date: string;
	desc: string;
	cp: string;
	commodity: string;
	amount_usd: number;
	direction: 'in' | 'out';
	status: 'projected' | 'confirmed' | 'settled';
}

export interface AuditEvent {
	ts: string;
	user: string;
	role: string;
	action: string;
	entity: string;
	detail: string;
}

export interface Quote {
	cp: string;
	price: number | null;
	valid: string | null;
	spread: number | null;
	status: 'best' | 'received' | 'pending' | 'rejected';
	received: string | null;
}

export const commodities: Commodity[] = [
	{ code: 'AL-LME', name: 'Alumínio LME',     unit: 'USD/t',   last: 2645.5,  prev: 2632.0 },
	{ code: 'CU-LME', name: 'Cobre LME',        unit: 'USD/t',   last: 9412.0,  prev: 9485.5 },
	{ code: 'ZN-LME', name: 'Zinco LME',        unit: 'USD/t',   last: 2812.5,  prev: 2798.0 },
	{ code: 'USDBRL', name: 'Dólar comercial',  unit: 'BRL/USD', last: 5.124,   prev: 5.098  },
	{ code: 'NI-LME', name: 'Níquel LME',       unit: 'USD/t',   last: 16240.0, prev: 16380.0 },
];

export const exposureBuckets: ExposureBucket[] = [
	{ month: 'jun/26', commercial_mt: 4200, hedged_mt: 3700, residual_mt: 500,  ratio: 88.1 },
	{ month: 'jul/26', commercial_mt: 3800, hedged_mt: 2900, residual_mt: 900,  ratio: 76.3 },
	{ month: 'ago/26', commercial_mt: 4100, hedged_mt: 1600, residual_mt: 2500, ratio: 39.0 },
	{ month: 'set/26', commercial_mt: 3500, hedged_mt: 800,  residual_mt: 2700, ratio: 22.9 },
	{ month: 'out/26', commercial_mt: 3900, hedged_mt: 400,  residual_mt: 3500, ratio: 10.3 },
	{ month: 'nov/26', commercial_mt: 3700, hedged_mt: 0,    residual_mt: 3700, ratio: 0    },
	{ month: 'dez/26', commercial_mt: 3400, hedged_mt: 0,    residual_mt: 3400, ratio: 0    },
	{ month: 'jan/27', commercial_mt: 3200, hedged_mt: 0,    residual_mt: 3200, ratio: 0    },
];

export const counterparties: Counterparty[] = [
	{ id: 'CP-001', name: 'Itaú BBA',         short: 'ITAU', rating: 'AA',  limit: 12_000_000, used:  8_240_000, status: 'active' },
	{ id: 'CP-002', name: 'Banco Santander',  short: 'SANT', rating: 'AA-', limit:  9_000_000, used:  3_120_000, status: 'active' },
	{ id: 'CP-003', name: 'BTG Pactual',      short: 'BTG',  rating: 'A+',  limit:  8_500_000, used:  6_700_000, status: 'active' },
	{ id: 'CP-004', name: 'JPMorgan',         short: 'JPM',  rating: 'AA',  limit: 15_000_000, used: 11_900_000, status: 'active' },
	{ id: 'CP-005', name: 'Bradesco BBI',     short: 'BRAD', rating: 'AA-', limit:  7_000_000, used:  1_840_000, status: 'active' },
	{ id: 'CP-006', name: 'Citi Brasil',      short: 'CITI', rating: 'A+',  limit:  6_500_000, used:          0, status: 'review' },
	{ id: 'CP-007', name: 'XP Investimentos', short: 'XP',   rating: 'A',   limit:  4_000_000, used:    980_000, status: 'active' },
];

export const rfqs: Rfq[] = [
	{ id: 'RFQ-2026-0184', commodity: 'AL-LME', qty: 1200,      direction: 'BUY',  intent: 'COMMERCIAL_HEDGE', window: 'jun/26', delivery_start: '2026-06-01', delivery_end: '2026-06-30', state: 'QUOTED',  created: '2026-05-27 09:14', quotes: 4, best: 2638.5,  requester: 'M. Santos'    },
	{ id: 'RFQ-2026-0183', commodity: 'CU-LME', qty: 350,       direction: 'SELL', intent: 'GLOBAL_POSITION',  window: 'jul/26', delivery_start: '2026-07-01', delivery_end: '2026-07-31', state: 'SENT',    created: '2026-05-27 08:42', quotes: 2, best: 9418.0,  requester: 'L. Ferreira'  },
	{ id: 'RFQ-2026-0182', commodity: 'AL-LME', qty: 800,       direction: 'BUY',  intent: 'COMMERCIAL_HEDGE', window: 'jun/26', delivery_start: '2026-06-15', delivery_end: '2026-06-30', state: 'SENT',    created: '2026-05-26 17:20', quotes: 3, best: 2642.0,  requester: 'M. Santos'    },
	{ id: 'RFQ-2026-0181', commodity: 'USDBRL', qty: 2_500_000, direction: 'BUY',  intent: 'COMMERCIAL_HEDGE', window: 'jul/26', delivery_start: '2026-07-15', delivery_end: '2026-07-15', state: 'QUOTED',  created: '2026-05-26 14:55', quotes: 5, best: 5.1185,  requester: 'R. Almeida'   },
	{ id: 'RFQ-2026-0180', commodity: 'AL-LME', qty: 600,       direction: 'BUY',  intent: 'COMMERCIAL_HEDGE', window: 'ago/26', delivery_start: '2026-08-01', delivery_end: '2026-08-31', state: 'CREATED', created: '2026-05-26 11:08', quotes: 0, best: null,    requester: 'M. Santos'    },
	{ id: 'RFQ-2026-0179', commodity: 'ZN-LME', qty: 220,       direction: 'SELL', intent: 'GLOBAL_POSITION',  window: 'jul/26', delivery_start: '2026-07-01', delivery_end: '2026-07-15', state: 'QUOTED',  created: '2026-05-26 10:31', quotes: 3, best: 2810.0,  requester: 'L. Ferreira'  },
	{ id: 'RFQ-2026-0178', commodity: 'CU-LME', qty: 500,       direction: 'BUY',  intent: 'COMMERCIAL_HEDGE', window: 'jun/26', delivery_start: '2026-06-10', delivery_end: '2026-06-25', state: 'QUOTED',  created: '2026-05-26 09:18', quotes: 4, best: 9405.5,  requester: 'R. Almeida'   },
];

export const orders: Order[] = [
	{ id: 'ORD-2026-0419', rfq: 'RFQ-2026-0177', commodity: 'AL-LME', qty: 1500,      direction: 'BUY',  price: 2631.0,  cp: 'ITAU', status: 'filled',    traded: '2026-05-27 09:02', settlement: '2026-06-30' },
	{ id: 'ORD-2026-0418', rfq: 'RFQ-2026-0176', commodity: 'USDBRL', qty: 3_000_000, direction: 'BUY',  price: 5.1115,  cp: 'JPM',  status: 'filled',    traded: '2026-05-27 08:21', settlement: '2026-07-15' },
	{ id: 'ORD-2026-0417', rfq: 'RFQ-2026-0175', commodity: 'AL-LME', qty: 900,       direction: 'BUY',  price: 2628.5,  cp: 'SANT', status: 'partial',   traded: '2026-05-26 16:48', settlement: '2026-06-30' },
	{ id: 'ORD-2026-0416', rfq: 'RFQ-2026-0174', commodity: 'CU-LME', qty: 400,       direction: 'SELL', price: 9420.0,  cp: 'BTG',  status: 'filled',    traded: '2026-05-26 15:11', settlement: '2026-07-31' },
	{ id: 'ORD-2026-0415', rfq: 'RFQ-2026-0173', commodity: 'AL-LME', qty: 700,       direction: 'BUY',  price: 2640.25, cp: 'ITAU', status: 'filled',    traded: '2026-05-26 13:02', settlement: '2026-06-30' },
	{ id: 'ORD-2026-0414', rfq: 'RFQ-2026-0172', commodity: 'ZN-LME', qty: 180,       direction: 'SELL', price: 2805.5,  cp: 'JPM',  status: 'filled',    traded: '2026-05-26 10:45', settlement: '2026-07-15' },
	{ id: 'ORD-2026-0413', rfq: 'RFQ-2026-0171', commodity: 'AL-LME', qty: 1100,      direction: 'BUY',  price: 2618.0,  cp: 'BTG',  status: 'cancelled', traded: '2026-05-26 09:18', settlement: null         },
	{ id: 'ORD-2026-0412', rfq: 'RFQ-2026-0170', commodity: 'USDBRL', qty: 1_500_000, direction: 'BUY',  price: 5.092,   cp: 'BRAD', status: 'filled',    traded: '2026-05-25 17:12', settlement: '2026-06-30' },
];

export const contracts: Contract[] = [
	{ id: 'CT-2026-0118', commodity: 'AL-LME', qty: 1500,      type: 'Forward',       fixed_leg: 'buy',  var_leg: 'sell', price: 2631.0,  cp: 'ITAU', settle: '2026-06-30', mtm:  21450.0, status: 'active'   },
	{ id: 'CT-2026-0117', commodity: 'USDBRL', qty: 3_000_000, type: 'NDF',           fixed_leg: 'buy',  var_leg: 'sell', price: 5.1115,  cp: 'JPM',  settle: '2026-07-15', mtm:  37500.0, status: 'active'   },
	{ id: 'CT-2026-0116', commodity: 'AL-LME', qty: 900,       type: 'Forward',       fixed_leg: 'buy',  var_leg: 'sell', price: 2628.5,  cp: 'SANT', settle: '2026-06-30', mtm:  15300.0, status: 'active'   },
	{ id: 'CT-2026-0115', commodity: 'CU-LME', qty: 400,       type: 'Swap',          fixed_leg: 'sell', var_leg: 'buy',  price: 9420.0,  cp: 'BTG',  settle: '2026-07-31', mtm:   3200.0, status: 'active'   },
	{ id: 'CT-2026-0114', commodity: 'AL-LME', qty: 700,       type: 'Asian Forward', fixed_leg: 'buy',  var_leg: 'sell', price: 2640.25, cp: 'ITAU', settle: '2026-06-30', mtm:   3675.0, status: 'active'   },
	{ id: 'CT-2026-0113', commodity: 'ZN-LME', qty: 180,       type: 'Forward',       fixed_leg: 'sell', var_leg: 'buy',  price: 2805.5,  cp: 'JPM',  settle: '2026-07-15', mtm:  -1260.0, status: 'active'   },
	{ id: 'CT-2026-0112', commodity: 'USDBRL', qty: 1_500_000, type: 'NDF',           fixed_leg: 'buy',  var_leg: 'sell', price: 5.092,   cp: 'BRAD', settle: '2026-06-30', mtm:  48000.0, status: 'active'   },
	{ id: 'CT-2026-0111', commodity: 'AL-LME', qty: 2000,      type: 'Asian Forward', fixed_leg: 'buy',  var_leg: 'sell', price: 2602.0,  cp: 'JPM',  settle: '2026-06-15', mtm:  87000.0, status: 'maturing' },
	{ id: 'CT-2026-0110', commodity: 'AL-LME', qty: 1200,      type: 'Forward',       fixed_leg: 'buy',  var_leg: 'sell', price: 2655.0,  cp: 'BTG',  settle: '2026-05-29', mtm: -11400.0, status: 'maturing' },
];

export const cashflow: Cashflow[] = [
	{ date: '2026-05-29', desc: 'CT-2026-0110 · AL-LME · Liquidação',  cp: 'BTG',  commodity: 'AL-LME', amount_usd:  13800,  direction: 'in',  status: 'projected' },
	{ date: '2026-06-15', desc: 'CT-2026-0111 · AL-LME · Liquidação',  cp: 'JPM',  commodity: 'AL-LME', amount_usd:  87000,  direction: 'in',  status: 'projected' },
	{ date: '2026-06-30', desc: 'CT-2026-0118 · AL-LME · Liquidação',  cp: 'ITAU', commodity: 'AL-LME', amount_usd:  21450,  direction: 'in',  status: 'projected' },
	{ date: '2026-06-30', desc: 'CT-2026-0116 · AL-LME · Liquidação',  cp: 'SANT', commodity: 'AL-LME', amount_usd:  15300,  direction: 'in',  status: 'projected' },
	{ date: '2026-06-30', desc: 'CT-2026-0114 · AL-LME · Liquidação',  cp: 'ITAU', commodity: 'AL-LME', amount_usd:   3675,  direction: 'in',  status: 'projected' },
	{ date: '2026-06-30', desc: 'CT-2026-0112 · USDBRL · Liquidação',  cp: 'BRAD', commodity: 'USDBRL', amount_usd:  48000,  direction: 'in',  status: 'projected' },
	{ date: '2026-07-15', desc: 'CT-2026-0117 · USDBRL · Liquidação',  cp: 'JPM',  commodity: 'USDBRL', amount_usd:  37500,  direction: 'in',  status: 'projected' },
	{ date: '2026-07-15', desc: 'CT-2026-0113 · ZN-LME · Liquidação',  cp: 'JPM',  commodity: 'ZN-LME', amount_usd:  -1260,  direction: 'out', status: 'projected' },
	{ date: '2026-07-31', desc: 'CT-2026-0115 · CU-LME · Liquidação',  cp: 'BTG',  commodity: 'CU-LME', amount_usd:   3200,  direction: 'in',  status: 'projected' },
];

export const auditLog: AuditEvent[] = [
	{ ts: '2026-05-27 09:14:22', user: 'M. Santos',   role: 'Trader',      action: 'rfq.create',         entity: 'RFQ-2026-0184',     detail: 'AL-LME 1200t buy · jun/26' },
	{ ts: '2026-05-27 09:12:08', user: 'sistema',     role: 'System',      action: 'exposure.snapshot',  entity: 'EXP-2026-05-27-091200', detail: 'Snapshot diário consolidado' },
	{ ts: '2026-05-27 09:08:14', user: 'L. Ferreira', role: 'Risco',       action: 'limit.adjust',       entity: 'CP-006',            detail: 'Citi · revisão de limite (sob análise)' },
	{ ts: '2026-05-27 09:04:52', user: 'R. Almeida',  role: 'Tesouraria',  action: 'order.fill',         entity: 'ORD-2026-0419',     detail: 'AL-LME 1500t @ 2631.00 · ITAU' },
	{ ts: '2026-05-27 08:42:11', user: 'L. Ferreira', role: 'Risco',       action: 'rfq.create',         entity: 'RFQ-2026-0183',     detail: 'CU-LME 350t sell · jul/26' },
	{ ts: '2026-05-27 08:21:33', user: 'R. Almeida',  role: 'Tesouraria',  action: 'order.fill',         entity: 'ORD-2026-0418',     detail: 'USDBRL 3M @ 5.1115 · JPM' },
	{ ts: '2026-05-27 08:14:09', user: 'sistema',     role: 'System',      action: 'mktdata.refresh',    entity: 'MKT-2026-05-27',    detail: 'Cotações LME (open)' },
	{ ts: '2026-05-26 17:55:40', user: 'A. Costa',    role: 'Aprovador',   action: 'approval.confirm',   entity: 'APR-2026-0096',     detail: 'Aprovação CT-2026-0118' },
	{ ts: '2026-05-26 17:20:01', user: 'M. Santos',   role: 'Trader',      action: 'rfq.create',         entity: 'RFQ-2026-0182',     detail: 'AL-LME 800t buy · jun/26' },
	{ ts: '2026-05-26 16:48:22', user: 'R. Almeida',  role: 'Tesouraria',  action: 'order.partial',      entity: 'ORD-2026-0417',     detail: 'AL-LME 900t @ 2628.50 · SANT' },
];

export const sampleQuotes: Quote[] = [
	{ cp: 'ITAU', price: 2638.5,  valid: '2026-05-27 09:34', spread: 0,    status: 'best',     received: '09:18:42' },
	{ cp: 'JPM',  price: 2639.25, valid: '2026-05-27 09:35', spread: 0.75, status: 'received', received: '09:18:51' },
	{ cp: 'SANT', price: 2641.0,  valid: '2026-05-27 09:33', spread: 2.5,  status: 'received', received: '09:19:02' },
	{ cp: 'BTG',  price: 2642.75, valid: '2026-05-27 09:34', spread: 4.25, status: 'received', received: '09:19:14' },
	{ cp: 'BRAD', price: null,    valid: null,               spread: null, status: 'pending',  received: null       },
];

// ============================================================
// Display helpers (mirror mock.js fmt.* — pt-BR locale defaults)
// ============================================================

export function fmtUSD(n: number): string {
	return 'US$ ' + n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtBRL(n: number): string {
	return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function fmtMT(n: number): string {
	return n.toLocaleString('pt-BR', { maximumFractionDigits: 0 }) + ' t';
}

export function fmtPct(n: number): string {
	return n.toLocaleString('pt-BR', { maximumFractionDigits: 1, minimumFractionDigits: 1 }) + '%';
}

export function fmtNum(n: number, d = 2): string {
	return n.toLocaleString('pt-BR', { maximumFractionDigits: d, minimumFractionDigits: d });
}

// ============================================================
// State label helper used by tables
// ============================================================

export type StateMapKind = 'neutral' | 'pos' | 'neg' | 'warn' | 'info';

const STATE_MAP: Record<string, { kind: StateMapKind; label: string }> = {
	CREATED:   { kind: 'neutral', label: 'Criada' },
	SENT:      { kind: 'info',    label: 'Enviada' },
	QUOTED:    { kind: 'pos',     label: 'Cotada' },
	AWARDED:   { kind: 'pos',     label: 'Adjudicada' },
	CANCELLED: { kind: 'neutral', label: 'Cancelada' },
	filled:    { kind: 'pos',     label: 'Liquidada' },
	partial:   { kind: 'warn',    label: 'Parcial' },
	cancelled: { kind: 'neutral', label: 'Cancelada' },
	pending:   { kind: 'warn',    label: 'Pendente' },
	active:    { kind: 'pos',     label: 'Ativo' },
	maturing:  { kind: 'warn',    label: 'Vencendo' },
	settled:   { kind: 'neutral', label: 'Liquidado' },
	review:    { kind: 'warn',    label: 'Em análise' },
	projected: { kind: 'info',    label: 'Projetado' },
	confirmed: { kind: 'pos',     label: 'Confirmado' },
	suspended: { kind: 'neg',     label: 'Suspenso' },
};

export function stateLabel(state: string): { kind: StateMapKind; label: string } {
	return STATE_MAP[state] ?? { kind: 'neutral', label: state };
}
