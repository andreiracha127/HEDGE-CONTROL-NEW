/**
 * Runtime validators for analytics snapshot response shapes (J-A6-03).
 *
 * The /pl/snapshots and /mtm/snapshots endpoints return single scalar
 * snapshot objects whose Decimal-typed columns serialise as strings. The
 * frontend used to apply `?? 0` and alternate-field-name fallbacks; that
 * silently rendered absent financial values as zero — institutional data
 * being substituted with display defaults.
 *
 * These validators reject responses where any required field is absent
 * (key undefined), or where a non-nullable required field is `null`. The
 * generated schema dictates which fields are nullable:
 *
 *   - PLSnapshotResponse.correlation_id: string | null  → null permitted
 *   - MTMSnapshotResponse.correlation_id: string         → null forbidden
 *
 * All other listed fields are non-nullable per the OpenAPI schema. True
 * backend zero values are *not* malformed — `0` and `"0"` are valid
 * Decimal serialisations and must pass through, so the check is presence
 * + non-null rather than truthiness.
 */
import type { PnlSnapshot, MtmSnapshot } from './types/entities';

export type ValidationResult<T> =
	| { ok: true; value: T }
	| { ok: false; missing: string[] };

interface FieldSpec {
	readonly key: string;
	readonly nullable: boolean;
}

const PNL_REQUIRED: ReadonlyArray<FieldSpec> = [
	{ key: 'id', nullable: false },
	{ key: 'entity_type', nullable: false },
	{ key: 'entity_id', nullable: false },
	{ key: 'period_start', nullable: false },
	{ key: 'period_end', nullable: false },
	{ key: 'realized_pl', nullable: false },
	{ key: 'unrealized_mtm', nullable: false },
	{ key: 'created_at', nullable: false },
	// schema-permitted: PLSnapshotResponse.correlation_id is `string | null`.
	{ key: 'correlation_id', nullable: true },
];

const MTM_REQUIRED: ReadonlyArray<FieldSpec> = [
	{ key: 'id', nullable: false },
	{ key: 'object_type', nullable: false },
	{ key: 'object_id', nullable: false },
	{ key: 'as_of_date', nullable: false },
	{ key: 'quantity_mt', nullable: false },
	{ key: 'entry_price', nullable: false },
	{ key: 'price_d1', nullable: false },
	{ key: 'mtm_value', nullable: false },
	{ key: 'created_at', nullable: false },
	// MTMSnapshotResponse.correlation_id is `string` (not nullable).
	{ key: 'correlation_id', nullable: false },
];

function collectMissing(
	body: unknown,
	required: ReadonlyArray<FieldSpec>,
): string[] {
	if (!body || typeof body !== 'object') return required.map((f) => f.key);
	const record = body as Record<string, unknown>;
	const missing: string[] = [];
	for (const { key, nullable } of required) {
		const present = Object.prototype.hasOwnProperty.call(record, key);
		if (!present || record[key] === undefined) {
			missing.push(key);
			continue;
		}
		if (record[key] === null && !nullable) missing.push(key);
	}
	return missing;
}

function periodOrderValid(
	body: unknown,
): { ok: true } | { ok: false; reason: string } {
	const record = body as { period_start?: unknown; period_end?: unknown };
	const start =
		typeof record.period_start === 'string' ? record.period_start : '';
	const end = typeof record.period_end === 'string' ? record.period_end : '';
	// ISO date strings (YYYY-MM-DD) sort lexicographically the same as
	// calendar order; same for full ISO datetimes. A reversed window is
	// malformed data regardless of which field is the bug.
	if (start && end && start > end) {
		return {
			ok: false,
			reason: `period_start (${start}) > period_end (${end})`,
		};
	}
	return { ok: true };
}

export function validatePnlSnapshot(
	body: unknown,
): ValidationResult<PnlSnapshot> {
	const missing = collectMissing(body, PNL_REQUIRED);
	if (missing.length > 0) return { ok: false, missing };
	const ordering = periodOrderValid(body);
	if (!ordering.ok) return { ok: false, missing: [ordering.reason] };
	return { ok: true, value: body as PnlSnapshot };
}

export function validateMtmSnapshot(
	body: unknown,
): ValidationResult<MtmSnapshot> {
	const missing = collectMissing(body, MTM_REQUIRED);
	if (missing.length > 0) return { ok: false, missing };
	return { ok: true, value: body as MtmSnapshot };
}
