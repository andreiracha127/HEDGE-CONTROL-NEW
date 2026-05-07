# Phase A2 — Stage 3 Jury — Consolidated Verdict

**Date:** 2026-05-06
**Phase:** A2 — RFQ Lifecycle
**Inputs:**
- Auditor A: docs/audits/2026-05-06-phase-a2-findings-opus.md (commit 9f6735729be0ee951644956a288bb18a96d7b162)
- Auditor B: docs/audits/2026-05-06-phase-a2-findings-gemini.md (commit 9f6735729be0ee951644956a288bb18a96d7b162)
**Code state:** `9f6735729be0ee951644956a288bb18a96d7b162`

## 1. Verdict summary

- **Tier 1 (Critical, constitutional violation, ship-blocker):** 14 findings
- **Tier 2 (High, should fix pre-prod):** 5 findings
- **Tier 3 (Medium, defer-acceptable):** 2 findings
- **Tier 4 (Low, hygiene):** 3 (count only, no detail)
- **Anti-findings (rejected from Stage 1/2):** 3 items
- **Subsumed:** 3 items
- **Cross-phase-A4 deferred:** 3 items

**Overall constitutional posture:** FAIL

Tier 1 failures exist in every economic boundary of A2: ranking determinism, canonical correlation, message evidence, award lifecycle, concurrent award, and soft-delete lifecycle. The phase cannot ship until those are remediated.

## 2. Convergent findings (both auditors caught — high confidence)

### J-A2-01 — SPREAD award books child contracts but leaves child RFQs awardable
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.1, §2.2, §2.6
- **Source findings:** F-A2-OPUS-02 + F-A2-GEMINI-01
- **Files\Lines:** `backend/app/services/rfq_service.py:1114-1179`
- **Issue:**
  > ```python
  > for trade_rfq_id, quote in (
  >     (rfq.buy_trade_id, top.buy_quote),
  >     (rfq.sell_trade_id, top.sell_quote),
  > ):
  >     trade_rfq = session.get(RFQ, trade_rfq_id)
  >     contract = HedgeContract(..., rfq_id=trade_rfq.id, ...)
  >     session.add(contract)
  > ```
- **Mechanism (jury-verified):**
  `RFQService.award` computes the parent spread ranking at `rfq_service.py:1115-1125`, creates contracts against `trade_rfq.id` at `1136-1166`, and never mutates `trade_rfq.state` or inserts child `RFQStateEvent`s. Only the parent RFQ transitions to `AWARDED` and `CLOSED` at `1226-1251`. The children can still satisfy the `state == QUOTED` gate in later `award` or `award_quote` calls.
- **Recommended fix direction:**
  In the same transaction that awards the spread parent, transition both child RFQs to a terminal state or explicit `BOOKED_BY_PARENT` state and emit child state events carrying parent RFQ id and child contract id.
- **Acceptance criteria for remediation:**
  - [ ] `backend/app/services/rfq_service.py:1127-1179` mutates both child RFQ lifecycle states in the spread award transaction
  - [ ] `backend/tests/test_rfqs_step3.py` asserts child RFQs cannot be awarded after parent spread award
  - [ ] No regression in existing spread contract creation tests
- **Reasoning over reviewers:**
  Both reviewers identified the same root cause. Gemini's framing was cleaner; Opus added the important global-position double-award impact.

### J-A2-02 — Quote prices and ranking arithmetic use float in the economic decision path
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.5, §2.6
- **Source findings:** F-A2-OPUS-03 + F-A2-GEMINI-02
- **Files\Lines:** `backend/app/models/quotes.py:18-20`; `backend/app/schemas/rfq.py:108-113`; `backend/app/services/rfq_service.py:187-191,286-306`
- **Issue:**
  > ```python
  > fixed_price_value: Mapped[float] = mapped_column("price_value", Float, nullable=False)
  > ```
  > ```python
  > ordered = sorted(
  >     quotes, key=lambda q: float(q.fixed_price_value), reverse=reverse
  > )
  > values = [float(q.fixed_price_value) for q in ordered]
  > ```
- **Mechanism (jury-verified):**
  `RFQQuoteCreate.fixed_price_value` is `float` in `schemas/rfq.py:111`, persisted as SQLAlchemy `Float` in `models/quotes.py:19`, then coerced again with `float(...)` during trade ranking and spread subtraction. Migration `025_decimal_primitives.py` converts `hedge_contracts.fixed_price_value`, but it does not convert `rfq_quotes.price_value`; the A2 decision input remains IEEE-754. Tie detection over `set(float_values)` is therefore not a canonical price comparison.
- **Recommended fix direction:**
  Convert quote price schema/model/migration to fixed-scale `Decimal`/`Numeric`, compare Decimal values directly, and serialize ranking snapshots with canonical fixed-point strings.
- **Acceptance criteria for remediation:**
  - [ ] `backend/app/schemas/rfq.py` uses Decimal validation for quote prices
  - [ ] `backend/app/models/quotes.py` and Alembic use `Numeric(18, 6)` or the platform price precision constant
  - [ ] `backend/tests/test_rfqs_step2.py` covers adversarial near-tie Decimal inputs without float collapse
- **Reasoning over reviewers:**
  Both reviewers were right on the price path. Opus overextended the claim to some contract columns; that partial claim is rejected in anti-findings.

