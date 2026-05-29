# W0 — Governance Amendment (Commercial Partners ↔ Hedge Separation + Commercial KYC) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Amend the constitutional source of truth (`docs/governance.md`, with a consistency check on `docs/systemconstitucion.md`) to encode the commercial-partner / hedge-counterparty separation and the re-targeted KYC model, so that downstream implementation waves (W1–W6) have an authoritative contract to conform to.

**Architecture:** Docs-only constitutional amendment. The AUTHORIZATION MATRIX gains a second counterparty domain (`commercial_partners`); the "Counterparty KYC gate (Pilot Hard Blocker 1)" section is split into a **hedge sanctions gate** (RFQ admission re-targeted from `kyc_status` to requiring a recorded `clear` sanctions screening) and a **commercial partner KYC + order gate** (new fail-closed hard block on order creation), plus new subsections governing sanctions screening, LEI validation, and credit/terms. There is no code in this wave; verification is internal-consistency + stale-reference sweep + the repo's Codex PR review.

**Tech Stack:** Markdown (`docs/governance.md`, `docs/systemconstitucion.md`); `git`; `Grep` for consistency sweeps.

**Spec:** [`docs/superpowers/specs/2026-05-29-commercial-partners-kyc-separation-design.md`](../specs/2026-05-29-commercial-partners-kyc-separation-design.md) — decisions D1–D6.

