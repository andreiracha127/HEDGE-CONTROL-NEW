# W4 — LEI Validation (GLEIF) Design

**Date:** 2026-05-31
**Wave:** W4 of the 7-wave commercial-partners/KYC effort (after W0 #111, W1 #112, W2 #113 — all merged to `main`). Sequenced ahead of W3 (RFQ-gate re-target); W4 depends only on W1.
**Branch:** `w4/lei-validation`
**Constitution:** `docs/governance.md` "LEI validation governance (binding)" (≈ lines 823-850).
**Predecessor spec:** `docs/superpowers/specs/2026-05-29-commercial-partners-kyc-separation-design.md` §5, §7 (`lei_validation`), §11 (W4 row).

## 1. Goal & boundary

A risk_manager/trader-triggered **LEI (Legal Entity Identifier, ISO 17442) validation** for `commercial_partners` only (customers + suppliers — LEI does not apply to hedge counterparties). LEI is OPTIONAL per partner and **WARN-NOT-BLOCK**: validation never blocks registration, order creation, KYC approval, or anything else. It only writes the informational `lei_status` / `lei_legal_name` / `lei_checked_at` fields and returns advisory warnings.

### Explicit non-goals (anti-scope)

- **No gate reads `lei_status`.** No gate (order, RFQ, KYC) hard-blocks on LEI — governance "LEI validation governance" + D5. This wave adds no gate logic.
- **No migration** — `lei`, `lei_status`, `lei_legal_name`, `lei_checked_at` columns and the `LeiStatus` enum `{not_provided, valid, invalid, lapsed, issued, error}` already exist on `CommercialPartner` from migration `049`.
- **No frontend** (W5). **No scheduled re-validation** — validation runs only on the manual endpoint (LEI is informational; governance does not mandate re-validation, and a stale LAPSED never gates anything).
- **No hedge-counterparty LEI** — `Counterparty` has no `lei` column; LEI is commercial-only.
- **No API key / boot validator** — the GLEIF API is public (no key), and LEI never blocks, so there is no fail-closed boot requirement (contrast `OPENSANCTIONS_API_KEY`).

### Components

**New:** `backend/app/services/gleif_client.py`, `backend/app/services/lei_validation_service.py`, `backend/app/schemas/lei.py` (`LeiValidationRead`).
**Modified:** `backend/app/api/routes/commercial_partners.py` (+`POST /{id}/validate-lei`), `backend/app/core/config.py` (`GLEIF_API_BASE_URL`), `frontend-svelte/src/lib/api/schema.d.ts` (regen for the new endpoint; `openapi_diff` CI gate).

Decomposition mirrors the W2 client/service/route split.

## 2. `gleif_client` (mockable I/O boundary)

`fetch_lei_record(lei: str) -> GleifRecord | None`

- `GET {GLEIF_API_BASE_URL}/lei-records/{lei}` (public, no auth header).
- Parses → `GleifRecord{registration_status: str, legal_name: str | None, legal_name_language: str | None, entity_status: str | None}` from the confirmed live shape: `data.attributes.registration.status`, `data.attributes.entity.legalName.name` / `.language`, `data.attributes.entity.status`.
- **HTTP 404 → returns `None`** — a definitive "this LEI is not registered in GLEIF" answer, not a transport error.
- Network error / HTTP non-2xx-non-404 / unparseable body / missing expected keys → raises typed `GleifLookupError`. The client NEVER fabricates a valid record.
- This is the single mock point in tests.

## 3. `lei_validation_service`

### `lei_checksum_ok(lei: str) -> bool` (pure)

ISO 7064 MOD 97-10: uppercase; require exactly 20 chars, all `[0-9A-Z]`; map `A-Z → 10..35`, digits as-is; interpret the resulting digit string as a base-10 integer; valid iff `int % 97 == 1`. Pure, no I/O.

### `validate_lei(session, commercial_partner_id, *, actor_sub, commit=True) -> CommercialPartner`

1. Load the partner via `CommercialPartnerService.get_by_id` (404 if missing/soft-deleted).
2. If `cp.lei` is null/empty → set `lei_status = not_provided`, `lei_legal_name = None`, `lei_checked_at = now(UTC)`; emit audit; return. (Nothing to validate.)
3. **Stage 1 — checksum.** If `not lei_checksum_ok(cp.lei)` → `lei_status = invalid`, `lei_checked_at = now`, `lei_legal_name = None`; emit audit; return (a malformed code cannot be looked up — skip GLEIF).
4. **Stage 2 — GLEIF** via `gleif_client.fetch_lei_record(cp.lei)`:
   - `GleifLookupError` → `lei_status = error`, `lei_checked_at = now` (leave `lei_legal_name` unchanged), warning `"GLEIF lookup failed: <detail>"`. **Never raises**; the route returns 200.
   - `None` (404) → `lei_status = invalid`, `lei_checked_at = now`, `lei_legal_name = None`, warning `"LEI not found in GLEIF registry"`.
   - record → map `registration_status`: `ISSUED → issued`; `LAPSED → lapsed`; **any other status → `lapsed`** (treated as not-currently-active), with warning `"GLEIF registration status: <raw>"`. Persist `lei_legal_name = record.legal_name`, `lei_checked_at = now`.
5. **Name cross-check (advisory).** When `lei_legal_name` is set and diverges from `cp.name` (compare case-insensitive, trimmed; divergent = neither is a substring of the other), append warning `"LEI legal name '<legal>' differs from partner name '<name>'"`. Never changes `lei_status`, never blocks.
6. Emit HMAC `commercial_partner_lei_validated` audit event `{commercial_partner_id, lei, previous_status, new_status, lei_legal_name, actor_sub}` on the request session (commit=False; the route's `unit_of_work` commits). A `lei_status` write is a mutation and carries signed evidence, consistent with the platform invariant.

Returns the updated partner plus the accumulated `warnings` (the route serializes both).

**`LeiStatus.valid` is reserved/unused by W4** — governance assigns `issued` to an active (ISSUED) LEI; W4 sets only `{not_provided, invalid, issued, lapsed, error}`. Recorded here so a future wave (or governance amendment) can define `valid` deliberately rather than by accident.

## 4. RBAC & endpoint

| Endpoint | trader | risk_manager | auditor |
|---|---|---|---|
| `POST /commercial-partners/{id}/validate-lei` | ✅ | ✅ | ✗ 403 |

- Gate `require_any_role("trader", "risk_manager")` — both roles manage commercial-partner LEI input (governance §6: trader does identity/contact/LEI-input CRUD); mirrors the W2 commercial `/screen` gate. auditor is read-only → 403.
- Returns **200** with `LeiValidationRead{lei: str | None, lei_status: str, lei_legal_name: str | None, lei_checked_at: datetime | None, warnings: list[str]}` — including when `lei_status = error` (WARN-not-block: the validation *ran* and recorded an informational error; not a 5xx).
- Wraps `validate_lei(..., commit=False)` in `unit_of_work` (audit emitted in the service, same pattern as the W2 sanctions routes).

## 5. Config

- `GLEIF_API_BASE_URL: str = "https://api.gleif.org/api/v1"` (overridable for tests/mock; no key).
- No boot validator (public API; LEI never gates).

## 6. Testing

- **checksum** (pure): valid LEIs (≥2 known-good), wrong length, non-alphanumeric char, wrong check digits → boundary table.
- **client** (mock `httpx`): parse `registration.status` / `entity.legalName.name` / `entity.status`; 404 → `None`; 5xx / network / unparseable → `GleifLookupError`.
- **service:** null lei → `not_provided`; checksum fail → `invalid` (asserts GLEIF client NOT called); ISSUED → `issued` + `lei_legal_name` persisted; LAPSED → `lapsed`; other status → `lapsed` + warning; 404 → `invalid` + warning; `GleifLookupError` → `error` + warning + **no raise**; name-mismatch → warning (status unchanged); HMAC `commercial_partner_lei_validated` event emitted.
- **route / RBAC:** trader 200, risk_manager 200, auditor 403; `error` path returns 200 (not 5xx).
- **route audit classification:** add `POST /commercial-partners/{id}/validate-lei` to `TestRouteCoverageStatic.CLASSIFICATION` as a service-layer audited mutation (audit emitted in the service, not via a route `audit_event` dep — same as the W2 sanctions routes), and extend the service-emission assertion to cover `lei_validation_service`.
- **schema drift:** regen `schema.d.ts` with `APP_ENV=test` (so `/internal/test/cleanup` stays present); `openapi_diff` green.
- No migration test (columns exist from `049`).

## 7. Process

One dispatch + one PR (protocol §11). Branch `w4/lei-validation` → Codex Connector review. CI gates: `Backend: pytest`, `alembic upgrade head against fresh Postgres` (no new migration; chain must still apply), `openapi_diff` (schema regen required), frontend `svelte-check`/`vitest` (unaffected), both E2E.