### J-A2-03 — Spread ranking ignores institutional spread direction
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.5, §2.6
- **Source findings:** F-A2-OPUS-05 + F-A2-GEMINI-02
- **Files\Lines:** `backend/app/services/rfq_service.py:306`
- **Issue:**
  > ```python
  > ordered = sorted(spreads, key=lambda s: s[1], reverse=True)
  > ```
- **Mechanism (jury-verified):**
  Trade ranking uses `reverse = rfq.direction == RFQDirection.sell` at `rfq_service.py:187`. Spread ranking always selects the largest `sell_quote - buy_quote` at `286-306`. The parent RFQ has a `direction` field in `models/rfqs.py:47-49` and `RFQCreate.direction` is mandatory, but the spread ranker does not use it or any replacement convention. That makes one side of spread economics rank the wrong counterparty.
- **Recommended fix direction:**
  Define the parent spread direction convention in A2 and make the ranker choose min or max spread from that explicit convention. If the current parent `direction` is not semantically sufficient, reject spread RFQs until an explicit direction is present.
- **Acceptance criteria for remediation:**
  - [ ] `backend/app/services/rfq_service.py:306` uses an explicit, tested spread direction rule
  - [ ] `backend/tests/test_rfqs_step2.py` covers both buy-spread and sell-spread ordering
  - [ ] The ranking snapshot records the sign convention used
- **Reasoning over reviewers:**
  I adopted the reviewers' Tier 1 posture because the code already has a mandatory direction field and then ignores it in the spread economic decision.

### J-A2-04 — Single-leg counterparties are silently excluded from spread ranking
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.5, §2.7
- **Source findings:** F-A2-OPUS-23 + F-A2-GEMINI-02
- **Files\Lines:** `backend/app/services/rfq_service.py:243-256`
- **Issue:**
  > ```python
  > eligible_counterparties = sorted(
  >     set(buy_latest.keys()) & set(sell_latest.keys())
  > )
  > ```
- **Mechanism (jury-verified):**
  `compute_spread_ranking` ranks only the intersection of latest buy-leg and sell-leg counterparties. A counterparty that quoted exactly one leg is not reported as incomplete, not included in failure metadata, and not represented in the later `ranking_snapshot` stored by `award` at `rfq_service.py:1237`. That is not the constitution's "incomplete quotes hard-fail" semantics.
- **Recommended fix direction:**
  Treat any active spread RFQ with partial counterparty quotes as a non-awardable ranking failure, or return a structured ranking failure that records excluded counterparties and leg missing reason.
- **Acceptance criteria for remediation:**
  - [ ] `backend/app/services/rfq_service.py:246-256` detects missing buy/sell leg counterparties explicitly
  - [ ] Existing test `test_spread_ranking_descending_and_ignores_missing_counterparty` is rewritten to expect hard-fail or structured exclusion
  - [ ] Award rejects rankings with incomplete counterparties
- **Reasoning over reviewers:**
  Gemini bundled this with ranking direction; Opus separated it. Separating it is more actionable and matches the constitutional hard-fail clause.

### J-A2-05 — Outbound RFQ bodies are not guaranteed to contain `RFQ#<rfq_number>`
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.3, §2.4
- **Source findings:** F-A2-OPUS-06 + F-A2-GEMINI-04
- **Files\Lines:** `backend/app/api/routes/rfqs.py:120-196`; `backend/app/services/rfq_message_builder.py:155-199`; `backend/app/services/rfq_engine.py:485-681`; `backend/app/services/rfq_service.py:473-487`
- **Issue:**
  > ```python
  > if cp.type == CounterpartyType.bank_br and payload.text_pt:
  >     message_body = payload.text_pt
  > elif payload.text_en:
  >     message_body = payload.text_en
  > else:
  >     message_body = fallback_body
  > ```
- **Mechanism (jury-verified):**
  The preview endpoint generates `text_en` and `text_pt` before an RFQ number exists. `build_rfq_message`, `build_pt_summary`, and `generate_rfq_text` have no `rfq_number` or `RFQ#` references. `RFQService.create` sends `payload.text_pt` or `payload.text_en` unchanged when present. The fallback includes `RFQ {rfq.rfq_number}`, not the required `RFQ#<rfq_number>`, and only runs when preview text is absent.
- **Recommended fix direction:**
  Inject `RFQ#<rfq_number>` in the send/persist path after the RFQ number is allocated and before any message leaves the process. Persist exactly the bytes sent.
- **Acceptance criteria for remediation:**
  - [ ] Every `RFQInvitation.message_body` created by `RFQService.create`, `refresh`, and `refresh_counterparty` contains `RFQ#<rfq_number>`
  - [ ] `backend/tests/test_rfqs_step1.py` or a new RFQ invitation test asserts preview text is wrapped with canonical id at send time
  - [ ] `backend/tests/test_rfq_message_builder.py` remains about trade text only unless builder signature is intentionally changed
- **Reasoning over reviewers:**
  Both reviewers were directionally right. The precise fix belongs in the post-number send path, not necessarily inside the pure LME formatter.