**Scope note:** This is the first of seven waves (W0–W6). It produces a self-contained, mergeable deliverable (an amendment-only PR, matching the repo's established amendment→dispatch→implementation protocol; cf. PR #96 amendment-only precedent). It changes **no** code, so no tests run; the implementation waves carry the code + tests that conform to this amendment.

---

> ## ⚠️ POST-EXECUTION AMENDMENT (Codex absorption, PR #111)
>
> This plan was executed, then AMENDED during Codex review absorption.
> **`docs/governance.md` is authoritative** over any inline "Replace with:"
> prose below. Binding deltas that supersede the original blocks:
> 1. **Hedge RFQ gate admits ONLY a recorded `clear`** (denies `blocked`,
>    `flagged`, AND unscreened-default) — NOT "deny only `blocked`". The 3
>    RFQ events are `rfq_*_rejected_sanctions_not_cleared` (NOT
>    `*_sanctions_blocked`). The **commercial** order gate stays
>    `sanctions_status != blocked` per the locked decision — unchanged.
> 2. **`sanctions_screenings.result` is NULL when `status=error`**; entity
>    `sanctions_status` updates only from the latest SUCCESSFUL screening.
> 3. **Generic PATCH excludes `kyc_status` + credit/terms for ALL actors**
>    (incl. risk_manager); they change only via the dedicated audited flows.
> 4. **New service identity `service:sanctions_screening`** for the
>    scheduled re-screen mutation (added to the AUTHORIZATION MATRIX).
> 5. **Migration resets fail-closed** — commercial `kyc_status`→`pending`,
>    `sanctions_status`→unscreened on both domains — no carried
>    `approved`/default-`clear` without screening evidence.
> 6. **`SanctionsStatus` gains an explicit `unscreened` member** (default,
>    NOT `clear`); the gate admits only a recorded `clear`.
> 7. **Adjudication path** — risk_manager overrides a `flagged` via
>    `POST {id}/adjudicate-sanctions`, writing an immutable
>    `sanctions_adjudications` row that supersedes the screening without
>    mutating it.
> 8. **Wave order** — screening lands in W2; the commercial order gate +
>    RFQ re-target land in W3 (depend on W2). A gate must not precede the
>    screening that makes partners admissible.
> 9. **Pre-FK migration validation** — orders referencing broker/bank rows
>    HALT the migration with a remediation report (no silent orphaning).
> 10. **Identity-field re-screen** — PATCHing a screening-relevant identity
>     field (name/country/tax_id/lei) on an approved/clear partner resets it
>     fail-closed (re-screen + re-approve).
> 11. **Hedge gate + adjudication** — hedge RFQ admission accepts effective
>     `clear` (screening OR adjudication); adjudication is valid only against
>     the LATEST screening while still `flagged` (cannot override a newer
>     `blocked`).
> 12. **`service:sanctions_screening` added to the JWT-pattern invariant**;
>     the `sanctions_adjudications` table is created in the W1 migration.
> 13. **Migration validates hedge-side FKs** (RFQ/quote/contract/llm) before
>     moving customer/supplier rows; **HB-3 `risk_flags` re-align is in W3
>     scope**; **kind-mismatch refusals emit `order_rejected_kind_mismatch`**.

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `docs/governance.md` | RBAC matrix + binding gates (constitutional). AUTHORIZATION MATRIX (lines ~189-357) and "Counterparty KYC gate / Pilot Hard Blocker 1" (lines ~359-561). | Modify |
| `docs/systemconstitucion.md` | Higher-level constitutional principles. Verify no counterparty/KYC principle contradicts the amendment; edit only if a contradiction exists. | Verify / conditional modify |

All edits use **unique anchor strings** (not line numbers — line numbers drift as edits apply). Each task quotes the exact existing text to match.

---

## Task 1: Re-scope the role bullets to two counterparty domains

**Files:**
- Modify: `docs/governance.md` (AUTHORIZATION MATRIX → "Human roles" → `trader` and `risk_manager` bullets)

- [ ] **Step 1: Replace the `trader` role bullet**

Anchor (match exactly):

```
- `trader` (commercial team)
  - Counterparty full access (read + CRUD) limited to type ∈ {customer, supplier},
    EXCEPT mutations to `kyc_status` — see "Counterparty KYC gate" below.
    `kyc_status` is risk_manager-only across all counterparty types.
  - Order CRUD (Sales Orders + Purchase Orders)
  - Read of operational primitives (orders, customer/supplier counterparties)
  - Cannot: HedgeContracts, RFQs, Deals, Links, Scenario, MTM/P&L writes,
    Counterparty {broker, bank_br} read or write, `kyc_status` mutations
    on any counterparty type, audit log
```

Replace with:

```
- `trader` (commercial team)
  - Commercial partner full access (read + CRUD) on `commercial_partners`
    (kind ∈ {customer, supplier}), EXCEPT `kyc_status` and the credit/terms
    fields — see "Commercial partner KYC + order gate" and "Credit and terms
    governance" below. `kyc_status` transitions and credit/terms approval are
    risk_manager-only.
  - May TRIGGER sanctions screening and LEI validation on a
    `commercial_partner` (the result-recording op is not a privileged write of
    the gated fields; it writes a screening/validation record and the derived
    `sanctions_status`/`lei_status`).
  - Order CRUD (Sales Orders + Purchase Orders)
  - Read of operational primitives (orders, commercial_partners)
  - Cannot: HedgeContracts, RFQs, Deals, Links, Scenario, MTM/P&L writes,
    hedge `counterparties` ({broker, bank_br}) read or write, `kyc_status` or
    credit/terms mutations on `commercial_partners`, audit log
```

- [ ] **Step 2: Replace the `risk_manager` Counterparty line**

Anchor (match exactly):

```
- `risk_manager` (system owner)
  - Counterparty CRUD all 4 types
```

Replace with:

```
- `risk_manager` (system owner)
  - Hedge counterparty (`counterparties`, type ∈ {broker, bank_br}) CRUD
  - Commercial partner (`commercial_partners`) full access, including the
    `kyc_status` transitions and credit/terms approval that trader cannot
    perform
```

- [ ] **Step 3: Verify the auditor bullet still reads correctly**

Run: `grep -n "auditor (oversight)" docs/governance.md`
Expected: the `auditor` bullet is unchanged and still grants "Read-only on every endpoint" — which now covers both `counterparties` and `commercial_partners` with no edit needed. No change required; this step is a confirmation only.

- [ ] **Step 4: Commit**

```bash
git add docs/governance.md
git commit -m "docs(gov): split role bullets into hedge counterparties + commercial_partners domains"
```

---

## Task 2: Rewrite the Counterparty authorization invariants for the two domains

**Files:**
- Modify: `docs/governance.md` (AUTHORIZATION MATRIX → "Authorization invariants" → the Counterparty mutation + read invariants)

- [ ] **Step 1: Replace the trader Counterparty-mutation invariant**

Anchor (match exactly):

```
- Counterparty mutations by `trader` require server-side authorization
  per HTTP method (route gate `require_any_role(trader, risk_manager)`
  is the first layer in all three; the second layer differs by method
  because PATCH and DELETE cannot rely on a payload type field):
  - POST: payload gate — assert `payload.type ∈ {customer, supplier}`
    when actor lacks risk_manager. Source of authorization is the
    incoming type.
  - PATCH: stored-record gate — load the existing counterparty, assert
    `existing.type ∈ {customer, supplier}` when actor lacks risk_manager,
    AND reject any payload field that would mutate `type` (current
    `CounterpartyUpdate` schema does not expose `type`, but the
    rejection guards future schema evolution). Source of authorization
    is the stored type, not the payload (the payload has no type field).
  - DELETE: stored-record gate — load the existing counterparty, assert
    `existing.type ∈ {customer, supplier}` when actor lacks risk_manager.
    DELETE has no request body; the stored-type check is the only
    authorization layer beyond the route gate.
```

Replace with:

```
- Hedge `counterparties` ({broker, bank_br}) are invisible to trader-only
  actors on every method. The route gates are `require_any_role(trader,
  risk_manager)` for writes and `require_any_role(trader, risk_manager,
  auditor)` for reads; the second layer denies trader-only access:
  - GET (list + by-id): a `{trader}`-only actor receives an empty list
    and a 404 by-id (NOT 403 — existence must not leak). risk_manager and
    auditor receive all rows.
  - POST / PATCH / DELETE: a `{trader}`-only actor is refused. For by-id
    methods the stored row is loaded and a 404 returned when the actor is
    trader-only (existence non-leak). The `counterparties` table holds
    ONLY hedge types after the W1 migration, so there is no per-type branch
    left on this table — trader simply has no hedge-counterparty access.
- Commercial partner mutations by `trader` (on `commercial_partners`) are
  authorized by the table itself, not by a per-row type branch (every row
  is commercial). The route gate `require_any_role(trader, risk_manager)`
  is the first layer; the second layer protects the risk_manager-only
  fields:
  - POST: trader MAY create a `commercial_partner` (kind ∈ {customer,
    supplier}); the create payload MUST NOT set `kyc_status` (server
    forces default `pending`) nor any credit/terms field (those require a
    separate risk_manager approval op).
  - PATCH: the generic PATCH route mutates identity/contact/LEI-input
    fields ONLY. `kyc_status` and credit/terms are NOT mutable via generic
    PATCH by ANY actor (including risk_manager) — a payload targeting them
    is refused with HTTP 403. Those fields change only via the dedicated
    audited flows (`POST {id}/kyc-status`, `PATCH {id}/credit`).
  - DELETE (soft): trader MAY soft-delete a `commercial_partner`.
```

- [ ] **Step 2: Replace the trader Counterparty-read invariant**

Anchor (match exactly):

```
- Counterparty reads by `trader` are also type-restricted (the prohibition
  is read-and-write, not write-only — broker/bank rows must be invisible
  to commercial actors). The condition is **trader-specific** (NOT
  "lacks risk_manager") because the GET route gate is
  `require_any_role(trader, risk_manager, auditor)` — auditor enters the
  handler and is read-only on every endpoint by matrix definition,
  including broker/bank rows for oversight purposes:
  - GET /counterparties (list): when the actor's effective role set is
    `{trader}` only (no risk_manager, no auditor), the list query MUST
    filter `type IN (customer, supplier)` server-side. The response
    never contains broker/bank rows, never even leaks counts. Auditors
    and risk_managers receive the unfiltered list.
  - GET /counterparties/{id}: when the actor's effective role set is
    `{trader}` only, load the existing counterparty + assert
    `existing.type ∈ {customer, supplier}`; raise HTTP 404 (NOT 403)
    if the stored type is broker/bank, to avoid leaking existence of
    the row. Auditors and risk_managers receive the row regardless of
    type.

  Note on the symmetric mutation invariants above (POST/PATCH/DELETE):
  the "when actor lacks risk_manager" condition there is correct because
  those route gates are `require_any_role(trader, risk_manager)` —
  auditor is rejected at the route gate before the handler runs, so
  "lacks risk_manager" is equivalent to "is trader" inside the handler.
  The GET route gate includes auditor, which is why the GET invariants
  must use the explicit trader-only condition instead.
```

Replace with:

```
- The hedge-counterparty read invisibility for trader is specified in the
  bullet above (empty list / 404 by-id for `{trader}`-only actors). The
  condition is **trader-specific** (NOT "lacks risk_manager") because the
  GET route gate is `require_any_role(trader, risk_manager, auditor)` —
  auditor enters the handler and is read-only on every endpoint by matrix
  definition, including hedge rows for oversight purposes.
- `commercial_partners` reads are permitted to all three human roles
  (trader, risk_manager, auditor); there is no per-row type restriction
  because every row is commercial. The risk_manager-only protection is on
  the WRITE side (kyc_status + credit/terms), not the read side — trader
  reads the full commercial partner record including its current
  `kyc_status`, `sanctions_status`, `lei_status`, and approved credit/terms
  so the order-entry UI can show compliance state.
```

- [ ] **Step 3: Run the consistency sweep for stale type-branch references**

Run: `grep -n "all 4 types\|type ∈ {customer, supplier}\|{broker, bank_br}" docs/governance.md`
Expected: no remaining reference implies "Counterparty CRUD all 4 types"; the only `{broker, bank_br}` references are the hedge-domain descriptions added in Tasks 1–2. Manually confirm each hit is intentional (hedge-domain context), not a stale single-table assumption.

- [ ] **Step 4: Commit**

```bash
git add docs/governance.md
git commit -m "docs(gov): rewrite counterparty authorization invariants for hedge + commercial domains"
```

---

## Task 3: Re-target the RFQ admission gate (kyc_status → sanctions_status)

**Files:**
- Modify: `docs/governance.md` ("Counterparty KYC gate (binding, Pilot Hard Blocker 1):" section header + the RFQ-gate scope body)

- [ ] **Step 1: Replace the section header + framing paragraph**

Anchor (match exactly):

```
Counterparty KYC gate (binding, Pilot Hard Blocker 1):

The counterparty `kyc_status` field is the constitutional gate for any
RFQ-lifecycle participation. The field already exists in the data
layer: the `KycStatus` enum is defined at
`backend/app/models/counterparty.py:23-27` (members {pending, approved,
expired, rejected}), and the mapped column on `Counterparty` is at
`backend/app/models/counterparty.py:67-71` (`nullable=False`,
`default=KycStatus.pending`). The field is exposed on the Counterparty
schema/route — what is missing is the gate that enforces its meaning.
This subsection binds that meaning constitutionally.

The gate admits ONLY `approved`. The other three members — `pending`,
`expired`, `rejected` — all deny with the same refusal semantics
described below; the difference between them is procedural (how the
counterparty arrived at that status and what the path forward is),
not gate behavior.
```

Replace with:

```
Hedge counterparty sanctions gate (binding):

SUPERSESSION NOTICE: This subsection re-targets the former "Counterparty
KYC gate (binding, Pilot Hard Blocker 1)". The constitutional KYC hard
block has MOVED to the commercial domain — see "Commercial partner KYC +
order gate (binding, Pilot Hard Blocker 1)" below. On the HEDGE domain
(`counterparties`, type ∈ {broker, bank_br}), RFQ-lifecycle admission is
now gated by the universal sanctions control, NOT by `kyc_status`. Hedge
counterparties are regulated brokers/banks; the full commercial KYC
dossier (LEI, credit) does not apply to them, but sanctions screening
applies to EVERY entity the platform transacts with.

The gate field on the hedge domain is `sanctions_status`
(`SanctionsStatus` enum, members {unscreened, clear, flagged, blocked};
`unscreened` is the default initial state, written by NO screening). The
gate ADMITS only `clear` — a `clear` written by an actual successful
screening. `blocked` denies; `flagged` denies pending risk_manager
adjudication to `clear`; and `unscreened` denies. The W1 model adds the
`unscreened` member as the column default (NOT `clear`); screening writes
only `clear`/`flagged`/`blocked`. A hedge counterparty's `sanctions_status`
is set by the sanctions-screening lifecycle (see "Sanctions screening
governance" below).
```

- [ ] **Step 2: Replace the gate-rule body so admission checks sanctions, not kyc**

Anchor (match exactly):

```
  Gate rule: any service-layer code path that creates an
  `RFQInvitation` row with `purpose ∈ {rfq_invite, refresh}` — whether
  reached through a human-issued route or invoked by the
  `service:rfq_outbound` outbound worker — MUST refuse if the target
  counterparty's `kyc_status != approved`. The HB-1 implementation
  dispatch is responsible for sweeping every admission-purpose
  invocation site and wiring the guard there. Refusal is HTTP 422
  for human-issued requests (or the equivalent application-layer
  rejection for service-driven paths). An audit event of type
  `rfq_invitation_rejected_kyc_not_approved` MUST be recorded BEFORE
  the rejection response is returned. Audit payload MUST include:
  `counterparty_id`, `kyc_status_observed`, `requesting_actor_sub`,
  `attempted_purpose` (one of `{rfq_invite, refresh}`), and `rfq_id`
  if the parent RFQ already exists. HMAC signature mandatory per
  `audit_trail_service` invariant. Outbox-purpose writes proceed
  normally with their existing audit trail; the KYC gate MUST NOT
  intercept them.
```

Replace with:

```
  Gate rule: any service-layer code path that creates an
  `RFQInvitation` row with `purpose ∈ {rfq_invite, refresh}` — whether
  reached through a human-issued route or invoked by the
  `service:rfq_outbound` outbound worker — MUST refuse unless the target
  hedge counterparty has a recorded sanctions screening whose result is
  `clear` (this denies `blocked`, `flagged`, AND an unscreened row that
  carries only a non-recorded default). The W3 dispatch is
  responsible for sweeping every admission-purpose invocation site
  (the six `assert_kyc_approved` call sites in `rfq_service.py` at
  ~580, 853, 1029, 1297, 1469, 1583) and replacing the guard with the
  sanctions check (`assert_sanctions_clear`). Refusal is HTTP 422 for
  human-issued requests (or the equivalent application-layer rejection
  for service-driven paths). An audit event of type
  `rfq_invitation_rejected_sanctions_not_cleared` MUST be recorded BEFORE
  the rejection response is returned. Audit payload MUST include:
  `counterparty_id`, `sanctions_status_observed`, `requesting_actor_sub`,
  `attempted_purpose` (one of `{rfq_invite, refresh}`), and `rfq_id`
  if the parent RFQ already exists. HMAC signature mandatory per
  `audit_trail_service` invariant. Outbox-purpose writes proceed
  normally with their existing audit trail; the sanctions gate MUST NOT
  intercept them.
```

- [ ] **Step 3: Replace the quote-ingestion + award gate paragraphs**

Anchor (match exactly):

```
- RFQ quote ingestion: inbound quotes from a counterparty whose
  `kyc_status` has dropped from `approved` since the invitation was
  issued MUST be rejected at the internal-processing boundary (after
  provider authentication succeeds at the webhook ingress; see
  Service identities above). The gate applies equally to the
  human-issued quote-submission route (`POST
  /rfqs/{rfq_id}/quotes`) and to the LLM-parsed inbound path
  downstream of `webhook_processor`. Audit event
  `rfq_quote_rejected_kyc_not_approved` with payload shape
  `{counterparty_id, kyc_status_observed, rfq_id, inbound_message_id
  (nullable for human-issued path), rejection_path,
  requesting_actor_sub (nullable for inbound/LLM path)}`. Sibling
  parity with `rfq_invitation_rejected_kyc_not_approved` and
  `rfq_award_rejected_kyc_not_approved`: the human-issued
  quote-submission path runs under a `risk_manager` JWT context so
  the actor sub is available exactly as it is on the award path and
  MUST be captured for audit attribution; the inbound/LLM path has
  no human actor, so the field is nullable. The webhook protocol
  itself is unchanged — the gate is the processing layer that
  decides whether the parsed quote persists into `RFQQuote`.

- RFQ award: the award path (`POST /rfqs/{rfq_id}/actions/award`,
  defined at `backend/app/api/routes/rfqs.py:474`) MUST refuse if the
  awarded quote's counterparty `kyc_status != approved` at the moment
  of award, even if the original invitation was created when the
  counterparty was approved. Audit event
  `rfq_award_rejected_kyc_not_approved` with payload
  `{counterparty_id, kyc_status_observed, rfq_id, quote_id,
  requesting_actor_sub}`.
```

Replace with:

```
- RFQ quote ingestion: inbound quotes from a hedge counterparty whose
  `sanctions_status` is no longer a recorded `clear` (re-screened to
  `blocked` or `flagged`) since the invitation was
  issued MUST be rejected at the internal-processing boundary (after
  provider authentication succeeds at the webhook ingress; see
  Service identities above). The gate applies equally to the
  human-issued quote-submission route (`POST
  /rfqs/{rfq_id}/quotes`) and to the LLM-parsed inbound path
  downstream of `webhook_processor`. Audit event
  `rfq_quote_rejected_sanctions_not_cleared` with payload shape
  `{counterparty_id, sanctions_status_observed, rfq_id, inbound_message_id
  (nullable for human-issued path), rejection_path,
  requesting_actor_sub (nullable for inbound/LLM path)}`. Sibling
  parity with `rfq_invitation_rejected_sanctions_not_cleared` and
  `rfq_award_rejected_sanctions_not_cleared`: the human-issued
  quote-submission path runs under a `risk_manager` JWT context so
  the actor sub is available exactly as it is on the award path and
  MUST be captured for audit attribution; the inbound/LLM path has
  no human actor, so the field is nullable. The webhook protocol
  itself is unchanged — the gate is the processing layer that
  decides whether the parsed quote persists into `RFQQuote`.

- RFQ award: the award path (`POST /rfqs/{rfq_id}/actions/award`,
  defined at `backend/app/api/routes/rfqs.py:474`) MUST refuse if the
  awarded quote's hedge counterparty `sanctions_status != clear` (or has
  no recorded `clear` screening) at the moment of award, even if the
  original invitation was created when the counterparty was clear. Audit
  event `rfq_award_rejected_sanctions_not_cleared` with payload
  `{counterparty_id, sanctions_status_observed, rfq_id, quote_id,
  requesting_actor_sub}`.
```

- [ ] **Step 4: Replace the fail-closed closing paragraph of the gate-scope block**

Anchor (match exactly):

```
The gate is fail-closed: the default `KycStatus.pending` denies, an
explicitly `expired` status denies, an explicitly `rejected` status
denies, and absence of the field (impossible per schema NOT NULL)
also denies. The only admit-path is `approved`. There is NO bypass
flag and NO config override. Operators wanting an exception MUST
first transition the counterparty's `kyc_status` to `approved` via
the status-transition path below; the gate then admits naturally.
```

Replace with:

```
The hedge sanctions gate is fail-closed against an explicit `blocked`:
a `blocked` status denies with no bypass flag and no config override.
A hedge counterparty with no recorded screening MUST NOT be admitted on
a defaulted `clear`; the W3 dispatch sets `sanctions_status` only from a
recorded screening result (see "Sanctions screening governance"), and
RFQ admission for an unscreened hedge counterparty is treated as denied
until a `clear` screening exists. Operators wanting to admit a `blocked`
counterparty MUST first remediate and re-screen (or risk_manager must
adjudicate a `flagged` result) so the recorded status becomes `clear`;
the gate then admits naturally.
```

- [ ] **Step 5: Generalize the status-transitions block to both domains**

Anchor (match exactly):

```
- `kyc_status` mutations on ANY counterparty type (transitions
  between any of the four members {pending, approved, expired,
  rejected}) are authorized only to `risk_manager`. This explicitly
  OVERRIDES the trader per-type CRUD admission for this single field
  (see trader role bullet above): trader CAN update customer/supplier
  counterparties' non-KYC fields (e.g. contact info, address) but
  CANNOT mutate `kyc_status` on any counterparty type. Auditor cannot
  mutate per matrix (read-only). Service identities
  (`service:westmetall_ingest`, `service:rfq_outbound`,
  `service:cashflow_pipeline`, `service:webhook_inbound`) have no
  Counterparty-mutation scope and therefore no `kyc_status` mutation
  scope either.

- Every transition MUST emit an audit event of type
  `counterparty_kyc_status_changed` with payload
  `{counterparty_id, previous_status, new_status,
  transition_actor_sub, reason}` where `reason` is mandatory free
  text (minimum 8 characters; enforced at the schema/service layer
  before persistence). HMAC-signed per audit-trail invariant.
```

Replace with:

```
- `kyc_status` mutations apply to `commercial_partners` ONLY (the
  commercial KYC domain). Transitions between any of the four members
  {pending, approved, expired, rejected} are authorized only to
  `risk_manager`. This explicitly OVERRIDES trader CRUD on
  `commercial_partners` for this single field (see trader role bullet
  above): trader CAN update a commercial partner's non-KYC,
  non-credit fields (e.g. contact info, address, LEI input) but CANNOT
  mutate `kyc_status`. Auditor cannot mutate per matrix (read-only).
  Service identities have no `commercial_partners`-mutation scope and
  therefore no `kyc_status` mutation scope. (Hedge `counterparties`
  retain a vestigial `kyc_status` column post-W1 but no gate reads it;
  it is scheduled for removal in a later migration.)

- A `commercial_partners` transition to `approved` is BLOCKED unless the
  partner's effective `sanctions_status` is `clear` — established EITHER by
  a successful `clear` screening OR by a risk_manager adjudication of a
  `flagged` result to `clear`. risk_manager cannot approve a partner whose
  effective `sanctions_status` is `unscreened`, `flagged`, or `blocked`; a
  `flagged` case must be adjudicated to `clear` first, and a `blocked` case
  must be remediated and re-screened (it cannot be adjudicated away).

- Every transition MUST emit an audit event of type
  `commercial_partner_kyc_status_changed` with payload
  `{commercial_partner_id, previous_status, new_status,
  transition_actor_sub, reason}` where `reason` is mandatory free
  text (minimum 8 characters; enforced at the schema/service layer
  before persistence). HMAC-signed per audit-trail invariant.
```

- [ ] **Step 6: Run the stale-reference sweep for the renamed audit events**

Run: `grep -n "rejected_kyc_not_approved\|counterparty_kyc_status_changed\|Counterparty KYC gate" docs/governance.md`
Expected: zero hits in the gate-scope body (all RFQ events now `*_rejected_sanctions_not_cleared`; the kyc transition event is `commercial_partner_kyc_status_changed`). Any remaining `*_rejected_kyc_not_approved` hit must be the commercial order gate added in Task 4 (acceptable) — confirm context.

- [ ] **Step 7: Commit**

```bash
git add docs/governance.md
git commit -m "docs(gov): re-target RFQ admission gate from kyc_status to sanctions_status (hedge sanctions gate)"
```

---

## Task 4: Add the Commercial partner KYC + order gate (new Pilot Hard Blocker 1)

**Files:**
- Modify: `docs/governance.md` (insert a new subsection immediately AFTER the status-transition block edited in Task 3, BEFORE the "Pilot scope binding" subsection)

- [ ] **Step 1: Insert the commercial gate subsection**

Anchor — insert the new block immediately BEFORE this existing line (match exactly to locate the insertion point):

```
Pilot scope binding (operational pre-condition for Pilot Hard
Blocker 1 closure):
```

Insert this block ABOVE that anchor:

```
Commercial partner KYC + order gate (binding, Pilot Hard Blocker 1):

This is the re-targeted home of the constitutional KYC hard block. A
`commercial_partner` (kind ∈ {customer, supplier}) is the source of all
commercial exposure (orders). Order creation is fail-closed against the
partner's compliance state.

Gate scope (binding): the order-creation paths — Purchase Order create
(`POST /orders/purchase`) and Sales Order create (`POST /orders/sales`)
— MUST refuse unless the referenced `commercial_partner` satisfies ALL of:

  - **Kind coherence**: a Purchase Order MUST reference a partner with
    `kind == supplier`; a Sales Order MUST reference a partner with
    `kind == customer`. A mismatch is refused (the order is buying from a
    supplier / selling to a customer; the inverse is a category error).
  - **KYC admission**: `kyc_status == approved`. The other three members
    (`pending`, `expired`, `rejected`) all deny; the default on creation
    is `pending`, so a never-approved partner is gated out.
  - **Sanctions admission**: `sanctions_status != blocked` (a `clear` or
    `flagged` partner passes the sanctions leg; `blocked` denies). Note
    that `kyc_status == approved` already implies a recorded `clear`
    screening per the transition invariant above, so the two legs are
    consistent and the `!= blocked` leg additionally catches a partner
    that WAS approved but has since been re-screened to `blocked`.

Refusal is HTTP 422. An audit event MUST be recorded BEFORE the rejection
response is returned, HMAC-signed per `audit_trail_service`:

  - `order_rejected_kyc_not_approved` when the kyc leg fails, payload
    `{commercial_partner_id, kind, order_type (PO|SO), kyc_status_observed,
    requesting_actor_sub}`.
  - `order_rejected_sanctions_blocked` when the sanctions leg fails,
    payload `{commercial_partner_id, kind, order_type, sanctions_status_observed,
    requesting_actor_sub}`.
  - `order_rejected_kind_mismatch` when kind coherence fails, payload
    `{commercial_partner_id, kind, order_type, requesting_actor_sub}`.

The audit row MUST survive the request rollback: the implementation uses
the dual-session pattern already established in
`backend/app/services/kyc_gate.py` (write the rejection audit on a
separate committed `SessionLocal`, then raise HTTPException so the outer
`unit_of_work` rolls back the failed mutation while the audit row
persists). The partner MUST be loaded via the service getter (not raw
`db.get`) so a soft-deleted partner fails closed with 404.

LEI is advisory at this gate: an invalid checksum, a lapsed GLEIF
registration, or a legal-name mismatch produces a warning surfaced to the
caller but does NOT block order creation (see "LEI validation
governance"). LEI is warn-not-block by constitutional decision.

The gate is fail-closed and has NO bypass flag and NO config override.
There is no credit-utilization leg at this gate in the current scope:
approved credit limits / approved supplier values are RECORDED and
audited (see "Credit and terms governance") but do not block order
creation by utilization; a cumulative-exposure credit gate is a separate
future amendment.
```

- [ ] **Step 2: Verify the insertion landed between the right neighbours**

Run: `grep -n "Commercial partner KYC + order gate\|Pilot scope binding\|Hedge counterparty sanctions gate" docs/governance.md`
Expected: line order is "Hedge counterparty sanctions gate" → "Commercial partner KYC + order gate" → "Pilot scope binding".

- [ ] **Step 3: Commit**

```bash
git add docs/governance.md
git commit -m "docs(gov): add commercial partner KYC + order gate (re-targeted Pilot Hard Blocker 1)"
```

---

## Task 5: Add the Sanctions screening governance subsection

**Files:**
- Modify: `docs/governance.md` (insert AFTER the "Schema (binding):" block of the (former) KYC gate section — i.e. after the line ending "...not a code change." that closes the gate section, BEFORE "Workflow Approval gate (binding, Pilot Hard Blocker 2):")

- [ ] **Step 1: Insert the sanctions screening subsection**

Anchor — insert the new block immediately BEFORE this existing line (match exactly):

```
Workflow Approval gate (binding, Pilot Hard Blocker 2):
```

Insert this block ABOVE that anchor:

```
Sanctions screening governance (binding):

Sanctions screening is the UNIVERSAL compliance control — it applies to
every entity the platform transacts with: both hedge `counterparties`
({broker, bank_br}) and `commercial_partners` ({customer, supplier}).

Provider (binding): the hosted OpenSanctions match API
(`POST https://api.opensanctions.org/match/sanctions?algorithm=logic-v2`,
header `Authorization: ApiKey <OPENSANCTIONS_API_KEY>`). The query is a
`Company`-schema match with properties `{name, jurisdiction: <country>,
registrationNumber: <tax_id?>, leiCode: <lei?>}`. `OPENSANCTIONS_API_KEY`
is REQUIRED (non-empty) in production/staging; an APP_ENV-gated boot
validator MUST refuse to start when the feature is enabled and the key is
absent, in the same shape as the `AUDIT_SIGNING_KEY` validator.

