/**
 * Three-decimal MT quantity validator (J-A6-11).
 *
 * Backend `MTQuantity` is a Decimal with `MT_NUMERIC_SCALE = 3`
 * (`backend/app/core/precision.py`). The frontend form must accept the
 * same three-decimal precision, reject anything beyond it before the
 * preview/submit boundary, and emit the raw decimal string in payloads
 * so that no JS Number coercion truncates trailing digits.
 *
 * Accepted shapes: `123`, `123.4`, `123.45`, `123.456`. Leading zeros
 * are tolerated (`0.5`, `00.5`). Trailing/leading whitespace is trimmed
 * before validation; the *canonical* string preserved on the form is
 * the literal user input, so we keep `123.456` exactly as typed.
 */

export const MT_DECIMAL_SCALE = 3;

const QUANTITY_RE = new RegExp(`^\\d+(?:\\.\\d{1,${MT_DECIMAL_SCALE}})?$`);

export type QuantityValidation =
	| { ok: true; canonical: string }
	| { ok: false; reason: string };

export function validateMtQuantity(raw: string | null | undefined): QuantityValidation {
	if (raw == null) return { ok: false, reason: 'Quantidade obrigatória' };
	const trimmed = raw.trim();
	if (trimmed === '') return { ok: false, reason: 'Quantidade obrigatória' };
	// Reject scientific notation, signs, commas, anything beyond `\d.\d{0,3}`
	if (!QUANTITY_RE.test(trimmed)) {
		// Distinguish "extra decimals" from "garbage" so the user sees a
		// precise error message.
		if (/^\d+(?:\.\d+)?$/.test(trimmed)) {
			return {
				ok: false,
				reason: `Quantidade aceita no máximo ${MT_DECIMAL_SCALE} casas decimais (MT)`,
			};
		}
		return { ok: false, reason: 'Quantidade inválida' };
	}
	// Pure parse must produce a positive finite number; `0` and `0.000` are
	// not valid trade quantities.
	const n = Number(trimmed);
	if (!Number.isFinite(n) || n <= 0) {
		return { ok: false, reason: 'Quantidade deve ser maior que zero' };
	}
	return { ok: true, canonical: trimmed };
}