### J-A2-06 — Inbound messages are correlated by phone and timestamp, not canonical id
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.4, §2.6
- **Source findings:** F-A2-OPUS-07 + F-A2-OPUS-08 + F-A2-GEMINI-03
- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:255-310`
- **Issue:**
  > ```python
  > phone_variants = RFQOrchestrator._phone_variants(msg.from_phone)
  > invitation = (
  >     session.query(RFQInvitation)
  >     .join(RFQ, RFQInvitation.rfq_id == RFQ.id)
  >     .filter(RFQInvitation.recipient_phone.in_(phone_variants), ...)
  >     .order_by(RFQ.created_at.desc(), RFQInvitation.created_at.desc())
  >     .first()
  > )
  > ```
- **Mechanism (jury-verified):**
  `_process_single_message` never parses `RFQ#<rfq_number>` from `msg.text`. It expands the sender phone into variants, chooses the newest active RFQ by `RFQ.created_at`, logs `orchestrator_multi_rfq_same_phone` when more than one active RFQ matches, and still proceeds. That is exactly the non-canonical fallback §2.4 forbids.
- **Recommended fix direction:**
  Parse the canonical id from inbound text first. If absent, park the message as uncorrelatable. If present, query by RFQ number only; phone can be a secondary consistency check but not a correlator.
- **Acceptance criteria for remediation:**
  - [ ] `backend/app/services/rfq_orchestrator.py:255-310` has no phone-only successful correlation path
  - [ ] `backend/tests/test_rfq_orchestrator.py` covers missing canonical id, wrong phone with correct id, and multiple active RFQs on one phone
  - [ ] No auto-quote is created without canonical-id correlation
- **Reasoning over reviewers:**
  Both reviewers identified the core violation. Opus's multi-RFQ timestamp finding is subsumed by this root cause.

### J-A2-07 — Invitation evidence is sent before durable persistence and failed sends can roll back the RFQ
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.3, §2.6
- **Source findings:** F-A2-OPUS-09 + F-A2-GEMINI-08; F-A2-OPUS-10 subsumed
- **Files\Lines:** `backend/app/services/rfq_service.py:484-522,764-801,938-975`; `backend/app/models/rfqs.py:121-128`; `backend/alembic/versions/004_create_rfq_tables.py:117`
- **Issue:**
  > ```python
  > result = WhatsAppService.send_text_message(
  >     phone=phone,
  >     text=message_body,
  > )
  > ...
  > session.add(RFQInvitation(..., sent_at=now_utc() if sent else None))
  > ```
- **Mechanism (jury-verified):**
  `RFQService.create` sends WhatsApp at `484-487` before inserting the `RFQInvitation` at `506-522`. `refresh` and `refresh_counterparty` repeat the same send-then-persist pattern. On failed sends, code passes `sent_at=None`, while the model and base migration declare `sent_at` non-nullable. `rg` found no later migration relaxing `sent_at`. A carrier failure can therefore roll back the RFQ after an external send attempt, and a process crash can produce a delivered message with no DB evidence.
- **Recommended fix direction:**
  Use an outbox-style flow: persist invitation rows with durable queued status first, commit or flush them as the source of truth, send from those rows, then update status/provider id/sent timestamp.
- **Acceptance criteria for remediation:**
  - [ ] `RFQInvitation.sent_at` can represent queued/failed sends without violating DB constraints
  - [ ] Send attempts update an existing evidence row rather than creating evidence after network I/O
  - [ ] Tests cover successful send, failed send, and post-send DB failure behavior
- **Reasoning over reviewers:**
  Gemini caught the external-transaction shape; Opus caught the schema mismatch. The combination is a direct evidence hard-fail.

### J-A2-08 — `reject_quote` hard-deletes quote evidence
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.3, §2.6
- **Source findings:** F-A2-OPUS-14 + F-A2-GEMINI-05
- **Files\Lines:** `backend/app/models/quotes.py:11-23`; `backend/app/services/rfq_service.py:810-878`
- **Issue:**
  > ```python
  > session.delete(quote)
  > ```
- **Mechanism (jury-verified):**
  `RFQQuote` has no `state`, `deleted_at`, `rejected_at`, or rejection provenance. `reject_quote` sends a message, deletes the row, and optionally emits only an RFQ state event if all quotes are gone. Reconstructing the quote population available to a trader at award time becomes impossible after a quote rejection.
- **Recommended fix direction:**
  Add immutable quote lifecycle metadata and replace physical delete with a state transition or soft-delete marker. Rankers must exclude rejected quotes while snapshots retain their existence.
- **Acceptance criteria for remediation:**
  - [ ] `backend/app/models/quotes.py` gains rejected/deleted metadata and migration
  - [ ] `backend/app/services/rfq_service.py:860` no longer deletes quote rows
  - [ ] Tests prove rejected quotes are excluded from ranking but visible in audit/history
- **Reasoning over reviewers:**
  Both reviewers were right. This is not a UX deletion; it removes economic evidence.

### J-A2-09 — Contract `trade_date` uses ambient local-server date
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.6, §2.7
- **Source findings:** F-A2-OPUS-16 + F-A2-GEMINI-07
- **Files\Lines:** `backend/app/services/rfq_service.py:1025-1027,1160-1162,1211-1213`
- **Issue:**
  > ```python
  > reference=f"HC-{_uuid.uuid4().hex[:8].upper()}",
  > trade_date=date.today(),
  > ```
- **Mechanism (jury-verified):**
  Award timestamps use `now_utc()`, but contract `trade_date` uses `date.today()` in the process timezone. A server in Sao Paulo near UTC midnight records a different date than the award timestamp's UTC date. The constitution explicitly hard-fails ambiguous dates.
- **Recommended fix direction:**
  Derive `trade_date` from a defined clock and business-date convention, minimally `now_utc().date()` if UTC is the platform convention.