Decoupling (binding): screening is a SEPARATE audited operation, never an
inline dependency of a gate. Screening writes a `sanctions_status` onto
the entity; the RFQ admission gate and the commercial order gate READ the
stored `sanctions_status`. This means the external API being unreachable
can NEVER take down order creation or RFQ admission — those paths read
the last recorded status. Screening triggers: (a) on entity create, (b) a
manual re-screen endpoint, (c) a scheduled daily re-screen running in the
existing `scheduler` service (`SCHEDULER_DISABLED=false`), never in web
workers.

No silent fallback (binding): a screening invocation that errors
(network/HTTP/parse failure) MUST record a screening record with
`status = error` and `error_detail`, and MUST raise — it MUST NOT set
`sanctions_status = clear` by default. A `clear` status is only ever
written from a successful screening that returned no above-threshold
match.

Result mapping (binding ranges; exact thresholds fixed in the W3
dispatch): no match → `clear`; a match at or above the HARD threshold →
`blocked`; a match below the hard threshold but above the review
threshold → `flagged` (requires risk_manager adjudication to `clear` or
`blocked`). The threshold values are an implementation parameter recorded
in the W3 dispatch, not silently chosen in code.

Evidence (binding): every screening invocation persists an append-only,
immutable `sanctions_screenings` record: `{partner_type
(commercial|hedge), partner_id, screened_at, provider, algorithm,
dataset_version, query_hash, top_score, match_count, matches_json, result
(clear|flagged|blocked, NULL when status=error), actor_sub, status
(success|error), error_detail}`. The entity's `sanctions_status` is
updated ONLY from the latest SUCCESSFUL (status=success) screening's
`result`; rows with status=error are recorded for audit (with
`result=NULL`) and never overwrite `sanctions_status`. Screening records
are never updated or deleted —
reconstructability requires the full screening history. No PII beyond what
is necessary for the match query leaves the platform; the design accepts
that the hosted API receives the partner name/jurisdiction/identifiers for
the match (a consequence of the hosted-provider decision).
```

- [ ] **Step 2: Commit**

```bash
git add docs/governance.md
git commit -m "docs(gov): add sanctions screening governance (universal, hosted OpenSanctions, decoupled, immutable evidence)"
```

---

## Task 6: Add the LEI validation governance subsection

**Files:**
- Modify: `docs/governance.md` (insert immediately AFTER the sanctions screening subsection from Task 5, still BEFORE "Workflow Approval gate (binding, Pilot Hard Blocker 2):")

- [ ] **Step 1: Insert the LEI validation subsection**

Anchor — insert immediately AFTER the last line of the Task-5 block (the line ending "...a consequence of the hosted-provider decision.") and BEFORE the "Workflow Approval gate" anchor:

```
LEI validation governance (binding):

