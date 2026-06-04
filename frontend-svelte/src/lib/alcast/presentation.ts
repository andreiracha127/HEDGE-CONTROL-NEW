export type BadgeKind = 'neutral' | 'pos' | 'neg' | 'warn' | 'info';

export type BadgePresentation = {
	kind: BadgeKind;
	label: string;
};

type EntityLike = Record<string, unknown> | null | undefined;

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const CLERK_SUBJECT_RE = /^user_[A-Za-z0-9]+$/;
const API_PATH_RE = /^\/[A-Za-z0-9_/-]+$/;
const RAW_KEY_VALUE_RE = /\b(?:state|status|endpoint|payload|object_id|actor_subject)=/i;
const RAW_TECHNICAL_RE = /\b(?:backend|endpoint|payload|mtm_value|object_id|actor_subject|exposures\/list|exposures\/net)\b/i;
const FIELD_NAME_RE = /^[a-z][a-z0-9]*(?:_[a-z0-9]+)+$/;

const STATE_MAP: Record<string, BadgePresentation> = {
	CREATED: { kind: 'neutral', label: 'Criada' },
	SENT: { kind: 'info', label: 'Enviada' },
	QUOTED: { kind: 'pos', label: 'Cotada' },
	AWARDED: { kind: 'pos', label: 'Adjudicada' },
	CLOSED: { kind: 'neutral', label: 'Encerrada' },
	CANCELLED: { kind: 'neutral', label: 'Cancelada' },
	CANCELED: { kind: 'neutral', label: 'Cancelada' },
	ACTIVE: { kind: 'pos', label: 'Ativa' },
	PENDING: { kind: 'warn', label: 'Pendente' },
	REVIEW: { kind: 'warn', label: 'Em análise' },
	IN_REVIEW: { kind: 'warn', label: 'Em análise' },
	UNDER_REVIEW: { kind: 'warn', label: 'Em análise' },
	IN_ANALYSIS: { kind: 'warn', label: 'Em análise' },
	SUSPENDED: { kind: 'neg', label: 'Suspensa' },
	FILLED: { kind: 'pos', label: 'Liquidada' },
	PARTIAL: { kind: 'warn', label: 'Parcial' },
	SETTLED: { kind: 'neutral', label: 'Liquidada' },
	MATURING: { kind: 'warn', label: 'Vencendo' },
	PROJECTED: { kind: 'info', label: 'Projetada' },
	CONFIRMED: { kind: 'pos', label: 'Confirmada' },
	REJECTED: { kind: 'neg', label: 'Rejeitada' },
	APPROVED: { kind: 'pos', label: 'Aprovada' },
	EXPIRED: { kind: 'warn', label: 'Vencida' },
	BEST: { kind: 'pos', label: 'Melhor cotação' },
	VALID: { kind: 'pos', label: 'Válida' },
	INVALID: { kind: 'neg', label: 'Inválida' },
};

const AUDIT_ENTITY_TYPE_MAP: Record<string, string> = {
	counterparty: 'Contraparte',
	hedge_contract: 'Contrato',
	hedge_contract_settlement: 'Liquidação de contrato',
	order: 'Ordem',
	rfq: 'RFQ',
	rfq_quote: 'Cotação RFQ',
	deal: 'Negócio',
	deal_link: 'Vínculo de negócio',
	deal_pnl_snapshot: 'Snapshot de P&L do negócio',
	linkage: 'Vínculo',
	sopo_link: 'Vínculo SO/PO',
	exposure: 'Exposição',
	exposure_reconciliation: 'Reconciliação de exposição',
	mtm_snapshot: 'Snapshot de MTM',
	pl_snapshot: 'Snapshot de P&L',
	cash_settlement_price: 'Preço de liquidação',
	cashflow_baseline_snapshot: 'Baseline de caixa',
	finance_pipeline_run: 'Execução de pipeline',
	finance_pipeline_step: 'Etapa de pipeline',
	hedge_task: 'Tarefa de hedge',
	inbound_webhook_message: 'Mensagem recebida',
	workflow_approval_request: 'Solicitação de aprovação',
};

const RATING_MAP: Record<string, string> = {
	LOW: 'Baixo',
	MEDIUM: 'Médio',
	HIGH: 'Alto',
	INVESTMENT_GRADE: 'Investment grade',
	UNRATED: 'Não classificado',
};

const ACTION_MAP: Record<string, string> = {
	RFQ_SENT: 'RFQ enviada',
	RFQ_CREATE: 'RFQ criada',
	RFQ_CREATED: 'RFQ criada',
	RFQ_QUOTED: 'Cotação recebida',
	RFQ_AWARDED: 'RFQ adjudicada',
	RFQ_INVITATION_REJECTED: 'Convite recusado',
	ORDER_CREATE: 'Ordem criada',
	ORDER_CREATED: 'Ordem criada',
	ORDER_FILLED: 'Ordem liquidada',
	CONTRACT_CREATE: 'Contrato criado',
	CONTRACT_CREATED: 'Contrato criado',
	CONTRACT_SETTLED: 'Contrato liquidado',
	WORKFLOW_APPROVAL_REQUESTED: 'Aprovação solicitada',
	WORKFLOW_APPROVAL_GRANTED: 'Aprovação concedida',
	WORKFLOW_APPROVAL_REJECTED: 'Aprovação rejeitada',
};

