import { describe, expect, it } from 'vitest';
import {
	actionLabel,
	displayActor,
	entityDisplayName,
	ratingLabel,
	safeBusinessText,
	sourceLabel,
	stateBadge,
} from './presentation';

describe('institutional presentation helpers', () => {
	it('translates operational states and ratings into business language', () => {
		expect(stateBadge('SENT')).toMatchObject({ label: 'Enviada', kind: 'info' });
		expect(stateBadge('QUOTED')).toMatchObject({ label: 'Cotada', kind: 'pos' });
		expect(stateBadge('under_review')).toMatchObject({ label: 'Em análise', kind: 'warn' });
		expect(actionLabel('rfq.create')).toBe('RFQ criada');
		expect(ratingLabel('low')).toBe('Baixo');
		expect(ratingLabel('medium')).toBe('Médio');
	});

	it('never returns raw backend-shaped values for unknown display text', () => {
		expect(stateBadge('state=SENT')).toMatchObject({ label: 'Indisponível', kind: 'neutral' });
		expect(safeBusinessText('/rfqs', 'Sem referência')).toBe('Sem referência');
		expect(safeBusinessText('mtm_value', 'Sem marcação')).toBe('Sem marcação');
		expect(safeBusinessText('9e2555f8-f29f-4e1c-9825-b4c5c8a13c12', 'Sem identificação')).toBe('Sem identificação');
	});

	it('uses institutional fallbacks for entity and actor identity', () => {
		expect(entityDisplayName({ id: '9e2555f8-f29f-4e1c-9825-b4c5c8a13c12' }, 'Contraparte sem nome')).toBe(
			'Contraparte sem nome',
		);
		expect(displayActor('user_3DlOwTmAbFZHTBxt5NU30jemklp')).toBe('Usuário autenticado');
		expect(displayActor('ana.risk@alcast.example')).toBe('ana.risk@alcast.example');
	});

	it('normalizes source labels without exposing transport details', () => {
		expect(sourceLabel('westmetall')).toBe('Fonte: Market Data');
		expect(sourceLabel('backend source')).toBe('Fonte indisponível');
	});
});