LEI (Legal Entity Identifier, ISO 17442) validation applies to
`commercial_partners` only (international-trade safety for customers and
suppliers). LEI is OPTIONAL per partner (not every domestic entity holds
one) and is WARN-NOT-BLOCK: an absent, invalid, lapsed, or name-mismatched
LEI never blocks registration or order creation.

Two-stage validation (binding):

  - Offline checksum: the LEI MUST pass the ISO 17442 / ISO 7064
    MOD 97-10 checksum (20 alphanumeric characters, last two are the
    check digits). A failed checksum sets `lei_status = invalid`.
  - Online lookup: `GET https://api.gleif.org/api/v1/lei-records/{lei}`
    (the public GLEIF API, no API key). The response yields the
    registration status (e.g. ISSUED / LAPSED) and the registered legal
    name. Map registration ISSUED → `lei_status = issued` (treated as
    valid); LAPSED → `lei_status = lapsed`. Persist the returned legal
    name in `lei_legal_name` and the check timestamp in `lei_checked_at`.

Name cross-check (advisory): if `lei_legal_name` diverges materially from
the partner `name`, surface a warning to the caller; do NOT block. The
divergence is informational for the risk_manager.

The GLEIF lookup is decoupled from any gate (like screening): it writes
`lei_status`/`lei_legal_name`/`lei_checked_at` onto the partner; no gate
hard-blocks on LEI. A GLEIF lookup error sets `lei_status = error` and
surfaces a warning — it does not fabricate a valid status.
```

- [ ] **Step 2: Commit**

```bash
git add docs/governance.md
git commit -m "docs(gov): add LEI validation governance (GLEIF, offline checksum, warn-not-block)"
```

---

## Task 7: Add the Credit and terms governance subsection

**Files:**
- Modify: `docs/governance.md` (insert immediately AFTER the LEI subsection from Task 6, still BEFORE "Workflow Approval gate (binding, Pilot Hard Blocker 2):")

- [ ] **Step 1: Insert the credit/terms subsection**

Anchor — insert immediately AFTER the last line of the Task-6 block (the line ending "...it does not fabricate a valid status.") and BEFORE the "Workflow Approval gate" anchor:

```
Credit and terms governance (binding):