- **Acceptance criteria for remediation:**
  - [ ] All three RFQ award contract constructors stop using `date.today()`
  - [ ] Tests freeze server timezone/clock and assert deterministic trade date
  - [ ] Existing award timestamp and trade date semantics are documented in the test name or fixture
- **Reasoning over reviewers:**
  Both reviewers were correct on the date ambiguity. I split the reference collision into a separate Tier 2 finding.

### J-A2-10 — Award paths read RFQ state without row-level serialization
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.2, §2.6
- **Source findings:** F-A2-OPUS-18 + F-A2-GEMINI-06
- **Files\Lines:** `backend/app/services/rfq_service.py:548-556,992-997,1101-1106`
- **Issue:**
  > ```python
  > rfq = RFQService.get(session, rfq_id)
  > if rfq.state != RFQState.quoted:
  >     raise HTTPException(...)
  > ```
- **Mechanism (jury-verified):**
  `RFQService.get` is a plain `session.get`. `award_quote` and `award` both check `state == QUOTED` without `with_for_update`, optimistic versioning, or a DB uniqueness invariant on award events/contracts per RFQ. Under PostgreSQL READ COMMITTED, two concurrent requests can both pass the state gate and create contracts. Linkage capacity protects only commercial-hedge cases with an order; global-position and spread awards have no equivalent backstop.
- **Recommended fix direction:**
  Lock the RFQ row at the first award statement and re-check state under the lock. Add database-level idempotency or uniqueness for awarded RFQ contract creation where feasible.
- **Acceptance criteria for remediation:**
  - [ ] `award` and `award_quote` acquire row-level locks before state checks
  - [ ] A concurrency regression test proves only one award succeeds for the same RFQ
  - [ ] The lock behavior is verified for PostgreSQL SQL generation, not only SQLite
- **Reasoning over reviewers:**
  Both reviewers converged. This is a direct "exactly one award" failure.

### J-A2-11 — Archived RFQs remain mutable through service paths
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.1, §2.7
- **Source findings:** F-A2-OPUS-19 + F-A2-GEMINI-09
- **Files\Lines:** `backend/app/services/rfq_service.py:548-556`; `backend/app/api/routes/rfqs.py:70-72,488-498`; `backend/app/services/rfq_orchestrator.py:264-310`
- **Issue:**
  > ```python
  > def get(session: Session, rfq_id: UUID) -> RFQ:
  >     rfq = session.get(RFQ, rfq_id)
  >     if not rfq:
  >         raise HTTPException(...)
  >     return rfq
  > ```
- **Mechanism (jury-verified):**
  `list_rfqs` filters `RFQ.deleted_at.is_(None)`, and `archive_rfq` sets `deleted_at`. `RFQService.get` ignores `deleted_at`, and most mutation/read routes use that getter. Direct ID calls can submit quotes, refresh, reject, award, or inspect quotes for archived RFQs. The inbound phone correlation also omits an `RFQ.deleted_at.is_(None)` filter.
- **Recommended fix direction:**
  Make live RFQ loading explicit. Default service mutation paths should reject archived RFQs, while auditor-only history endpoints should opt into archived reads.
- **Acceptance criteria for remediation:**
  - [ ] `RFQService.get` or a new `get_live` rejects `deleted_at IS NOT NULL` for mutations
  - [ ] Orchestrator active-RFQ queries include `RFQ.deleted_at.is_(None)`
  - [ ] `backend/tests/test_soft_delete.py` covers archived RFQ mutation rejection
- **Reasoning over reviewers:**
  Opus assigned Tier 1 and Gemini Tier 2. I adopt Tier 1 because archived RFQs can still create contracts.

### J-A2-12 — Contract references use a 32-bit random namespace without retry
- **Adjudicated severity:** Tier 2
- **Constitutional rule:** §2.6
- **Source findings:** F-A2-OPUS-17 + F-A2-GEMINI-07
- **Files\Lines:** `backend/app/services/rfq_service.py:1025,1160,1211`; `backend/app/models/contracts.py:89-90`
- **Issue:**
  > ```python
  > reference=f"HC-{_uuid.uuid4().hex[:8].upper()}",
  > ```
  > ```python
  > reference: Mapped[str | None] = mapped_column(
  >     String(length=50), unique=True, nullable=True
  > )
  > ```
- **Mechanism (jury-verified):**
  Eight hex characters provide 32 bits of entropy. At institutional volume, birthday collisions become likely enough to produce sporadic award failures. The unique constraint prevents duplicate references, so this is fail-loud rather than silent corruption.
- **Recommended fix direction:**
  Use a full UUID, a sequence-backed contract reference, or retry on unique collision inside the award transaction.
- **Acceptance criteria for remediation:**
  - [ ] Award paths no longer rely on 8 hex characters without retry
  - [ ] Tests monkeypatch the generator to collide and assert deterministic recovery or clean conflict
  - [ ] No duplicate contract references can be committed
- **Reasoning over reviewers:**
  Both reviewers caught the issue. I downgraded Gemini's Tier 1 severity because the database uniqueness constraint prevents silent duplication; the remaining impact is reliability and award retryability.

## 3. Opus-only findings (jury-validated)

