# Phase A2 — PR #4 Dispatch — Outbound Evidence & Canonical Identifier (refreshed)

**Wave:** 1b (final outstanding W-1 PR; W-1 + W-2 already merged)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-09 (refresh of original 2026-05-06 dispatch)
**Findings covered:** J-A2-05 (T1, outbound `RFQ#`) + J-A2-07 (T1, send-before-persist + sent_at) + J-A2-08 (T1, reject_quote evidence destruction) + J-A2-OPUS-02 (T1, action message persistence)
**Branch name:** `audit-a2/outbound-evidence`
**Base:** `main` (currently `9cef9ec`, post-PR #33 alembic chain hygiene + PR #34 audit-artifacts backfill)

---

## 0. Refresh notes (read first)

This dispatch is a **factual refresh** of the original `2026-05-06-phase-a2-pr-4-outbound-evidence-canonical-id-dispatch.md` (committed on the `audit/phase-a2` branch at `39c1b9d`, never merged). The institutional purpose, scope, findings covered, schema design, and acceptance criteria are **unchanged**. What is updated:

- All file:line citations re-anchored to `main = b1e66d5` (line drift up to ~140 lines on `rfq_service.py` due to W-1 PR #28 + W-2 PR #29/#30 advancing line counts).
- Migration revision string: `036_rfq_outbound_evidence` → **`037_rfq_outbound_evidence`**, `down_revision = "036_merge_w1_heads"` (was `"032_linkage_capacity_live_filter"`).
- §8 sequencing: rewritten as **single-PR sequencing**. W-1 (PR-1/2/3 = #28/#26/#27) and W-2 (PR-6/7/8 = #29/#30/#31) and the alembic merge hotfix (PR #33) are all merged. PR-4 is now the only outstanding W-1 surface and ships against linear main; **no rebase coordination required**.
- §9 "Out of scope" pruned: references to PR-1/PR-3 rebase coordination removed; PR-6/PR-7 are no longer "future PRs" but in-main facts.
- `award_quote` (legacy non-canonical award path) was **deleted** by PR-7 (#30); references removed.
- Constitution citations (`governance.md:111-115`, `:117-121`, `:159-174`, `:208-217`) verified — **zero drift**.
- Three Codex catches absorbed against pre-merge dispatch (commit `841b574`):
  - **P1 enum-create-before-add-column** (§3.4 migration) — pattern now mirrors `017_add_rfq_channel_type_to_counterparty.py:17-18`: `sa.Enum(...).create(op.get_bind(), checkfirst=True)` before `op.add_column`, `.drop(op.get_bind(), checkfirst=True)` after `op.drop_column`.
  - **P1 reject_quote durability coupling** (§3.3) — quote state transition and queued reject outbox row must land in the SAME `session.commit()` (strategy b, not a). Splitting them allows a route-commit failure after a successful WhatsApp send to leave the counterparty informed of rejection while the quote stays active.
  - **P2 read-schema follow-through** (§3.4 + §6 + §9) — `RFQInvitationRead.provider_message_id` must become `str | None = None` in lockstep with the column relaxation; otherwise every `RFQRead` response containing a queued/failed invitation fails Pydantic validation. Add OpenAPI + frontend schema regen as a required side-output.
  - **P2 downgrade backfill** (§3.4) — `downgrade()` cannot reassert `NOT NULL` on `sent_at` / `provider_message_id` without first backfilling NULL rows that PR-4 legitimately introduces. Pattern mirrors 035 precedent: `UPDATE rfq_invitations SET provider_message_id = '' WHERE provider_message_id IS NULL` and `UPDATE rfq_invitations SET sent_at = created_at WHERE sent_at IS NULL` before `ALTER COLUMN ... SET NOT NULL`. Downgrade remains destructive (purpose + failure_reason + state + rejected_* data dropped); backfill is consistent with that one-way nature.

The Phase A2 audit-cycle artifacts (3 stage prompts + 2 findings reports + jury verdict) are now in main since PR #34 (2026-05-09). Read the jury verdict directly at `docs/audits/2026-05-06-phase-a2-jury-verdict.md`. The four findings PR-4 closes (J-A2-05, J-A2-07, J-A2-08, J-A2-OPUS-02) are authoritative as written there.

---

## 1. Mission

Make every outbound RFQ-pipeline message **persisted before sending** (or persisted-and-updated as the source of truth) and **prefixed with the canonical identifier `RFQ#<rfq_number>`** before it leaves the process. Stop using `session.delete()` on `RFQQuote` rows; quotes are economic evidence and must be preserved through state, not erased. Persist the action messages (`notify_award`, `notify_reject`, `reject_quote` outbound) as the constitution requires — messages are evidence, not UI artifacts.

This PR touches `RFQService.create`, `RFQService.refresh`, `RFQService.refresh_counterparty`, `RFQService.reject_quote`, `RFQOrchestrator.notify_award`, `RFQOrchestrator.notify_reject`, the `RFQInvitation` and `RFQQuote` models, and ships a single migration. Because PR-1/2/3 and PR-6/7/8 already merged, **PR-4 ships against linear main with no sibling-PR rebase coordination**.

**Persona:** Senior software engineer building an institutional trading platform. Constitution `docs/governance.md` is supreme authority — **RFQ SYSTEM § Message Governance** (governance.md:111-115, "All RFQ invitations are persisted; terms sent = terms stored; messages are evidence, not UI artifacts"), **RFQ SYSTEM § Correlation** (governance.md:117-121, canonical identifier mandatory), **GOVERNANCE HARD FAILS** (governance.md:159-174, "evidence missing" / "no silent fallback"), **OUTPUT CONTRACT** (governance.md:208-217, precise + audit-friendly).

> **Note on §-numbering throughout this dispatch:** `governance.md` does **not** use numbered subsections. The `§2.X` labels below are this dispatch's internal mnemonics. Mapping:
> - `§2.3` → **RFQ SYSTEM § Message Governance** (governance.md:111-115)
> - `§2.4` → **RFQ SYSTEM § Correlation** (governance.md:117-121)
> - `§2.6` → **GOVERNANCE HARD FAILS** (governance.md:159-174)
> - `§2.7` → **OUTPUT CONTRACT** (governance.md:208-217)

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-06-phase-a2-jury-verdict.md`** — §2 J-A2-05 (convergent T1, outbound canonical id), §2 J-A2-07 (convergent T1, send-before-persist + sent_at), §2 J-A2-08 (convergent T1, reject_quote hard-delete), §3 J-A2-OPUS-02 (Opus-only T1, action message persistence). Read all four in full.
- **`docs/governance.md`** — binding sections: **RFQ SYSTEM § Message Governance** (lines 111-115), **RFQ SYSTEM § Correlation** (lines 117-121), **GOVERNANCE HARD FAILS** (lines 159-174), **OUTPUT CONTRACT** (lines 208-217). See §1 for `§2.X` mnemonic mapping.
- **`backend/app/services/rfq_service.py:366-581`** — `RFQService.create` (send-before-persist + fallback body without `RFQ#`).
- **`backend/app/services/rfq_service.py:844-941`** — `RFQService.refresh` (uses `RFQ#` in header but body is `text_pt`/`text_en` without prefix).
- **`backend/app/services/rfq_service.py:1018-1114`** — `RFQService.refresh_counterparty` (uses `_pick_action_message`).
- **`backend/app/services/rfq_service.py:947-1016`** — `RFQService.reject_quote` (uses `_pick_action_message`, calls `session.delete(quote)` at line 999).
- **`backend/app/services/rfq_service.py:73-78`** — `_pick_action_message` (canned PT/EN templates, no `rfq_number` parameter).
- **`backend/app/services/rfq_service.py:58-71`** — `_DEFAULT_MESSAGES` constant. Templates are content-only (no `{rfq_number}` placeholder); the canonical-id prefix is a transport-level concern (§3.1).
- **`backend/app/services/rfq_orchestrator.py:674-720`** — `notify_award` (LLM-generated, no persistence; the `LLMAgent.generate_outbound_message` + `WhatsAppService.send_text_message` block).
- **`backend/app/services/rfq_orchestrator.py:721-749`** — `notify_reject` (LLM-generated, no persistence; loops over deduped recipients).
- **`backend/app/models/rfqs.py:109-142`** — `RFQInvitation` model. Note `sent_at: nullable=False`, `provider_message_id: nullable=False` — both still NOT NULL on `b1e66d5`.
- **`backend/app/models/quotes.py:15-35`** — `RFQQuote` model. PR-1 (#28) already shipped Decimal `fixed_price_value` and UUID FK `counterparty_id`; PR-4 layers `state` + `rejected_*` on top — non-overlapping columns, no rebase coordination.
- **`backend/alembic/versions/004_create_rfq_tables.py`** — original RFQ table creation, declares `sent_at NOT NULL`. Read to confirm; no later migration relaxes it.
- **`backend/alembic/versions/036_merge_w1_heads.py`** — current alembic head (no-op merge of W-1 forked heads `033` + `035`). PR-4's migration chains off this.

---

## 3. Scope IN — what PR-4 ships

> **Line-number disclaimer:** all line numbers below are validated at `b1e66d5` (2026-05-09). They will drift if any other PR merges before PR-4. **Locate edits by symbol / identifier first** (function name, attribute name, literal string). A `grep -n` on the cited symbol is the source of truth — the line numbers are advisory only.

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
- `RFQService.create` — `rfq_service.py:520-523` (the `WhatsAppService.send_text_message` call inside the invitation loop). Also fix the fallback body at `rfq_service.py:509-512` which currently writes `RFQ {rfq.rfq_number}` (with a space, no `#`).
- `RFQService.refresh` — `rfq_service.py:904-907`.
- `RFQService.refresh_counterparty` — `rfq_service.py:1078-1081`.
- `RFQService.reject_quote` — `rfq_service.py:981-983` (the `_pick_action_message` site immediately preceding `WhatsAppService.send_text_message`).
- `RFQOrchestrator.notify_award` — `rfq_orchestrator.py:709-720` (the `LLMAgent.generate_outbound_message` → `WhatsAppService.send_text_message` block).
- `RFQOrchestrator.notify_reject` — `rfq_orchestrator.py:743-750` (per-recipient loop body).

After PR-4, `grep -nE "WhatsAppService.send_text_message|_pick_action_message|LLMAgent.generate_outbound_message" backend/app/services/rfq_*.py` should show every call site whose text output passes through `prefix_with_canonical_id` first. **Do NOT rely on `_DEFAULT_MESSAGES` templates carrying `RFQ#` themselves** — keep the helper at the call site; templates remain about content, the prefix is a transport-level invariant.

### 3.2 Persist before send — **durable** outbox pattern on `RFQInvitation`

The queued `RFQInvitation` row containing `message_body` must be **durably committed to the database before `WhatsAppService.send_text_message` is invoked**. `session.flush()` alone is **NOT sufficient** — it makes the row visible within the current transaction but a process crash, exception, or downstream rollback between the WhatsApp send and the route's eventual `commit()` would discard the queued row, leaving the counterparty with a message and the system with no evidence. That is the precise §2.3 / §2.6 violation PR-4 exists to close; a flush-only pattern leaves the bug in place at a different layer.

**Required pattern** (per send call site):

1. **Persist the queued row in a transaction that commits before the network call.** Acceptable implementation strategies:
   - **(a) Separate `SessionLocal()` for the outbox write** — open a fresh session, add+commit+close. Most isolated; zero impact on the enclosing transaction. Required for orchestrator paths (`notify_award` / `notify_reject`) which have no enclosing route transaction guaranteed.
   - **(b) Service-side checkpoint commit** — service calls `session.commit()` after adding the queued row, then proceeds. Breaks the strict UoW pattern (route-only commit) but is institutionally acceptable for outbox checkpoints because the row MUST survive subsequent failures, and the constitutional invariant (§2.3) outranks the architectural preference.
   - **(c) Two-phase route transaction** — restructure the route to commit the RFQ + queued invitations as transaction-1, iterate WhatsApp sends + status updates as transaction-2. Cleanest UoW-respecting option for `RFQService.create` (which needs RFQ atomicity with its invitations); requires route-level coordination.

   Choose (a) for `notify_award` / `notify_reject`. Choose (b) for `reject_quote` so the **quote state transition and the queued reject outbox row land in the SAME durable checkpoint** (see §3.3 below — they cannot be split). Choose (b) or (c) for `RFQService.create` / `refresh` / `refresh_counterparty`. Whichever pattern is chosen, the **fresh-session readback test (§7)** must demonstrate that the row is durable before `send_text_message` returns.

   Example (pattern a):
   ```python
   from app.core.database import SessionLocal

   def _persist_outbox_queued(rfq_id, rfq_number, ..., message_body, purpose, idempotency_key) -> UUID:
       outbox_session = SessionLocal()
       try:
           row = RFQInvitation(
               rfq_id=rfq_id, rfq_number=rfq_number,
               ...,
               send_status=RFQInvitationStatus.queued,
               sent_at=None,
               provider_message_id=None,
               message_body=message_body,
               purpose=purpose,
               idempotency_key=idempotency_key,
           )
           outbox_session.add(row)
           outbox_session.commit()
           return row.id
       finally:
           outbox_session.close()
   ```

2. `result = WhatsAppService.send_text_message(...)`. The row is durable; subsequent failures cannot lose evidence.

3. **Update status** in the route's (or service's) ongoing session:
   ```python
   row = session.get(RFQInvitation, row_id)
   if result.success:
       row.send_status = RFQInvitationStatus.sent
       row.sent_at = now_utc()
       row.provider_message_id = result.provider_message_id
   else:
       row.send_status = RFQInvitationStatus.failed
       row.failure_reason = f"{result.error_code}: {result.error_message}"
   # the route or service commits at boundary
   ```

   If the route's later commit fails after a successful send, the row stays as `queued` with `sent_at=NULL`. **This failure mode is institutionally MUCH milder than evidence loss**: a reconciliation worker can later flip `queued` rows to `sent` based on WhatsApp's `provider_message_id` retrieved from the provider API; no worker can recover a row that was never written. Status accuracy is a downstream audit concern; durable evidence is the §2.3 invariant PR-4 must close.

4. Do NOT raise on send failure inside the loop unless the failure is structural (network unreachable for all, etc.); a single failed send must not roll back the entire RFQ creation. With the durable-outbox change the row exists either way (queued or sent/failed); the §3.6 latent NOT NULL violation is resolved as a side effect.

This requires the schema changes in §3.4.

**Apply the pattern to:**
- `RFQService.create` — invitation loop at `rfq_service.py:487-558`. Recommended strategy: (c) two-phase route transaction so RFQ + queued invitations land atomically in tx-1 before any WhatsApp sends; status updates in tx-2.
- `RFQService.refresh` — recipient loop within `rfq_service.py:844-941` (per-recipient `RFQInvitation` insertion at 926-940). Recommended: (b) service-side checkpoint commit per recipient.
- `RFQService.refresh_counterparty` — single-counterparty body at `rfq_service.py:1018-1114` (insertion at 1100-1114). Recommended: (b) service-side checkpoint commit.

### 3.3 `reject_quote`: preserve quote evidence, persist outbound message

**Stop deleting quote rows.** Replace `session.delete(quote)` at `rfq_service.py:999` with a state transition. Add to `RFQQuote` model:

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

**Update every site that queries `RFQQuote` so rejected rows do NOT contribute to ranking, latest-quote selection, or the post-reject "remaining" count.** The pure-function rankers `compute_trade_ranking` (`rfq_service.py:160-212`) and `compute_spread_ranking` (`rfq_service.py:214-357`) consume already-fetched quote sets, so **the filter must apply at the upstream queries**, not inside the rankers themselves. The five known query sites that need `.filter(RFQQuote.state == QuoteState.active)` are:

- `rfq_service.py:145` — `get_latest_trade_quotes` (feeds `compute_trade_ranking` via `select_latest_quotes_by_counterparty`).
- `rfq_service.py:245` — `compute_spread_ranking` buy-leg query.
- `rfq_service.py:247` — `compute_spread_ranking` sell-leg query.
- `rfq_service.py:1003-1006` — `reject_quote`'s own "remaining quotes" count (drives the `quoted → sent` revert; today the count is wrong if any prior quote was already rejected because rejection deleted the row, but post-PR-4 a soft-state row would survive and inflate the count).
- `rfq_orchestrator.py:463-466` — orchestrator-side quote query (re-validate context before edit).
- `backend/app/api/routes/rfqs.py:222-223` — read route exposing quotes per RFQ; rejected quotes must remain **listable** here for forensics, but flagged via the `state` field that PR-4 surfaces on `RFQQuoteRead`. This site does NOT get a filter; the operator-visible response distinguishes active from rejected via the field.

`select_latest_quotes_by_counterparty` (`rfq_service.py:100-140`) is a pure function over a pre-fetched list and **does not need an internal filter**; the contract is "given quotes, return the latest per counterparty". The state filter belongs at the query boundary, not the in-memory selector.

**Persist the outbound reject message** to `RFQInvitation` (the same table — see §3.4 purpose discussion). Use the outbox pattern from §3.2, but with one **mandatory coupling rule**:

> **Quote state transition and reject outbox row MUST land in the same durable checkpoint.** Specifically: do NOT use strategy (a) (separate `SessionLocal()`) for the reject outbox; use strategy (b) (service-side checkpoint commit) so the SAME `session.commit()` that durably persists the queued `purpose=reject_quote` row also durably persists `quote.state = QuoteState.rejected` (+ `rejected_at`/`rejected_reason`/`rejected_by`). Order of operations within `reject_quote`:
>
> 1. Set `quote.state = QuoteState.rejected` + `rejected_at` + `rejected_reason` + `rejected_by`.
> 2. Add the queued `RFQInvitation` row (`purpose=reject_quote`, prefixed `message_body`).
> 3. `session.commit()` — both mutations land atomically.
> 4. `result = WhatsAppService.send_text_message(...)`.
> 5. Update the queued row's status (`sent`/`failed` + `sent_at`/`provider_message_id`/`failure_reason`) and commit again.
>
> **Why this rule exists:** if the reject outbox were durable in its own session (strategy a) while the state transition stayed in the route's enclosing transaction, a route-level commit failure after a successful WhatsApp send would leave the counterparty informed of a rejection while the quote remained `state=active` in the DB — eligible for ranking, eligible to win the award. That is a **convergence-loss bug worse than the evidence-loss bug** PR-4 is closing: outbound says one thing, the system state says another. Coupling the two mutations into one commit eliminates the divergence; if the commit fails, neither change persists, no message has been sent, and the operator can retry. Strategy (b) is required here even though it breaks strict UoW — the constitutional invariant (§2.3 + §2.6) outranks the architectural preference, same justification as elsewhere in §3.2.

### 3.4 Schema changes on `RFQInvitation` and `RFQQuote`

**`RFQInvitation`** (`backend/app/models/rfqs.py:109-142`):
- `sent_at`: change to `nullable=True` (NULL while queued/failed; populated only on success).
- `provider_message_id`: change to `nullable=True` (NULL while queued/failed).
- Add `purpose: Mapped[RFQInvitationPurpose] = mapped_column(Enum(...), nullable=False, server_default="rfq_invite")` — values: `"rfq_invite"`, `"refresh"`, `"reject_quote"`, `"award_notify"`, `"reject_notify"`. This lets every outbound action share the same evidence table without ambiguity at audit time.
- Add `failure_reason: Mapped[str | None] = mapped_column(String(length=256), nullable=True)`.

**Read schema follow-through** (`backend/app/schemas/rfq.py:45-60`, `RFQInvitationRead`):
- `provider_message_id: str` → `provider_message_id: str | None = None`. Today the field is non-optional; once the column relaxes to nullable, any RFQ that has even one queued/failed invitation will fail Pydantic response-validation at every route that returns `RFQRead` (which embeds `invitations: list[RFQInvitationRead]` at `rfq.py:236`). `sent_at: datetime | None = None` is already optional and needs no change.
- After this Pydantic change, regenerate the OpenAPI snapshot + frontend schema as part of the same PR (see §11 step 15).
- Surface `state` on `RFQQuoteRead` so the read route at `routes/rfqs.py:222-223` can distinguish active from rejected quotes (per §3.3).

**`RFQQuote`** (`backend/app/models/quotes.py:15-35`):
- Add `state`, `rejected_at`, `rejected_reason`, `rejected_by` per §3.3. These columns are non-overlapping with PR-1's `fixed_price_value` (Decimal) and `counterparty_id` (UUID FK), already in main.

**Migration `037_rfq_outbound_evidence`** (revision string: `"037_rfq_outbound_evidence"` — 25 chars, well under the 32-char alembic limit; `down_revision = "036_merge_w1_heads"`):

```python
"""Phase A2 PR-4: outbound evidence + canonical id schema.

Revision ID: 037_rfq_outbound_evidence
Revises: 036_merge_w1_heads
Create Date: 2026-05-09 ...
"""

revision = "037_rfq_outbound_evidence"
down_revision = "036_merge_w1_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # RFQ invitation: relax NOT NULL on sent_at and provider_message_id, add purpose + failure_reason
    # RFQ invitation: relax NOT NULLs first (low risk, no enum work needed)
    op.alter_column("rfq_invitations", "sent_at", existing_type=sa.DateTime(timezone=True), nullable=True)
    op.alter_column("rfq_invitations", "provider_message_id", existing_type=sa.String(length=128), nullable=True)

    # CRITICAL: create the PostgreSQL enum types BEFORE op.add_column references them.
    # Pattern mirrors backend/alembic/versions/017_add_rfq_channel_type_to_counterparty.py:17-18:
    # `sa.Enum(...).create(op.get_bind(), checkfirst=True)` then op.add_column.
    # Skipping this step causes Postgres `ALTER TABLE ... ADD COLUMN ... <enum>` to fail because
    # the type does not yet exist. checkfirst=True keeps it idempotent across re-runs.
    rfq_invitation_purpose = sa.Enum(
        "rfq_invite", "refresh", "reject_quote", "award_notify", "reject_notify",
        name="rfq_invitation_purpose",
    )
    rfq_invitation_purpose.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "rfq_invitations",
        sa.Column(
            "purpose",
            rfq_invitation_purpose,
            nullable=False,
            server_default="rfq_invite",
        ),
    )
    op.add_column(
        "rfq_invitations",
        sa.Column("failure_reason", sa.String(length=256), nullable=True),
    )

    rfq_quote_state = sa.Enum("active", "rejected", name="rfq_quote_state")
    rfq_quote_state.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "rfq_quotes",
        sa.Column(
            "state",
            rfq_quote_state,
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column("rfq_quotes", sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("rfq_quotes", sa.Column("rejected_reason", sa.String(length=128), nullable=True))
    op.add_column("rfq_quotes", sa.Column("rejected_by", sa.String(length=64), nullable=True))


def downgrade() -> None:
    # Drop columns first; only then drop the enum types (otherwise Postgres errors with
    # "cannot drop type ... because other objects depend on it"). Mirror 017's drop pattern:
    # `sa.Enum(name=...).drop(op.get_bind(), checkfirst=True)`.
    op.drop_column("rfq_quotes", "rejected_by")
    op.drop_column("rfq_quotes", "rejected_reason")
    op.drop_column("rfq_quotes", "rejected_at")
    op.drop_column("rfq_quotes", "state")
    sa.Enum(name="rfq_quote_state").drop(op.get_bind(), checkfirst=True)

    op.drop_column("rfq_invitations", "failure_reason")
    op.drop_column("rfq_invitations", "purpose")
    sa.Enum(name="rfq_invitation_purpose").drop(op.get_bind(), checkfirst=True)

    # Backfill NULL outbox-shape rows BEFORE reasserting NOT NULL.
    # Post-PR-4, queued/failed rows can legitimately have provider_message_id=NULL
    # and sent_at=NULL; `ALTER COLUMN ... SET NOT NULL` would fail on Postgres
    # with those rows present. Pattern mirrors 035 precedent (event_timestamp
    # backfilled from created_at before NOT NULL re-imposed).
    #
    # Downgrade is already destructive (purpose + failure_reason + state +
    # rejected_* data are dropped above), so backfilling sent_at from
    # created_at and provider_message_id from "" is consistent with the
    # one-way nature of this rollback. Operators must accept evidence loss
    # if they choose to downgrade post-deployment.
    op.execute(
        """
        UPDATE rfq_invitations
           SET provider_message_id = ''
         WHERE provider_message_id IS NULL
        """
    )
    op.execute(
        """
        UPDATE rfq_invitations
           SET sent_at = created_at
         WHERE sent_at IS NULL
        """
    )
    op.alter_column("rfq_invitations", "provider_message_id", existing_type=sa.String(length=128), nullable=False, server_default="")
    op.alter_column("rfq_invitations", "sent_at", existing_type=sa.DateTime(timezone=True), nullable=False)
```

Skip on SQLite if the existing migration pattern in 025 / 033 does so (`if bind.dialect.name != "postgresql": return`). The test fixture builds via `Base.metadata.create_all()`, not alembic, so SQLite-side correctness comes from the model declarations — the migration only needs to handle Postgres.

### 3.5 Persist `notify_award` and `notify_reject` outbound

In `backend/app/services/rfq_orchestrator.py`:

- `notify_award` (current shape at `:674-720`) — use **§3.2 strategy (a)** (separate `SessionLocal()` for the outbox write), since the orchestrator path has no enclosing route transaction guarantee:
  ```python
  message = LLMAgent.generate_outbound_message(...)
  message = prefix_with_canonical_id(message, rfq.rfq_number)
  row_id = _persist_outbox_queued(
      rfq_id=rfq.id, rfq_number=rfq.rfq_number,
      counterparty_id=cp_uuid,
      recipient_name=invitation.recipient_name,
      recipient_phone=invitation.recipient_phone,
      channel=RFQInvitationChannel.whatsapp,
      message_body=message,
      purpose=RFQInvitationPurpose.award_notify,
      idempotency_key=f"award-notify:{rfq.rfq_number}:{cp_uuid}",
  )  # commits in its own session; row is durable
  result = WhatsAppService.send_text_message(...)
  # update status in the orchestrator's session (or in another fresh session if none)
  invitation_row = session.get(RFQInvitation, row_id)
  if result.success:
      invitation_row.send_status = RFQInvitationStatus.sent
      invitation_row.sent_at = now_utc()
      invitation_row.provider_message_id = result.provider_message_id
  else:
      invitation_row.send_status = RFQInvitationStatus.failed
      invitation_row.failure_reason = f"{result.error_code}: {result.error_message}"
  ```

- `notify_reject` (current shape at `:721-749`): same pattern, looped per deduped recipient (`seen.values()` at line 743), with `purpose=RFQInvitationPurpose.reject_notify`. Each iteration is one separate-session commit before its send call.

The LLM-generated text concern is **deferred to Phase A4** (X-A2-J-03 in jury §8). PR-4 only ensures the **persistence** invariant; A4 will decide whether `LLMAgent.generate_outbound_message` is replaced with deterministic templating.

**Note:** PR-7 (#30) tightened `RFQService.award` for atomicity (`SELECT ... FOR UPDATE`, `populate_existing`, child-contract close events) but did **not** modify `notify_award` or `notify_reject` in the orchestrator. Those signatures and bodies are stable since pre-W-1 and match the original dispatch's expectations.

### 3.6 Latent NOT NULL violation — flag in PR description

Three sites today assign `sent_at=None` while the model declares `sent_at: nullable=False`:

- `rfq_service.py:553-555` — `create` invitation insertion: `sent_at=now_utc() if send_status == RFQInvitationStatus.sent else None`.
- `rfq_service.py:937` — `refresh` invitation insertion: `sent_at=now if send_status == RFQInvitationStatus.sent else None`.
- `rfq_service.py:1111` — `refresh_counterparty` invitation insertion: same pattern.

Either the failed-send branch is untested, the DB silently accepts (unlikely on Postgres), or the production codepath crashes. The §3.4 schema change (relax `sent_at` to nullable) **resolves** this latent bug as a side effect. Call this out explicitly in the PR description as `[BEHAVIOR_SHIFT]` so reviewers know the schema change is also a latent-bug fix, not just an outbox enabler.

After the §3.4 change, the `has_sent` query at `rfq_service.py:562-570` continues to work correctly — it filters on `send_status == sent`, which remains the canonical "this row reached the wire" predicate; nullability of `sent_at` does not affect the result.

If any other consumer of `RFQInvitation` rows assumes `sent_at IS NOT NULL`, audit and fix. Likely candidates: `refresh_counterparty` reads `existing` invitations to find phone — works with NULL `sent_at`; the orchestrator inbound query reads recipients regardless of `sent_at`; verify both.

---

## 4. Scope OUT — explicitly NOT in PR-4

- **Inbound canonical-id correlation rewrite** — PR-5 (J-A2-06). PR-4 ensures every outbound *contains* `RFQ#<rfq_number>`, which is the prerequisite for PR-5's enforcement. PR-5 dispatches only after PR-4 merges.
- **Decimal primitives + counterparty FK on RFQQuote** — already shipped by PR-1 (#28, in main). Do not revert.
- **Contract trade_date + reference scheme** — already shipped by PR-2 (#26, in main).
- **Soft-delete on RFQ + archive route** — already shipped by PR-3 (#27, in main). PR-3 added `RFQ.deleted_at` filtering and `RFQService.get_live`/`archive`; PR-4 does not need to touch RFQ-level soft-delete.
- **`RFQStateEvent.event_timestamp` mandatory** — already shipped by PR-3 (#27, migration `035_rfq_state_event_ts_not_null`).
- **Spread direction, single-leg hard-fail, auto-quote defaulting** — already shipped by PR-6 (#29, ranking integrity).
- **Award atomicity, child-RFQ lifecycle, `award_quote` removal** — already shipped by PR-7 (#30, award atomicity). The legacy non-canonical `award_quote` method **no longer exists** in the codebase; do not reintroduce.
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
- [ ] `RFQService.create`, `refresh`, `refresh_counterparty` follow the **durable** outbox pattern: queued `RFQInvitation` row is committed to the database (NOT just flushed) before `WhatsAppService.send_text_message` is invoked. No invitation insertion happens *after* the network call. A fresh-session readback (separate `SessionLocal()`) can find the row by id while the send is in flight.
- [ ] `notify_award` and `notify_reject` outbound use a separate-session commit (§3.2 strategy (a)) so the queued row survives any subsequent orchestrator failure.
- [ ] `reject_quote` uses strategy (b) per §3.3 coupling rule: the queued reject `RFQInvitation` row AND the `quote.state = QuoteState.rejected` transition land in the SAME `session.commit()` before `WhatsAppService.send_text_message` is invoked. A test simulates a route-level commit failure after a successful reject send and asserts that EITHER both the state transition and the outbox row persisted (commit succeeded) OR neither persisted (commit failed) — never one without the other.
- [ ] `RFQInvitation.sent_at` is `nullable=True` in model + DB schema. `provider_message_id` is `nullable=True`.
- [ ] `RFQInvitation.purpose` enum exists with all 5 values (`rfq_invite`, `refresh`, `reject_quote`, `award_notify`, `reject_notify`).
- [ ] `RFQInvitation.failure_reason` column exists (nullable String(256)).
- [ ] `RFQInvitationRead.provider_message_id` is `str | None = None` in `backend/app/schemas/rfq.py`. A test exercises `RFQRead` validation against an RFQ whose invitations include at least one `queued` row with `provider_message_id IS NULL` and asserts no `ValidationError` is raised.
- [ ] `RFQQuote` no longer has any `session.delete(...)` invocation. State transition replaces it. `state == 'rejected'` quotes are excluded from ranking and from the latest-quote selection upstream queries.
- [ ] `notify_award` and `notify_reject` persist `RFQInvitation` rows with appropriate `purpose`.
- [ ] `reject_quote` persists an outbound `RFQInvitation` row with `purpose='reject_quote'`.
- [ ] Migration `037_rfq_outbound_evidence` ships; up/down/up roundtrip clean on local Postgres. Include a roundtrip variant where a `queued` outbox row (with `sent_at=NULL` and `provider_message_id=NULL`) is inserted between upgrade and downgrade — downgrade must succeed without violating the restored NOT NULL constraints (per the §3.4 backfill UPDATE statements).
- [ ] `alembic heads` reports a single head after the migration applies.
- [ ] Test asserts `RFQ#<rfq_number>` in every persisted `RFQInvitation.message_body` after `create`/`refresh`/`refresh_counterparty`/`reject_quote`/`notify_award`/`notify_reject`.
- [ ] Test asserts that a `WhatsAppService.send_text_message` failure leaves a `failed` invitation row with `sent_at IS NULL` and `failure_reason` populated (no rollback of RFQ creation).
- [ ] Test asserts a rejected quote is preserved in the DB with `state=rejected`, `rejected_at` set, and is invisible to ranking + latest-quote selection.
- [ ] Test asserts the post-reject "remaining quotes" count at `reject_quote` filters on `state == active` so the `quoted → sent` revert kicks in correctly when all surviving quotes are rejected.
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
  - `test_select_latest_quotes_by_counterparty_consumed_with_rejected_filtered_upstream`
- New test file `backend/tests/test_outbound_evidence.py`:
  - `test_prefix_with_canonical_id_idempotent`
  - `test_prefix_with_canonical_id_handles_existing_prefix_with_whitespace`
  - `test_outbox_failed_send_leaves_queued_row_with_failure_reason`
  - `test_outbox_row_durably_committed_before_whatsapp_send` — fake `WhatsAppService.send_text_message` to assert via a **fresh `SessionLocal()`** (not the test's existing fixture session) that the corresponding `RFQInvitation` row already exists at the moment `send_text_message` is invoked. This is the §3.2 durability invariant; flush-only patterns will fail this test.
  - `test_outbox_row_survives_post_send_rollback` — with a successful send, force the route's session to roll back AFTER send returns; assert the queued row remains in the database (i.e., the queued commit was independent of the route transaction).
- `backend/tests/test_rfq_orchestrator.py`:
  - `test_notify_award_persists_evidence_and_prefixes_id`
  - `test_notify_reject_persists_one_row_per_recipient`

---

## 8. Critical sequencing

PR-4 ships against **linear main** (`b1e66d5` at authoring time). All sibling PRs from W-1 (#26, #27, #28) and W-2 (#29, #30, #31) plus the alembic merge hotfix (#33) are merged. **No rebase coordination, no migration head competition, no shared-file conflicts to anticipate.** The only concern is rebase against main if main advances during review, which is mechanical.

- **Branch base:** `origin/main` at `b1e66d5` or later.
- **Migration chain:** `037_rfq_outbound_evidence.down_revision = "036_merge_w1_heads"`. After the migration applies, `alembic heads` reports a single head: `037_rfq_outbound_evidence`.
- **Downstream dependency:** PR-5 (inbound canonical-id correlation, J-A2-06) **requires** PR-4 to land first because PR-5 enforces that inbound text without `RFQ#<rfq_number>` is parked. If PR-4 is not in main yet, outbound bodies might still be `RFQ {rfq_number}` (space) which would not match a strict `RFQ#` parser, and counterparties would re-send with broken correlation. PR-5 dispatches only after PR-4 merges.

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

Phase A2 jury verdict (FAIL @ commit `9f67357`) — addresses Tier 1 findings
J-A2-05 + J-A2-07 + J-A2-08 + J-A2-OPUS-02. Constitution §2.3, §2.4, §2.6,
§2.7. Final outstanding W-1 surface; W-1 (PR-1/2/3 = #28/#26/#27) and W-2
(PR-6/7/8 = #29/#30/#31) and the alembic chain hotfix (#33) are already in
main.

[BEHAVIOR_SHIFT] Side-effect of relaxing `RFQInvitation.sent_at` to nullable:
the latent NOT NULL violation in failed-send branches of `create` / `refresh` /
`refresh_counterparty` (assigning `sent_at=None` against a NOT NULL column)
is resolved as a no-cost fix.

## Files changed

- `backend/app/services/rfq_service.py` — `prefix_with_canonical_id` helper,
  outbox refactor of `create`/`refresh`/`refresh_counterparty`/`reject_quote`,
  state transition in `reject_quote`, exclude rejected from upstream ranking
  queries
- `backend/app/services/rfq_orchestrator.py` — `notify_award` /
  `notify_reject` persistence; orchestrator-side quote query rejected-state
  filter
- `backend/app/models/rfqs.py` — `RFQInvitation.sent_at` nullable,
  `provider_message_id` nullable, `purpose` enum, `failure_reason` column
- `backend/app/models/quotes.py` — `state` enum, `rejected_at`,
  `rejected_reason`, `rejected_by`
- `backend/app/schemas/rfq.py` — `RFQInvitationRead.provider_message_id` → `str | None`; surface `state` on `RFQQuoteRead`
- `docs/api/openapi_v1.json` + `frontend-svelte/src/lib/api/schema.d.ts` — regen after schema changes (per §11 step 15)
- `backend/app/api/routes/rfqs.py` — confirm read route surfaces state field
  (rejected quotes remain listable for forensics; no filter applied here)
- `backend/alembic/versions/037_rfq_outbound_evidence.py`
- Tests: `test_rfqs_step1.py`, `test_rfqs_step2.py`, `test_rfqs_step3.py`,
  `test_outbound_evidence.py` (new), `test_rfq_orchestrator.py`

## Acceptance evidence

- [ ] All criteria from dispatch §6 met
- [ ] Migration roundtrip clean on local Postgres
- [ ] `alembic heads` reports single head after upgrade
- [ ] No `session.delete` on `RFQQuote` remains in the codebase
- [ ] Every outbound text routes through `prefix_with_canonical_id`
- [ ] Queued `RFQInvitation` rows are **durably committed** (NOT just flushed) before any `WhatsAppService.send_text_message` call — verified by `test_outbox_row_durably_committed_before_whatsapp_send` and `test_outbox_row_survives_post_send_rollback`

## Constitutional impact

§2.3 (terms sent = terms stored, evidence persisted), §2.4 (canonical id
mandatory), §2.6 (evidence not deleted), §2.7 (audit-friendly).

## Out of scope

- Inbound canonical-id correlation (PR-5, dispatched after PR-4 merges)
- LLM templating replacement (Phase A4)

## Closes

J-A2-05 + J-A2-07 + J-A2-08 + J-A2-OPUS-02.
```

---

## 10. Constraints — what NOT to do

- DO NOT modify `_pick_action_message` to insert `RFQ#<rfq_number>` into the canned templates. Keep templates content-only; `prefix_with_canonical_id` enforces the transport invariant. This separation is intentional: §2.3 says terms sent = stored — the **prefix** is part of the stored body too, but it must be a single source of truth.
- DO NOT remove the `_DEFAULT_MESSAGES` constant or canned-template structure. PR-4 does not redesign messaging; it just persists and prefixes.
- DO NOT make `sent_at` non-null in any future migration without the orchestrator's authorization — keeping it nullable is the outbox invariant.
- DO NOT use `session.delete` on `RFQQuote` anywhere in the codebase post-PR. If you find a non-`reject_quote` site that deletes quotes, report to orchestrator before changing scope.
- DO NOT alter `RFQQuote.fixed_price_value` or `RFQQuote.counterparty_id` types — PR-1 (#28) already shipped them as `Decimal` and `UUID FK`. Reverting is forbidden.
- DO NOT reintroduce a `RFQService.award_quote` method — PR-7 (#30) deleted the legacy non-canonical award path; the canonical award is `RFQService.award` only.
- DO NOT re-fork the alembic chain. The migration must declare `down_revision = "036_merge_w1_heads"` (single string), so the head remains linear after PR-4.
- DO NOT use `session.flush()` alone before the network call. `flush()` is **not durable** — the row is rolled back if the enclosing transaction does not commit. Use one of the §3.2 strategies (separate session, service-side checkpoint commit, or two-phase route transaction) so the queued row is durably committed to the database before `WhatsAppService.send_text_message` is invoked. If the executor's first instinct is "just flush", that's the bug PR-4 exists to close — do not write that code.
- DO NOT auto-merge — wait for Codex review.
- DO NOT use `--no-verify` to skip git hooks. If a hook fails, fix and create a new commit.

---

## 11. Workflow

1. `git fetch origin && git worktree add D:\Projetos\Hedge-Control-New-pr4 origin/main && cd D:\Projetos\Hedge-Control-New-pr4 && git checkout -b audit-a2/outbound-evidence`
2. Configure `.claude/settings.local.json` per A1 worktree pattern.
3. Read jury §2 J-A2-05 + §2 J-A2-07 + §2 J-A2-08 + §3 J-A2-OPUS-02 in full (`docs/audits/2026-05-06-phase-a2-jury-verdict.md`).
4. Read `_DEFAULT_MESSAGES` body in `rfq_service.py:58-71` to confirm current template structure (PT/EN canned messages, no `{rfq_number}` placeholder).
5. Implement `prefix_with_canonical_id` helper.
6. Refactor `create` → outbox pattern; verify the fallback at `rfq_service.py:509-512` also routes through the helper.
7. Refactor `refresh` and `refresh_counterparty` → outbox pattern.
8. Refactor `reject_quote` → state transition (replace `session.delete(quote)` at line 999) + outbox-persist outbound message; thread `user_id` through the route → service.
9. Refactor `notify_award` and `notify_reject` in orchestrator → persist with appropriate `purpose`.
10. Add `RFQQuote.state == active` filter at the five upstream query sites listed in §3.3 (DO NOT add it inside the rankers themselves).
11. Model + migration changes (`RFQInvitation.sent_at`/`provider_message_id`/`purpose`/`failure_reason`, `RFQQuote.state`/`rejected_*`).
12. `pytest backend/tests/test_rfqs_step1.py backend/tests/test_rfqs_step3.py -v` after each major edit.
13. Full backend suite: `pytest backend/tests/ -v` — green except known failures.
14. Migration roundtrip on local Postgres: `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`. Confirm `alembic heads` reports single head.
15. Frontend regen if any schema field changes touch surfaced read schemas (e.g., `RFQQuoteRead.state`):
    - `python -c "from app.main import app; import json; json.dump(app.openapi(), open('docs/api/openapi_v1.json', 'w'), indent=2, sort_keys=True)"`
    - `OPENAPI_SOURCE=docs/api/openapi_v1.json node scripts/regen-schema.mjs`
16. `git push -u origin audit-a2/outbound-evidence && gh pr create --base main --title "<§9 title>" --body-file <body>`
17. **STOP. Wait for Codex review.** Address each catch as a new commit. PR-4 has the largest scope of W-1; expect 4-6 catches based on W-1/W-2 history (per memory `reference_codex_connector_calibration`).
18. Report back to orchestrator.

---

## 12. Final report shape

When complete, report to orchestrator:
- Branch + PR URL + final SHA.
- Files touched (grouped: services / orchestrator / models / migration / schemas / routes / tests / frontend).
- Migration roundtrip evidence (single head confirmed via `alembic heads`).
- Test pass/fail counts vs main baseline.
- Codex review status + catches absorbed (Round / count / sticky-FP audit-trail entries if any, per `reference_codex_connector_calibration` protocol).
- Any unexpected rebase against main (none anticipated; flag if encountered).

Keep report under 600 words.

Boa caça.