Credit/terms are commercial-domain attributes on `commercial_partners`,
asymmetric by kind:

  - customer: an approved financial credit limit (`credit_limit`,
    `credit_currency`) and approved payment conditions
    (`payment_conditions`). Semantics: the maximum receivable exposure
    Alcast extends to the customer, plus the approved payment terms.
  - supplier: an approved value (`approved_value`, `approved_currency`)
    and approved terms (`approved_terms`). Semantics: the value/terms
    Alcast is authorized to commit to this supplier.

Precision (binding): all monetary credit/value fields are `Decimal`
end-to-end (Numeric columns), never `float`. This corrects the legacy
`credit_limit_usd: float` violation and conforms to the platform precision
contract.

Authorization (binding): setting or changing any credit/terms field is
risk_manager-only (trader is refused with HTTP 403, per the AUTHORIZATION
MATRIX commercial-partner invariants). Every credit/terms mutation emits
an audit event `commercial_partner_credit_approved` with payload
`{commercial_partner_id, kind, fields_changed, previous_values,
new_values, approving_actor_sub}`, HMAC-signed.

Scope boundary (binding): in the current scope credit/terms are RECORDED
and audited but do NOT gate order creation by utilization — the commercial
order gate is kyc + sanctions + kind only (see "Commercial partner KYC +
order gate"). A cumulative-exposure credit-utilization gate (refusing an
order that would push aggregate open receivable/payable beyond the
approved limit) is a SEPARATE future amendment; until it lands, no code
path may silently enforce a utilization block.
```

- [ ] **Step 2: Commit**

```bash
git add docs/governance.md
git commit -m "docs(gov): add credit and terms governance (asymmetric by kind, Decimal, risk_manager-approved, utilization gate deferred)"
```

---

## Task 8: Re-map the Pilot scope binding across the two domains

**Files:**
- Modify: `docs/governance.md` ("Pilot scope binding (operational pre-condition for Pilot Hard Blocker 1 closure):" subsection)

- [ ] **Step 1: Replace the pilot-scope body**

Anchor (match exactly):

```
The 8 counterparties enumerated in
`docs/2026-05-tech-lead-executive-analysis.md` §4 — Stonex Financial,
Marex, Banco BS2, Itaú, Alecar, Rusal, Casa do Alumínio, Aluminios
del Mexico — MUST be persisted with `kyc_status = approved` BEFORE
pilot launch. This persistence is an operational pre-condition
recorded in §7 of the pilot brief as part of the risk_manager
sign-off. Any counterparty present in the platform but NOT in this
list remains at default `kyc_status = pending` and is therefore
gated out of every RFQ lifecycle event by the rules above. Adding a
9th pilot counterparty is governed by §4 of the pilot brief (requires
re-signature) AND by an explicit `kyc_status = approved` persistence
event with audit trail.
```

Replace with:

```
The 8 pilot entities enumerated in
`docs/2026-05-tech-lead-executive-analysis.md` §4 split across the two
domains by their economic role. The W1 migration places each entity in
the correct table; the risk_manager sign-off (§7 of the pilot brief)
records the per-domain pre-condition below.

  - HEDGE counterparties (`counterparties`, broker/bank — RFQ recipients):
    Stonex Financial, Marex, Banco BS2, Itaú. Each MUST have a recorded
    sanctions screening with result `clear` BEFORE pilot launch. An
    unscreened or `blocked` hedge counterparty is gated out of every RFQ
    lifecycle event by the hedge sanctions gate.
  - COMMERCIAL partners (`commercial_partners`, customer/supplier — order
    sources): Alecar, Rusal, Casa do Alumínio, Aluminios del Mexico. Each
    MUST be persisted with `kyc_status = approved` AND a recorded
    sanctions screening with result `clear` BEFORE pilot launch. A partner
    not meeting both is gated out of order creation by the commercial KYC
    + order gate.