### J-A2-OPUS-01 — `award_quote` bypasses canonical ranking and omits ranking snapshot
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.2, §2.5, §2.6
- **Source findings:** F-A2-OPUS-01 + F-A2-OPUS-22
- **Files\Lines:** `backend/app/api/routes/rfqs.py:407-427`; `backend/app/services/rfq_service.py:979-1093`
- **Issue:**
  > ```python
  > quote = session.get(RFQQuote, quote_id)
  > ...
  > contract = HedgeContract(..., fixed_price_unit=quote.fixed_price_unit, ...)
  > ...
  > RFQStateEvent(..., winning_quote_ids=..., award_timestamp=award_time)
  > ```
- **Mechanism (jury-verified):**
  `award_quote` accepts an arbitrary quote id, creates a contract, and never calls `compute_trade_ranking` or `compute_spread_ranking`. It therefore bypasses canonical-unit checks, tie checks, best-price selection, and ranking snapshot persistence. The parallel route at `routes/rfqs.py:407-427` is a second award action beside `actions/award`.
- **Recommended fix direction:**
  Remove `award_quote` or make it a strict ranking-backed override path that persists a full ranking snapshot and explicit override reason. The constitutional reading favors one canonical award endpoint.
- **Acceptance criteria for remediation:**
  - [ ] `award_quote` cannot create a contract from a quote that the ranker would reject
  - [ ] Award events from every award path contain `ranking_snapshot`
  - [ ] Tests cover non-canonical unit, tie, and non-top quote selection
- **Reasoning over reviewers:**
  Gemini did not isolate this path. Opus was correct, and F-A2-OPUS-01 is subsumed by the broader bypass finding.
- **Why Gemini missed:** Gemini focused on `award` and cross-file lifecycle, not the parallel route.

### J-A2-OPUS-02 — Post-creation outbound action messages are sent without durable evidence
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.3, §2.7
- **Source findings:** F-A2-OPUS-11 + F-A2-OPUS-12
- **Files\Lines:** `backend/app/services/rfq_service.py:54-67,840-858,1042-1060`; `backend/app/services/rfq_orchestrator.py:596-607,631-637`
- **Issue:**
  > ```python
  > msg = _pick_action_message(cp, "contract")
  > result = WhatsAppService.send_text_message(
  >     phone=cp.whatsapp_phone, text=msg
  > )
  > ```
  > ```python
  > message = LLMAgent.generate_outbound_message(...)
  > WhatsAppService.send_text_message(phone=inv.recipient_phone, text=message)
  > ```
- **Mechanism (jury-verified):**
  `reject_quote` and `award_quote` send WhatsApp messages and persist no `RFQInvitation` or equivalent outbound evidence row. `notify_award` and `notify_reject` generate text at send time and also persist nothing. These messages are economic/legal evidence and cannot live only in logs.
- **Recommended fix direction:**
  Consolidate all RFQ outbound messages into one durable evidence/outbox table or make `RFQInvitation` cover every outbound message type. LLM-generated outbound text should be replaced or persisted before send.
- **Acceptance criteria for remediation:**
  - [ ] Reject, refresh, award, and notify messages all create durable message evidence rows
  - [ ] Message evidence includes rendered body, recipient, channel, provider id/status, and RFQ canonical id
  - [ ] Tests assert no direct `send_text_message` path exists without persistence
- **Reasoning over reviewers:**
  This is Opus-only as a named finding. Gemini's external transaction finding covers invitation creation but not these post-creation messages.
- **Why Gemini missed:** It audited the send-before-persist shape and did not enumerate each outbound action path.

