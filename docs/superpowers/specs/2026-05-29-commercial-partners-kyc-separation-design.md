# Design — Commercial Partners ↔ Hedge Counterparty Separation + Commercial KYC (Sanctions / LEI / Credit)

- **Date:** 2026-05-29
- **Status:** Approved design (brainstorming complete) — ready for implementation planning
- **Authority:** Andrei (governance authority). All forks below were decided interactively.
- **Constitutional impact:** YES. Amends `docs/governance.md` (AUTHORIZATION MATRIX + KYC gate). This design supersedes the current "Counterparty KYC gate (binding, Pilot Hard Blocker 1)" placement.

---

## 1. Problem statement

When creating a new commercial order (PO = purchase / SO = sale), the order form lists **hedge counterparties** (brokers/banks such as Marex, Sucden, Itaú BBA, BTG, Bradesco) instead of **suppliers** (PO) and **customers** (SO).

Root cause:
- The order-new loader [`+page.ts`](../../../frontend-svelte/src/routes/(protected)/orders/new/+page.ts) fetches `GET /counterparties?limit=200` with **no type filter**, and [`+page.svelte`](../../../frontend-svelte/src/routes/(protected)/orders/new/+page.svelte) renders **every** row.
- The domain conflates two fundamentally different concepts in **one** table: [`counterparties`](../../../backend/app/models/counterparty.py) carries `type ∈ {broker, bank_br, customer, supplier}` plus KYC/credit fields applied indiscriminately to all four.