(The exact hedge-vs-commercial partition of each named entity is fixed in
the W1 migration dispatch against the source list; the four/four split
above is the governing intent.) Any entity present in the platform but NOT
in this list remains at its fail-closed default (hedge: unscreened →
denied; commercial: `kyc_status = pending` → denied). Adding a 9th pilot
entity is governed by §4 of the pilot brief (requires re-signature) AND by
the explicit per-domain approval/screening persistence events with audit
trail.
```

- [ ] **Step 2: Update the "Schema (binding)" note that claims no migration is needed**

Anchor (match exactly):

```
- NO alembic migration is required for the gate itself. The
  `Counterparty.kyc_status` column and `KycStatus` enum already exist
  (introduced in the Phase A1 Counterparty model creation). The
  HB-1 implementation dispatch therefore prescribes service-layer
  guards + audit-event wiring + tests; it does NOT prescribe a model
  or migration change for the gate.
```

Replace with:

```
- A migration IS required for the re-targeted model (this supersedes the
  original HB-1 "no migration" note). The W1 dispatch creates the
  `commercial_partners` and `sanctions_screenings` tables (+ enums), and
  migrates the existing customer/supplier rows out of `counterparties`
  into `commercial_partners` reusing the same UUID (so `orders.counterparty_id`
  stays valid), then repoints the `orders` FK to `commercial_partners` and
  restricts `counterparties` to {broker, bank_br}. Migrated rows are reset
  FAIL-CLOSED — commercial `kyc_status` → `pending`, and `sanctions_status`
  → an unscreened state on BOTH domains — rather than carrying a legacy
  `approved` / default-`clear` without `sanctions_screenings` evidence. The
  vestigial `counterparties.kyc_status` column is kept by W1 and dropped in
  a later migration. ENUM lifecycle for fresh Postgres follows the CLAUDE.md
  rules (explicit `.create()` before `ALTER TABLE`, explicit `CAST(... AS <enum>)`).