### J-A2-OPUS-03 — Auto-created quotes silently default missing LLM fields
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.5, §2.6
- **Source findings:** F-A2-OPUS-13
- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:509-526`
- **Issue:**
  > ```python
  > convention = parsed.float_pricing_convention or "avg"
  > ...
  > fixed_price_value=float(price_value or 0),
  > fixed_price_unit=parsed.fixed_price_unit or "USD/MT",
  > float_pricing_convention=float_conv,
  > ```
- **Mechanism (jury-verified):**
  `_auto_create_quote` converts absent price to `0`, absent unit to `USD/MT`, and invalid convention to `avg`. The price-in-text guard checks only the numeric value and does not prove unit or convention. A partial or ambiguous counterparty response can become a rankable quote with system-invented terms.
- **Recommended fix direction:**
  Auto-create only when all canonical quote fields are explicitly extracted and validated from the raw message. Missing or invalid fields must route to human review.
- **Acceptance criteria for remediation:**
  - [ ] `_auto_create_quote` rejects missing price/unit/convention instead of defaulting
  - [ ] `backend/tests/test_rfq_orchestrator.py` covers missing unit, missing convention, and missing price
  - [ ] The returned status is non-mutating and audit-friendly
- **Reasoning over reviewers:**
  Opus was right to keep this inside A2: the mutation and defaults are in `rfq_orchestrator.py`, even if the parser is an A4 dependency.
- **Why Gemini missed:** Gemini deferred most LLM extraction behavior to A4 and did not inspect the A2 defaulting code as a mutation boundary.

### J-A2-OPUS-04 — RFQ quantity remains float at the A2 boundary
- **Adjudicated severity:** Tier 2
- **Constitutional rule:** §2.6
- **Source findings:** F-A2-OPUS-04
- **Files\Lines:** `backend/app/models/rfqs.py:44`; `backend/app/schemas/rfq.py:64`; `backend/app/services/rfq_service.py:388-397,1013,1148,1199`
- **Issue:**
  > ```python
  > quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
  > ```
- **Mechanism (jury-verified):**
  `RFQCreate.quantity_mt` is float and `RFQ.quantity_mt` is stored as `Float`. Migration `025_decimal_primitives.py` converted orders, hedge contracts, and linkages to Numeric, but not RFQs. A2 therefore still accepts and stores RFQ quantities through a binary-float boundary before creating Numeric contracts/linkages.
- **Recommended fix direction:**
  Align RFQ quantity with platform MT precision (`Numeric(15, 3)` / Decimal schema) and quantize before residual exposure checks.
- **Acceptance criteria for remediation:**
  - [ ] RFQ schema/model/migration use Decimal/Numeric MT precision
  - [ ] Residual exposure comparisons are Decimal comparisons
  - [ ] Tests cover boundary quantities at 0.001 MT precision
- **Reasoning over reviewers:**
  Opus was partly right. The HedgeContract storage claim is false in current code; the RFQ-side boundary remains real but lower severity than Opus assigned.
- **Why Gemini missed:** Gemini focused on price ranking rather than quantity precision.

### J-A2-OPUS-05 — `RFQQuote.counterparty_id` lacks database referential integrity
- **Adjudicated severity:** Tier 2
- **Constitutional rule:** §2.7
- **Source findings:** F-A2-OPUS-15
- **Files\Lines:** `backend/app/models/quotes.py:18`; `backend/app/schemas/rfq.py:108-113`
- **Issue:**
  > ```python
  > counterparty_id: Mapped[str] = mapped_column(String(length=64), nullable=False)
  > ```
- **Mechanism (jury-verified):**
  Quotes store counterparty ids as strings with no FK to `counterparties.id`. Invitations have a UUID FK, but quotes do not. Award and reporting paths later treat this string as authoritative counterparty identity.
- **Recommended fix direction:**
  Migrate `rfq_quotes.counterparty_id` to UUID with `ForeignKey("counterparties.id", ondelete="RESTRICT")`.
- **Acceptance criteria for remediation:**
  - [ ] Model, schema, and migration use UUID/FK for quote counterparty
  - [ ] Tests reject non-existent counterparties at quote submission
  - [ ] Existing orchestrator string conversions are removed or isolated at serialization boundaries
- **Reasoning over reviewers:**
  Valid Tier 2 auditability issue.
- **Why Gemini missed:** Gemini grep-read models and did not inspect quote referential integrity.

### J-A2-OPUS-06 — `archive_rfq` mutates lifecycle without RFQ state event or state gate
- **Adjudicated severity:** Tier 2
- **Constitutional rule:** §2.1, §2.3
- **Source findings:** F-A2-OPUS-20
- **Files\Lines:** `backend/app/api/routes/rfqs.py:474-502`
- **Issue:**
  > ```python
  > if rfq.deleted_at is not None:
  >     raise HTTPException(...)
  > rfq.deleted_at = datetime.now(timezone.utc)
  > session.commit()
  > ```
- **Mechanism (jury-verified):**
  The route writes `deleted_at` directly, does not require a terminal RFQ state, and does not emit an `RFQStateEvent`. The central audit decorator records route activity, but the RFQ lifecycle timeline endpoint will not show why the RFQ disappeared from the default list.
- **Recommended fix direction:**
  Move archive into service-layer lifecycle code, require allowed states, use `now_utc()`, and emit a state/timeline event or explicit archive event visible through the RFQ history API.
- **Acceptance criteria for remediation:**
  - [ ] `archive_rfq` no longer performs a direct untracked mutation
  - [ ] Tests assert archive is rejected for non-archivable states
  - [ ] State/history endpoint exposes the archive action
- **Reasoning over reviewers:**
  Valid but secondary to the Tier 1 soft-delete mutability finding.
- **Why Gemini missed:** Gemini caught the missing live filter but not the archive mutation itself.

### J-A2-OPUS-07 — RFQ state events allow and create missing event timestamps
- **Adjudicated severity:** Tier 2
- **Constitutional rule:** §2.3, §2.7
- **Source findings:** F-A2-OPUS-21
- **Files\Lines:** `backend/app/models/rfqs.py:158-160`; `backend/app/services/rfq_service.py:537-543`
- **Issue:**
  > ```python
  > event_timestamp: Mapped[DateTime | None] = mapped_column(
  >     DateTime(timezone=True), nullable=True
  > )
  > ```
  > ```python
  > RFQStateEvent(
  >     rfq_id=rfq.id,
  >     from_state=RFQState.created,
  >     to_state=RFQState.sent,
  > )
  > ```
- **Mechanism (jury-verified):**
  The created-to-sent transition omits `event_timestamp`, and the model allows it. Other event paths explicitly pass `now_utc()`. This weakens the event contract and forces auditors to infer event time from insertion time.
- **Recommended fix direction:**
  Make `event_timestamp` mandatory at the model/service contract or provide a server default and still pass explicit event time from application code.
- **Acceptance criteria for remediation:**
  - [ ] All RFQStateEvent inserts include an event timestamp
  - [ ] Schema/migration prevent null event timestamps for new rows
  - [ ] Tests fail if a lifecycle event lacks explicit timestamp
- **Reasoning over reviewers:**
  Valid Tier 2 auditability issue.
- **Why Gemini missed:** Gemini focused on higher-severity state integrity gaps.

### J-A2-OPUS-08 — Broad `_auto_create_quote` exception handler can misreport post-commit state
- **Adjudicated severity:** Tier 3
- **Constitutional rule:** §2.6, §2.7
- **Source findings:** F-A2-OPUS-25
- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:528-556`
- **Issue:**
  > ```python
  > try:
  >     quote = RFQService.submit_quote(session, rfq.id, quote_payload)
  >     session.commit()
  >     logger.info(...)
  >     return {...}
  > except Exception as exc:
  >     logger.error("orchestrator_auto_quote_failed", ...)
  > ```