function asText(value: unknown): string {
	return typeof value === 'string' ? value.trim() : value == null ? '' : String(value).trim();
}

export function isTechnicalValue(value: unknown): boolean {
	const text = asText(value);
	if (!text) return false;
	return (
		UUID_RE.test(text) ||
		CLERK_SUBJECT_RE.test(text) ||
		API_PATH_RE.test(text) ||
		RAW_KEY_VALUE_RE.test(text) ||
		RAW_TECHNICAL_RE.test(text) ||
		FIELD_NAME_RE.test(text)
	);
}

export function safeBusinessText(value: unknown, fallback = 'Indisponível'): string {
	const text = asText(value);
	if (!text || isTechnicalValue(text)) return fallback;
	return text;
}

export function stateBadge(value: unknown): BadgePresentation {
	const raw = asText(value);
	if (!raw) return { kind: 'neutral', label: 'Indisponível' };
	const key = raw.toUpperCase();
	const mapped = STATE_MAP[key];
	if (mapped) return mapped;
	if (isTechnicalValue(raw)) return { kind: 'neutral', label: 'Indisponível' };
	return { kind: 'neutral', label: 'Não classificado' };
}

export function ratingLabel(value: unknown): string {
	const raw = asText(value);
	if (!raw || raw === '—') return 'Não classificado';
	const mapped = RATING_MAP[raw.toUpperCase()];
	if (mapped) return mapped;
	if (isTechnicalValue(raw)) return 'Não classificado';
	return safeBusinessText(raw, 'Não classificado');
}

export function sourceLabel(value: unknown): string {
	const raw = asText(value).toLowerCase();
	if (!raw || RAW_TECHNICAL_RE.test(raw)) return 'Fonte indisponível';
	if (raw.includes('westmetall') || raw.includes('market')) return 'Fonte: Market Data';
	if (raw.includes('sap')) return 'Fonte: SAP';
	return `Fonte: ${safeBusinessText(value, 'Indisponível')}`;
}

export function displayActor(value: unknown, fallback = 'Sistema'): string {
	const text = asText(value);
	if (!text) return fallback;
	if (CLERK_SUBJECT_RE.test(text)) return 'Usuário autenticado';
	return safeBusinessText(text, fallback);
}

export function actionLabel(value: unknown): string {
	const raw = asText(value);
	if (!raw) return 'Evento registrado';
	const mapped = ACTION_MAP[raw.toUpperCase().replace(/[^A-Z0-9]+/g, '_')];
	if (mapped) return mapped;
	return safeBusinessText(raw, 'Evento registrado');
}

function entityTypeLabel(value: unknown): string {
	const raw = asText(value).toLowerCase();
	if (!raw) return '';
	const mapped = AUDIT_ENTITY_TYPE_MAP[raw];
	if (mapped) return mapped;
	const humanized = raw.replace(/_/g, ' ').trim();
	return humanized ? humanized.charAt(0).toUpperCase() + humanized.slice(1) : '';
}

// Audit ledger surface: auditors must keep the link between a signed event and
// the record it mutated. Unlike other surfaces we deliberately preserve the raw
// entity_id (it is the reconstruction/filter key), prefixed by a business label
// for the entity_type.
export function auditEntityLabel(
	entityType: unknown,
	entityId: unknown,
	fallback = 'Registro operacional',
): string {
	const typeLabel = entityTypeLabel(entityType);
	const idText = asText(entityId);
	if (typeLabel && idText) return `${typeLabel} · ${idText}`;
	if (typeLabel) return typeLabel;
	if (idText) return idText;
	return fallback;
}

export function entityDisplayName(entity: EntityLike, fallback = 'Registro sem nome'): string {
	if (!entity) return fallback;
	const candidates = [
		entity.displayName,
		entity.display_name,
		entity.legal_name,
		entity.name,
		entity.short_name,
		entity.short,
		entity.counterparty_name,
		entity.counterparty_short,
		entity.rfq_number,
		entity.contract_number,
		entity.order_number,
		entity.primary_email,
		entity.email,
	];
	for (const candidate of candidates) {
		const label = safeBusinessText(candidate, '');
		if (label) return label;
	}
	return fallback;
}

export function directionLabel(value: unknown): string {
	const normalized = asText(value).toLowerCase();
	if (['buy', 'purchase', 'po', 'long', 'in'].includes(normalized)) return 'Compra';
	if (['sell', 'sales', 'so', 'short', 'out'].includes(normalized)) return 'Venda';
	return 'Não informado';
}
