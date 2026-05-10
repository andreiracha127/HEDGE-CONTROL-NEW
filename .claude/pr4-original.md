# Phase A2 — PR #4 Dispatch — Outbound Evidence & Canonical Identifier

**Wave:** 1 (foundational, no upstream dependencies — but largest scope)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-06
**Findings covered:** J-A2-05 (T1, outbound `RFQ#`) + J-A2-07 (T1, send-before-persist + sent_at) + J-A2-08 (T1, reject_quote evidence destruction) + J-A2-OPUS-02 (T1, action message persistence)
**Branch name:** `audit-a2/outbound-evidence`
**Base:** `main` (latest, currently `9f67357`)

---

## 1. Mission

Make every outbound RFQ-pipeline message **persisted before sending** (or persisted-and-updated as the source of truth) and **prefixed with the canonical identifier `RFQ#<rfq_number>`** before it leaves the process. Stop using `session.delete()` on `RFQQuote` rows; quotes are economic evidence and must be preserved through state, not erased. Persist the action messages (`notify_award`, `notify_reject`, `reject_quote` outbound) as the constitution requires (§2.3 — messages are evidence, not UI artifacts).

This is the largest Wave 1 PR. It touches `RFQService.create`, `RFQService.refresh`, `RFQService.refresh_counterparty`, `RFQService.reject_quote`, `RFQOrchestrator.notify_award`, `RFQOrchestrator.notify_reject`, the `RFQInvitation` and `RFQQuote` models, and ships a migration. It runs in parallel with PR-1, PR-2, PR-3; **rebase coordination with PR-1 is required** because both touch `RFQQuote`.

**Persona:** Senior software engineer building an institutional trading platform. Constitution `docs/governance.md` is supreme authority — **RFQ SYSTEM § Message Governance** (governance.md:111-115, "All RFQ invitations are persisted; terms sent = terms stored; messages are evidence, not UI artifacts"), **RFQ SYSTEM § Correlation** (governance.md:117-121, canonical identifier mandatory), **GOVERNANCE HARD FAILS** (governance.md:159-174, "evidence missing" / "no silent fallback"), **OUTPUT CONTRACT** (governance.md:208-217, precise + audit-friendly).

> **Note on §-numbering throughout this dispatch:** `governance.md` does **not** use numbered subsections. The `§2.X` labels below are this dispatch's internal mnemonics. Mapping:
> - `§2.3` → **RFQ SYSTEM § Message Governance** (governance.md:111-115)
> - `§2.4` → **RFQ SYSTEM § Correlation** (governance.md:117-121)
> - `§2.6` → **GOVERNANCE HARD FAILS** (governance.md:159-174)
> - `§2.7` → **OUTPUT CONTRACT** (governance.md:208-217)

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-06-phase-a2-jury-verdict.md`** — §2 J-A2-05 (convergent T1, outbound canonical id), §2 J-A2-07 (convergent T1, send-before-persist + sent_at), §2 J-A2-08 (convergent T1, reject_quote hard-delete), §3 J-A2-OPUS-02 (Opus-only T1, action message persistence). Read all four in full.
- **`docs/governance.md`** — binding sections: **RFQ SYSTEM § Message Governance**, **RFQ SYSTEM § Correlation**, **GOVERNANCE HARD FAILS**, **OUTPUT CONTRACT**. See §1 for `§2.X` mnemonic mapping.
- **`backend/app/services/rfq_service.py:330-544`** — `RFQService.create` (send-before-persist + fallback body without `RFQ#`).
- **`backend/app/services/rfq_service.py:705-802`** — `RFQService.refresh` (uses `RFQ#` in header but body is `text_pt`/`text_en` without prefix).
- **`backend/app/services/rfq_service.py:879-975`** — `RFQService.refresh_counterparty` (override with `_pick_action_message` after building `RFQ#` header).
- **`backend/app/services/rfq_service.py:808-877`** — `RFQService.reject_quote` (uses `_pick_action_message`, calls `session.delete(quote)`).
- **`backend/app/services/rfq_service.py:69-74`** — `_pick_action_message` (canned PT/EN templates, no `rfq_number` parameter).
- **`backend/app/services/rfq_service.py:53`** (and read full body) — `_DEFAULT_MESSAGES` constant. Verify whether the templates contain a `{rfq_number}` placeholder or are fully canned.
- **`backend/app/services/rfq_orchestrator.py:561-606`** — `notify_award` (LLM-generated, no persistence).
- **`backend/app/services/rfq_orchestrator.py:608-636`** — `notify_reject` (LLM-generated, no persistence).
- **`backend/app/models/rfqs.py:99-132`** — `RFQInvitation` model. Note `sent_at: nullable=False`, `provider_message_id: nullable=False`.
- **`backend/app/models/quotes.py:10-22`** — `RFQQuote` model (currently no state, no soft-delete). Coordinate with PR-1 author since PR-1 also edits this file.
- **`backend/alembic/versions/004_create_rfq_tables.py`** — original RFQ table creation, declares `sent_at NOT NULL`. Read to confirm; the jury observed no later migration relaxes it.