- **Mechanism (jury-verified):**
  The `except Exception` covers both pre-commit mutation failures and post-commit logging/serialization failures. If commit succeeds but a later statement raises, the returned status can say `auto_quote_failed` while the quote exists. This is plausible but lower likelihood than the main A2 hard-fails.
- **Recommended fix direction:**
  Split pre-commit and post-commit phases, catch expected exceptions narrowly, and use a distinct partial-success status if post-commit observability fails.
- **Acceptance criteria for remediation:**
  - [ ] No broad exception handler wraps both commit and post-commit return construction
  - [ ] Test simulates post-commit logger/serializer failure and asserts accurate status
  - [ ] Session rollback behavior is explicit for pre-commit failures
- **Reasoning over reviewers:**
  Real but not a ship-blocking constitutional defect by itself.
- **Why Gemini missed:** It did not inspect this rare post-commit error shape.

### J-A2-OPUS-09 — Manual quote validation accepts negative price and arbitrary unit until ranking
- **Adjudicated severity:** Tier 3
- **Constitutional rule:** §2.7
- **Source findings:** F-A2-OPUS-26
- **Files\Lines:** `backend/app/schemas/rfq.py:108-113`; `backend/app/services/rfq_service.py:593-600`
- **Issue:**
  > ```python
  > fixed_price_value: float
  > fixed_price_unit: str = Field(..., max_length=32)
  > ```
- **Mechanism (jury-verified):**
  Manual quote submission does not enforce positive price or canonical unit at ingest. The rankers later hard-fail non-canonical units, but storing invalid economic inputs increases audit noise and becomes dangerous when bypass paths such as `award_quote` exist.
- **Recommended fix direction:**
  Add positive price validation and canonical unit validation at quote creation, while keeping ranker hard-fails as a second line of defense.
- **Acceptance criteria for remediation:**
  - [ ] Negative/zero quote prices are rejected by schema/service
  - [ ] Non-canonical units are rejected or normalized with evidence at ingest
  - [ ] Existing ranker non-comparable tests remain
- **Reasoning over reviewers:**
  Opus's Tier 3 severity is correct after separately promoting `award_quote` bypass as Tier 1.
- **Why Gemini missed:** Gemini rolled quote validation into the hard-delete finding and did not separate manual ingest validation.

## 4. Gemini-only findings (jury-validated)

(None. Gemini-only formal findings were either convergent with Opus findings or downgraded within convergent J-A2-12.)

## 5. Anti-findings (FPs from Stage 1/2)

### A-A2-J-01 — SPREAD linkage partial rollback is not a bug
- **Source:** A-A2-OPUS-02 + A-A2-GEMINI-01
- **Reviewer claim:**
  > A second linkage failure in spread award might commit the first contract/linkage partially.
- **Actual code:**
  > ```python
  > session.add(contract)
  > session.flush()
  > ...
  > LinkageService.create(session, trade_rfq.order_id, contract.id, trade_rfq.quantity_mt)
  > ```
- **Why it is NOT a bug:**
  The contract flushes and linkage inserts occur in the same SQLAlchemy session/transaction. Route code commits after `RFQService.award` returns; an exception before that rolls the transaction back. The child-RFQ-state issue is real, but partial commit of the spread linkage sequence is not.

### A-A2-J-02 — Latest-quote selection is not nondeterministic due to Python dict iteration
- **Source:** F-A2-GEMINI-02 adjacent-risk claim; Auditor A Q2 anti-finding
- **Reviewer claim:**
  > The tiebreaker of dicts is unstable cross-version and infrastructure.
- **Actual code:**
  > ```python
  > ordered = sorted(
  >     quotes,
  >     key=lambda q: (q.counterparty_id, q.received_at, q.created_at, str(q.id)),
  > )
  > latest: dict[str, RFQQuote] = {}
  > ```
- **Why it is NOT a bug:**
  The code first establishes a total order by counterparty, received timestamp, created timestamp, and UUID string. Python dict insertion order is a language guarantee in supported Python 3.x. The ranking price arithmetic is broken, but latest-quote selection is deterministic.

### A-A2-J-03 — HedgeContract quantity storage is not currently Float
- **Source:** F-A2-OPUS-04 partial claim
- **Reviewer claim:**
  > `RFQ.quantity_mt` and `HedgeContract.quantity_mt` are Float.
- **Actual code:**
  > ```python
  > quantity_mt: Mapped[Decimal] = mapped_column(
  >     Numeric(MT_NUMERIC_PRECISION, MT_NUMERIC_SCALE), nullable=False
  > )
  > ```
- **Why it is NOT a bug:**
  Current `backend/app/models/contracts.py` uses Decimal/Numeric for `HedgeContract.quantity_mt`, and migration `025_decimal_primitives.py` converts `hedge_contracts.quantity_mt`. The RFQ quantity boundary remains a validated Tier 2 issue; the HedgeContract storage half is rejected.

## 6. Subsumed findings