```

- [ ] **Step 3: Commit**

```bash
git add docs/governance.md
git commit -m "docs(gov): re-map pilot scope across hedge + commercial domains; correct migration note"
```

---

## Task 9: systemconstitucion.md consistency check

**Files:**
- Verify: `docs/systemconstitucion.md` (conditional modify only if a contradiction exists)

- [ ] **Step 1: Search the constitution for counterparty/KYC principles**

Run: `grep -ni "counterpart\|kyc\|sanction\|customer\|supplier\|broker\|credit limit\|lei" docs/systemconstitucion.md`
Expected: a list of any higher-level principles that mention these concepts.

- [ ] **Step 2: Read each hit in context and judge contradiction**

For each line returned, read ~15 lines of surrounding context. A statement is a CONTRADICTION (must fix) only if it asserts something the amendment now reverses — e.g. "KYC gates RFQ participation" stated as a top-level principle, or "counterparties are a single registry". A statement is FINE (no edit) if it is a general principle (e.g. "no mutation without evidence", "backend authoritative for economics") that the amendment upholds.

- [ ] **Step 3: Apply the minimal edit IF and ONLY IF a contradiction was found**

If a contradiction exists, edit the offending sentence to reference the two domains and the re-targeted gate, citing `docs/governance.md` as the operative detail. If NO contradiction exists, make no edit and note that in the commit body. (Do not invent edits — the constitution is deliberately terse; governance.md carries the operative detail.)

- [ ] **Step 4: Commit (only if Step 3 produced an edit)**

```bash
git add docs/systemconstitucion.md
git commit -m "docs(constitution): align counterparty/KYC principle with governance amendment (commercial vs hedge domains)"
```

If no edit was made, skip this commit and record in the PR description: "systemconstitucion.md reviewed — no contradiction, no edit required."

---

## Task 10: Final consistency sweep + amendment PR

**Files:**
- Read-only sweep over `docs/governance.md`

- [ ] **Step 1: Stale-vocabulary sweep**

Run: `grep -n "Counterparty KYC gate\|kyc_status != approved\|kyc_status = approved BEFORE\|Counterparty CRUD all 4 types\|all 4 types\|customer/supplier counterparties" docs/governance.md`
Expected: zero hits, EXCEPT intentional references inside the commercial gate (where `kyc_status == approved` is the commercial admission leg). Confirm every remaining hit is commercial-domain context, not a stale hedge/single-table assumption.

- [ ] **Step 2: Event-name parity sweep**

Run: `grep -n "_rejected_sanctions_blocked\|_rejected_kyc_not_approved\|order_rejected_kind_mismatch\|commercial_partner_kyc_status_changed\|commercial_partner_credit_approved" docs/governance.md`
Expected: the three RFQ events are all `*_rejected_sanctions_not_cleared`; the order gate has `order_rejected_kyc_not_approved`, `order_rejected_sanctions_blocked`, `order_rejected_kind_mismatch`; the kyc transition is `commercial_partner_kyc_status_changed`; the credit event is `commercial_partner_credit_approved`. No orphan `rfq_*_rejected_kyc_not_approved` remains.

- [ ] **Step 3: Cross-reference sweep**

Run: `grep -n "Hedge counterparty sanctions gate\|Commercial partner KYC + order gate\|Sanctions screening governance\|LEI validation governance\|Credit and terms governance" docs/governance.md`
Expected: each subsection title appears exactly once, and any in-text cross-reference (e.g. "see Sanctions screening governance") matches a title that exists. Fix any dangling reference.

- [ ] **Step 4: Read the full amended region once, end to end**

Read `docs/governance.md` from the "AUTHORIZATION MATRIX" header through "Workflow Approval gate (binding, Pilot Hard Blocker 2):" in one pass. Confirm the narrative flows: matrix (two domains) → hedge sanctions gate → commercial KYC + order gate → pilot scope → schema note → sanctions screening → LEI → credit/terms. Fix any ordering or duplication inline.

- [ ] **Step 5: Push the branch and open the amendment PR**

```bash
git push -u origin spec/commercial-partners-kyc-separation
gh pr create --title "docs(gov): W0 — commercial partners ↔ hedge separation + commercial KYC amendment" --body "$(cat <<'EOF'
W0 of the commercial-partners / KYC-separation effort. Amendment-only PR
(no code), per the amendment→dispatch→implementation protocol.