---

## 3. Scope IN — what PR-4 ships

> **Line-number disclaimer:** all line numbers below are approximate at the time of authoring (`9f67357`). Validation against the actual codebase shows drift up to ~20 lines on some references (notably the `has_sent` block in `RFQService.create` referenced as 506-516 — the **actual** line is ~526-534). **Locate edits by symbol / identifier first** (function name, attribute name, literal string). A `grep -n` on the cited symbol is the source of truth — the line numbers are advisory only.

### 3.1 Canonical-id injection helper

Add a single helper used by every send path:

```python
# backend/app/services/rfq_service.py (top of file or in a new app/services/_rfq_text.py module)
def prefix_with_canonical_id(body: str, rfq_number: str) -> str:
    """Ensure the outbound message starts with `RFQ#<rfq_number>`.

    If the body already begins with the canonical id (after optional
    whitespace), return as-is. Otherwise prepend `RFQ#<rfq_number> — `.
    Idempotent. Pure function — does not touch the DB.
    """
    canonical = f"RFQ#{rfq_number}"
    stripped = body.lstrip()
    if stripped.startswith(canonical):
        return body
    return f"{canonical} — {body}"
```

Use this helper at every `WhatsAppService.send_text_message(... text=...)` call site **after** computing `message_body`, **before** the network call, **and** persist the helper's output (not the unprefixed input) to `RFQInvitation.message_body`. The output is the evidence; that is what gets stored.

**Sites that must call `prefix_with_canonical_id`:**
- `RFQService.create` — `rfq_service.py:484-487` (also fix the fallback at `474-478` which currently writes `RFQ {rfq_number}` without `#`)
- `RFQService.refresh` — `rfq_service.py:763-768`
- `RFQService.refresh_counterparty` — `rfq_service.py:937-942`
- `RFQService.reject_quote` — `rfq_service.py:840-844` (the `_pick_action_message` site)
- `RFQOrchestrator.notify_award` — `rfq_orchestrator.py:594-606`
- `RFQOrchestrator.notify_reject` — `rfq_orchestrator.py:629-637`

After PR-4, `grep -nE "WhatsAppService.send_text_message|_pick_action_message" backend/app/services/rfq_*.py` should show every output going through `prefix_with_canonical_id` first. **Do NOT rely on `_DEFAULT_MESSAGES` templates carrying `RFQ#` themselves** — keep the helper at the call site; templates remain about content, the prefix is a transport-level invariant.

### 3.2 Persist before send — outbox pattern on `RFQInvitation`

Convert each send path from "send → if success persist with sent_at; if failure persist with sent_at=None" to:

1. Construct `RFQInvitation` with `send_status=RFQInvitationStatus.queued`, `sent_at=NULL`, `provider_message_id=NULL`, `message_body=<final, prefixed text>`. Add to session and `flush()` (durable in this transaction).
2. `result = WhatsAppService.send_text_message(...)`.
3. If `result.success`: update the **same row** with `send_status=sent`, `sent_at=now_utc()`, `provider_message_id=result.provider_message_id`. Otherwise: `send_status=failed`, leave `sent_at=NULL`, optionally store `result.error_code/message` in a new `failure_reason` column or a structured log link.
4. Do NOT raise on send failure inside the loop unless the failure is structural (network unreachable for all, etc.); a single failed send must not roll back the entire RFQ creation. Currently the row was only inserted on a successful path; with the outbox change the row exists either way.

This requires the schema changes in §3.4.

**Apply the pattern to:**
- `RFQService.create` (loop over `payload.invitations`, lines 449-505)
- `RFQService.refresh` (loop over `recipients.values()`, lines 742-797)
- `RFQService.refresh_counterparty` (single counterparty, lines 920-972)

### 3.3 `reject_quote`: preserve quote evidence, persist outbound message

**Stop deleting quote rows.** Replace `session.delete(quote)` at `rfq_service.py:860` with a state transition. Add to `RFQQuote` model:

```python
# backend/app/models/quotes.py
class QuoteState(enum.Enum):
    active = "active"
    rejected = "rejected"

class RFQQuote(Base):
    ...
    state: Mapped[QuoteState] = mapped_column(
        Enum(QuoteState, name="rfq_quote_state"),
        nullable=False,
        server_default="active",
    )
    rejected_at: Mapped[DateTime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejected_reason: Mapped[str | None] = mapped_column(String(length=128), nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String(length=64), nullable=True)
```

In `reject_quote`, replace the delete with:

```python
quote.state = QuoteState.rejected
quote.rejected_at = now_utc()
quote.rejected_reason = "manual_reject"  # or accept a reason argument if the route surfaces one
quote.rejected_by = user_id  # add user_id parameter to reject_quote signature; thread from route
```

**Update `RFQService.select_latest_quotes_by_counterparty` and the ranking paths** (`compute_trade_ranking`, `compute_spread_ranking`) to filter `RFQQuote.state == QuoteState.active`. The "remaining quotes" count at `reject_quote:866-871` must also filter on `state == active` so the `quoted → sent` revert kicks in correctly.

**Persist the outbound reject message** to `RFQInvitation` (the same table — see §3.4 purpose discussion). Use the outbox pattern from §3.2.

### 3.4 Schema changes on `RFQInvitation` and `RFQQuote`

**`RFQInvitation`** (`backend/app/models/rfqs.py:99-132`):
- `sent_at`: change to `nullable=True` (NULL while queued/failed; populated only on success).
- `provider_message_id`: change to `nullable=True` (NULL while queued/failed).
- Add `purpose: Mapped[RFQInvitationPurpose] = mapped_column(Enum(...), nullable=False, server_default="rfq_invite")` — values: `"rfq_invite"`, `"refresh"`, `"reject_quote"`, `"award_notify"`, `"reject_notify"`. This lets every outbound action share the same evidence table without ambiguity at audit time.
- (Optional, recommended) `failure_reason: Mapped[str | None] = mapped_column(String(length=256), nullable=True)`.

**`RFQQuote`** (`backend/app/models/quotes.py:10-22`):
- Add `state`, `rejected_at`, `rejected_reason`, `rejected_by` per §3.3.

**Migration** `036_rfq_outbound_evidence` (revision string; `down_revision = "032_linkage_capacity_live_filter"` — coordinate `alembic heads` during rebase since PR-1 will use 033, PR-2 may use 034, PR-3 will use 035):

```python
def upgrade():
    # RFQ invitation: relax NOT NULL on sent_at and provider_message_id, add purpose
    op.alter_column("rfq_invitations", "sent_at", existing_type=sa.DateTime(timezone=True), nullable=True)
    op.alter_column("rfq_invitations", "provider_message_id", existing_type=sa.String(length=128), nullable=True)
    op.add_column(
        "rfq_invitations",
        sa.Column(
            "purpose",
            sa.Enum("rfq_invite", "refresh", "reject_quote", "award_notify", "reject_notify",
                    name="rfq_invitation_purpose"),
            nullable=False,
            server_default="rfq_invite",
        ),
    )
    op.add_column(
        "rfq_invitations",
        sa.Column("failure_reason", sa.String(length=256), nullable=True),
    )

    # RFQ quote: state, rejected_at, rejected_reason, rejected_by
    op.add_column(
        "rfq_quotes",
        sa.Column(
            "state",
            sa.Enum("active", "rejected", name="rfq_quote_state"),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column("rfq_quotes", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("rfq_quotes", sa.Column("rejected_reason", sa.String(length=128), nullable=True))
    op.add_column("rfq_quotes", sa.Column("rejected_by", sa.String(length=64), nullable=True))


def downgrade():
    op.drop_column("rfq_quotes", "rejected_by")
    op.drop_column("rfq_quotes", "rejected_reason")
    op.drop_column("rfq_quotes", "rejected_at")
    op.drop_column("rfq_quotes", "state")
    op.execute("DROP TYPE IF EXISTS rfq_quote_state")
    op.drop_column("rfq_invitations", "failure_reason")
    op.drop_column("rfq_invitations", "purpose")
    op.execute("DROP TYPE IF EXISTS rfq_invitation_purpose")
    op.alter_column("rfq_invitations", "provider_message_id", existing_type=sa.String(length=128), nullable=False, server_default="")
    op.alter_column("rfq_invitations", "sent_at", existing_type=sa.DateTime(timezone=True), nullable=False)
```

Skip on SQLite if the existing migration pattern in 025 does so (`if bind.dialect.name != "postgresql": return`).

### 3.5 Persist `notify_award` and `notify_reject` outbound

In `backend/app/services/rfq_orchestrator.py`:

- `notify_award`:
  ```python
  message = LLMAgent.generate_outbound_message(...)
  message = prefix_with_canonical_id(message, rfq.rfq_number)
  invitation_row = RFQInvitation(
      rfq_id=rfq.id, rfq_number=rfq.rfq_number,
      counterparty_id=cp_uuid,
      recipient_name=invitation.recipient_name,
      recipient_phone=invitation.recipient_phone,
      channel=RFQInvitationChannel.whatsapp,
      message_body=message,
      provider_message_id=None,
      send_status=RFQInvitationStatus.queued,
      sent_at=None,
      idempotency_key=f"award-notify:{rfq.rfq_number}:{cp_uuid}",
      purpose=RFQInvitationPurpose.award_notify,
  )
  session.add(invitation_row)
  session.flush()
  result = WhatsAppService.send_text_message(...)
  if result.success:
      invitation_row.send_status = RFQInvitationStatus.sent
      invitation_row.sent_at = now_utc()
      invitation_row.provider_message_id = result.provider_message_id
  else:
      invitation_row.send_status = RFQInvitationStatus.failed
      invitation_row.failure_reason = f"{result.error_code}: {result.error_message}"
  ```

- `notify_reject`: same pattern, looped per recipient, with `purpose=reject_notify`.

The LLM-generated text concern is **deferred to Phase A4** (X-A2-J-03 in jury §8). PR-4 only ensures the **persistence** invariant; A4 will decide whether `LLMAgent.generate_outbound_message` is replaced with deterministic templating.

### 3.6 Update existing call sites that receive failures

In `RFQService.create` after the loop, the `has_sent` check (~`rfq_service.py:526-534` at `9f67357` — locate by `has_sent =` symbol; the previous draft of this dispatch cited 506-516 which is actually the `RFQInvitation` insert block above) must continue to filter `send_status == sent`. With outbox, `queued` and `failed` rows now exist; verify the filter still produces the right result — it should, since the filter is explicit on `sent`.

> **Latent NOT NULL violation discovered during validation** — flag in PR description as `[BEHAVIOR_SHIFT]`: at `rfq_service.py:~517-519`, `~798`, and `~972` (current state of code), failed-send paths assign `sent_at=None` while the model + migration 004 declare `sent_at NOT NULL`. Either the failed-send branch is untested, the DB silently accepts (unlikely on Postgres), or the production codepath crashes. The §3.4 schema change (relax `sent_at` to nullable) **resolves** this latent bug as a side effect. Call this out explicitly in the PR description so the orchestrator knows the schema change is also a latent-bug fix, not just an outbox enabler.

If any other consumer of `RFQInvitation` rows assumes `sent_at IS NOT NULL`, audit and fix. (Likely candidates: `refresh_counterparty` reads `existing` invitations to find phone — this still works with NULL `sent_at`; the orchestrator inbound query reads recipients regardless of sent_at; verify both.)

---

## 4. Scope OUT — explicitly NOT in PR-4

- **Inbound canonical-id correlation rewrite** — PR-5 (J-A2-06). PR-4 ensures every outbound *contains* `RFQ#<rfq_number>`, which is the prerequisite for PR-5's enforcement. PR-5 does the inbound parser.
- **Decimal primitives + counterparty FK on RFQQuote** — PR-1. **Coordinate at rebase**: PR-1 changes `RFQQuote.fixed_price_value` and `RFQQuote.counterparty_id`; PR-4 adds `state`, `rejected_at`, `rejected_reason`, `rejected_by`. Different fields — should rebase cleanly. If conflict, the later-merged PR rebases.
- **Contract trade_date + reference scheme** — PR-2.
- **Soft-delete on RFQ + archive route** — PR-3. PR-3 adds `RFQ.deleted_at` filtering; PR-4 does not need to touch RFQ-level soft-delete.
- **`RFQStateEvent.event_timestamp` mandatory** — PR-3.
- **Spread direction, single-leg hard-fail, auto-quote defaulting** — PR-6.
- **Award atomicity, `award_quote` canonicality, child-RFQ lifecycle** — PR-7.
- **Replacing `LLMAgent.generate_outbound_message` with deterministic templating** — Phase A4 (X-A2-J-03).
- **Replacing `_pick_action_message` canned templates with versioned message templates** — out of scope; PR-4 only adds the canonical-id prefix at the transport boundary.

---

## 5. Constitutional rules (binding)

(Mnemonic mapping per §1: `§2.3` → governance.md `RFQ SYSTEM § Message Governance`; `§2.4` → governance.md `RFQ SYSTEM § Correlation`; `§2.6` → governance.md `GOVERNANCE HARD FAILS`; `§2.7` → governance.md `OUTPUT CONTRACT`.)

- **§2.3 — Message Governance** (governance.md:111-115) — "All RFQ invitations are persisted." Today, action messages (`notify_award`, `notify_reject`, `reject_quote` outbound) are not persisted. PR-4 closes the gap. "Terms sent = terms stored." With outbox, the same string is the persisted body and the wire body — equality by construction.
- **§2.4 — Correlation** (governance.md:117-121) — "Canonical identifier `RFQ#<rfq_number>` mandatory in all outbound messages." Helper enforces this at every send call.
- **§2.6 — Hard Fails** (governance.md:159-174) — "Evidence missing" is a hard-fail. Hard-deleting `RFQQuote` is institutionally identical to evidence missing. Soft-state preserves it.
- **§2.7 — Output Contract** (governance.md:208-217) — Output precise + audit-friendly. Outbox row IS the audit artifact.

---

## 6. Acceptance criteria

- [ ] `prefix_with_canonical_id(body, rfq_number)` helper exists and is idempotent
- [ ] Every `WhatsAppService.send_text_message(... text=X)` call site routes `X` through the helper first
- [ ] Every `RFQInvitation.message_body` contains `RFQ#<rfq_number>` (verified by a model-level check or test that asserts startswith)
- [ ] `RFQService.create`, `refresh`, `refresh_counterparty` follow the outbox pattern: persist `queued` row first, send, update status. No invitation insertion happens *after* the network call.
- [ ] `RFQInvitation.sent_at` is `nullable=True` in model + DB schema. `provider_message_id` is `nullable=True`.
- [ ] `RFQInvitation.purpose` enum exists with all 5 values.
- [ ] `RFQQuote` no longer has any `session.delete(...)` invocation. State transition replaces it. `state == 'rejected'` quotes are excluded from ranking and from the `select_latest_quotes_by_counterparty` output.
- [ ] `notify_award` and `notify_reject` persist `RFQInvitation` rows with appropriate `purpose`.
- [ ] `reject_quote` persists an outbound `RFQInvitation` row with `purpose='reject_quote'`.
- [ ] Migration `036_rfq_outbound_evidence` ships; up/down/up roundtrip clean on local Postgres.
- [ ] Test asserts `RFQ#<rfq_number>` in every persisted `RFQInvitation.message_body` after `create`/`refresh`/`refresh_counterparty`/`reject_quote`/`notify_award`/`notify_reject`.
- [ ] Test asserts that a `WhatsAppService.send_text_message` failure leaves a `failed` invitation row with `sent_at IS NULL` (no rollback of RFQ creation).
- [ ] Test asserts a rejected quote is preserved in the DB with `state=rejected`, `rejected_at` set, and is invisible to ranking.
- [ ] Existing tests pass with the new schema; if a test asserted on `session.delete()` behavior, rewrite it for the new soft-state.

---

## 7. Test coverage required

- `backend/tests/test_rfqs_step1.py`:
  - `test_create_rfq_invitation_body_contains_canonical_id` (every counterparty)
  - `test_create_rfq_invitation_persisted_before_send_failure_does_not_rollback`
- `backend/tests/test_rfqs_step3.py`:
  - `test_refresh_invitation_body_contains_canonical_id`
  - `test_refresh_counterparty_invitation_body_contains_canonical_id`
  - `test_award_notify_persisted_with_canonical_id`
  - `test_reject_notify_persisted_for_each_recipient`
  - `test_reject_quote_preserves_evidence_via_state_not_delete`
  - `test_reject_quote_outbound_persisted_with_canonical_id`
- `backend/tests/test_rfqs_step2.py`:
  - `test_ranking_excludes_rejected_quotes`
  - `test_select_latest_quotes_by_counterparty_excludes_rejected`
- New test file `backend/tests/test_outbound_evidence.py`:
  - `test_prefix_with_canonical_id_idempotent`
  - `test_prefix_with_canonical_id_handles_existing_prefix_with_whitespace`
  - `test_outbox_failed_send_leaves_queued_row_with_failure_reason`
- `backend/tests/test_rfq_orchestrator.py`:
  - `test_notify_award_persists_evidence_and_prefixes_id`
  - `test_notify_reject_persists_one_row_per_recipient`

---

## 8. Critical sequencing

**Revised Wave 1 topology (post-validation, 2026-05-07):** PR-4 must merge **last** — it collides with both PR-1 and PR-3 at the file/function level. PR-2 is fully independent.

- **Strategy:** start authoring PR-4 in parallel with PR-1/PR-2/PR-3 to maximize wall-clock progress, but expect 2-3 sequential rebases before merge: rebase on PR-2 (if 034 mig conflicts), rebase on PR-1 (multiple file collisions, see below), rebase on PR-3 (reject_quote collision).
- **PR-1 ↔ PR-4 collision surface** (rebase obligatory):
  - **`backend/app/models/quotes.py`**: PR-1 changes `fixed_price_value` (Float→Numeric) and `counterparty_id` (String→UUID FK) on the same class to which PR-4 *adds* `state` / `rejected_at` / `rejected_reason` / `rejected_by`. Adjacent edits → small textual conflict, semantically compatible.
  - **`backend/app/services/rfq_service.py:compute_trade_ranking` and `compute_spread_ranking`**: **direct collision**. PR-1 rewrites sort/tie bodies for Decimal; PR-4 adds `RFQQuote.state == active` filter to the queries feeding these. **Hand-merge: keep PR-1's Decimal sort + add PR-4's state filter to the upstream query feeding the rankers.**
  - **`backend/app/services/rfq_service.py:reject_quote`**: PR-1 changes `counterparty_id` typing (currently has an `isinstance(..., str)` ternary at this site that becomes obsolete once UUID); PR-4 rewrites the function body. After rebase: drop the obsolete `isinstance` ternary AND keep PR-3's `get_live` call (see PR-3 collision below).
  - **`backend/app/schemas/rfq.py`**: PR-1 changes `fixed_price_value`/`counterparty_id` types on `RFQQuoteCreate`/`RFQQuoteRead`; PR-4 adds `state` to `RFQQuoteRead`. Adjacent edits, low conflict risk.
- **PR-3 ↔ PR-4 collision on `reject_quote`** (rebase obligatory): PR-3 swaps `RFQService.get` → `get_live` inside `reject_quote`; PR-4 rewrites the same function. **Keep PR-3's `get_live` call** when rewriting.
- **Migration ordering:** PR-4 uses `036_rfq_outbound_evidence`. After PR-1/PR-2/PR-3 merge, the head will be 035 (PR-3) — chain `down_revision = "035_rfq_state_event_timestamp_not_null"`. Adjust if any sibling does not merge as expected.
- **Downstream:** PR-5 (inbound canonical-id correlation) **requires** PR-4 to land first because PR-5 will enforce that inbound text without `RFQ#<rfq_number>` is parked. If PR-4 is not in main yet, outbound bodies might still be `RFQ {rfq_number}` (space) which would not match a strict `RFQ#` parser, and counterparties would re-send with broken correlation. PR-5 dispatches only after PR-4 merges.

---

## 9. PR shape

**Title:** `fix(audit-a2): PR-4 — outbound evidence + canonical id (J-A2-05, J-A2-07, J-A2-08, J-A2-OPUS-02)`

**Body skeleton:**

```markdown
## Summary

Persist every RFQ outbound message before sending and prefix every body with
`RFQ#<rfq_number>`. Replace `session.delete(quote)` in `reject_quote` with a
state transition so quote evidence survives. Persist `notify_award`,
`notify_reject`, and `reject_quote` outbound messages as `RFQInvitation` rows
with explicit `purpose`.

Phase A2 jury verdict (FAIL @ commit 9f67357) — addresses Tier 1 findings
J-A2-05 + J-A2-07 + J-A2-08 + J-A2-OPUS-02. Constitution §2.3, §2.4, §2.6,
§2.7.

## Files changed

- `backend/app/services/rfq_service.py` — `prefix_with_canonical_id` helper,
  outbox refactor of `create`/`refresh`/`refresh_counterparty`/`reject_quote`,
  state transition in `reject_quote`, exclude rejected from ranking
- `backend/app/services/rfq_orchestrator.py` — `notify_award`/`notify_reject`
  persistence
- `backend/app/models/rfqs.py` — `RFQInvitation.sent_at` nullable, `provider_message_id`
  nullable, `purpose` enum, `failure_reason` column
- `backend/app/models/quotes.py` — `state` enum, `rejected_at`, `rejected_reason`,
  `rejected_by`
- `backend/app/schemas/rfq.py` — surface `state` on `RFQQuoteRead` if appropriate
- `backend/alembic/versions/036_rfq_outbound_evidence.py`
- Tests: `test_rfqs_step1.py`, `test_rfqs_step2.py`, `test_rfqs_step3.py`,
  `test_outbound_evidence.py` (new), `test_rfq_orchestrator.py`

## Acceptance evidence

- [ ] All criteria from dispatch §6 met
- [ ] Migration roundtrip clean on local Postgres
- [ ] No `session.delete` on `RFQQuote` remains in the codebase
- [ ] Every outbound text routes through `prefix_with_canonical_id`

## Constitutional impact

§2.3 (terms sent = terms stored, evidence persisted), §2.4 (canonical id
mandatory), §2.6 (evidence not deleted), §2.7 (audit-friendly).

## Out of scope

- Inbound canonical-id correlation (PR-5)
- LLM templating replacement (Phase A4)
- Decimal/FK on RFQQuote (PR-1; rebase coordination)
- Contract hygiene (PR-2)
- RFQ soft-delete + archive (PR-3)
- Ranking integrity (PR-6)
- Award atomicity / canonicality (PR-7)

## Closes

J-A2-05 + J-A2-07 + J-A2-08 + J-A2-OPUS-02.
```

---

## 10. Constraints — what NOT to do

- DO NOT modify `_pick_action_message` to insert `RFQ#<rfq_number>` into the canned templates. Keep templates content-only; `prefix_with_canonical_id` enforces the transport invariant. This separation is intentional: §2.3 says terms sent = stored — the **prefix** is part of the stored body too, but it must be a single source of truth.
- DO NOT remove the `_DEFAULT_MESSAGES` constant or canned-template structure. PR-4 does not redesign messaging; it just persists and prefixes.
- DO NOT make `sent_at` non-null in any future migration without the orchestrator's authorization — keeping it nullable is the outbox invariant.
- DO NOT use `session.delete` on `RFQQuote` anywhere in the codebase post-PR. If you find a non-`reject_quote` site that deletes quotes, report to orchestrator before changing scope.
- DO NOT alter `RFQQuote.fixed_price_value` or `RFQQuote.counterparty_id` types in this PR. Those are PR-1's surface. Coordinate at rebase.
- DO NOT skip the `session.flush()` between row insertion and network call; without it, the row is not durable in the transaction and a process crash mid-send loses evidence.
- DO NOT auto-merge — wait for Codex review.
- DO NOT use `--no-verify` to skip git hooks. If a hook fails, fix and create a new commit.

---

## 11. Workflow

1. `git fetch origin && git worktree add D:\Projetos\Hedge-Control-New-pr4 origin/main && cd D:\Projetos\Hedge-Control-New-pr4 && git checkout -b audit-a2/outbound-evidence`
2. Configure `.claude/settings.local.json` per A1 worktree pattern
3. Read jury §2 J-A2-05 + §2 J-A2-07 + §2 J-A2-08 + §3 J-A2-OPUS-02 in full
4. Read `_DEFAULT_MESSAGES` body in `rfq_service.py:53-67` to understand current template structure
5. Implement `prefix_with_canonical_id` helper
6. Refactor `create` → outbox pattern; verify the fallback at line 474-478 also routes through helper
7. Refactor `refresh` and `refresh_counterparty` → outbox pattern
8. Refactor `reject_quote` → state transition + outbox-persist outbound message
9. Refactor `notify_award` and `notify_reject` in orchestrator → persist with appropriate `purpose`
10. Update `select_latest_quotes_by_counterparty` and rankers to filter `state == active`
11. Model + migration changes (`RFQInvitation.sent_at/provider_message_id/purpose/failure_reason`, `RFQQuote.state/rejected_*`)
12. `pytest backend/tests/test_rfqs_step1.py backend/tests/test_rfqs_step3.py -v` after each major edit
13. Full backend suite: `pytest backend/tests/ -v` — green except known failures
14. Migration roundtrip: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
15. Frontend regen if any schema field changes touch surfaced read schemas (e.g., `RFQQuoteRead.state`)
16. `git push -u origin audit-a2/outbound-evidence && gh pr create --base main --title "<§9 title>" --body-file <body>`
17. **STOP. Wait for Codex review.** Address each catch as a new commit. PR-4 has the largest scope of W-1; expect 6-9 catches.
18. Report back to orchestrator.

---

## 12. Final report shape

When complete, report to orchestrator:
- Branch + PR URL + final SHA
- Files touched (grouped: services / orchestrator / models / migration / schemas / tests / frontend)
- Migration roundtrip evidence
- Test pass/fail counts vs main baseline
- Codex review status + catches absorbed (Wave / Round / count)
- PR-1 rebase coordination notes (if any conflict in `models/quotes.py`)

Keep report under 600 words.

Boa caça.
