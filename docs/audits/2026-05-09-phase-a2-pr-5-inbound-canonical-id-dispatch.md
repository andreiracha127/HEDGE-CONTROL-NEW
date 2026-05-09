# Phase A2 — PR #5 Dispatch — Inbound Canonical-ID Correlation (refreshed)

**Wave:** 1b (final outstanding A2 PR; PR-4 / #36 merged 2026-05-09 as `bf592f117`)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-09 (refresh of original 2026-05-06 dispatch)
**Findings covered:** J-A2-06 (T1, inbound canonical-id correlation)
**Branch name:** `audit-a2/inbound-canonical-id`
**Base:** `main` (currently `bf592f117`, post-PR #36 outbound evidence + canonical id)

---

## 0. Refresh notes (read first)

This dispatch is a **factual refresh + rigor upgrade** of `docs/audits/2026-05-06-phase-a2-pr-5-inbound-canonical-id-dispatch.md` (committed on the `audit/phase-a2` branch at `39c1b9d`, never merged). The institutional purpose (replace phone+timestamp correlation with canonical-id correlation), the scope (`_process_single_message` only), the single finding closed (J-A2-06), and the no-migration shape are **unchanged**. What is updated:

- **Format upgraded from "reduced rigor / Wave 2 demo cycle" (191 lines) to institutional rigor matching the PR-4 refresh shape** (§0–§12 ceremony, line-validated citations, explicit Codex-cycle wait, governance cited by line numbers rather than section names, mandatory worktree + bypassPermissions workflow). The original's "concise dispatch — Wave 2 demo cycle" trailer is removed; PR-5 is the closing PR of A2 and ships under the same protocol that produced PRs #28, #29, #30, #31, #36.
- All file:line citations re-anchored to `main = bf592f117`. The original cited `_process_single_message` at `:248-310` with the multi-RFQ warning at `:289-302`; current shape is **`_process_single_message` at `:258-535`**, phone-correlation block at **`:282-293`**, multi-RFQ-same-phone warning block at **`:307-326`**, archived-RFQ post-fetch check at **`:328-340`**.
- `RFQ.rfq_number` generation site moved: original cited `rfq_service.py:421-423`, now at **`rfq_service.py:554-558`** (PR-1 #28 + PR-4 #36 widened the `RFQService.create` body).
- The original's `_CANONICAL_ID_RE` (`r"RFQ#(?P<num>RFQ-\d{4}-\d{6})"`) is preserved verbatim — `f"RFQ-{year}-{int(seq.id):06d}"` at `rfq_service.py:558` confirms format `RFQ-YYYY-NNNNNN` with 4-digit year + 6-digit zero-padded sequence.
- §3 redesigned around an **explicit defense-in-depth posture**: canonical-id is the primary correlator (governance.md:117-121); the post-canonical phone-on-invitation check is a **secondary consistency probe** (status `phone_mismatch`), not a fallback correlator. Phone-only correlation paths are removed end-to-end.
- §3 retains the **`rfq_archived` post-fetch branch**: rather than filter `RFQ.deleted_at IS NULL` in the WHERE clause (which the original §2.2 implied), the dispatch keeps the current orchestrator's distinct `rfq_archived` status by post-fetching `rfq.deleted_at`. This preserves the operator queue routing distinction and avoids a status-name regression flagged by the existing test `test_inbound_message_skips_archived_rfq` (`backend/tests/test_rfq_orchestrator.py:841`).
- §8 sequencing rewritten: PR-5 ships against **linear main** (`bf592f117`). PR-4 (#36) is in-main since 2026-05-09; the precondition that "every outbound body carries `RFQ#<rfq_number>`" is **already satisfied** — without it the canonical-id parser would never match for replies to pre-PR-4 invitations. **No rebase coordination, no migration head competition, no shared-file conflicts.**
- §3 + §4 cleanly hand off three adjacent surfaces to **Phase A4** (per `docs/audits/2026-05-06-phase-a2-jury-verdict.md` §8 X-A2-J-* and the `project_phase_a2_to_a4_handoff` memory): X-A2-J-01 (raw inbound durability), X-A2-J-02 (LLM confidence calibration), X-A2-J-03 (LLM outbound generation). PR-5 must NOT redesign any of these.
- Constitution citations (`governance.md:111-115`, `:117-121`, `:159-174`, `:208-217`) verified against `bf592f117` — **zero drift**.
- §7 added a dedicated test module `backend/tests/test_inbound_canonical_id.py` (helper-level + integration-level coverage) — original had only step-3 inline tests in `test_rfq_orchestrator.py`. Both locations now in scope.
- §11 workflow now mirrors the PR-4 protocol exactly (worktree creation, `.claude/settings.local.json`, per-step pytest, frontend regen check, Codex-cycle wait). The original's "no §11 workflow ceremony" was a Wave-2-demo shortcut; A2 closure under the institutional protocol requires the full ceremony.

The Phase A2 audit-cycle artifacts (3 stage prompts + 2 findings reports + jury verdict) are in main since PR #34. Read the jury verdict directly at `docs/audits/2026-05-06-phase-a2-jury-verdict.md` §2 J-A2-06; that finding's authoritative wording is unchanged.

---

## 1. Mission

Replace the phone-and-timestamp inbound correlation in `RFQOrchestrator._process_single_message` with **canonical-id correlation by `RFQ#<rfq_number>` only**, per `docs/governance.md:117-121` ("Inbound messages are correlated ONLY via this identifier"). Today the orchestrator expands the sender phone into Brazilian variants, picks the newest active RFQ by `RFQ.created_at`, merely *logs* `orchestrator_multi_rfq_same_phone` when more than one match exists, and proceeds to auto-quote — that is the §2.4 / §2.6 violation J-A2-06 names. After PR-5, inbound text without a parseable `RFQ#<rfq_number>` is **parked** (status `no_canonical_id`, no DB lookup attempted, no auto-quote); inbound text whose canonical id matches a live RFQ is correlated by `rfq_number` only, with the recipient phone surviving as a **secondary consistency probe** that emits `phone_mismatch` rather than a fallback correlator.

This PR touches `RFQOrchestrator._process_single_message` and a small parser helper; it ships **no migration, no schema change, no model change**. Tests in `backend/tests/test_rfq_orchestrator.py` whose premise was phone-only correlation are rewritten; a new module `backend/tests/test_inbound_canonical_id.py` covers the helper + integration matrix.

PR-5 is the **last outstanding Phase A2 jury finding**. After merge, A2 closes at 21/21 (T1+T2+T3); the three cross-A4 deferred surfaces (X-A2-J-01/02/03) pass to Phase A4.

**Persona:** Senior software engineer building an institutional trading platform. Constitution `docs/governance.md` is supreme authority — **RFQ SYSTEM § Correlation** (governance.md:117-121, "Canonical identifier `RFQ#<rfq_number>`. Mandatory in all outbound messages. Inbound messages are correlated ONLY via this identifier"), **GOVERNANCE HARD FAILS** (governance.md:159-174, "No silent fallback. No heuristic correction"), **OUTPUT CONTRACT** (governance.md:208-217, precise + audit-friendly).

> **Note on §-numbering throughout this dispatch:** `governance.md` does **not** use numbered subsections. The `§2.X` labels below are this dispatch's internal mnemonics. Mapping:
> - `§2.4` → **RFQ SYSTEM § Correlation** (governance.md:117-121)
> - `§2.6` → **GOVERNANCE HARD FAILS** (governance.md:159-174)
> - `§2.7` → **OUTPUT CONTRACT** (governance.md:208-217)

---

## 2. Reference docs (read before coding)

- **`docs/audits/2026-05-06-phase-a2-jury-verdict.md` §2 J-A2-06** (lines 145-170). Read in full — that is the only finding PR-5 closes.
- **`docs/governance.md`** — binding sections: **RFQ SYSTEM § Correlation** (lines 117-121), **GOVERNANCE HARD FAILS** (lines 159-174), **OUTPUT CONTRACT** (lines 208-217). See §1 for `§2.X` mnemonic mapping.
- **`backend/app/services/rfq_orchestrator.py:115-142`** — `RFQOrchestrator` class top + `_phone_variants` static method. The phone variants helper survives PR-5; it is repurposed as a **secondary consistency probe**, not a primary correlator.
- **`backend/app/services/rfq_orchestrator.py:258-535`** — `_process_single_message` body. The phone-correlation block is `:282-293`; the multi-RFQ-same-phone warning is `:307-326`; the archived-RFQ post-fetch check is `:328-340`; the rfq-not-quotable branch is `:342-352`; the trivial-message + LLM classify guards live downstream at `:354-407`. PR-5 replaces only the **correlator** (282-326); the downstream guards stay as-is on already-correlated messages.
- **`backend/app/services/rfq_service.py:554-558`** — RFQ number generation (`f"RFQ-{year}-{int(seq.id):06d}"`). Confirms the regex format `RFQ-\d{4}-\d{6}`.
- **`backend/app/services/rfq_service.py:84-99`** — `prefix_with_canonical_id` helper (PR-4). The outbound side guarantees every body either *starts with* `RFQ#<rfq_number>` (after optional whitespace) or the helper prepends `RFQ#<rfq_number> — `. The inbound parser regex must therefore tolerate both leading-and-internal positions; use `re.search` (not `re.match`).
- **`backend/app/schemas/whatsapp.py:51-58`** — `WhatsAppInboundMessage` Pydantic model (`message_id`, `from_phone`, `timestamp`, `text`, `sender_name`). PR-5 reads `text` only; no schema change.
- **`backend/app/models/rfqs.py:100-101`** — `RFQInvitationChannel.whatsapp` enum. The post-canonical phone probe filters on this channel.
- **`backend/app/models/rfqs.py:118-169`** — `RFQInvitation` model; the relevant columns for the secondary phone probe are `rfq_id`, `recipient_phone` (`String(50)`), `channel`.
- **`backend/app/models/rfqs.py:127`** — `RFQInvitation.rfq_number = String(length=32)`. Confirms a parsed canonical id (`"RFQ-YYYY-NNNNNN"`, 15 chars) fits comparable columns; lookup is on `RFQ.rfq_number` (also `String(32)`), not on the invitation's denormalised copy.
- **`backend/app/models/rfqs.py`** RFQState enum — values `created`, `sent`, `quoted`, `awarded`, `closed`. Quotable-state filter for the canonical-id lookup is `state IN (sent, quoted)`, mirroring the existing query at `rfq_orchestrator.py:289`.
- **`backend/tests/test_rfq_orchestrator.py:159-898`** — full inbound test suite. Line 210 `test_process_no_matching_rfq`, line 222 `test_process_rfq_not_quotable`, line 841 `test_inbound_message_skips_archived_rfq`, line 866 `test_archived_rfq_does_not_fall_through_to_older_live_rfq`. The last test's premise is phone-fall-through and **must be rewritten** for the canonical-id world (canonical-id is unique → no fall-through possible; the rewritten test asserts that an inbound carrying canonical id `A` lands on RFQ `A` regardless of how many other live RFQs exist on the same phone).
- **`backend/alembic/versions/037_rfq_outbound_evidence.py`** — current alembic head. PR-5 ships **no migration**; do NOT chain anything off this. (See §3.4.)

---

## 3. Scope IN — what PR-5 ships

> **Line-number disclaimer:** all line numbers below are validated at `bf592f117` (2026-05-09). They will drift if any other PR merges before PR-5 — but no other A2 PR is open, and PR-5 is the closing PR of the wave. **Locate edits by symbol / identifier first** (function name, attribute name, literal string). A `grep -n` on the cited symbol is the source of truth — line numbers are advisory only.

### 3.1 Canonical-id parser helper

Add a single pure function used by `_process_single_message`. Place it alongside `RFQOrchestrator`'s other static helpers in `backend/app/services/rfq_orchestrator.py` (i.e., near `_phone_variants` / `_is_trivial_message` / `_price_appears_in_text` at lines 122-183), or as a module-level helper above the class. Do **not** create a new module just for this function — keep the helper colocated with the only consumer.

```python
import re

# Format mirrored from rfq_service.py:558 — `f"RFQ-{year}-{int(seq.id):06d}"`.
# 4-digit year + 6-digit zero-padded sequence; uppercase RFQ literal.
_CANONICAL_ID_RE = re.compile(r"RFQ#(?P<num>RFQ-\d{4}-\d{6})")


def _parse_canonical_id(text: str | None) -> str | None:
    """Extract `RFQ-YYYY-NNNNNN` from a message body.

    Returns the bare rfq_number (without the `RFQ#` prefix) if a single
    match is found anywhere in the text; None if absent or the input is
    falsy. `re.search` (not `re.match`) is used because the outbound
    helper `prefix_with_canonical_id` (rfq_service.py:84-99) places the
    prefix at the *start* of the body, but counterparties may quote-reply
    with the canonical id appearing after their text — both positions are
    acceptable.

    Idempotent. Pure. Does NOT touch the database.
    """
    if not text:
        return None
    m = _CANONICAL_ID_RE.search(text)
    return m.group("num") if m else None
```

**Regex anchoring rationale:**
- `re.search` covers both "prefix at start" (the canonical outbound shape) and "prefix appearing inside a quoted reply" (counterparties using WhatsApp's quote feature, which may indent or whitespace-pad the original text). The original 2026-05-06 dispatch already specified `search` over `match`; preserved.
- `RFQ-\d{4}-\d{6}` is an exact match for `f"RFQ-{year}-{int(seq.id):06d}"` at `rfq_service.py:558`. Year is always 4-digit (will not collide with 5-digit format until year 10000). Sequence is `:06d`-formatted from a `RFQSequence.id` integer; once the sequence exceeds 999_999 the format will widen — at that point this regex needs a corresponding update, but PR-5 does NOT pre-emptively widen for that scenario (premature design).
- The literal `RFQ#` separator is mandatory — `re.search` will not match a body that contains `RFQ-2026-000123` without the `#` separator. That is intentional: the canonical id is `RFQ#<rfq_number>`, not the bare `rfq_number`. A counterparty echo without the `#` is institutionally a non-canonical reply and must park.
- Multiple canonical ids in a single message body (counterparty quotes two RFQs in one reply): `re.search` returns only the first. PR-5 does NOT support multi-RFQ-per-message dispatch — the constitution's correlation clause is one canonical id per message, the outbound shape is one canonical id per outbound message, and a multi-id inbound is operationally a forwarded thread. If a future use case demands multi-id handling, that is a Phase A4 / A5 surface, not PR-5.

### 3.2 Rewrite `_process_single_message` correlation

**File:** `backend/app/services/rfq_orchestrator.py:258-535`.

**Replace** the phone-correlation block at `:282-326` (the `phone_variants → query(RFQInvitation).join(RFQ, ...).first()` lookup at 282-293, `not invitation` branch at 295-305, and `active_rfq_count > 1` warning block at 307-326) with the canonical-id-first correlator below. **Preserve** the downstream archived-RFQ check at 328-340, the rfq-not-quotable branch at 342-352, and every guard / LLM block from line 354 onward — those operate on already-correlated messages and PR-5 does not redesign them.

```python
# ── Step 1: parse canonical id from inbound text ──
canonical_number = _parse_canonical_id(msg.text)
if canonical_number is None:
    logger.warning(
        "orchestrator_no_canonical_id",
        from_phone=msg.from_phone,
        message_id=msg.message_id,
    )
    return {
        "message_id": msg.message_id,
        "status": "no_canonical_id",
        "from_phone": msg.from_phone,
    }

# ── Step 2: locate the live RFQ by canonical id ──
# state filter mirrors the pre-PR-5 query (sent, quoted). deleted_at is
# intentionally NOT in the WHERE clause; the post-fetch check below
# preserves the existing `rfq_archived` status surface so operator-side
# routing of archived replies is unchanged.
rfq = (
    session.query(RFQ)
    .filter(
        RFQ.rfq_number == canonical_number,
        RFQ.state.in_([RFQState.sent, RFQState.quoted]),
    )
    .first()
)
if rfq is None:
    logger.warning(
        "orchestrator_canonical_id_unknown",
        from_phone=msg.from_phone,
        canonical_number=canonical_number,
        message_id=msg.message_id,
    )
    return {
        "message_id": msg.message_id,
        "status": "canonical_id_unknown",
        "canonical_number": canonical_number,
    }

# ── Step 3: archived-RFQ short-circuit (preserves existing behavior) ──
if rfq.deleted_at is not None:
    logger.info(
        "orchestrator_rfq_archived",
        rfq_id=str(rfq.id),
        from_phone=msg.from_phone,
        message_id=msg.message_id,
    )
    return {
        "message_id": msg.message_id,
        "status": "rfq_archived",
        "rfq_id": str(rfq.id),
    }

# ── Step 4: locate the invitation row for downstream code paths
#           (counterparty_id, recipient_name, recipient_phone). The
#           phone match is a SECONDARY CONSISTENCY PROBE, not a
#           correlator — canonical id has already won correlation. ──
phone_variants = RFQOrchestrator._phone_variants(msg.from_phone)
invitation = (
    session.query(RFQInvitation)
    .filter(
        RFQInvitation.rfq_id == rfq.id,
        RFQInvitation.recipient_phone.in_(phone_variants),
        RFQInvitation.channel == RFQInvitationChannel.whatsapp,
    )
    .order_by(RFQInvitation.created_at.desc())
    .first()
)
if invitation is None:
    # Canonical id matched a real RFQ, but the sender phone does not
    # appear among the invitations for that RFQ. Park as a consistency
    # mismatch — do NOT silently auto-quote. Operator review is required
    # because this is either a counterparty forwarding an outbound to a
    # different number (legitimate but needs human eyes) or a hostile
    # echo of the canonical id from an unrelated party.
    logger.warning(
        "orchestrator_phone_does_not_match_canonical_id",
        from_phone=msg.from_phone,
        canonical_number=canonical_number,
        rfq_id=str(rfq.id),
        message_id=msg.message_id,
    )
    return {
        "message_id": msg.message_id,
        "status": "phone_mismatch",
        "canonical_number": canonical_number,
        "rfq_id": str(rfq.id),
    }

# ── Downstream: existing guards (trivial, classify_intent,
#                parse_quote, price-in-text, dedupe, auto_create_quote)
#                operate on the (rfq, invitation) tuple unchanged. ──
```

**Identifiers used:** `_parse_canonical_id`, `RFQ`, `RFQState`, `RFQInvitation`, `RFQInvitationChannel`, `RFQOrchestrator._phone_variants`. All five are already imported at `rfq_orchestrator.py:34-42` — no new imports beyond `re` (which is already imported at `:21`).

**The multi-RFQ-same-phone warning at `:307-326` is unreachable post-PR-5.** Canonical id is unique on `RFQ.rfq_number`; the WHERE-clause filter returns at most one RFQ. **Delete the warning block** and the `from sqlalchemy import func, distinct` import contributors that are no longer used (audit `from sqlalchemy import func, distinct, or_` at `:28` — `distinct` may become unused; remove if so to keep the import set honest. `func` and `or_` are likely used elsewhere — verify before deleting; do not delete imports that other code in the file still depends on).

### 3.3 Status return value taxonomy

PR-5 introduces three new status values returned by `_process_single_message`:

| Status | Trigger | Persistence | Operator action (downstream) |
|---|---|---|---|
| `no_canonical_id` | `_parse_canonical_id(msg.text)` returns None | Non-mutating; no DB lookup attempted | Route to human review queue; counterparty did not echo `RFQ#<rfq_number>` |
| `canonical_id_unknown` | Parsed id has no live (state ∈ {sent, quoted}) RFQ | Non-mutating; one DB query attempted | Route to human review queue; counterparty referenced a stale or fabricated id |
| `phone_mismatch` | Canonical id matches a live RFQ but sender phone is not on any invitation for that RFQ | Non-mutating; two DB queries attempted | Route to human review queue; potential cross-counterparty forwarding or hostile echo |

The downstream `webhook_processor` (Phase A4 X-A2-J-01 surface) is the consumer that routes these three statuses to the operator queue. PR-5's responsibility ends at returning the structured status; **PR-5 does NOT modify webhook_processor**, does NOT add a parked-message persistence table, does NOT add a UI surface for the parked queue. Those are A4.

The pre-existing statuses (`no_matching_rfq`, `rfq_not_quotable`, `rfq_archived`, `trivial_message_skipped`, `counterparty_declined`, `counterparty_question`, `needs_human_review`, `llm_unavailable`, `hallucinated_price_blocked`, `duplicate_quote_skipped`, `auto_quote_*`) are all preserved with their pre-PR-5 semantics. The `no_matching_rfq` status (returned at `:295-305` today when the phone-correlation lookup yielded zero invitations) becomes **unreachable** after PR-5 — it is replaced by `no_canonical_id` (no parseable id at all) or `canonical_id_unknown` (id parsed but no live RFQ). Audit downstream consumers of `no_matching_rfq` before deletion: if any test or webhook consumer asserts on this status string, update it.

### 3.4 No schema changes, no migration

PR-5 is a **pure code change**. There is no `038_*.py` migration. There is no model field added to `RFQ`, `RFQInvitation`, `RFQQuote`, `RFQStateEvent`, or any other table. There is no Pydantic schema modification.

Reasoning: the canonical id is already on `RFQ.rfq_number` (since RFQ creation, pre-A2). After PR-4 (`bf592f117`), every outbound `RFQInvitation.message_body` either starts with `RFQ#<rfq_number>` (new path) or is prefixed by `prefix_with_canonical_id` at all six call sites (`RFQService.create`, `refresh`, `refresh_counterparty`, `reject_quote`, `RFQOrchestrator.notify_award`, `notify_reject`). The inbound side just **parses what counterparties echo back** — no new columns required. The "parked message" persistence layer (X-A2-J-01) is a Phase A4 concern and is explicitly out of scope (§4); it would add a table and migration, but PR-5 does not.

If a future evolution adds a parked-message table, it would chain off `037_rfq_outbound_evidence` as `038_<slug>` (≤32 chars, e.g., `038_inbound_parked_audit`) — but that decision is owned by Phase A4, not by PR-5. Do **NOT** speculatively add the migration.

### 3.5 Test rewrite for tests whose premise was phone-only correlation

The following tests in `backend/tests/test_rfq_orchestrator.py` have premises that are phone-only-correlation-specific. They must be rewritten so that every successful-correlation test injects `RFQ#<rfq_number>` into the inbound text, and every failure-mode test asserts the new status taxonomy:

- `test_process_no_matching_rfq` (line 210) — premise was "no invitation row matches phone variants". After PR-5, the equivalent failure modes are `no_canonical_id` (text lacked the prefix) or `canonical_id_unknown` (id parsed but no live RFQ). Rewrite as two tests covering both. Do NOT keep a `no_matching_rfq` assertion.
- `test_process_rfq_not_quotable` (line 222) — premise was "phone-matched invitation links to a non-quotable RFQ". After PR-5, the matching code path is dead (the WHERE clause filters `state.in_(sent, quoted)` already, so a non-quotable state returns zero rows → `canonical_id_unknown`). Rewrite as a test asserting that an RFQ in `awarded` state, looked up by canonical id, returns `canonical_id_unknown` (since it is filtered out by the state predicate).
- `test_process_counterparty_declined` (line 238), `test_process_counterparty_question` (line 261), `test_process_needs_human_review` (line 280), `test_process_llm_unavailable` (line 299), `test_process_auto_quote_created` (line 318), `test_process_auto_quote_fails_gracefully` (line 348), `test_auto_quote_*` (lines 372-444), `test_hallucinated_price_blocked` (line 780), `test_trivial_message_skipped_in_flow` (line 803), `test_classify_first_blocks_greeting_with_digits` (line 817) — all of these test **downstream guards** on already-correlated messages. Add `RFQ#<rfq_number>` to the inbound `text` fixture so correlation succeeds; assert downstream behavior unchanged.
- `test_inbound_message_skips_archived_rfq` (line 841) — fixture must inject canonical id; assertion `rfq_archived` is preserved (the post-fetch `deleted_at` check in §3.2 step 3 keeps this status alive).
- `test_archived_rfq_does_not_fall_through_to_older_live_rfq` (line 866) — premise no longer applies under canonical-id correlation (canonical id is unique → no fall-through possible). Rewrite as: "given two live RFQs `A` (archived) and `B` (active) on the same counterparty phone, an inbound carrying `RFQ#<A.rfq_number>` returns `rfq_archived`; an inbound carrying `RFQ#<B.rfq_number>` correlates to `B`". This is the canonical-id world's analogue of the prior fall-through guard.

The new tests in §7 (`test_inbound_canonical_id.py`) are *additive*; they do not replace the rewrites above.

---

## 4. Scope OUT — explicitly NOT in PR-5

- **Raw inbound message durability (X-A2-J-01)** — Phase A4. PR-5 does NOT add a parked-message persistence table, does NOT modify `webhook_processor.py`, does NOT change the inbound queue surface. The four parked statuses (`no_canonical_id`, `canonical_id_unknown`, `phone_mismatch`, plus the pre-existing `rfq_archived`) are returned to whatever caller consumes `_process_single_message`'s dict; the persistence layer is owned by A4.
- **LLM confidence calibration / degraded mode (X-A2-J-02)** — Phase A4. PR-5 does NOT touch `LLMAgent.classify_intent`, `LLMAgent.parse_quote_message`, `LLMAgent.should_auto_create_quote`, the hard-coded `0.85` threshold, or any LLM-side guard. Those operate on already-correlated messages downstream of PR-5's correlator.
- **LLM-generated outbound award/reject text (X-A2-J-03)** — Phase A4. PR-5 does NOT modify `RFQOrchestrator.notify_award` (683-774), `notify_reject` (776-847), or any outbound generation path.
- **Auto-quote silent defaulting** (`or "avg"`, `or 0`, `or "USD/MT"`) — out of scope for A2 entirely. Closest A2 surface was J-A2-OPUS-03 (in-scope of A2 wave 2), already merged via PR #29.
- **Refactoring `RFQOrchestrator._phone_variants`** — preserved as the secondary consistency probe. Behaviour unchanged. Do NOT inline, rename, or delete.
- **Multi-canonical-id-per-message handling** — out of scope (one `re.search` match; extras ignored). If a future use case demands it, a follow-up dispatch addresses it then.
- **Schema or model changes** — none. PR-5 ships `0` migration files, `0` model field changes, `0` Pydantic schema changes (see §3.4).
- **Modifying `RFQService` or `RFQ` model** — none. PR-5 reads `RFQ.rfq_number` only.
- **Frontend regen** — none expected; PR-5 does not change any read schema. If `pytest` somehow surfaces a schema drift, that is an unexpected side-effect — flag to orchestrator before changing scope.

---

## 5. Constitutional rules (binding)

(Mnemonic mapping per §1: `§2.4` → governance.md `RFQ SYSTEM § Correlation`; `§2.6` → governance.md `GOVERNANCE HARD FAILS`; `§2.7` → governance.md `OUTPUT CONTRACT`.)

- **§2.4 — Correlation** (governance.md:117-121) — "Canonical identifier `RFQ#<rfq_number>`. Mandatory in all outbound messages. **Inbound messages are correlated ONLY via this identifier.**" Phone is not a correlator. Timestamp is not a tiebreak. PR-5 enforces.
- **§2.6 — Hard Fails** (governance.md:159-174) — "No silent fallback. No heuristic correction." Phone-variant matching plus `RFQ.created_at desc` tiebreak is exactly a heuristic correction; PR-5 removes it. Inbound text without canonical id parks; it does NOT fall through to phone matching.
- **§2.7 — Output Contract** (governance.md:208-217) — "Audit-friendly. Free of speculation." Each parked status (`no_canonical_id`, `canonical_id_unknown`, `phone_mismatch`) carries enough structured fields (canonical_number, rfq_id, from_phone, message_id) for the operator queue to disambiguate the failure mode at audit time.

---

## 6. Acceptance criteria

- [ ] `_parse_canonical_id(text)` helper exists, returns the bare `rfq_number` for `"RFQ#RFQ-2026-000123"`, returns `None` for missing/malformed text.
- [ ] `_parse_canonical_id` is idempotent (same input → same output) and pure (no DB access).
- [ ] `_process_single_message` calls `_parse_canonical_id` BEFORE any `session.query(...)`. The first DB access is the canonical-id lookup, never a phone lookup.
- [ ] When `_parse_canonical_id` returns `None`, `_process_single_message` returns `{"status": "no_canonical_id", ...}` without performing any DB query.
- [ ] When the parsed id matches no live (state ∈ {sent, quoted}) RFQ, returns `{"status": "canonical_id_unknown", "canonical_number": ...}`.
- [ ] When the matched RFQ has `deleted_at IS NOT NULL`, returns `{"status": "rfq_archived", "rfq_id": ...}` (status preserved from pre-PR-5 behavior; canonical-id world's archived branch).
- [ ] When the matched RFQ is live but no `RFQInvitation` row exists for that RFQ + sender phone variant + whatsapp channel, returns `{"status": "phone_mismatch", "canonical_number": ..., "rfq_id": ...}`.
- [ ] When the canonical id matches a live RFQ AND the sender phone is on an invitation, the existing downstream pipeline (trivial / classify_intent / parse_quote / price-in-text / dedupe / auto_create_quote) executes unchanged and the auto-quote succeeds.
- [ ] No path in `_process_single_message` correlates by phone alone after this PR. Grep the function body: `session.query(RFQInvitation).join(RFQ, ...)` should return zero hits; the only `session.query(RFQInvitation)` call is the §3.2 step-4 secondary probe filtered on `rfq_id == rfq.id`.
- [ ] No path uses `RFQ.created_at` ordering as a tiebreak for correlation. `order_by(RFQ.created_at.desc())` does not appear in `_process_single_message` after PR-5.
- [ ] The `active_rfq_count > 1` warning block (`orchestrator_multi_rfq_same_phone` log line) at the pre-PR-5 lines `:307-326` is **deleted**. `grep -n "orchestrator_multi_rfq_same_phone"` on `backend/app/services/` returns zero hits.
- [ ] No new migration file is created; `alembic heads` continues to report a single head at `037_rfq_outbound_evidence`.
- [ ] No model column added; no Pydantic schema field added.
- [ ] X-A2-J-01 (raw inbound durability) is **explicitly out of scope** per §4 and per the A4 deferral memo; no `webhook_processor.py` changes, no parked-message table.
- [ ] Tests in §7 pass; rewritten tests per §3.5 pass; the full backend suite (`pytest backend/tests/ -v`) is green except for any pre-existing skips/xfails baseline-tracked.

---

## 7. Test coverage required

**New module: `backend/tests/test_inbound_canonical_id.py`** (helper-level + integration matrix, mirrors the J-A2-06 jury verdict acceptance criteria 165-168):

- `test_parse_canonical_id_extracts_from_prefixed_body` — `"RFQ#RFQ-2026-000123 — your quote please"` → `"RFQ-2026-000123"`.
- `test_parse_canonical_id_handles_whitespace_prefix` — `"  RFQ#RFQ-2026-000123 ..."` → `"RFQ-2026-000123"` (the outbound helper at `rfq_service.py:84-99` strips leading whitespace via `lstrip()` before the canonical check; inbound parser must tolerate the same with `re.search`).
- `test_parse_canonical_id_handles_internal_position` — `"Olá! RFQ#RFQ-2026-000456 está confirmado"` → `"RFQ-2026-000456"` (`re.search`, not `re.match`).
- `test_parse_canonical_id_returns_none_on_missing` — `"Bom dia, segue minha cotação"` → `None`. No exception; no log; no DB.
- `test_parse_canonical_id_returns_none_on_empty_or_none` — `""` and `None` both return `None` without exception.
- `test_parse_canonical_id_rejects_bare_rfq_number_without_hash` — `"RFQ-2026-000123"` (no `#`) → `None`.
- `test_parse_canonical_id_rejects_short_sequence` — `"RFQ#RFQ-2026-12345"` (5 digits) → `None`.
- `test_inbound_with_canonical_id_resolves_by_rfq_number` — fixture: live RFQ A; inbound `from_phone=+5511999999999`, `text="RFQ#<A.rfq_number> ..."`. Asserts `_process_single_message` returns the auto-quote success path, `rfq_id == A.id`, downstream guards executed.
- `test_inbound_without_canonical_id_is_parked_not_correlated_by_phone` — fixture: live RFQ A with invitation to `+5511999999999`; inbound from same phone, `text="ola tudo bem"` (no canonical id). Asserts `{"status": "no_canonical_id"}` and no auto-quote, no DB query attempted on the invitation table (mock `session.query` to fail-loud if called).
- `test_inbound_with_canonical_id_phone_mismatch_defense_in_depth` — fixture: live RFQ A with invitation to `+5511111111111`; inbound from `+5522222222222` carrying `RFQ#<A.rfq_number>`. Asserts `{"status": "phone_mismatch", "canonical_number": ..., "rfq_id": str(A.id)}` and no auto-quote.
- `test_inbound_with_canonical_id_unknown_rfq` — fixture: no RFQ with `rfq_number == "RFQ-2026-999999"`; inbound carries `RFQ#RFQ-2026-999999`. Asserts `{"status": "canonical_id_unknown", "canonical_number": "RFQ-2026-999999"}`.
- `test_inbound_with_canonical_id_archived_rfq` — fixture: RFQ A with `deleted_at IS NOT NULL`, state in {sent, quoted}; inbound carries the canonical id. Asserts `{"status": "rfq_archived", "rfq_id": str(A.id)}` (canonical-id world's archived branch).
- `test_inbound_with_canonical_id_terminal_state_rfq` — fixture: RFQ A in `awarded` state; inbound carries the canonical id. Asserts `{"status": "canonical_id_unknown", ...}` because the WHERE-clause filter excludes terminal states.
- `test_inbound_with_canonical_id_skips_phone_variant_match_on_other_rfq` — fixture: live RFQ A on phone `+55119999`, live RFQ B on phone `+55119998`; inbound from `+55119999` carries `RFQ#<B.rfq_number>`. Asserts `{"status": "phone_mismatch", ...}` (cross-RFQ canonical id with non-matching phone parks; does NOT silently fall through to RFQ A on the same phone — that would be the J-A2-06 bug returning).

**Integration tests in existing `backend/tests/test_rfq_orchestrator.py`** (rewrites per §3.5):

- Rewrite `test_process_no_matching_rfq` → `test_process_no_canonical_id` + `test_process_canonical_id_unknown`.
- Rewrite `test_process_rfq_not_quotable` → `test_process_canonical_id_for_terminal_state_rfq_returns_canonical_id_unknown`.
- Update fixtures for every `test_process_*` test that exercises the auto-quote path so the inbound `text` carries `RFQ#<rfq_number>`.
- Rewrite `test_archived_rfq_does_not_fall_through_to_older_live_rfq` per §3.5.

---

## 8. Critical sequencing

PR-5 ships against **linear main** (`bf592f117` at authoring time). All A2 sibling PRs are merged: W-1 (#26, #27, #28), W-2 (#29, #30, #31), alembic merge hotfix (#33), audit artifacts backfill (#34), W-1b dispatch refresh (#35), and **PR-4 (#36, the precondition)**. PR-5 is the closing PR of A2.

- **Branch base:** `origin/main` at `bf592f117` or later.
- **Migration chain:** PR-5 ships **no migration**. `alembic heads` continues to report a single head at `037_rfq_outbound_evidence`.
- **Precondition (already satisfied):** PR-4 (#36) guarantees every outbound `RFQInvitation.message_body` carries `RFQ#<rfq_number>` via `prefix_with_canonical_id` (`rfq_service.py:84-99`). Without this, the inbound parser would have zero match for replies to pre-PR-4 invitations and PR-5 would hard-fail every legitimate inbound. **PR-5 cannot land before PR-4 lands.** Since PR-4 is in-main since 2026-05-09, this constraint is satisfied at authoring time.
- **No rebase coordination, no migration head competition, no shared-file conflicts to anticipate.** The only concern is mechanical rebase against main if main advances during review.
- **Downstream:** none. PR-5 closes Phase A2. The three deferred surfaces (X-A2-J-01/02/03) hand off to Phase A4 per the `project_phase_a2_to_a4_handoff` memory; no Phase A2 PR depends on PR-5.

---

## 9. PR shape

**Title:** `fix(audit-a2): PR-5 — inbound canonical-id correlation (J-A2-06)`

**Body skeleton:**

```markdown
## Summary

Replace phone-and-timestamp inbound correlation in
`RFQOrchestrator._process_single_message` with canonical-id correlation by
`RFQ#<rfq_number>` only, per `governance.md:117-121`. Inbound text without a
parseable canonical id is parked (status `no_canonical_id`); inbound text
whose canonical id matches a live RFQ correlates by `rfq_number` only, with
the sender phone surviving as a secondary consistency probe (status
`phone_mismatch`) rather than a fallback correlator.

Phase A2 jury verdict (FAIL @ commit `9f67357`) — addresses Tier 1 finding
J-A2-06. Constitution §2.4 (canonical correlation), §2.6 (no silent fallback,
no heuristic correction). Closing PR of Phase A2: after merge, A2 stands at
21/21 jury findings closed.

[BEHAVIOR_SHIFT] Three new return statuses (`no_canonical_id`,
`canonical_id_unknown`, `phone_mismatch`) replace the previous
`no_matching_rfq` status. Downstream consumers (webhook_processor — Phase A4)
must route these to the human review queue. PR-5 itself does NOT modify
webhook_processor; queue routing is a Phase A4 surface (X-A2-J-01).

## Files changed

- `backend/app/services/rfq_orchestrator.py` — `_parse_canonical_id` helper,
  rewrite of `_process_single_message` correlator (canonical-id-first, phone
  as secondary probe), deletion of `orchestrator_multi_rfq_same_phone` block.
- `backend/tests/test_inbound_canonical_id.py` (new) — helper-level +
  integration matrix per dispatch §7.
- `backend/tests/test_rfq_orchestrator.py` — fixture updates (inject `RFQ#`
  prefix into inbound `text`), rewrites of phone-only-correlation tests per
  §3.5.

## Acceptance evidence

- [ ] All criteria from dispatch §6 met
- [ ] `alembic heads` reports a single head at `037_rfq_outbound_evidence`
  (no new migration shipped)
- [ ] No `session.query(RFQInvitation).join(RFQ, ...)` correlator in
  `_process_single_message`
- [ ] No `RFQ.created_at` order_by in `_process_single_message`
- [ ] `orchestrator_multi_rfq_same_phone` log line removed
- [ ] X-A2-J-01 (raw inbound durability) explicitly deferred to Phase A4

## Constitutional impact

§2.4 (canonical correlation enforced; phone is no longer a correlator),
§2.6 (no silent fallback; heuristic phone+timestamp correction removed),
§2.7 (parked statuses are structured + audit-friendly).

## Out of scope

- Raw inbound message persistence — Phase A4 (X-A2-J-01).
- LLM confidence calibration — Phase A4 (X-A2-J-02).
- LLM-generated outbound text — Phase A4 (X-A2-J-03).

## Closes

J-A2-06.
```

---

## 10. Constraints — what NOT to do

- **DO NOT** redesign the raw inbound durability surface (X-A2-J-01). That is Phase A4. PR-5 ends at returning a structured status; the persistence + queue routing layer is out of scope.
- **DO NOT** modify `LLMAgent.classify_intent`, `LLMAgent.parse_quote_message`, or `LLMAgent.should_auto_create_quote` (X-A2-J-02 — Phase A4).
- **DO NOT** modify `RFQOrchestrator.notify_award` or `notify_reject` (X-A2-J-03 — Phase A4).
- **DO NOT** add a migration file. PR-5 is parser-only. If a future evolution adds a parked-message table, that decision is owned by Phase A4.
- **DO NOT** re-fork the alembic chain. The single head remains `037_rfq_outbound_evidence`.
- **DO NOT** delete `RFQOrchestrator._phone_variants`. It is repurposed as the secondary consistency probe in §3.2 step 4.
- **DO NOT** filter `RFQ.deleted_at IS NULL` in the canonical-id WHERE clause. The post-fetch check at §3.2 step 3 preserves the existing `rfq_archived` status; folding it into WHERE would degrade the operator queue routing distinction (archived would silently become `canonical_id_unknown`).
- **DO NOT** change the `RFQ.state` filter from `IN (sent, quoted)`. Adding `created` would correlate to RFQs whose invitations were never sent (counterparty cannot have replied yet); adding `awarded`/`closed` would re-open terminal RFQs to inbound mutation.
- **DO NOT** call `_parse_canonical_id` more than once per message. Cache the result.
- **DO NOT** use `re.match` in the parser; use `re.search` (per §3.1 rationale). Quote-replies place the canonical id mid-body.
- **DO NOT** weaken the regex (e.g., to `RFQ-?#?\d+`). The canonical id is exactly `RFQ#RFQ-YYYY-NNNNNN`; partial matches park.
- **DO NOT** introduce `re.findall`-based multi-id handling. One canonical id per message; extras ignored. Multi-id support is a future feature, not PR-5's scope.
- **DO NOT** modify `webhook_processor.py`, `whatsapp_service.py`, `whatsapp_providers/`, or anything in `backend/app/services/whatsapp_*`. PR-5 stops at the orchestrator boundary.
- **DO NOT** rewrite `_phone_variants` or change its return-list semantics. The secondary probe assumes Brazilian 8/9-digit handling.
- **DO NOT** auto-merge — wait for Codex review (per `feedback_review_priority` memory).
- **DO NOT** use `--no-verify` to skip git hooks. If a hook fails, fix and create a new commit.
- **DO NOT** force-push without `--force-with-lease`. Direct `--force` is denied at the worktree's `.claude/settings.local.json`.

---

## 11. Workflow

1. `git fetch origin && git worktree add D:\Projetos\Hedge-Control-New-pr5 origin/main && cd D:\Projetos\Hedge-Control-New-pr5 && git checkout -b audit-a2/inbound-canonical-id`. Verify Serena's project root rebinds to the new worktree before any edit (per `project_phase_a2_w1b_pr4_closed` memory lesson — Serena may keep the prior project root pointer; `mcp__serena__activate_project` on the worktree path before any file write).
2. Configure `.claude/settings.local.json` per the A1 worktree pattern: `defaultMode: bypassPermissions` with explicit allow list for `git`, `gh`, `pytest`, `python`, `alembic`; deny rules for raw `--force` (not `--force-with-lease`), `gh pr merge --auto`, `--no-verify`, push to `main`.
3. Read jury §2 J-A2-06 in full (`docs/audits/2026-05-06-phase-a2-jury-verdict.md` lines 145-170).
4. Read `_process_single_message` body in `backend/app/services/rfq_orchestrator.py:258-535` to confirm the line numbers in this dispatch are still accurate; if main has advanced, locate by symbol name.
5. Read `prefix_with_canonical_id` at `rfq_service.py:84-99` to confirm the outbound shape (canonical id at start of body, optional whitespace) the inbound parser must tolerate.
6. Implement `_parse_canonical_id` helper per §3.1 (alongside other static helpers in `rfq_orchestrator.py`).
7. Rewrite the correlator block in `_process_single_message` per §3.2: parse canonical id → live-RFQ lookup → archived post-fetch → secondary phone probe. Preserve all downstream guards from line 354 onward.
8. Delete the `orchestrator_multi_rfq_same_phone` warning block. Audit imports — drop `distinct` and `func` if unused (verify other code in the file does not still depend on them before deleting).
9. Rewrite/update tests per §3.5 in `backend/tests/test_rfq_orchestrator.py`; inject `RFQ#<rfq_number>` into inbound `text` fixtures for every successful-correlation test.
10. Create `backend/tests/test_inbound_canonical_id.py` per §7 (helper-level + integration matrix).
11. `pytest backend/tests/test_rfq_orchestrator.py backend/tests/test_inbound_canonical_id.py -v` after each major edit.
12. Full backend suite: `pytest backend/tests/ -v` — green except known baseline failures.
13. `python -c "from alembic.script import ScriptDirectory; from alembic.config import Config; print(ScriptDirectory.from_config(Config('backend/alembic.ini')).get_heads())"` must report a single head: `('037_rfq_outbound_evidence',)`.
14. `grep -n "session.query(RFQInvitation).join(RFQ" backend/app/services/rfq_orchestrator.py` must return zero hits in `_process_single_message` (the secondary probe per §3.2 step 4 does NOT join — it filters on `rfq_id == rfq.id`).
15. `grep -n "orchestrator_multi_rfq_same_phone\|RFQ.created_at.desc" backend/app/services/rfq_orchestrator.py` must return zero hits.
16. `git push -u origin audit-a2/inbound-canonical-id && gh pr create --base main --title "<§9 title>" --body-file <body>`.
17. **STOP. Wait for Codex review.** Per `reference_codex_connector_calibration`: each push triggers a fresh review at the new HEAD SHA; check `gh api .../pulls/<N>/reviews` AND `gh api .../issues/<N>/comments` (top-level comment approvals are not in `/reviews`). Address each catch as a new commit (NOT amend). PR-5 has the smallest scope of A2 — expect 1-3 catches based on PR-4 history.
18. Report back to orchestrator per §12.

---

## 12. Final report shape

When complete, report to orchestrator:

- Branch + PR URL + final SHA.
- Files touched (grouped: orchestrator / new tests / rewritten tests). PR-5 should NOT touch models / migrations / schemas / services other than `rfq_orchestrator.py`; flag any deviation.
- Confirmation that `alembic heads` reports a single head at `037_rfq_outbound_evidence` (no migration shipped).
- Test pass/fail counts vs main baseline; specifically the `test_inbound_canonical_id.py` matrix and the rewritten `test_rfq_orchestrator.py` cases.
- Codex review status + catches absorbed (Round / count / sticky-FP audit-trail entries if any, per `reference_codex_connector_calibration` protocol).
- Confirmation that X-A2-J-01 / 02 / 03 surfaces were NOT touched.
- Confirmation that the multi-RFQ-same-phone warning block was removed (grep evidence).
- Any unexpected rebase against main (none anticipated; flag if encountered).

Keep report under 500 words.

Boa caça.