Two distinct domains must be separated:
- **Hedge counterparties** — who Alcast trades derivatives with (RFQ/Deal/Linkage/Contract/MTM). Regulated brokers/banks. Registered by **risk_manager**.
- **Commercial partners** — customers (buy Alcast's product) and suppliers (sell raw material to Alcast). The source of commercial exposure (orders). Registered by **trader**. Require full commercial KYC.

## 2. Decisions (locked)

| # | Fork | Decision |
|---|------|----------|
| D1 | KYC re-targeting | **Sanctions screening stays universal** (incl. hedge); **full commercial KYC** (LEI + dossier + credit) is **exclusive to commercial partners**. Separates "sanctions gate" from "commercial KYC". |
| D2 | Data model | **`counterparties` = hedge only** (`broker`, `bank_br`). New **`commercial_partners`** table with `kind ∈ {customer, supplier}`. `orders.counterparty_id` → `commercial_partners`. Migrate existing customer/supplier rows, **reusing the same UUID** to preserve FKs. |
| D3 | Commercial gate | **Hard, fail-closed** at order creation: `kyc_status = approved` AND `sanctions_status != blocked`; else HTTP 422 + audit event. **LEI = warn, not block.** |
| D4 | OpenSanctions deployment | **Hosted API** (`api.opensanctions.org`, `ApiKey`). **Decoupled**: screening is a separate audited op that writes `sanctions_status`; the gate reads stored status. Screening itself **hard-fails** on API error (never silent "clear"). |
| D5 | Credit enforcement | **Record now, credit-utilization gate later.** This effort stores limits/terms (customer: financial limit + payment conditions; supplier: approved value + terms for Alcast). The order gate is **only** kyc+sanctions; cumulative-exposure credit gate is a future sub-project. |
| D6 | Sequencing | **No throwaway hotfix.** Go straight through the redesign; the order-form fix is born correct inside it. |

## 3. Constitutional amendment (governance.md)

This is **Wave 0** and gates everything downstream. Amend `docs/governance.md` (and verify `docs/systemconstitucion.md` for any higher-level counterparty/KYC principle that must stay consistent):

1. **Two counterparty domains** (new subsection): define hedge `counterparties` (broker/bank, risk_manager-owned, sanctions-screened) vs `commercial_partners` (customer/supplier, trader-owned, full commercial KYC).
2. **Re-target Pilot Hard Blocker 1.** The RFQ admission gate stops checking `kyc_status` and instead requires a **recorded `clear` sanctions screening** on the hedge counterparty (denies `blocked`, `flagged`, AND unscreened). The 6 call sites of `assert_kyc_approved` in [`rfq_service.py`](../../../backend/app/services/rfq_service.py) (lines ~580, 853, 1029, 1297, 1469, 1583) migrate to `assert_sanctions_clear`. Audit events: `rfq_*_rejected_sanctions_not_cleared`. (The **commercial** order gate is separately `sanctions_status != blocked` per D3 — unchanged.)
3. **New Hard Blocker — commercial order gate** (§4 below).
4. **Pilot scope re-mapping** ([governance.md:525-539](../../../docs/governance.md)): the 8 pilot entities split — hedge entities (Stonex/Marex, Banco BS2, Itaú) must have a recorded sanctions screening with result `clear`; commercial entities (Rusal, Casa do Alumínio, Aluminios del Mexico, Alecar) become `commercial_partners` and must be `kyc_status = approved` AND `sanctions_status = clear` before pilot launch.
5. **Precision contract**: credit/approved-value fields are `Decimal` end-to-end (corrects the current `credit_limit_usd: float` violation).
6. **RBAC matrix** additions (§6 below).

> **Note:** `counterparties.kyc_status` becomes vestigial on the hedge domain (the RFQ gate no longer reads it). Keep the column for this effort to minimize churn; drop in a later migration.

## 4. Commercial order gate (fail-closed)

New primitive `assert_commercial_partner_admissible` — mirrors the dual-session pattern of [`kyc_gate.py`](../../../backend/app/services/kyc_gate.py) (audit row written on a separate committed `SessionLocal` so it survives the outer `unit_of_work` rollback on HTTPException).

Called in order creation (PO/SO) in `order_service`:
- **Kind coherence:** `PO → kind == supplier`, `SO → kind == customer`. Mismatch → 422.
- **Admissibility:** `kyc_status == approved` AND `sanctions_status != blocked`.
- On refusal: emit HMAC-signed audit event **before** raising — `order_rejected_kyc_not_approved` or `order_rejected_sanctions_blocked` — with payload `{commercial_partner_id, kind, kyc_status_observed, sanctions_status_observed, requesting_actor_sub, order_type}`. Then raise **HTTP 422**.
- Load via the service getter (NOT raw `db.get`) so soft-deleted rows fail closed with 404 (same rationale as `kyc_gate.py:55-68`).
- **`flagged` handling:** `flagged` passes the `!= blocked` check by design (it is informational — a sub-threshold potential match awaiting risk_manager adjudication). The kyc-approval invariant is the primary guard: risk_manager will not move `kyc_status → approved` while a partner is `flagged` or `blocked`. Adjudication resolves `flagged → clear` or `flagged → blocked`.
- LEI: invalid / lapsed / legal-name mismatch produces an advisory warning surfaced to the caller; it does **not** block.

## 5. Data model

### 5.1 `commercial_partners`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | reuse source `counterparties.id` on migration |
| kind | Enum(`customer`,`supplier`) | not null |
| name | str(200) | not null |
| short_name | str(50) | nullable |
| tax_id | str(50) | unique, nullable |
| country | str(3) | not null (ISO-3) |
| city, address | str / text | nullable |
| contact_name/email/phone, whatsapp_phone | str | nullable |
| lei | str(20) | nullable |
| lei_status | Enum(`not_provided`,`valid`,`invalid`,`lapsed`,`issued`,`error`) | default `not_provided` |
| lei_legal_name | str(200) | nullable (from GLEIF) |
| lei_checked_at | datetime | nullable |
| kyc_status | Enum(`pending`,`approved`,`expired`,`rejected`) | default `pending` (fail-closed) |
| sanctions_status | Enum(`unscreened`,`clear`,`flagged`,`blocked`) | default `unscreened` (NOT `clear`); screening writes `clear`/`flagged`/`blocked`. A partner cannot reach `kyc_status=approved` without an effective `clear` (a `clear` screening OR a risk_manager adjudication of a `flagged` result; §6), so an `unscreened` or unresolved-`flagged` partner is gated out |
| risk_rating | Enum(`low`,`medium`,`high`) | default `medium` |
| **customer-only** `credit_limit` | Numeric(18,2) Decimal | nullable; CHECK null when kind=supplier |
| **customer-only** `credit_currency` | str(3) | nullable |
| **customer-only** `payment_conditions` | JSON | `{terms_days:int, advance_pct:Decimal, method:str, notes:str}` |
| **supplier-only** `approved_value` | Numeric(18,2) Decimal | nullable; CHECK null when kind=customer |
| **supplier-only** `approved_currency` | str(3) | nullable |
| **supplier-only** `approved_terms` | JSON | `{terms_days:int, incoterm:str, delivery:str, notes:str}` |
| is_active, notes | bool / text | |
| created_at, updated_at, is_deleted, deleted_at | | soft-delete, mirrors `counterparties` |

> Credit/terms modeled as nullable kind-specific columns + CHECK constraints (Postgres) for v1 simplicity. Child-table refactor is an option if the field sets grow. SQLite-compatible DDL with `with_variant` fallbacks per the P2 dispatch rule.

### 5.2 `sanctions_screenings` (append-only, immutable)
`id`, `partner_type` (`commercial`|`hedge`), `partner_id`, `screened_at`, `provider` (`opensanctions`), `algorithm` (`logic-v2`), `dataset_version`, `query_hash`, `top_score` (Numeric), `match_count`, `matches_json`, `result` (`clear`|`flagged`|`blocked`; **NULL when `status`=`error`**), `actor_sub`, `status` (`success`|`error`), `error_detail`. The partner's `sanctions_status` is set **only** from the latest **successful** (`status`=`success`) screening's `result`; `error` rows are recorded for audit and never overwrite it. Never updated/deleted.

**`sanctions_adjudications`** (append-only, immutable): `{id, partner_type, partner_id, superseded_screening_id, decision (`clear`|`blocked`), reason, adjudicating_actor_sub, adjudicated_at}` — a risk_manager override of a `flagged` screening; sets `sanctions_status` without mutating the screening row. Current `sanctions_status` = latest of {successful screening result, adjudication} by timestamp (a later screening supersedes a prior adjudication, and vice-versa).

### 5.3 Migration (numeric chain, single-head; ENUM lifecycle care)
- Create enums + `commercial_partners` + `sanctions_screenings`. Named ENUMs explicitly created before `ALTER TABLE ADD COLUMN`; explicit `CAST(... AS <enum>)` for text literals (per CLAUDE.md fresh-Postgres rules).
- Copy `counterparties` rows where `type ∈ {customer, supplier}` into `commercial_partners` **with the same `id`** (kind = old type; map credit_limit→customer credit_limit / supplier approved_value as appropriate; carry risk_rating/contacts/notes/timestamps). **Reset fail-closed**: `kyc_status` → `pending` and `sanctions_status` → unscreened — do NOT carry a legacy `approved` / default-`clear` without `sanctions_screenings` evidence, else the commercial order gate would pass without a recorded clear screening. The pilot pre-condition re-establishes `approved`+`clear` for the named pilots via real screening + risk_manager sign-off. (Hedge `counterparties` are likewise reset to an unscreened `sanctions_status`.)
- **Pre-FK validation (fail-closed)**: before repointing, enumerate `orders` whose `counterparty_id` references a broker/bank `counterparties` row (a pre-fix data artifact of the order form that listed hedge counterparties). If any exist, the migration HALTS with a remediation report — each affected order is manually re-pointed to the correct `commercial_partner` (or voided) first. NO silent orphaning or guessing.
- Repoint `orders.counterparty_id` FK: `counterparties.id` → `commercial_partners.id` (values unchanged because the migrated commercial UUIDs were reused; the pre-FK validation guarantees no surviving broker/bank reference).
- Restrict `counterparties` to hedge: remove/soft-retire migrated customer/supplier rows; keep `type ∈ {broker, bank_br}` going forward.
- Guard with `tests/test_alembic_chain.py` (single head) + the `alembic-fresh-postgres` CI job.

## 6. RBAC (AUTHORIZATION MATRIX additions)

| Actor | hedge `counterparties` | `commercial_partners` |
|-------|------------------------|------------------------|
| **trader** | none (broker/bank invisible → 404) | CRUD identity/contact/LEI input; **trigger** sanctions screening; **cannot** approve kyc or set credit/terms |
| **risk_manager** | full CRUD + manage screening | identity/contact CRUD; `kyc_status` transitions + credit/terms approval via dedicated flows (NOT generic PATCH); full read |
| **auditor** | read-only | read-only |

Invariants: `kyc_status → approved` requires effective `sanctions_status` = `clear` (a successful `clear` screening OR a risk_manager adjudication of a `flagged` result; a `blocked` must be remediated + re-screened, never adjudicated away); credit/terms mutation is risk_manager-only and audited (`commercial_partner_credit_approved`). RBAC tests in `tests/test_rbac_matrix_enforcement.py`.

## 7. Services / integration

- **`sanctions_screening_service`** — `POST https://api.opensanctions.org/match/sanctions?algorithm=logic-v2`, header `Authorization: ApiKey <OPENSANCTIONS_API_KEY>`, request body = OpenSanctions `EntityMatchQuery` envelope `{"queries": {"q1": {"schema": "Company", "properties": {"name": [..], "jurisdiction": [<country>], "registrationNumber": [<tax_id>], "leiCode": [<lei>]}}}}` (top-level `queries` map, ARRAY-valued properties — a bare entity body 422s). Map response `match`/`score` → `result`: no match → `clear`; match below hard threshold → `flagged` (risk_manager adjudicates); match ≥ hard threshold → `blocked`. Thresholds defined in the Wave-2 dispatch. Persist immutable `sanctions_screenings` row + update partner `sanctions_status`. **Hard-fail** (record `status=error`, raise) on API/network error — never set `clear` silently. `OPENSANCTIONS_API_KEY` required in prod/staging via an APP_ENV-gated boot validator (same shape as `AUDIT_SIGNING_KEY`). Decoupled triggers: on create, manual `POST /commercial-partners/{id}/screen` and `POST /counterparties/{id}/screen` (hedge, risk_manager), and a scheduled daily re-screen in the existing `scheduler` service (covers both domains), attributed to the new `service:sanctions_screening` identity (added to the AUTHORIZATION MATRIX in W0).
- **`lei_validation_service`** — offline ISO 7064 MOD 97-10 checksum + `GET https://api.gleif.org/api/v1/lei-records/{lei}` (no key) → `registrationStatus` (ISSUED/LAPSED) + legal name. Set `lei_status` + `lei_legal_name` + `lei_checked_at`. Warn (not block) on invalid checksum, lapsed status, or legal-name mismatch vs `name`.
- **`commercial_partner_service`** — CRUD with audit-trail emission (mirrors `counterparty_service`); `kyc_status` transition (risk_manager, screening-clear invariant); credit/terms approval (risk_manager).

## 8. API routes

`commercial_partners` router (mounted alongside `counterparties`):
- `POST` / `GET` (filter by `kind`, `kyc_status`, `is_active`; trader sees only commercial) / `GET {id}` / `PATCH` / `DELETE`.
- `POST {id}/kyc-status` (risk_manager) — reuse `KycStatusTransitionRequest` shape.
- `POST {id}/screen` — trigger sanctions screening.
- `POST {id}/validate-lei` — trigger LEI validation.
- `POST {id}/adjudicate-sanctions` (risk_manager) — override a `flagged` screening to `clear`/`blocked` with mandatory reason; writes an immutable `sanctions_adjudications` row, never mutates the screening.
- `PATCH {id}/credit` (risk_manager) — customer limit/conditions or supplier value/terms.

`counterparties` (hedge) router — add:
- `POST {id}/screen` (risk_manager) — trigger sanctions screening on a hedge counterparty. Screening is universal, so hedge counterparties need a manual re-screen path to move an RFQ-blocking `sanctions_status` back to `clear` without waiting for the scheduled re-screen.
- `POST {id}/adjudicate-sanctions` (risk_manager) — override a `flagged` hedge screening to `clear`/`blocked` (same immutable-adjudication semantics as the commercial router).

Orders purchase/sales routes call the commercial gate and validate kind. Regenerate `frontend-svelte/src/lib/api/schema.d.ts` from `/openapi.json` in the same change (avoid drift; mind `Field()` constraint → `title` JSDoc drift).

## 9. Frontend

- Three registration surfaces: **Clientes** + **Fornecedores** (trader), **Contrapartes** (risk_manager) — each list + form, showing KYC/sanctions/LEI/credit state.
- `orders/new`: load `commercial_partners` filtered by `kind` (PO→supplier, SO→customer); show compliance inline; disable submit when inadmissible (backend remains authoritative).
- KYC/sanctions/credit panels: read for trader, manage for risk_manager.

## 10. Testing

- RBAC matrix (trader/risk_manager/auditor × commercial_partners + hedge counterparties; broker/bank → 404 for trader).
- Commercial gate (order refused on `kyc != approved` / `sanctions == blocked`; kind mismatch; audit row survives `unit_of_work` rollback).
- RFQ gate re-target (sanctions, not kyc).
- Migration (single-head; fresh-Postgres ENUM lifecycle; UUID-preserving row migration; orders FK integrity).
- Sanctions service (mock OpenSanctions; hard-fail on error; immutable screening rows; status update; threshold mapping).
- LEI service (offline checksum vectors; GLEIF mock; warn-not-block paths).
- Precision (Decimal credit/value; reject float on ingest).

## 11. Implementation waves (→ dispatches)

Maps to the repo's amendment → dispatch → implementation protocol. Each wave = one dispatch + one PR.

| Wave | Scope | Depends on |
|------|-------|------------|
| **W0** | Governance amendment (docs) — encodes D1–D6, RBAC, gates, pilot re-map | — |
| **W1** | Data model + migration + `commercial_partner_service` CRUD + routes + RBAC (no external calls) | W0 |
| **W2** | Sanctions screening service (OpenSanctions hosted) + endpoints + scheduled re-screen + status lifecycle (`unscreened` default, adjudication path) — must precede any gate that requires a recorded `clear` | W1 |
| **W3** | Commercial order gate + kind validation (PO→supplier, SO→customer) **and** RFQ gate re-target (kyc → sanctions, recorded-`clear`) — depends on W2 so partners can reach approved+clear and hedge statuses are populated | W2 |
| **W4** | LEI validation service (GLEIF) + endpoint | W1 |
| **W5** | Frontend: three registration surfaces + order-form fix + compliance panels + schema regen | W1–W4 |
| **W6** | Credit/terms approval flows (customer limits/conditions; supplier value/terms) + display | W1, W5 |

## 12. Out of scope (explicit)

- Cumulative credit-utilization gate on order creation (deferred — D5).
- Self-hosted yente (rejected in favor of hosted API — D4).
- Full KYC documentary suite (`KycDocument`, `CreditCheck`, `KycCheck` attestation models) — remains the separate post-pilot concern noted in [governance.md:550-555](../../../docs/governance.md).
- Dropping the vestigial `counterparties.kyc_status` column (later migration).
- LEI as a hard requirement (it is warn-not-block per D3).