### S-A2-J-01 — F-A2-OPUS-01 subsumed by J-A2-OPUS-01
- **Reason:** The missing `ranking_snapshot` is a direct consequence of `award_quote` bypassing the canonical ranker and award action.

### S-A2-J-02 — F-A2-OPUS-08 subsumed by J-A2-06
- **Reason:** Timestamp proximity is the failure mode of the broader phone-only inbound correlation path.

### S-A2-J-03 — F-A2-OPUS-10 subsumed by J-A2-07
- **Reason:** `sent_at` nullability is part of the invitation evidence persistence defect and should be fixed in the same outbox/evidence change.

## 7. Fresh findings (jury caught what both missed — rare)

(None.)

## 8. Cross-phase-A4 deferred

### X-A2-J-01 — Raw inbound message durability before A2 processing
- **A2 surface:** `backend/app/services/rfq_orchestrator.py:250-253`
- **A4 dependency:** `webhook_processor.py` / inbound message queue
- **Governance clause at risk:** §2.3
- **Why deferred to A4:** A2 receives a `WhatsAppInboundMessage` object and processes it; the durable raw-message ingestion layer is outside the A2 file perimeter.
- **What A4 audit must verify:** Confirm every raw inbound provider payload is durably persisted before parsing or RFQ correlation, including orphan/no-match/rejected messages.

### X-A2-J-02 — LLM confidence and degraded-mode semantics in quote extraction
- **A2 surface:** `backend/app/services/rfq_orchestrator.py:337-341,411-417`
- **A4 dependency:** `LLMAgent.classify_intent`, `LLMAgent.parse_quote_message`, `LLMAgent.should_auto_create_quote`
- **Governance clause at risk:** §2.4, §2.5, §2.6
- **Why deferred to A4:** A2 contains a real boundary concern, but threshold calibration and parser reliability live in A4. A2 must still fail closed when classifier/parse confidence is unavailable or incomplete.
- **What A4 audit must verify:** Confirm confidence thresholds are deterministic, calibrated, version-controlled, and never allow mutation on ambiguous or incomplete quote extraction.

### X-A2-J-03 — LLM-generated outbound award/reject text
- **A2 surface:** `backend/app/services/rfq_orchestrator.py:596-607,631-637`
- **A4 dependency:** `LLMAgent.generate_outbound_message`
- **Governance clause at risk:** §2.3, §2.7
- **Why deferred to A4:** A2 must persist outbound evidence regardless; A4 must separately determine whether `generate_outbound_message` is deterministic templating or model generation.
- **What A4 audit must verify:** If it is model-backed generation, replace or constrain it so binding economic messages are deterministic, versioned, and reconstructable.

## 9. Open questions for orchestrator

(None.)

## 10. Remediation dispatch metadata

For the orchestrator to decide remediation scope:

- **Total Tier 1 fixes required:** 14
- **Total Tier 2 fixes required:** 5
- **Total Tier 3 fixes deferrable:** 2
- **Estimated remediation scope:** split per concern:
  - Ranking and numeric primitives: quote Decimal, spread direction, incomplete spread quotes, quote validation.
  - Canonical messaging and evidence: outbound `RFQ#`, inbound id-only correlation, outbox/invitation evidence, action message persistence.
  - Award lifecycle: remove or constrain `award_quote`, add award locks, close spread child RFQs.
  - Soft-delete/archive lifecycle: live RFQ loading, archived mutation rejection, archive events.
  - Contract hygiene: UTC trade date, longer/retryable references, RFQ quantity Decimal, quote counterparty FK.
- **Critical sequencing:** Fix outbound canonical id before enforcing inbound id-only correlation in production migration. Fix Decimal quote storage before rewriting ranking/tie tests. Add award locks before concurrency remediation tests become meaningful. Decide `award_quote` canonicality before implementing its snapshot behavior.
- **Required regression tests:**
  - `backend/tests/test_rfqs_step2.py` — covers J-A2-02, J-A2-03, J-A2-04, J-A2-OPUS-09
  - `backend/tests/test_rfqs_step3.py` — covers J-A2-01, J-A2-10, J-A2-OPUS-01, J-A2-09, J-A2-12
  - `backend/tests/test_rfq_orchestrator.py` — covers J-A2-06, J-A2-OPUS-03, X-A2-J-02 boundary behavior
  - `backend/tests/test_rfq_message_builder.py` or RFQ service creation tests — covers J-A2-05 without polluting pure trade-text builders if injection stays in send path
  - `backend/tests/test_soft_delete.py` — covers J-A2-11 and J-A2-OPUS-06
  - A new quote evidence test module — covers J-A2-08, J-A2-OPUS-02, J-A2-OPUS-05, J-A2-OPUS-07

## 11. Self-bias confession (mandatory)

Per the 3-model audit pattern:

- **Findings I reversed from my first pass:** 1 (F-A2-OPUS-04 partially: HedgeContract quantity is Numeric in current code; RFQ quantity remains a Tier 2 issue)
- **Findings where I gave benefit-of-doubt to a reviewer:** 2 (F-A2-OPUS-05/F-A2-GEMINI-02 on spread direction; F-A2-OPUS-13 on LLM defaulting as an A2 mutation-boundary issue)
- **Findings where I overruled both reviewers:** 0
- **Findings where I disagreed with worst-of-severity and downgraded:** 1 (F-A2-GEMINI-07 reference collision downgraded to Tier 2 because `HedgeContract.reference` is unique and collision is fail-loud, not silent duplicate or unreconstructable contract)
