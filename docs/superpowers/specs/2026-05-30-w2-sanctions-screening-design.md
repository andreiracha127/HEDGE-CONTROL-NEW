# W2 — Sanctions Screening Service Design

**Date:** 2026-05-30
**Wave:** W2 of the 7-wave commercial-partners/KYC effort (after W0 #111, W1 #112 merged `main` `898a0bc`).
**Branch:** `w2/sanctions-screening`
**Constitution:** `docs/governance.md` — "Sanctions screening governance (binding)" + "Adjudication (binding)" (≈ lines 733–821), "MARKET-DATA GOVERNANCE" precision rules, AUTHORIZATION MATRIX (`service:sanctions_screening`).
**Predecessor spec:** `docs/superpowers/specs/2026-05-29-commercial-partners-kyc-separation-design.md` §5.2, §7, §11 (W2 row).

## 1. Goal & boundary

W2 is the **writer** of sanctions evidence and `sanctions_status`. It implements the OpenSanctions screening lifecycle, the risk_manager adjudication path, the manual screen endpoints, the scheduled daily re-screen, the `OPENSANCTIONS_API_KEY` boot validator, and the `service:sanctions_screening` identity. It applies to **both** domains: hedge `counterparties` ({broker, bank_br}) and `commercial_partners` ({customer, supplier}).

**Unblocks:** a successful `clear` screening (or a risk_manager adjudication of a `flagged` result) sets `sanctions_status = clear`, which lets `CommercialPartnerService.set_kyc_status` reach `approved`, which lets the already-live commercial order gate admit SO/PO creation. The W1 deploy left every migrated partner `pending`/`unscreened` with no governed path to `clear`; W2 provides it.

### Explicit non-goals (anti-scope)

- **No gate logic changes.** The RFQ admission gate still reads hedge `kyc_status` (`assert_kyc_approved`); its re-target to `assert_sanctions_clear` at the six `rfq_service.py` call sites is **W3**. The commercial order gate already reads stored `sanctions_status` (`!= blocked`) and is unchanged.
- **No LEI/GLEIF work** (W4). **No frontend** (W5; the order-form repoint already landed in W1). **No credit-utilization gate** (W6+).
- **No migration** — `sanctions_screenings` / `sanctions_adjudications` tables and enums already exist from migration `049` (created W1, written here).
- **No on-create auto-screening.** Create stays `unscreened` (W1 behavior); screening is triggered explicitly via `POST /{id}/screen` and the scheduled re-screen. Create never depends on OpenSanctions uptime. Per governance.md "Sanctions screening governance → Decoupling", the on-create trigger is OPTIONAL and DEFERRED — the fail-closed gates already deny `unscreened` entities until a recorded screening lands, so W2 ships only the manual + scheduled triggers.

## 2. Components

**New files**
- `backend/app/services/opensanctions_client.py` — thin, mockable I/O boundary to the hosted OpenSanctions match API.
- `backend/app/services/sanctions_screening_service.py` — domain-agnostic orchestration: `screen()` + `adjudicate()` + effective-status helper. Reuses the `kyc_gate.py` dual-session pattern.
- `backend/app/tasks/sanctions_rescreen_task.py` — scheduler entry `run_sanctions_rescreen_daily()`.
- `backend/app/schemas/sanctions.py` — `SanctionsScreeningRead`, `SanctionsAdjudicationRequest`, `SanctionsAdjudicationRead`.

**Modified files**
- `backend/app/api/routes/commercial_partners.py` — `POST /{id}/screen` (trader + risk_manager), `POST /{id}/adjudicate-sanctions` (risk_manager).
- `backend/app/api/routes/counterparties.py` — `POST /{id}/screen` (risk_manager), `POST /{id}/adjudicate-sanctions` (risk_manager).
- `backend/app/core/config.py` — `OPENSANCTIONS_API_KEY`, `SANCTIONS_SCREENING_ENABLED`, `SANCTIONS_REVIEW_THRESHOLD`, `SANCTIONS_HARD_THRESHOLD`, APP_ENV-gated boot validator.
- `backend/app/core/auth.py` — add `service:sanctions_screening` to `_INTERNAL_SERVICE_IDENTITIES`.
- `backend/app/tasks/scheduler.py` — register `sanctions_rescreen_daily` cron job.
- `frontend-svelte/src/lib/api/schema.d.ts` — regen (new endpoints; `openapi_diff` CI gate).

## 3. `opensanctions_client`

`screen_entity(name: str, country: str | None, tax_id: str | None, lei: str | None) -> MatchResult`

- Request: `POST https://api.opensanctions.org/match/sanctions?algorithm=logic-v2`, header `Authorization: ApiKey <OPENSANCTIONS_API_KEY>`. Body is the `EntityMatchQuery` envelope:
  ```json
  {"queries": {"q1": {"schema": "Company", "properties": {
     "name": ["<name>"], "jurisdiction": ["<country>"],
     "registrationNumber": ["<tax_id>"], "leiCode": ["<lei>"]}}}}
  ```
  Properties are **array-valued**; `registrationNumber` / `leiCode` / `jurisdiction` keys are **omitted** when the source value is `None` (a bare/scalar body is rejected by the API).
- Response → `MatchResult{top_score: Decimal, match_count: int, matches: list, dataset_version: str | None, algorithm: "logic-v2"}`. `top_score` = max match `score`, constructed `Decimal(str(score))` (precision contract — float parsing prohibited). `match_count` = number of returned matches. `matches` = the raw match list (persisted to `matches_json`). `dataset_version` from the response envelope if present, else `None`.
- Raises typed `ScreeningProviderError` on: missing/empty key at call time, network/timeout error, HTTP non-2xx, or unparseable body. The client **never** returns a default `clear`.

## 4. `sanctions_screening_service`

### `screen(session, partner_type, partner_id, *, actor_sub, commit=True) -> SanctionsScreening`

1. Load the entity by `partner_type` (`CommercialPartner` for `commercial`, `Counterparty` for `hedge`) via the service `get_by_id` (returns `None` for soft-deleted) → `HTTP 404` if absent.
2. Build query inputs from the entity identity: `name`, `country`, `tax_id`; plus `lei` for commercial partners (hedge `Counterparty` has no `lei` column → pass `None`).
3. `client.screen_entity(...)` → `MatchResult`.
4. Map `top_score` → `result` (pure function `map_score_to_result`): `< REVIEW` → `clear`; `REVIEW ≤ s < HARD` → `flagged`; `≥ HARD` → `blocked`. Defaults `REVIEW=0.70`, `HARD=0.90`.
5. `query_hash` = SHA-256 of the canonical (sorted) query-input JSON.
6. Persist an immutable `sanctions_screenings` row: `status=success`, `result`, `top_score`, `match_count`, `matches_json`, `provider="opensanctions"`, `algorithm`, `dataset_version`, `screened_at=now(UTC)`, `actor_sub`.
7. Set `entity.sanctions_status = result` (direct attribute set — this IS the dedicated sanctions flow the generic-PATCH 403 guard points to).
8. Emit HMAC `audit_trail_service` event `sanctions_status_changed`: `{partner_type, partner_id, previous_status, new_status, screening_id, top_score, result, actor_sub}`.

**Provider failure (no silent fallback):** on `ScreeningProviderError`, open a **separate `SessionLocal`**, persist a `sanctions_screenings` row with `status=error`, `result=NULL`, `error_detail`, `commit=True`, close it, then raise `HTTPException(502)`. The request session's `sanctions_status` is **not** mutated and **no** status-change audit event is emitted. (Dual-session because `unit_of_work` rolls back the request session on any exception — mirrors `kyc_gate.py`.)

### `adjudicate(session, partner_type, partner_id, *, decision, reason, actor_sub) -> SanctionsAdjudication`

- `decision ∈ {clear, blocked}`; `reason` mandatory, ≥ 8 chars (enforced at schema + service).
- **Validity:** permitted only when the **latest compliance event** for the entity — the latest of {`status=success` screenings, adjudications} ordered by timestamp — is a screening with `result=flagged`. A `flagged` already superseded by a newer `blocked`/`clear` screening or a prior adjudication → `HTTP 422` (closes the stale-flagged-overrides-newer-hard-hit loophole).
- Write an immutable `sanctions_adjudications` row (`superseded_screening_id` = that latest flagged screening, `decision`, `reason`, `adjudicating_actor_sub`, `adjudicated_at=now(UTC)`). Never mutate the screening row.
- Set `entity.sanctions_status = decision`; emit HMAC `sanctions_status_adjudicated`: `{partner_type, partner_id, previous_status, new_status, superseded_screening_id, reason, actor_sub}`.

### `effective_sanctions_status(session, partner_type, partner_id)` helper

Returns the result/decision of the latest event among {`status=success` screenings, adjudications} by timestamp (latest-event-wins). Used by `adjudicate()`'s validity check and available for tests; the stored `sanctions_status` column is kept consistent with it by `screen()`/`adjudicate()`.

## 5. RBAC & endpoints

| Endpoint | trader | risk_manager | auditor |
|---|---|---|---|
| `POST /commercial-partners/{id}/screen` | ✅ trigger | ✅ | ✗ |
| `POST /commercial-partners/{id}/adjudicate-sanctions` | ✗ 403 | ✅ | ✗ |
| `POST /counterparties/{id}/screen` | ✗ 404 (hedge invisible to trader) | ✅ | ✗ |
| `POST /counterparties/{id}/adjudicate-sanctions` | ✗ 403¹ | ✅ | ✗ |

- Trader may trigger screening on a **commercial** partner (design spec §6: "trigger sanctions screening"); trader cannot adjudicate (risk_manager-only) and has no hedge access (hedge endpoints hide existence from trader).
- ¹ As built, hedge `/adjudicate-sanctions` returns **403** (not 404) for a trader: the `require_role("risk_manager")` dependency fires before the body's `_is_trader_only` 404 guard. This leaks no existence (the 403 is returned before any DB read, identical for existent/non-existent ids) and matches the existing risk_manager-only hedge mutation routes (e.g. kyc-status). Hedge `/screen` keeps the trader→404 existence-hiding because its gate admits trader (`require_any_role("trader","risk_manager")`) and the body guard converts to 404.
- `service:sanctions_screening` — used by the scheduled re-screen task only; authorized to write screenings + the derived `sanctions_status` (no order / RFQ / deal / credit / `kyc_status` mutation). Added to `_INTERNAL_SERVICE_IDENTITIES`.
- `/screen` returns `200` with the `SanctionsScreeningRead` (incl. the new `sanctions_status`); provider failure → `502`. `/adjudicate-sanctions` returns `200` with `SanctionsAdjudicationRead`; invalid target → `422`.

## 6. Config / boot validator / scheduler

- `OPENSANCTIONS_API_KEY: str = ""`; `SANCTIONS_SCREENING_ENABLED: bool = True`; `SANCTIONS_REVIEW_THRESHOLD: Decimal = 0.70`; `SANCTIONS_HARD_THRESHOLD: Decimal = 0.90` (thresholds are institutional parameters recorded here per governance:776–782).
- Boot validator (mirror of the `AUDIT_SIGNING_KEY` validator, APP_ENV-gated): when `APP_ENV ∈ {production, staging}` **and** `SANCTIONS_SCREENING_ENABLED` **and** `OPENSANCTIONS_API_KEY` is empty → refuse to start (`ValueError`). In dev/test it is a no-op so the suite runs without a key (the client is mocked).
- Scheduler: `_scheduler.add_job(run_sanctions_rescreen_daily, trigger="cron", id="sanctions_rescreen_daily", hour=2, minute=0)` (02:00 UTC, off-peak, distinct from `finance_pipeline_daily` 19:00). Runs only in the `scheduler` service (existing `SCHEDULER_DISABLED` web-worker gating). The task iterates **active, non-deleted** partners across **both** domains, calls `screen()` per entity under `actor_sub="service:sanctions_screening"`, **continues on per-entity error** (the service already records the `status=error` row on its own session), and logs a run summary `{screened, errors}`. (Pilot scale is 8 entities; batching/pagination is a future optimization, not W2.)

## 7. Testing

- **client:** mock `httpx` — assert envelope shape (array properties, omitted-when-None keys), `Authorization: ApiKey` header, parse of `top_score`/`match_count`/`dataset_version`; `ScreeningProviderError` on non-2xx, network error, unparseable body, empty key.
- **threshold mapping** (pure fn): `0.69→clear`, `0.70→flagged`, `0.89→flagged`, `0.90→blocked` (boundary table).
- **screen():** success per tier sets `sanctions_status` + writes one `success` row + emits HMAC event; provider error writes one `error` row (result NULL) on a separate session, raises 502, leaves `sanctions_status` untouched, emits no status-change event; missing/soft-deleted entity → 404. Both domains.
- **adjudicate():** valid `flagged→clear` and `flagged→blocked`; reject when latest event is not a screening / not `flagged` / already superseded (422); `reason` < 8 chars rejected; writes immutable row, sets status, emits HMAC; never mutates the screening row.
- **effective-status helper:** latest-event-wins across mixed screening/adjudication timelines.
- **routes / RBAC:** the table in §5 enforced (trader screens commercial but 404 on hedge and 403 on adjudicate; risk_manager all; auditor blocked); extends `tests/test_rbac_matrix_enforcement.py`.
- **boot validator:** prod + enabled + empty key → refuse; dev/test → no-op.
- **re-screen task:** iterates both domains, continue-on-error, summary counts.
- No migration test (tables exist from `049`).

## 8. Carried-forward W1 items folded here

- Register `service:sanctions_screening` in `auth.py` `_INTERNAL_SERVICE_IDENTITIES` (W2 is its first consumer).
- (Out of scope, tracked separately: hedge `credit_limit_usd: float → Decimal` cleanup; the generic-PATCH `kyc_status` silent-drop task.)

## 9. Process

One dispatch + one PR (protocol §11). Branch `w2/sanctions-screening` → Codex Connector review (`+1` = acceptance; inline comments lag — re-poll). CI gates: `Backend: pytest`, `alembic upgrade head against fresh Postgres` (no new migration, but the chain must still apply), `openapi_diff` (schema.d.ts regen required), frontend `svelte-check`/`vitest` (unaffected), both E2E.