Encodes spec decisions D1–D6:
- Two counterparty domains in the AUTHORIZATION MATRIX (hedge `counterparties`
  broker/bank, risk_manager-owned; `commercial_partners` customer/supplier,
  trader-owned).
- RFQ admission gate re-targeted: `kyc_status` → `sanctions_status != blocked`
  (hedge sanctions gate).
- New commercial partner KYC + order gate (fail-closed: kyc approved +
  sanctions not blocked + kind coherence; re-targeted Pilot Hard Blocker 1).
- Sanctions screening governance (universal, hosted OpenSanctions, decoupled,
  immutable evidence, no silent fallback).
- LEI validation governance (GLEIF, offline checksum, warn-not-block).
- Credit/terms governance (asymmetric by kind, Decimal, risk_manager-approved,
  utilization gate deferred).
- Pilot scope re-mapped across both domains; migration note corrected.

Spec: docs/superpowers/specs/2026-05-29-commercial-partners-kyc-separation-design.md
Plan: docs/superpowers/plans/2026-05-29-w0-governance-amendment.md

Downstream waves W1–W6 implement the code that conforms to this contract.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 6: Await Codex Connector review**

Per the repo protocol (review gates as of 2026-05-26): Codex Connector is the sole gate. A `+1` reaction on the PR = acceptance; `eyes` = processing (NOT acceptance). Query `/issues/{N}/reactions`, not just `/pulls/{N}/reviews`. Absorb any P1/P2 findings before merge.

---

## Self-Review (completed by plan author)

**1. Spec coverage** — every spec section maps to a task:
- §2 D1 (KYC re-targeting) → Tasks 3 (hedge sanctions gate) + 4 (commercial gate).
- §2 D2 (data model) → governed by the corrected migration note in Task 8 Step 2 (the model itself is W1 code, out of W0 scope).
- §2 D3 (commercial gate) → Task 4.
- §2 D4 (OpenSanctions hosted, decoupled) → Task 5.
- §2 D5 (record credit now) → Task 7.
- §2 D6 (no hotfix) → no governance text needed (sequencing decision; recorded in spec §6 / plan scope note).
- §3 (amendment items 1–6) → Tasks 1–8.
- §6 (RBAC) → Tasks 1–2.
- §5.2 sanctions_screenings evidence shape → Task 5 (governance-level); table DDL is W1.
- LEI (§7 services) → Task 6. Credit (§7) → Task 7. Pilot re-map → Task 8.

**2. Placeholder scan** — no "TBD/TODO/handle appropriately". The only deferral is the sanctions score THRESHOLD values, explicitly bound to the W3 dispatch in Task 5 by constitutional decision (ranges given: clear / flagged / blocked), which is correct governance granularity, not a placeholder.

**3. Type/name consistency** — audit event names are consistent across Tasks 3/4/8/10: RFQ events `rfq_{invitation,quote,award}_rejected_sanctions_not_cleared`; order events `order_rejected_{kyc_not_approved,sanctions_blocked,kind_mismatch}`; transition `commercial_partner_kyc_status_changed`; credit `commercial_partner_credit_approved`. Field names (`sanctions_status`, `kyc_status`, `lei_status`, `credit_limit`, `approved_value`) match the spec §5.1.

**Note for the executor:** This wave is docs-only. There is intentionally no `pytest`/`npm` step — verification is the grep sweeps + the end-to-end read (Task 10) + the Codex PR review. Do NOT add code or tests in this wave; W1 carries the model + migration + tests that conform to this amendment.
