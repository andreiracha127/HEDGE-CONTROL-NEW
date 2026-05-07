# Phase A2 — Stage 1 Findings — Auditor A (Opus)

**Date:** 2026-05-06
**Scope commit:** `9f6735729be0ee951644956a288bb18a96d7b162`
**Files audited:**
- `backend/app/services/rfq_service.py`
- `backend/app/services/rfq_orchestrator.py`
- `backend/app/services/rfq_engine.py` (grep'd for identifier injection only)
- `backend/app/services/rfq_message_builder.py` (grep'd for identifier injection only)
- `backend/app/models/rfqs.py`
- `backend/app/models/quotes.py`
- `backend/app/api/routes/rfqs.py`
- `backend/app/schemas/rfq.py`
- `backend/alembic/versions/004_create_rfq_tables.py` (cross-checked schema)
- `backend/app/models/contracts.py` (grep'd for `unique=True` on reference)
- `backend/app/services/llm_agent.py` (grep'd for `CONFIDENCE_THRESHOLD` only — A4 module)

## Executive summary

- Tier 1 (Critical, constitutional violation, ship-blocker): **18 findings**
- Tier 2 (High, should fix pre-merge / pre-prod): **5 findings**
- Tier 3 (Medium, defer-acceptable): **6 findings**
- Tier 4 (Low, hygiene): **3 (count only)**
- Anti-findings (rejection of suspected issues): **2 items**
- Cross-phase-A4 risks: **3 items**

**Overall constitutional posture:** **FAIL.** Multiple keystone violations: (i) no canonical-identifier correlation on the inbound boundary (entirely phone-based, with timestamp tiebreak), (ii) preview-time message builders never inject `RFQ#<rfq_number>` into `text_en`/`text_pt` so outbound invites that use those fields are non-compliant with §2.4 by construction, (iii) numeric core (price/quantity) stored as IEEE-754 `Float` rather than `Decimal/Numeric`, (iv) `award_quote` is a parallel "award" path that bypasses ranking and never persists `ranking_snapshot`, (v) `trade_date = date.today()` ambient local-server timezone, (vi) no row-level lock on RFQ during award (concurrent-award race), (vii) `RFQ.deleted_at` is filtered only by `list_rfqs` and the two background jobs — never by `get`, `submit_quote`, `award`, `award_quote`, the inbound message router, or the rankers. Each of these is independently a §2.x ship-blocker.

## Structured Q&A

### Q1 — Atomicidade e integridade do Award

**Answer:** Partially. The HTTP route boundary places `award` and `award_quote` in a single `session.commit()`, so contract creation and the final `RFQStateEvent` rows commit together. **But two structural defects break the institutional intent:** (a) `award_quote` (rfq_service.py:978–1093) creates a contract and emits state events but **does not compute or persist `ranking_snapshot` at all** — direct §2.6 reconstruction violation; (b) the SPREAD branch of `award` (rfq_service.py:1114–1178) creates two child contracts and may invoke `LinkageService.create` twice but **never transitions the state of the referenced `buy_trade_id` / `sell_trade_id` child RFQs** — those child RFQs remain `QUOTED` and remain individually awardable.

**Evidence:**

```python
# rfq_service.py:1067-1080  — award_quote: NO ranking_snapshot
session.add(
    RFQStateEvent(
        rfq_id=rfq.id,
        from_state=RFQState.quoted,
        to_state=RFQState.awarded,
        user_id=user_id,
        winning_quote_ids=json.dumps([str(quote.id)], sort_keys=True),
        winning_counterparty_ids=json.dumps(
            [quote.counterparty_id], sort_keys=True
        ),
        award_timestamp=award_time,
        event_timestamp=award_time,
    )
)
```

vs. `award` at rfq_service.py:1237 which does pass `ranking_snapshot=json.dumps(...)`.

```python
# rfq_service.py:1127-1178  — SPREAD award: only the parent RFQ is mutated
for trade_rfq_id, quote in (
    (rfq.buy_trade_id, top.buy_quote),
    (rfq.sell_trade_id, top.sell_quote),
):
    ...
    trade_rfq = session.get(RFQ, trade_rfq_id)
    ...
    contract = HedgeContract(...)
    session.add(contract)
    session.flush()
    created_contract_ids.append(str(contract.id))

    if (
        trade_rfq.intent == RFQIntent.commercial_hedge
        and trade_rfq.order_id is not None
    ):
        LinkageService.create(...)
# No `trade_rfq.state = ...`, no RFQStateEvent for trade_rfq.
```

**Mechanism:** A spread award books contracts against the buy-trade and sell-trade RFQs but leaves both child RFQs in `QUOTED`. A trader (or another concurrent operator) can subsequently call `POST /rfqs/{buy_trade_id}/actions/award` or `award-quote` and book *another* contract against the same child RFQ — the only protection is `state == QUOTED` (still true) plus an out-of-band check on `LinkageService` capacity (Phase A1). For `intent == global_position` children (no order_id), nothing prevents double award.

**Severity if violation:** Tier 1 (see F-A2-OPUS-01, F-A2-OPUS-02).

---

### Q2 — Determinismo do ranking de trade

**Answer:** **No** — the ranking is non-deterministic in two reinforcing ways.

**Evidence:**

```python
# rfq_service.py:187-199
reverse = rfq.direction == RFQDirection.sell
ordered = sorted(
    quotes, key=lambda q: float(q.fixed_price_value), reverse=reverse
)
values = [float(q.fixed_price_value) for q in ordered]
if len(set(values)) != len(values):
    return TradeRankingRead(
        rfq_id=rfq.id,
        status="FAILURE",
        failure_code=TradeRankingFailureCode.tie,
        failure_reason="Tie detected",
        ranking=[],
    )
```

The conversion is `float(q.fixed_price_value)`. In Python this is identity *because the storage column is already `Float`*:

```python
# models/quotes.py:19
fixed_price_value: Mapped[float] = mapped_column("price_value", Float, nullable=False)
```

So the institutional concern flips: the **storage itself** is IEEE-754 `Float`. There is no Decimal anywhere in the price path (boundary schema also: `schemas/rfq.py:111` `fixed_price_value: float`).

**Mechanism:**

1. **Decimal-precision collapse at the schema boundary.** Prices arriving as JSON numbers in the `POST /rfqs/{id}/quotes` body are parsed by Pydantic into Python `float`, then persisted as PostgreSQL `Float`. Any counterparty quote with > ~15 significant decimal digits is silently truncated *before* it ever reaches ranking.
2. **Tie detection by `set(values)` over `float`.** Because the values are already collapsed to IEEE-754 doubles, two distinct counterparty intentions that round to the same `float` (a real risk for premium/discount quotes calculated as differentials) collide silently in `set(...)` — the system declares `tie` (FAILURE) where there was no tie. Conversely, two values that *would* be equal in Decimal but differ at bit ULP-level produce `len(set) == len(values)` and the system silently prefers one — a real, undetectable, non-deterministic ranking outcome under Pydantic / PostgreSQL Float coercion paths.
3. **Tie hard-fail is correct in spirit** (returns FAILURE/`TIE`), but the input domain is not Decimal so the predicate is unsound.

`select_latest_quotes_by_counterparty` (rfq_service.py:96–132) is fine — sort key is `(counterparty_id, received_at, created_at, str(q.id))` which is fully ordered. Iteration over `latest.values()` then becomes `dict.values()` which is insertion-ordered (Python 3.7+ guaranteed). That part is deterministic.

`reverse = rfq.direction == RFQDirection.sell` (line 187) is **institutionally correct**: for SELL direction, counterparty offers the highest bid → it's the best for us; we want the highest first.

**Severity if violation:** Tier 1 (F-A2-OPUS-03).

---

### Q3 — Determinismo do ranking de spread

**Answer:** **No.** Three independent issues — same Float problem, an absolute `reverse=True` ignoring spread-direction, and silent drop of single-leg counterparties.

**Evidence:**

```python
# rfq_service.py:246-248
eligible_counterparties = sorted(
    set(buy_latest.keys()) & set(sell_latest.keys())
)
```

```python
# rfq_service.py:286-294
spreads.append(
    (
        cp,
        float(sell_quote.fixed_price_value)
        - float(buy_quote.fixed_price_value),
        buy_quote,
        sell_quote,
    )
)
```

```python
# rfq_service.py:296-306
spread_values = [s[1] for s in spreads]
if len(set(spread_values)) != len(spread_values):
    return SpreadRankingRead(...)  # tie

ordered = sorted(spreads, key=lambda s: s[1], reverse=True)
```

**Mechanism:**

1. **Counterparty intersection silently drops single-leg quotes.** Constitution §2.5 says "Incomplete quotes hard-fail." A counterparty that quoted only the buy leg is, by definition, incomplete relative to the spread RFQ — they should hard-fail (or at minimum be surfaced as `non_comparable` for that counterparty). Instead they are silently removed via `set(buy_latest.keys()) & set(sell_latest.keys())`. There is no `RFQStateEvent`, no failure code, no audit trail of who was excluded. This makes the ranking decision unreconstructible from `ranking_snapshot` alone (the snapshot only stores the survivors).
2. **`reverse=True` is unconditional.** The spread ranking has no analog of trade ranking's `reverse = rfq.direction == RFQDirection.sell`. The code always picks the **largest spread** regardless of the parent RFQ's intent or who is the institutional principal of the spread. For a buy-side spread (where the principal pays the spread and wants to *minimize* it), this awards the worst counterparty.
3. **Float precision.** Same mechanism as Q2 — `float(sell) - float(buy)` is double-precision subtraction; for typical commodity quote magnitudes (USD/MT in the hundreds), spread differences below ~1e-13 collapse to zero and trigger a spurious `tie`. Spreads in commodities are routinely sub-percent of price; this is not a hypothetical class of failure for derivatives.

**Severity if violation:** Tier 1 (F-A2-OPUS-04, F-A2-OPUS-05).

---

### Q4 — Canonical identifier `RFQ#<rfq_number>` (§2.4)

**Answer:** **No** — §2.4 is structurally violated on both outbound and inbound.

**Evidence — RFQ number generation:**

```python
# rfq_service.py:420-424
seq = RFQSequence()
session.add(seq)
session.flush()
year = now_utc().year
rfq_number = f"RFQ-{year}-{int(seq.id):06d}"
```

```python
# models/rfqs.py:175-178
class RFQSequence(Base):
    __tablename__ = "rfq_sequences"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
```

`RFQSequence.id` is autoincrement → **monotonic + race-free** at PG level, **not gap-free** (rollback gaps possible — acceptable). Year is `now_utc().year` (good — UTC). `rfq_number` has `unique=True` (models/rfqs.py:38) so collision risk is null. **OK.**

**Evidence — outbound omission of `RFQ#<rfq_number>`:**

`rfq_engine.py` and `rfq_message_builder.py` were grep'd for `rfq_number` and `RFQ#`: **0 matches.** `build_rfq_message` (the English LME text) and `build_pt_summary` (the Portuguese one-liner) are pure trade-text renderers — they never receive an `rfq_number` argument and they never inject the canonical id.

The `text_en` / `text_pt` produced by `POST /rfqs/preview-text` (routes/rfqs.py:120–196) are the same strings later persisted in `RFQ.text_en` / `RFQ.text_pt` and used as the body of every WhatsApp invitation (rfq_service.py:477–482):

```python
# rfq_service.py:473-482
fallback_body = (
    f"RFQ {rfq.rfq_number} — {rfq.commodity} "
    f"{rfq.quantity_mt}MT {rfq.direction.value}"
)
if cp.type == CounterpartyType.bank_br and payload.text_pt:
    message_body = payload.text_pt
elif payload.text_en:
    message_body = payload.text_en
else:
    message_body = fallback_body
```

The fallback path *does* contain the id, but the trader-driven flow (preview → use `text_pt` / `text_en`) does not. **Every invite produced through the normal preview workflow leaves with no canonical identifier.**

**Evidence — per-counterparty action messages (no id):**

```python
# rfq_service.py:54-67
_DEFAULT_MESSAGES = {
    "refresh": {"pt": "Atualize o preço por favor", "en": "Refresh, please"},
    "reject":  {"pt": "Fechamos aqui, muito obrigado pela cotação", "en": "Closed here, thanks for the quote"},
    "contract":{"pt": "Fechado no último preço", "en": "Book in the last price"},
}
```

These are sent unmodified by `reject_quote` (line 841), `award_quote` (line 1043), and `refresh_counterparty` (line 930). **None contains `RFQ#<rfq_number>`.**

**Evidence — inbound correlation by phone, not by id:**

```python
# rfq_orchestrator.py:264-275
phone_variants = RFQOrchestrator._phone_variants(msg.from_phone)
invitation = (
    session.query(RFQInvitation)
    .join(RFQ, RFQInvitation.rfq_id == RFQ.id)
    .filter(
        RFQInvitation.recipient_phone.in_(phone_variants),
        RFQInvitation.channel == RFQInvitationChannel.whatsapp,
        RFQ.state.in_([RFQState.sent, RFQState.quoted]),
    )
    .order_by(RFQ.created_at.desc(), RFQInvitation.created_at.desc())
    .first()
)
```

`_process_single_message` **never parses `RFQ#<rfq_number>` from the inbound message text.** It correlates exclusively by phone, with `_phone_variants` doing fuzzy 8-/9-digit Brazilian-mobile expansion. When more than one active RFQ matches the same phone, the resolver is `ORDER BY RFQ.created_at DESC LIMIT 1` — the multi-match is detected and *logged as a warning* (lines 290–307) but the route is not blocked, and the newest RFQ is silently selected. That is exactly the "timestamp proximity" fallback §2.4 forbids.

**Mechanism:**

Outbound omission and inbound non-parsing reinforce each other. Because the trader-built `text_pt` / `text_en` does not embed the canonical id, even a future inbound parser that *did* try to extract `RFQ#<rfq_number>` from the reply quote would mostly fail and have to fall back to phone — the path the system is on today.

**Severity if violation:** Tier 1. See F-A2-OPUS-06 (outbound id omission), F-A2-OPUS-07 (inbound phone-only correlation), F-A2-OPUS-08 (multi-RFQ tiebreak by created_at).

---

### Q5 — Persistência de mensagens como evidência (§2.3)

**Answer:** **No** — three independent gaps.

**Evidence — send-before-persist window in `RFQService.create`:**

```python
# rfq_service.py:484-522
result = WhatsAppService.send_text_message(
    phone=phone,
    text=message_body,
)
if result.success:
    send_status = RFQInvitationStatus.sent
    provider_message_id = result.provider_message_id or ""
    ...
session.add(
    RFQInvitation(
        rfq_id=rfq.id,
        ...
        sent_at=now_utc()
        if send_status == RFQInvitationStatus.sent
        else None,
        idempotency_key=idem_key,
    )
)
```

WhatsApp send happens before the `RFQInvitation` is `session.add(...)`'d. If the worker is killed between line 487 and line 522, the message reached the counterparty but no row exists. **Constitutional evidence gap.**

**Evidence — `sent_at` schema/code mismatch (will fail in production):**

```python
# alembic/versions/004_create_rfq_tables.py:117
sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
```

vs. rfq_service.py:517–519 passing `None` whenever `send_status != sent`. PostgreSQL will raise `IntegrityError`; the entire RFQ creation rolls back. This is the *opposite* of evidence persistence — a single failed-send invitation rolls the whole RFQ back to non-existence. (Tests likely pass on SQLite or only with all-success WhatsApp mocks; verify in jury read.)

**Evidence — `reject_quote` and `award_quote` send WhatsApp but persist nothing:**

```python
# rfq_service.py:840-858 (reject_quote) and 1042-1060 (award_quote)
if cp and cp.whatsapp_phone:
    msg = _pick_action_message(cp, "reject")  # or "contract"
    result = WhatsAppService.send_text_message(
        phone=cp.whatsapp_phone, text=msg
    )
    ...  # log only, no session.add(RFQInvitation(...))
```

The outbound message is observable in logs only — there is no `RFQInvitation` row, no audit table. A counterparty receives a "Fechado no último preço" / "Closed here" message and the system has no first-class evidence of the send. (Note: `RFQStateEvent` records the award event but not the *message* that went out.) This is exactly "messages are evidence, not UI artifacts" inverted.

**Evidence — `notify_award` / `notify_reject` use LLM-generated text and never persist:**

```python
# rfq_orchestrator.py:596-607 (notify_award)
message = LLMAgent.generate_outbound_message(
    action="award", language=language,
    recipient_name=invitation.recipient_name,
    rfq_number=rfq.rfq_number,
    ...
)
WhatsAppService.send_text_message(
    phone=invitation.recipient_phone,
    text=message,
)
```

The text is generated by the LLM at send time (text-only, no template), the result is sent, and **no row is appended to `RFQInvitation`.** Even the `rfq_number` argument is *passed to the template generator* but the audit cannot prove that the rendered text actually contained it. (`notify_reject` at lines 609–637 has the same shape.)

**Evidence — `RFQStateEvent.ranking_snapshot` is sufficient for `award` but not `award_quote`:**

`award` persists a JSON dump of the full ranking (rfq_service.py:1237). `award_quote` does not (lines 1067–1080 — no `ranking_snapshot=` kwarg). For `award_quote` the only forensic record is `winning_quote_ids` — there is no record of *what the ranking was at decision time*, no record of *which rivals existed*, no record of whether the winning quote was even in the canonical-unit set. **§2.6 reconstruction violation.**

**Severity if violation:** Tier 1 (F-A2-OPUS-09 through F-A2-OPUS-12).

---

### Q6 — Validade de quote e lifecycle (§2.5)

**Answer:** **Multiple gaps.** `RFQQuote` has no state, no soft-delete, no audit of supersession; quote validation is thin.

**Evidence — `RFQQuote` minimal model:**

```python
# models/quotes.py:11-23
class RFQQuote(Base):
    __tablename__ = "rfq_quotes"
    id: Mapped[uuid.UUID] = ...
    rfq_id: Mapped[uuid.UUID] = ...
    counterparty_id: Mapped[str] = mapped_column(String(length=64), nullable=False)
    fixed_price_value: Mapped[float] = mapped_column("price_value", Float, nullable=False)
    fixed_price_unit: Mapped[str] = mapped_column("price_unit", String(length=32), nullable=False)
    float_pricing_convention: Mapped[str] = mapped_column("pricing_convention", String(length=64), nullable=False)
    received_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

No `state`, no `deleted_at`, no `superseded_by`, no `accepted_at` / `rejected_at`. `counterparty_id` is `String` not `UUID + ForeignKey` — so referential integrity to `counterparties.id` is not enforced at the DB layer (the quote could reference a deleted or non-existent counterparty).

**Evidence — `submit_quote` validation gaps:**

```python
# rfq_service.py:567-602
quote = RFQQuote(
    rfq_id=rfq_id,
    counterparty_id=payload.counterparty_id,
    fixed_price_value=payload.fixed_price_value,
    fixed_price_unit=payload.fixed_price_unit,
    float_pricing_convention=payload.float_pricing_convention.value,
    received_at=payload.received_at,
)
```

There is no check that `payload.fixed_price_value > 0`, no check that `fixed_price_unit` is in the canonical set (`USD/MT`, etc.) — that check only fires later inside the rankers. A quote with `fixed_price_value=-5.0` and `fixed_price_unit="banana"` will persist successfully; the ranking will fail with `non_comparable` only when someone calls `compute_*_ranking`.

**Evidence — `select_latest_quotes_by_counterparty` keeps all rows but ranks one:**

```python
# rfq_service.py:100-132
ordered = sorted(
    quotes,
    key=lambda q: (q.counterparty_id, q.received_at, q.created_at, str(q.id)),
)
```

Older quotes are preserved in the table — that's good for evidence reconstruction. **But there is no row marker indicating "this quote was superseded by quote X".** The latest-selection logic is implicit and lives only in `select_latest_quotes_by_counterparty`. A maintainer who runs `SELECT * FROM rfq_quotes WHERE rfq_id = ?` gets every revision but cannot tell which one fed the actual award without re-running the selection algorithm — and the algorithm could change.

**Evidence — incomplete quotes hard-fail behaviour:**

`compute_trade_ranking` (rfq_service.py:166–185) does return `FAILURE/non_comparable` when any quote has a non-canonical unit or units mismatch. That's correct.

**However**, the orchestrator's `_auto_create_quote` (rfq_orchestrator.py:519–526) silently coerces missing/invalid LLM-extracted fields:

```python
quote_payload = RFQQuoteCreate(
    rfq_id=rfq.id,
    counterparty_id=str(invitation.counterparty_id),
    fixed_price_value=float(price_value or 0),
    fixed_price_unit=parsed.fixed_price_unit or "USD/MT",
    float_pricing_convention=float_conv,  # default 'avg' if invalid
    received_at=msg.timestamp,
)
```

If the LLM returns `fixed_price_unit=None`, the system **defaults to `"USD/MT"` silently** and records the quote as if the counterparty had agreed to that unit. Same for `float_pricing_convention` defaulting to `avg` (lines 510–513 fallback `except ValueError: float_conv = FloatPricingConvention.avg`). And `fixed_price_value=float(price_value or 0)` lets a `None` price collapse to `0` and persist.

This is precisely the §2.5 "incomplete quotes hard-fail" violation — incomplete LLM output is silently completed by the orchestrator with defaults rather than being parked for human review.

**Severity if violation:** Tier 1 for the silent-defaulting (F-A2-OPUS-13); Tier 2 for the model-shape gaps (F-A2-OPUS-14, F-A2-OPUS-15).

---

### Q7 — Invariantes de criação do contrato (§2.2, §2.6)

**Answer:** **No.** Three independent constitutional violations.

**Evidence — `HC-{uuid4().hex[:8]}` reference:**

```python
# rfq_service.py:1025, 1160, 1211 (three call sites, all identical)
reference=f"HC-{_uuid.uuid4().hex[:8].upper()}",
```

```python
# models/contracts.py:90
String(length=50), unique=True, nullable=True
```

The `reference` column is `unique=True` so a collision raises `IntegrityError` — fail-loud, not silent. **However**, 8 hex chars = 32 bits; by the birthday formula a 1% collision probability is reached at ~9,300 contracts and 50% at ~77,000. There is **no retry loop** — a collision aborts the entire award (rollback, contract not created, RFQStateEvent rolled back). At any non-trivial volume this turns into spurious award failures.

**Evidence — `trade_date = date.today()`:**

```python
# rfq_service.py:1026, 1161, 1212 (three call sites)
trade_date=date.today(),
```

`date.today()` returns the **local-server-timezone date**. On a server configured for UTC this matches `now_utc().date()`; on a server with `TZ=America/Sao_Paulo` (which is the trader's locale), trades booked between 21:00 and 24:00 BRT have `trade_date` of the day BRT, while `event_timestamp` is the next day in UTC. §2.6 explicitly lists "ambiguous dates — `trade_date` ... in implicit timezone" as hard-fail. `now_utc().date()` is the obvious determinate choice.

**Evidence — `LinkageService.create` call site does not engulf:**

```python
# rfq_service.py:1062-1063, 1169-1178, 1220-1223
if rfq.intent == RFQIntent.commercial_hedge and rfq.order_id is not None:
    LinkageService.create(session, rfq.order_id, contract.id, rfq.quantity_mt)
```

No `try`/`except`. If `LinkageService.create` raises, the exception propagates up, the route's `session.commit()` never runs, and the implicit `__exit__` of the FastAPI session dependency rolls back. **That part is correct** — Phase A1's hardening is respected at the call site. Anti-finding A-A2-OPUS-01.

**Evidence — SPREAD partial-failure:**

For SPREAD, two `HedgeContract`s and potentially two `LinkageService.create` calls happen in sequence inside a single transaction (rfq_service.py:1127–1178). If the second `LinkageService.create` raises, the entire transaction rolls back including the first contract — **transactionally consistent**. Anti-finding A-A2-OPUS-02. (The earlier finding about not transitioning child RFQ states is independent — it's a *correctness* gap, not an *atomicity* gap.)

**Severity if violation:** Tier 1 for trade_date and uuid8 (F-A2-OPUS-16, F-A2-OPUS-17).

---

### Q8 — Race conditions (§2.6, §2.5)

**Answer:** **Yes — at least two real races.**

**Evidence — concurrent award (no row lock):**

```python
# rfq_service.py:1095-1106 (award) and 992-997 (award_quote)
rfq = RFQService.get(session, rfq_id)
if rfq.state != RFQState.quoted:
    raise HTTPException(...)
```

`RFQService.get` (lines 547–556) is `session.get(RFQ, rfq_id)` — no `with_for_update()`, no version column, no `SELECT ... FOR UPDATE`. Under PostgreSQL READ COMMITTED isolation (FastAPI/SQLAlchemy default) two concurrent `POST /rfqs/{id}/actions/award` requests can both observe `state == QUOTED`, both compute ranking, both create contracts, both add RFQStateEvents. The only protection is contract-side `unique=True` on `reference` — which sometimes (rarely) collides and aborts one branch — but `reference` is random, so it doesn't collide.

For SPREAD, both transactions can also both create child contracts and both call `LinkageService.create` — Phase A1's linkage-side capacity constraints would presumably catch the second one only if the linkage row uniqueness/check fires before commit. Outside `commercial_hedge`, no such backstop exists.

**Evidence — read-skew on `latest_quotes` during award:**

`compute_trade_ranking` is called inside `award` (rfq_service.py:1181–1192). Between "compute the ranking" and "persist `ranking_snapshot`", a second SQL connection (e.g., `submit_quote`, the orchestrator's `_auto_create_quote`) can `INSERT` a new quote. The `ranking_snapshot` reflects the state at `compute_*` time; the contract however is keyed off `top_quote.id` already loaded in memory. The contract still wins, but the persisted snapshot can disagree with the *current* table state at commit time. A jury reading the audit later sees `ranking_snapshot` listing 3 quotes and the table containing 4 — looks like tampering. (Mitigation: `with_for_update` on RFQ + a serializable snapshot of quotes, or repeatable-read isolation level.)

**Evidence — orchestrator vs. award:**

`RFQOrchestrator._auto_create_quote` calls `session.commit()` inside itself (rfq_orchestrator.py:530), bypassing the per-request session boundary. If a manual award runs in parallel against the same RFQ, the `submit_quote` call inside `_auto_create_quote` reads `rfq.state` (rfq_service.py:587–591) without a lock. If state is still `QUOTED` and the manual `award` is mid-transaction, the autoquote can persist *after* the award snapshot was computed but *before* the award transaction commits.

**Evidence — background jobs:**

`check_rfq_timeouts` and `check_low_response_rfqs` (rfq_orchestrator.py:643–751) only read; they don't mutate state. Low-risk on their own. But comments say "Does NOT auto-transition state — the trader decides." That's load-bearing safety; the design correctly avoided automated timeout-→-cancel transitions.

**Severity if violation:** Tier 1 (F-A2-OPUS-18).

---

### Q9 — Integridade da máquina de estado (§2.1, §2.3, §2.7)

**Answer:** **No.** Soft-delete is filtered inconsistently, several mutation paths skip `RFQStateEvent`.

**Evidence — `deleted_at` filtering:**

`grep` for `deleted_at` in `rfq_service.py` returns **0 hits**. The service layer never filters `RFQ.deleted_at IS NULL`. The route layer only filters in `list_rfqs` (routes/rfqs.py:71–72) and the orchestrator filters only in `check_rfq_timeouts` and `check_low_response_rfqs` (lines 663, 708).

Concretely, **all of the following operate on archived RFQs as if they were live**:

- `RFQService.get` (line 550) — `session.get(RFQ, rfq_id)` no filter
- `RFQService.submit_quote` (line 575) — uses `get` then proceeds
- `RFQService.award` and `award_quote` — both gated only on `state == QUOTED`, not on `deleted_at`
- `RFQService.compute_trade_ranking` / `compute_spread_ranking` — operate on the RFQ instance handed in
- `RFQOrchestrator._process_single_message` (lines 264–275) — phone-match query has no `RFQ.deleted_at IS NULL`
- `routes/rfqs.py:get_rfq`, `list_rfq_quotes`, `list_rfq_state_events`, `get_trade_ranking`, `get_spread_ranking`, `reject_rfq`, `cancel_rfq`, `reject_quote`, `refresh_counterparty`, `award_quote`, `refresh_rfq`, `award_rfq` — all operate without the filter

A trader can `archive_rfq` (sets `deleted_at`), then `award_rfq` against the same id and book a contract — the archive does not protect the row.

**Evidence — `archive_rfq` lacks state and audit-trail discipline:**

```python
# routes/rfqs.py:474-502
@router.patch("/{rfq_id}/archive", ...)
def archive_rfq(...):
    rfq = session.get(RFQ, rfq_id)
    if not rfq:
        raise HTTPException(...)
    if rfq.deleted_at is not None:
        raise HTTPException(409, "RFQ already archived")
    rfq.deleted_at = datetime.now(timezone.utc)
    session.commit()
    ...
```

Archives any state — including AWARDED, CLOSED, even QUOTED-but-not-yet-awarded. **No `RFQStateEvent` row is added.** The audit_event decorator writes to the central audit log, but the canonical RFQ timeline (`RFQStateEvent`) skips this mutation entirely.

**Evidence — `RFQQuote` has no soft-delete and `reject_quote` hard-deletes:**

```python
# rfq_service.py:860
session.delete(quote)
```

A rejected quote vanishes from the row store — it cannot be reconstructed post-mortem ("did counterparty X actually quote 100.5?"). The only trail is whatever `audit_event` writes (which is generic, not domain-specific to the quote's content).

**Evidence — RFQState transitions allowed:**

Allowed by code (state checked then mutated):
- `CREATED → SENT` (create flow, only if at least one invitation succeeded — rfq_service.py:535–543)
- `CREATED → CLOSED` via cancel (line 686)
- `SENT → QUOTED` via submit_quote (line 605)
- `SENT → CLOSED` via cancel (line 686)
- `QUOTED → SENT` via reject_quote when no quotes remain (line 869)
- `QUOTED → CLOSED` via reject (line 666)
- `QUOTED → AWARDED → CLOSED` via award (lines 1226, 1243) and award_quote (1066, 1082)

I see **no path for `closed → quoted` or `awarded → quoted`** — that part is sound. But there is also no DB-level CHECK constraint preventing these transitions; the integrity is only as strong as service-layer guards. (Tier 3.)

**Evidence — `RFQStateEvent.event_timestamp` nullable:**

```python
# models/rfqs.py:158-160
event_timestamp: Mapped[DateTime | None] = mapped_column(
    DateTime(timezone=True), nullable=True
)
```

The state-event audit row can be inserted with `event_timestamp=NULL`, which is exactly what `reject_quote`'s `ALL_QUOTES_REJECTED` event does at rfq_service.py:870–878 — it does set `event_timestamp=now_utc()` actually, so OK. But the schema itself permits null — and `RFQService.create`'s `CREATED → SENT` event at lines 537–543 omits `event_timestamp` entirely, falling back to NULL. §2.3 evidence persistence requires every state event to be timestamped.

**Severity if violation:** Tier 1 for soft-delete leakage and archive bypass (F-A2-OPUS-19, F-A2-OPUS-20). Tier 2 for `event_timestamp` nullability (F-A2-OPUS-21).

---

### Q10 — Hard-fail vs degraded mode no pipeline (§2.6)

**Answer:** **Multiple degraded-mode paths in the inbound pipeline.**

**Evidence — LLM classification down → fall through to parse_quote:**

```python
# rfq_orchestrator.py:336-341
try:
    classification = LLMAgent.classify_intent(msg.text)
except LLMUnavailableError:
    classification = None  # proceed with parse_quote as fallback
```

When the classify step fails (LLM down), the pipeline **does not park the message**; it proceeds to the more-permissive parse step. If parse returns `confidence >= 0.85` and the price string appears in the text (line 411), the orchestrator auto-creates a quote. Single-LLM-call confidence in absence of intent classification = degraded mode under §2.6.

**Evidence — silent default of unit / convention / price:**

```python
# rfq_orchestrator.py:509-526
convention = parsed.float_pricing_convention or "avg"
try:
    float_conv = FloatPricingConvention(convention)
except ValueError:
    float_conv = FloatPricingConvention.avg
...
quote_payload = RFQQuoteCreate(
    rfq_id=rfq.id,
    counterparty_id=str(invitation.counterparty_id),
    fixed_price_value=float(price_value or 0),
    fixed_price_unit=parsed.fixed_price_unit or "USD/MT",
    float_pricing_convention=float_conv,
    received_at=msg.timestamp,
)
```

`fixed_price_value or 0`, `fixed_price_unit or "USD/MT"`, `float_conv` defaulting to `avg` on invalid string — **three silent defaults** for fields that are constitutionally required to be hard-fail-on-incomplete (§2.5).

**Evidence — confidence threshold is a coarse cliff:**

`CONFIDENCE_THRESHOLD = 0.85` (llm_agent.py:40, A4 module — flagged as `cross-phase-A4-risk`). At confidence 0.85 a quote auto-enters the ranking and can become the winning quote in `award`. There is no second human-in-the-loop check between auto_quote_created and the award route. §2.5 + §2.4 are violated: a quote correlated by phone (not canonical id) and parsed by LLM at 0.85 confidence flows directly into a binding economic decision.

**Evidence — `_auto_create_quote`'s blanket `except Exception`:**

```python
# rfq_orchestrator.py:545-556
except Exception as exc:
    logger.error("orchestrator_auto_quote_failed", ...)
    return {
        "message_id": msg.message_id,
        "status": "auto_quote_failed",
        ...
    }
```

This is on the auto-quote path; a `RFQService.submit_quote` `HTTPException` (e.g., RFQ in wrong state) gets logged as a failure and the message is dropped. Combined with `session.commit()` at line 530, *if commit succeeded but a follow-up step raised*, the dropped message would actually correspond to a persisted quote — observability gap.

**Evidence — `award` and `award_quote` block on FAILURE ranking (correct):**

```python
# rfq_service.py:1116-1120 and 1183-1187
if ranking_payload.status != "SUCCESS" or not ranking_payload.ranking:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Ranking is not awardable",
    )
```

OK — `award` (RFQ-level) blocks correctly with 409. **However, `award_quote` does not invoke the ranker at all** — see Q1, Q5. A trader can `award_quote` against a RFQ whose ranking would return FAILURE (tie, non_comparable, etc.). Direct §2.5 hard-fail bypass.

**Severity if violation:** Tier 1 (multiple — F-A2-OPUS-13 silent defaults, F-A2-OPUS-22 award_quote ranking bypass).

---

## Findings

### F-A2-OPUS-01 — `award_quote` persists no `ranking_snapshot`; reconstruction impossible

- **Files\Lines:** `backend/app/services/rfq_service.py:978-1093`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6 ("Contracts cannot be reconstructed — `ranking_snapshot` não-persistido"), §2.7 (audit-friendly).
- **Issue:**
  > ```python
  > # 1067-1080
  > session.add(
  >     RFQStateEvent(
  >         rfq_id=rfq.id,
  >         from_state=RFQState.quoted,
  >         to_state=RFQState.awarded,
  >         user_id=user_id,
  >         winning_quote_ids=json.dumps([str(quote.id)], sort_keys=True),
  >         winning_counterparty_ids=json.dumps([quote.counterparty_id], sort_keys=True),
  >         award_timestamp=award_time,
  >         event_timestamp=award_time,
  >     )
  > )
  > ```
  Contrast with `award` at line 1237 which passes `ranking_snapshot=json.dumps(ranking_snapshot, sort_keys=True)`.
- **Mechanism:** `award_quote` is a parallel "trader picks a quote directly" path used by `POST /rfqs/{id}/actions/award-quote` (routes/rfqs.py:407–427). It loads the chosen quote, books a contract, but never computes or stores the surrounding ranking. Auditing the decision later (e.g., "was this choice off-best by N basis points?") requires reconstructing all rival quotes from raw `rfq_quotes` rows — but there is no record of which quotes the trader saw at decision time, what their canonical-unit checks said, or what the implicit comparison set was.
- **Reproduction / impact:** Counterparty A and B each submit quotes. Trader awards B's quote via `award-quote` even though A's price is better. The audit log shows winning_quote_ids = [B's id] but no record of A. Post-mortem cannot prove whether the trader saw A or even whether A was canonical.
- **Suggested direction:** `award_quote` should compute `compute_trade_ranking` (or `compute_spread_ranking` for SPREAD intent) and persist the snapshot, regardless of whether the chosen quote is rank 1. If the trader chooses a non-top quote, that should be a separate, explicit, audited decision — not an audit gap.
- **Adjacent risk:** Same audit gap when `award_quote` is called for SPREAD intent (the route doesn't disallow it; only the `intent != spread` check inside `award` is missing here).

### F-A2-OPUS-02 — SPREAD `award` does not transition child trade RFQ states

- **Files\Lines:** `backend/app/services/rfq_service.py:1114-1178`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.1 (lifecycle canonical, "no atalho"), §2.2 ("Exactly one canonical Award action").
- **Issue:**
  > ```python
  > # 1127-1178 (excerpt)
  > for trade_rfq_id, quote in (
  >     (rfq.buy_trade_id, top.buy_quote),
  >     (rfq.sell_trade_id, top.sell_quote),
  > ):
  >     ...
  >     trade_rfq = session.get(RFQ, trade_rfq_id)
  >     ...
  >     contract = HedgeContract(...)
  >     session.add(contract)
  >     session.flush()
  >     created_contract_ids.append(str(contract.id))
  >     if trade_rfq.intent == RFQIntent.commercial_hedge and trade_rfq.order_id is not None:
  >         LinkageService.create(session, trade_rfq.order_id, contract.id, trade_rfq.quantity_mt)
  > # No state mutation of trade_rfq, no RFQStateEvent for trade_rfq.
  > ```
- **Mechanism:** The SPREAD award books contracts against both child RFQs but does not transition them out of `QUOTED`. After the parent SPREAD goes to `AWARDED → CLOSED`, the children remain awardable in isolation. A second call to `award` or `award_quote` on `buy_trade_id` (`state == QUOTED` still satisfied) creates *another* contract against the same quote.
- **Reproduction / impact:** Create a SPREAD RFQ referencing buy-trade B and sell-trade S. Award the SPREAD. B and S still report `state=QUOTED`. Call `POST /rfqs/{B}/actions/award`; a new HedgeContract is booked against the same buy_quote — double exposure. For `intent == commercial_hedge` children, `LinkageService.create` would be called a second time and may fail capacity-side (Phase A1 backstop), so the catastrophic case is in `intent == global_position` children where there is no linkage backstop.
- **Suggested direction:** When the SPREAD parent transitions to `AWARDED`, both children should also transition to `CLOSED` (or a new state `BOOKED_BY_PARENT`) with their own `RFQStateEvent`s linking back to the parent's award.
- **Adjacent risk:** `submit_quote` (line 619–649) propagates QUOTED state from a child to the parent SPREAD; the inverse propagation on award is missing.

### F-A2-OPUS-03 — Price storage and arithmetic on IEEE-754 `Float`, not `Decimal`

- **Files\Lines:** `backend/app/models/quotes.py:19`; `backend/app/schemas/rfq.py:111,123`; `backend/app/services/rfq_service.py:189,191,289,290`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.5 ("Fully deterministic"), §2.6 ("Price reference unprovable", "Ranking non-deterministic — Decimal-via-float that collapses precision").
- **Issue:**
  > ```python
  > # models/quotes.py:19-20
  > fixed_price_value: Mapped[float] = mapped_column("price_value", Float, nullable=False)
  > fixed_price_unit: Mapped[str] = mapped_column("price_unit", String(length=32), nullable=False)
  > ```
  > ```python
  > # services/rfq_service.py:188-191
  > ordered = sorted(
  >     quotes, key=lambda q: float(q.fixed_price_value), reverse=reverse
  > )
  > values = [float(q.fixed_price_value) for q in ordered]
  > ```
- **Mechanism:** Prices enter as Python `float` at the schema (`schemas/rfq.py:111`), are stored as PostgreSQL `Float` (8-byte IEEE-754), and are compared as `float` in the ranker. Two distinct counterparty intentions that differ by less than ~1e-13 of magnitude collapse to identical bit patterns and trigger spurious `tie` failures; conversely, Decimal-equivalent values can differ at ULP and silently choose a winner. Spread arithmetic at lines 289–290 multiplies the precision loss across two operands. The constitution explicitly cites this exact failure mode.
- **Reproduction / impact:** With three quotes 100.001, 100.001 (intended duplicate), 100.0019, the table-after-roundtrip representation may yield two equal floats and one distinct → `len(set(values)) != len(values)` → ranking returns FAILURE/TIE — but the *real* tie is between the first two and the system declares the entire ranking unawardable. The reverse case (two intended-distinct prices collapsing) yields a deterministic-looking winner that depends on insertion order at the DB level.
- **Suggested direction:** Storage column `Numeric(18, 6)` (or similar precision matching commodity quote conventions); schema field `Decimal` with `decimal_places=6` Pydantic validator; ranker keys `q.fixed_price_value` directly (Decimal-comparable) without `float(...)` coercion. Tie detection via `len(set(decimal_values))` is then exact.
- **Adjacent risk:** `RFQ.quantity_mt` is also `Float` (models/rfqs.py:44), which feeds `LinkageService.create(rfq.order_id, contract.id, rfq.quantity_mt)` (line 1063). Capacity arithmetic is done in float — see F-A2-OPUS-04.

### F-A2-OPUS-04 — `RFQ.quantity_mt` and `HedgeContract.quantity_mt` are Float; capacity arithmetic loses precision

- **Files\Lines:** `backend/app/models/rfqs.py:44`; usage `backend/app/services/rfq_service.py:1063,1148,1199,1222`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6 ("Over-allocation").
- **Issue:**
  > ```python
  > # models/rfqs.py:44
  > quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
  > ```
- **Mechanism:** Linkage capacity (Phase A1) computes residual exposure as `Σ contract_quantities`. Float subtraction accumulates ULP error; near boundary `residual ≈ 0`, a Float-arithmetic over-allocation by 1e-10 MT slips through the `> residual` test in `RFQService.create` (line 393) and the linkage-side check.
- **Reproduction / impact:** Order quantity 1000.0 MT. Three RFQ contracts of 333.333... MT each. In Decimal the residual is exactly 0; in Float it can be ±1e-12. A fourth small contract of 1e-13 MT could pass the strict `> 0` check.
- **Suggested direction:** Convert quantity columns to `Numeric(18, 6)` and update Pydantic schemas. Worth scoping with Phase A1 reviewers since linkage capacity is on their seam.
- **Adjacent risk:** Cross-phase-A1 risk; the linkage hardening assumed Decimal at its boundary.

### F-A2-OPUS-05 — Spread ranking always sorts `reverse=True`, ignoring spread direction

- **Files\Lines:** `backend/app/services/rfq_service.py:306`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.5 (deterministic but **wrong** in direction is still hard-fail because the institutional decision is wrong, not non-deterministic).
- **Issue:**
  > ```python
  > # 306
  > ordered = sorted(spreads, key=lambda s: s[1], reverse=True)
  > ```
  No analog of trade-ranking's `reverse = rfq.direction == RFQDirection.sell`.
- **Mechanism:** The code unconditionally picks the largest sell − buy spread. For an institution buying the spread (paying sell − buy), the optimal counterparty is the *smallest* spread; for an institution selling the spread, the largest. The parent SPREAD RFQ has no `direction` of its own (the children carry directions), but the institutional principal is the trader who created the SPREAD, and the sign convention depends on whether the SPREAD is being acquired or unwound. The ranker has no input that disambiguates this.
- **Reproduction / impact:** Buy-side spread acquisition: counterparty A offers buy@100/sell@103 (spread=3). Counterparty B offers buy@100/sell@105 (spread=5). The system awards B (worse for the buyer of the spread, who pays an extra 2 USD/MT × quantity). Tier 1 because direction-wrong is a binding economic mistake repeating every spread award.
- **Suggested direction:** SPREAD RFQs need an explicit institutional direction (buying-spread vs. selling-spread) — likely on the parent RFQ or derived from the buy_trade/sell_trade pair's direction. The ranker keys off that.
- **Adjacent risk:** All historical spread awards may have been off by sign for one of the two institutional sides; backfill audit warranted.

### F-A2-OPUS-06 — Outbound `text_en` / `text_pt` invitation bodies omit `RFQ#<rfq_number>`

- **Files\Lines:** `backend/app/services/rfq_engine.py` (entire — no `rfq_number` string match); `backend/app/services/rfq_message_builder.py` (entire — no `rfq_number` string match); `backend/app/services/rfq_service.py:473-487`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.4 ("Mandatory in all outbound messages — se um invite sai sem o id, é violação").
- **Issue:**
  > ```python
  > # rfq_service.py:473-482
  > fallback_body = (
  >     f"RFQ {rfq.rfq_number} — {rfq.commodity} "
  >     f"{rfq.quantity_mt}MT {rfq.direction.value}"
  > )
  > if cp.type == CounterpartyType.bank_br and payload.text_pt:
  >     message_body = payload.text_pt
  > elif payload.text_en:
  >     message_body = payload.text_en
  > else:
  >     message_body = fallback_body
  > ```
  And `build_rfq_message` / `build_pt_summary` never inject `rfq_number` (verified by `grep`).
- **Mechanism:** The standard trader workflow is: call `POST /rfqs/preview-text` → review the LME-formatted `text` → submit `RFQCreate` with `text_en` / `text_pt`. The preview endpoint (routes/rfqs.py:120–196) does not even know the rfq_number (the RFQ is not yet created). The persisted text therefore cannot contain the canonical id. The id is only in the *fallback* path, used when both text_en and text_pt are empty — i.e., never in the real flow.
- **Reproduction / impact:** Every counterparty invitation goes out without `RFQ#<rfq_number>`. A counterparty cannot include the id in their reply; the orchestrator therefore cannot correlate by id; the inbound side falls back to phone (F-A2-OPUS-07). The two findings are mutually reinforcing.
- **Suggested direction:** The send path in `RFQService.create` must prepend (or append) `RFQ#<rfq_number>` to whatever `text_pt` / `text_en` came from preview, before calling `WhatsAppService.send_text_message` and before persisting `message_body`. The persisted text should be byte-equal to what was sent.
- **Adjacent risk:** `RFQService.refresh` and `refresh_counterparty` use the per-counterparty action message (`_pick_action_message`) which also lacks the id. Same fix.

### F-A2-OPUS-07 — Inbound correlation is phone-only; no canonical-id parsing

- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:255-275`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.4 ("Inbound messages are correlated ONLY via this identifier. Não pode haver fallback por número de telefone, por similaridade de texto, por LLM 'best-guess match', por timestamp proximity").
- **Issue:**
  > ```python
  > # 264-275
  > phone_variants = RFQOrchestrator._phone_variants(msg.from_phone)
  > invitation = (
  >     session.query(RFQInvitation)
  >     .join(RFQ, RFQInvitation.rfq_id == RFQ.id)
  >     .filter(
  >         RFQInvitation.recipient_phone.in_(phone_variants),
  >         RFQInvitation.channel == RFQInvitationChannel.whatsapp,
  >         RFQ.state.in_([RFQState.sent, RFQState.quoted]),
  >     )
  >     .order_by(RFQ.created_at.desc(), RFQInvitation.created_at.desc())
  >     .first()
  > )
  > ```
- **Mechanism:** Inbound messages are correlated to RFQ via phone-number lookup (with `_phone_variants` Brazilian-mobile fuzzing — itself a similarity heuristic). The message text is *never* parsed for `RFQ#<rfq_number>` before the correlation decision. This is a direct §2.4 violation. If the parser found the id in the text, it should be the **only** correlation key; the phone is at best a sanity check.
- **Reproduction / impact:** Counterparty quotes RFQ-2026-000123 by phone, then quotes RFQ-2026-000200 from the same phone before the first is awarded. Both RFQs are SENT/QUOTED, both match the phone. The orchestrator silently picks the newest by `RFQ.created_at`, attaching the message to RFQ-200 even when the body says "for RFQ-123 we offer 100.5".
- **Suggested direction:** Add an `RFQ#<rfq_number>` parser as the primary correlator (regex on the inbound text). If found, hard-match; if not found, the message is parked as `orphan_no_canonical_id` for human review — not silently phone-resolved. Phone match becomes evidence-only.
- **Adjacent risk:** `_auto_create_quote` builds on this incorrect correlation; the auto-quote attaches to the wrong RFQ in the multi-active scenario.

### F-A2-OPUS-08 — Multi-RFQ tiebreak on inbound is `RFQ.created_at DESC` (timestamp proximity)

- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:273,290-307`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.4 ("não pode haver fallback ... por timestamp proximity").
- **Issue:**
  > ```python
  > # 273
  > .order_by(RFQ.created_at.desc(), RFQInvitation.created_at.desc())
  > # 290-307
  > active_rfq_count = (...).scalar()
  > if active_rfq_count > 1:
  >     logger.warning("orchestrator_multi_rfq_same_phone", ...)
  > ```
- **Mechanism:** When more than one active RFQ shares the inbound phone, the system *logs a warning* and proceeds with the newest. The constitution explicitly forbids resolution by timestamp proximity. The right action when canonical id is absent and multiple active RFQs match is to park the message, not auto-resolve.
- **Reproduction / impact:** See F-A2-OPUS-07's reproduction case — the wrong RFQ is selected silently.
- **Suggested direction:** Replace the `.first()` call with a multi-match check that hard-fails when active_rfq_count > 1 and the inbound text lacks `RFQ#<rfq_number>`.
- **Adjacent risk:** Subsumed by the broader fix in F-A2-OPUS-07.

### F-A2-OPUS-09 — `RFQService.create` sends WhatsApp before persisting `RFQInvitation`

- **Files\Lines:** `backend/app/services/rfq_service.py:484-522`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.3 ("All RFQ invitations are persisted", "Messages are evidence, not UI artifacts").
- **Issue:**
  > ```python
  > # 484-505
  > result = WhatsAppService.send_text_message(
  >     phone=phone,
  >     text=message_body,
  > )
  > if result.success:
  >     send_status = RFQInvitationStatus.sent
  >     ...
  > # 506-522
  > session.add(
  >     RFQInvitation(...)
  > )
  > ```
- **Mechanism:** External HTTP send (`WhatsAppService.send_text_message`) executes before the database row is staged. A worker crash, OOM, or network partition between line 487 and line 522 leaves the counterparty with a sent message and the system with no record — the canonical "evidence missing" hard-fail.
- **Reproduction / impact:** Difficult to deterministically reproduce in test, but routine in production at scale (any process restart during invitation send loop). Audit can never reconstruct what the counterparty actually received.
- **Suggested direction:** Persist `RFQInvitation` with `send_status=queued` first, then attempt send, then update the existing row to `sent`/`failed` with `provider_message_id`. The orchestrator's `dispatch_whatsapp_invitations` (rfq_orchestrator.py:179–219) already follows the right pattern for the queued-by-design path.
- **Adjacent risk:** The same anti-pattern in `RFQService.refresh` (lines 763–801) and `refresh_counterparty` (lines 938–975) — send first, persist after.

### F-A2-OPUS-10 — `RFQInvitation.sent_at` is NOT NULL but code passes None on failure / queue

- **Files\Lines:** `backend/app/services/rfq_service.py:517-519,798,972`; `backend/app/models/rfqs.py:127`; `backend/alembic/versions/004_create_rfq_tables.py:117`
- **Severity:** Tier 1 (production-breaking; functional bug compounded with §2.3)
- **Constitutional rule violated:** §2.3 (evidence persistence becomes lossy because the entire RFQ rolls back).
- **Issue:**
  > ```python
  > # rfq_service.py:517-519
  > sent_at=now_utc()
  > if send_status == RFQInvitationStatus.sent
  > else None,
  > ```
  > ```python
  > # alembic/versions/004_create_rfq_tables.py:117
  > sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
  > ```
- **Mechanism:** When any invitation send fails (carrier outage, bad phone, throttling), the code passes `sent_at=None`. PostgreSQL raises `IntegrityError: null value in column "sent_at" violates not-null constraint`, the entire `session.commit()` in `routes/rfqs.py:create_rfq` rolls back, the RFQ is not created. A single per-counterparty WhatsApp failure therefore aborts the whole RFQ. This is the inverse of the intent (per-counterparty failure → just mark that one as `failed`).
- **Reproduction / impact:** Create an RFQ with two invitations where one phone is unreachable. Expected: RFQ is created, one invitation is `sent`, one is `failed`. Actual: 500 error, no RFQ row, no RFQInvitation rows. Tests likely don't catch this because the WhatsAppService mock returns `success=True` for all calls.
- **Suggested direction:** Either change the column to nullable in a follow-up migration, or always set `sent_at=now_utc()` regardless of send_status (with the understanding that for `failed` invitations it represents the *attempt* timestamp). The first option is cleaner.
- **Adjacent risk:** Same problem in `refresh` (line 798) and `refresh_counterparty` (line 972).

### F-A2-OPUS-11 — `reject_quote` and `award_quote` send WhatsApp messages without `RFQInvitation` persistence

- **Files\Lines:** `backend/app/services/rfq_service.py:840-858, 1042-1060`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.3 ("Messages are evidence, not UI artifacts").
- **Issue:**
  > ```python
  > # 1042-1060 (award_quote excerpt; reject_quote at 840-858 mirrors)
  > if cp and cp.whatsapp_phone:
  >     msg = _pick_action_message(cp, "contract")
  >     result = WhatsAppService.send_text_message(
  >         phone=cp.whatsapp_phone, text=msg
  >     )
  >     if result.success:
  >         _logger.info("rfq_contract_whatsapp_sent", ...)
  >     else:
  >         _logger.error("rfq_contract_whatsapp_failed", ...)
  > # No session.add(RFQInvitation(...)).
  > ```
- **Mechanism:** The contract-confirmation message ("Fechado no último preço") and the rejection message ("Closed here, thanks for the quote") are sent directly via `WhatsAppService` and the only post-mortem evidence is a structured log line. Logs are not the canonical evidence store; an auditor reading the database will find no record of these legally-significant outbound messages. Discovery, dispute resolution, and counterparty challenges depend on `RFQInvitation` being the source of truth.
- **Reproduction / impact:** Counterparty disputes the contract: "I never received an award message." The system has logs (rotateable, sometimes lost), no DB row.
- **Suggested direction:** Append `RFQInvitation` rows for these messages too, or introduce a sibling table `RFQOutboundMessage` covering all post-creation outbound (refresh-counterparty already does this in `refresh_counterparty`, so the pattern is established).
- **Adjacent risk:** `notify_award` and `notify_reject` in the orchestrator (rfq_orchestrator.py:562–637) have the same gap and additionally use LLM-generated text — see F-A2-OPUS-12.

### F-A2-OPUS-12 — `notify_award` / `notify_reject` send LLM-generated text and never persist

- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:562-637`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.3 ("Terms sent = terms stored"), §2.7 ("free of speculation").
- **Issue:**
  > ```python
  > # 596-607
  > message = LLMAgent.generate_outbound_message(
  >     action="award",
  >     language=language,
  >     recipient_name=invitation.recipient_name,
  >     rfq_number=rfq.rfq_number,
  >     price=price,
  >     unit=unit,
  > )
  > WhatsAppService.send_text_message(
  >     phone=invitation.recipient_phone,
  >     text=message,
  > )
  > ```
- **Mechanism:** Outbound award/reject text is *generated by the LLM at send time*. Even with deterministic prompt templates, LLM output is non-deterministic (temperature, model version drift). The result is sent to the counterparty and never persisted; auditors cannot prove what the counterparty actually received.
- **Reproduction / impact:** Counterparty receives a malformed award message ("Congratulations, you won at $1000/MT" when actual price was $100/MT — hallucinated zero); audit table has no record, only logs (which don't store the rendered message).
- **Suggested direction:** Award/reject notifications should be deterministic templates (no LLM in the outbound path), persisted as evidence rows (RFQInvitation or sibling table) before send.
- **Adjacent risk:** Cross-phase-A4 boundary; flag the LLM-in-outbound usage to the A4 audit.

### F-A2-OPUS-13 — Orchestrator silently completes incomplete LLM extractions (default unit, convention, price→0)

- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:509-526`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.5 ("Incomplete quotes hard-fail"), §2.6 ("evidence missing").
- **Issue:**
  > ```python
  > # 509-526
  > convention = parsed.float_pricing_convention or "avg"
  > try:
  >     float_conv = FloatPricingConvention(convention)
  > except ValueError:
  >     float_conv = FloatPricingConvention.avg
  >
  > price_value = parsed.fixed_price_value
  > if price_value is None and parsed.premium_discount is not None:
  >     price_value = parsed.premium_discount
  >
  > quote_payload = RFQQuoteCreate(
  >     rfq_id=rfq.id,
  >     counterparty_id=str(invitation.counterparty_id),
  >     fixed_price_value=float(price_value or 0),
  >     fixed_price_unit=parsed.fixed_price_unit or "USD/MT",
  >     float_pricing_convention=float_conv,
  >     received_at=msg.timestamp,
  > )
  > ```
- **Mechanism:** Three fields are silently defaulted: `fixed_price_value` falls to 0 when the LLM returns null; `fixed_price_unit` defaults to `"USD/MT"` (a *guessed* unit attributed to the counterparty); `float_pricing_convention` defaults to `avg` on any invalid string (including the empty string). A counterparty WhatsApp reply with insufficient data therefore yields an auto-created quote with system-attributed values that the counterparty never said.
- **Reproduction / impact:** Counterparty replies "100" (no unit). LLM extracts `fixed_price_value=100, fixed_price_unit=None`. Orchestrator persists a quote with `unit="USD/MT"`. The ranker sees a canonical-unit quote and ranks it as if the counterparty agreed to USD/MT pricing — they never did.
- **Suggested direction:** When LLM returns `fixed_price_unit=None`, `fixed_price_value=None`, or an invalid `float_pricing_convention`, the message must be parked for human review (`status="needs_human_review"` already exists in the codebase — line 491–498 — extend its use). No silent defaulting in the auto-create path.
- **Adjacent risk:** `_price_appears_in_text` (line 152–173) is a partial guard but only checks the *value*, not the unit or convention.

### F-A2-OPUS-14 — `RFQQuote` has no soft-delete; `reject_quote` hard-deletes evidence

- **Files\Lines:** `backend/app/models/quotes.py` (no `deleted_at`); `backend/app/services/rfq_service.py:860`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.3 ("Messages are evidence ... auditable post-mortem"), §2.6 ("Contracts cannot be reconstructed — histórico de quotes não-imutável").
- **Issue:**
  > ```python
  > # rfq_service.py:860
  > session.delete(quote)
  > ```
  And `models/quotes.py:11-23` has no `deleted_at`.
- **Mechanism:** A quote rejected by the trader is removed from the row store. Reconstruction of "what offers existed at the time the trader rejected counterparty X" is impossible from the quotes table — the rejected row is gone. The state-event row (`ALL_QUOTES_REJECTED`) records that the trader rejected, but not *what they rejected*.
- **Reproduction / impact:** Counterparty disputes: "I quoted 105.5; you accepted 106 from someone else; I want to see all quotes that existed at award time." The 105.5 row is gone if the trader had pre-rejected it.
- **Suggested direction:** Add `RFQQuote.deleted_at` (and a `rejected_at`/`rejected_by` pair); replace `session.delete(quote)` with a `quote.deleted_at = now_utc()` mark. Update `select_latest_quotes_by_counterparty` and the rankers to filter `deleted_at IS NULL`.
- **Adjacent risk:** Same pattern likely applies to any future quote-supersession path; design now.

### F-A2-OPUS-15 — `RFQQuote.counterparty_id` is `String(64)` not `UUID + ForeignKey`

- **Files\Lines:** `backend/app/models/quotes.py:18`; `backend/app/schemas/rfq.py:110,122,139`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.7 ("verifiable, audit-friendly").
- **Issue:**
  > ```python
  > # models/quotes.py:18
  > counterparty_id: Mapped[str] = mapped_column(String(length=64), nullable=False)
  > ```
- **Mechanism:** No FK to `counterparties.id`. A quote can reference a non-existent or deleted counterparty without DB-level rejection. The string type also means the orchestrator does `str(invitation.counterparty_id)` (rfq_orchestrator.py:521), introducing a UUID↔string round-trip that is fragile.
- **Reproduction / impact:** Hard to trigger maliciously, but a deletion of a counterparty row leaves dangling references in `rfq_quotes`. Reports joining quotes to counterparties produce orphan rows.
- **Suggested direction:** Migration to `UUID(as_uuid=True), ForeignKey("counterparties.id", ondelete="RESTRICT")`.
- **Adjacent risk:** None — local fix.

### F-A2-OPUS-16 — `HedgeContract.trade_date = date.today()` uses local-server timezone

- **Files\Lines:** `backend/app/services/rfq_service.py:1026,1161,1212`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6 ("Dates ambiguous — `trade_date` ... in implicit timezone or in format local-server-only").
- **Issue:**
  > ```python
  > # 1026 (also 1161, 1212)
  > trade_date=date.today(),
  > ```
- **Mechanism:** `date.today()` returns the date in the server's local timezone. The codebase elsewhere is strict about UTC (`now_utc()` at app.core.utils, used everywhere else). For a server in `America/Sao_Paulo` (BRT), trades booked at 22:00 BRT on 2026-05-06 record `trade_date=2026-05-06` while the audit `event_timestamp` is `2026-05-07T01:00Z`. Cross-day reporting and cross-region replication get desynchronized.
- **Reproduction / impact:** Repeatable any night-shift operation in BRT; settlement systems consuming `trade_date` for T+1 / T+2 calculations get the wrong day for ~3 hours/day.
- **Suggested direction:** `trade_date=now_utc().date()` (or, more institutionally, persist the full `award_timestamp` as a `DateTime(timezone=True)` column and derive `trade_date` at read time from a defined business-day calendar).
- **Adjacent risk:** `RFQ.created_at` is `server_default=func.now()` which is UTC in PostgreSQL by default — OK. But other Date-typed columns (delivery_window_*) are pure `Date` with no implicit timezone; ensure they are documented as "calendar date in commodity market timezone" (which is contract-specific).

### F-A2-OPUS-17 — `HedgeContract.reference = HC-<8 hex chars>` collides at scale

- **Files\Lines:** `backend/app/services/rfq_service.py:1025,1160,1211`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.6 (reconstructibility — collision-induced rollback discards an entire award).
- **Issue:**
  > ```python
  > # 1025 (also 1160, 1211)
  > reference=f"HC-{_uuid.uuid4().hex[:8].upper()}",
  > ```
- **Mechanism:** 8 hex chars = 32 bits. Birthday collision: 1% at ~9,300 contracts, 50% at ~77,000. `HedgeContract.reference` is `unique=True` (models/contracts.py:90) so a collision raises `IntegrityError` on commit and rolls back the entire award. There is no retry loop in `RFQService.award` / `award_quote`, so the trader sees a 500 and must retry manually.
- **Reproduction / impact:** Spurious award failures at high volume; concentration of failures in time-of-day windows where contract creation peaks. Not a silent corruption — fail-loud — but it is an uptime/reliability tax that the design didn't intend.
- **Suggested direction:** Use full UUID (32 hex chars) or a sequence-backed reference (`HC-{year}-{seq:08d}` mirroring `RFQSequence`).
- **Adjacent risk:** None — local.

### F-A2-OPUS-18 — `award` / `award_quote` read RFQ state without `with_for_update`; concurrent-award race

- **Files\Lines:** `backend/app/services/rfq_service.py:550, 992-997, 1101-1106`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6 ("Over-allocation"), §2.2 ("Exactly one canonical Award action").
- **Issue:**
  > ```python
  > # 550
  > rfq = session.get(RFQ, rfq_id)
  > # 1102-1106 (award)
  > rfq = RFQService.get(session, rfq_id)
  > if rfq.state != RFQState.quoted:
  >     raise HTTPException(...)
  > ```
- **Mechanism:** Default isolation in PostgreSQL via SQLAlchemy is READ COMMITTED. Two concurrent `award` requests both observe `state == QUOTED`, both pass the gate, both run the ranker and create contracts. The first to commit succeeds; the second commits as well unless something downstream raises. The only collision points are (a) `HedgeContract.reference` UNIQUE — random, won't collide; (b) `LinkageService` capacity — only when `intent == commercial_hedge` and `order_id` is present. For `intent == global_position` or `intent == spread`, *no* DB-level safeguard prevents the double award.
- **Reproduction / impact:** Two browser tabs open by the same trader, each clicking "Award" within ~50 ms. Two contracts booked from the same RFQ. Two `RFQStateEvent` `QUOTED → AWARDED` rows with the same `rfq_id`.
- **Suggested direction:** First statement of `award` / `award_quote` should be `session.query(RFQ).filter(RFQ.id == rfq_id).with_for_update().one_or_none()`. Combined with the request transaction, this serializes concurrent awards on the same RFQ.
- **Adjacent risk:** Same shape in `submit_quote` (line 575) — concurrent quote submissions and a state-transition race from `SENT → QUOTED`. Lower stakes but same fix.

### F-A2-OPUS-19 — Service paths do not filter `RFQ.deleted_at IS NULL`; archived RFQs remain mutable

- **Files\Lines:** `backend/app/services/rfq_service.py:550` (and every method that calls `RFQService.get`); `backend/app/services/rfq_orchestrator.py:264-275, 309-310`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.1 (lifecycle integrity), §2.7 (audit-friendly).
- **Issue:** `grep deleted_at backend/app/services/rfq_service.py` returns **0 hits**.
- **Mechanism:** `archive_rfq` (routes/rfqs.py:474–502) sets `deleted_at` but no service-layer check honors it. After archival the RFQ is hidden from `list_rfqs` (route filters at line 71–72) but is still reachable by id for `award`, `award_quote`, `submit_quote`, `reject_quote`, `refresh`, etc.
- **Reproduction / impact:** Archive RFQ X. Call `POST /rfqs/X/actions/award` — succeeds. Now there is an awarded contract whose source RFQ is logically deleted; `list_rfqs` does not show the RFQ but `HedgeContract.rfq_id` points to it.
- **Suggested direction:** `RFQService.get` should reject `deleted_at IS NOT NULL` with 404. Inbound message correlation should also exclude soft-deleted RFQs (the orchestrator filters elsewhere but not in the phone-match query).
- **Adjacent risk:** Phase A1 closed similar findings for Order/HedgeContract — pattern needs replication here.

### F-A2-OPUS-20 — `archive_rfq` does not emit `RFQStateEvent` and does not check state

- **Files\Lines:** `backend/app/api/routes/rfqs.py:474-502`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.3 (state events as audit trail), §2.1 (state machine integrity).
- **Issue:**
  > ```python
  > # 488-499
  > rfq = session.get(RFQ, rfq_id)
  > if not rfq:
  >     raise HTTPException(404, "RFQ not found")
  > if rfq.deleted_at is not None:
  >     raise HTTPException(409, "RFQ already archived")
  > rfq.deleted_at = datetime.now(timezone.utc)
  > session.commit()
  > ```
- **Mechanism:** The `deleted_at` mutation is not paired with an `RFQStateEvent` row, so the canonical RFQ timeline (`GET /rfqs/{id}/state-events`) does not show the archive action. The audit_event decorator writes to the central audit log, but the state-event timeline is the institutional record.
- **Suggested direction:** Add a state event with a special `to_state` (or a non-state-transition flag) and forbid archival of states that are not terminal-equivalent (CLOSED only).
- **Adjacent risk:** Auditor reading the timeline misses why an RFQ is unfindable in `list_rfqs`.

### F-A2-OPUS-21 — `RFQStateEvent.event_timestamp` nullable; `CREATED → SENT` event omits it

- **Files\Lines:** `backend/app/models/rfqs.py:158-160`; `backend/app/services/rfq_service.py:537-543`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.3 (evidence persistence) — partial.
- **Issue:**
  > ```python
  > # rfq_service.py:537-543
  > session.add(
  >     RFQStateEvent(
  >         rfq_id=rfq.id,
  >         from_state=RFQState.created,
  >         to_state=RFQState.sent,
  >     )
  > )
  > # No event_timestamp= passed.
  > ```
- **Mechanism:** The schema permits `event_timestamp=NULL`, and `create` does not supply one for the `CREATED → SENT` transition. The `created_at` server-default partially substitutes (insertion timestamp ≈ event timestamp here) but the contract is weaker than other code paths (which all pass `event_timestamp=now_utc()`).
- **Suggested direction:** Make the column NOT NULL with a server default of `now()`, or always pass `event_timestamp` from application code and constrain at schema. Audit invariant: every state event has an explicit timestamp.
- **Adjacent risk:** Any other code path emitting `RFQStateEvent` without `event_timestamp` shares this gap.

### F-A2-OPUS-22 — `award_quote` bypasses the ranker entirely

- **Files\Lines:** `backend/app/services/rfq_service.py:978-1093`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.5 (ranking is the canonical decision input), §2.2 ("Exactly one canonical Award action").
- **Issue:** `award_quote` accepts a `quote_id` from the trader, books a contract from that quote, and never calls `compute_trade_ranking` or `compute_spread_ranking`. There is no canonical-unit check on the chosen quote (the ranker would catch a non-canonical unit; `award_quote` does not). There is no tie check; no comparison with rivals.
- **Mechanism:** The path is reached by `POST /rfqs/{id}/actions/award-quote` (routes/rfqs.py:407–427). Trader picks any quote — including one with `fixed_price_unit="banana"`. Contract is booked with that unit. (Linkage capacity will still be enforced via `LinkageService.create` for `commercial_hedge`, but the institutional decision validation is gone.)
- **Reproduction / impact:** Trader awards a quote whose unit is not in the canonical set (e.g., a typo "USD/Ton" instead of "USD/MT"). The contract is booked with that unit; downstream pricing systems mis-interpret. Or: trader awards a quote whose price would have been ranked `tie` (unawardable) by the ranker; `award_quote` lets it through.
- **Suggested direction:** Either (a) `award_quote` invokes the appropriate ranker, requires `SUCCESS`, and verifies the chosen quote is in the ranking; or (b) `award_quote` is removed in favor of the ranking-driven `award`. The constitution implies (b): "Exactly one canonical Award action."
- **Adjacent risk:** F-A2-OPUS-01 (no `ranking_snapshot` persisted) is a direct consequence; merging F-A2-OPUS-01 into this finding is reasonable.

### F-A2-OPUS-23 — Counterparties with single-leg quotes silently dropped from spread ranking

- **Files\Lines:** `backend/app/services/rfq_service.py:246-256`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.5 ("Incomplete quotes hard-fail").
- **Issue:**
  > ```python
  > # 246-248
  > eligible_counterparties = sorted(
  >     set(buy_latest.keys()) & set(sell_latest.keys())
  > )
  > ```
- **Mechanism:** Counterparties who quoted only the buy or only the sell leg are silently excluded via set intersection. There is no audit trail of who was excluded, no failure code, no `ranking_snapshot` field for "excluded counterparties". The constitution's interpretation of "incomplete quotes hard-fail" is read as "incomplete quotes cannot be silently excluded; they must surface."
- **Suggested direction:** Persist the excluded set in `ranking_snapshot` (e.g., `excluded_counterparties: [{cp_id, reason: "missing_buy_leg"}]`) so the audit can reconstruct the full population. Optional: surface as warning in the `SpreadRankingRead` response.
- **Adjacent risk:** None.

### F-A2-OPUS-24 — LLM classify-down fall-through to permissive parse path

- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:336-341`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.6 (degraded mode tolerated in economic path).
- **Issue:**
  > ```python
  > # 336-341
  > try:
  >     classification = LLMAgent.classify_intent(msg.text)
  > except LLMUnavailableError:
  >     classification = None  # proceed with parse_quote as fallback
  > ```
- **Mechanism:** When the cheaper classifier is down, the system proceeds to the heavier `parse_quote_message`. If parse returns confidence ≥ 0.85 and the price-in-text guard passes, the quote is auto-created. The system is in degraded mode (single LLM-call confidence) without explicit gating.
- **Suggested direction:** When `classify_intent` raises `LLMUnavailableError`, the message should be parked for human review (status `llm_unavailable_classify`), not fall through to parse.
- **Adjacent risk:** Cross-phase-A4 boundary; the LLMAgent module is A4.

### F-A2-OPUS-25 — `_auto_create_quote`'s `except Exception` masks post-commit failures

- **Files\Lines:** `backend/app/services/rfq_orchestrator.py:528-556`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.6 (mutation evidence post-commit).
- **Issue:**
  > ```python
  > # 528-556
  > try:
  >     quote = RFQService.submit_quote(session, rfq.id, quote_payload)
  >     session.commit()
  >     ...
  > except Exception as exc:
  >     logger.error("orchestrator_auto_quote_failed", ...)
  >     return {...}
  > ```
- **Mechanism:** If `session.commit()` succeeds but the subsequent log/return code raises (rare but possible in resource-exhaustion scenarios), the quote exists in DB and the message is logged as `auto_quote_failed`. Observability inversion — the auditor reading orchestrator logs concludes the quote was *not* created.
- **Suggested direction:** Narrow the `except` to anticipated exceptions (`HTTPException`, `IntegrityError`, `LLMUnavailableError`) and tag any log as `partial_failure_post_commit` if the commit succeeded.
- **Adjacent risk:** None.

### F-A2-OPUS-26 — `RFQQuote` validation (positive price, canonical unit) deferred to ranking

- **Files\Lines:** `backend/app/services/rfq_service.py:567-602`; `backend/app/schemas/rfq.py:108-114`
- **Severity:** Tier 3
- **Constitutional rule violated:** §2.7 ("output contract — verifiable").
- **Issue:** No `fixed_price_value > 0` check at schema or service. No canonical-unit check at ingest. The DB will accept negative prices and arbitrary unit strings.
- **Suggested direction:** Pydantic `Field(..., gt=0)` on `RFQQuoteCreate.fixed_price_value` and an enum or Literal[...] on `fixed_price_unit`.
- **Adjacent risk:** None.

### F-A2-OPUS-27 — Tier 4 hygiene (count only)

3 items. (No detail per output rules.)

---

## Anti-findings (issues you considered but rejected)

### A-A2-OPUS-01 — `LinkageService.create` engulfed in `award`

- **Initial concern:** `LinkageService.create` raises on capacity violation (Phase A1 invariant) and the call site does nothing visible to handle it.
- **Actual code:**
  > ```python
  > # rfq_service.py:1062-1063, 1169-1178, 1220-1223
  > if rfq.intent == RFQIntent.commercial_hedge and rfq.order_id is not None:
  >     LinkageService.create(session, rfq.order_id, contract.id, rfq.quantity_mt)
  > ```
- **Why it is NOT a bug:** Plain unguarded call. The exception propagates to the FastAPI layer; `get_session`'s `__exit__` rolls back; the contract `session.add()` is rolled back together. Boundary discipline is correct.

### A-A2-OPUS-02 — SPREAD partial-failure (one contract / one linkage commits, the other fails)

- **Initial concern:** Two `HedgeContract`s + two `LinkageService.create` calls in sequence; if the second fails, is the first orphaned?
- **Actual code:**
  > ```python
  > # rfq_service.py:1127-1178 — sequential session.add + session.flush + LinkageService.create
  > ```
- **Why it is NOT a bug:** All four operations are within the same SQLAlchemy session, which is the same DB transaction (FastAPI session dependency commits at end of request). A raise during the second linkage rolls back both contracts, both linkages, both flushes, and the parent state events. Atomicity holds. (The orthogonal child-RFQ-state-not-transitioned issue is a different problem — see F-A2-OPUS-02.)

---

## Cross-phase-A4 risks

### X-A2-OPUS-01 — A2 inbound correlation depends on LLM/WhatsApp/webhook reliability

- **A2 surface:** `backend/app/services/rfq_orchestrator.py:264-498` (entire `_process_single_message`).
- **A4 dependency:** `webhook_processor.dequeue_message`, `LLMAgent.classify_intent`, `LLMAgent.parse_quote_message`, `LLMAgent.should_auto_create_quote`.
- **Governance clause at risk:** §2.4 (correlation), §2.5 (incomplete quotes), §2.6 (evidence).
- **Why it matters:** A2 currently routes inbound by phone (F-A2-OPUS-07) because the outbound text doesn't carry the canonical id (F-A2-OPUS-06). Even after fixing A2's outbound and adding a regex parser, the LLM is still the last line — a fragile dependency for an institutional decision. A4 must guarantee deterministic structured extraction, hard-fail semantics on `LLMUnavailableError`, and immutable persistence of the raw inbound message body before the orchestrator touches it.

### X-A2-OPUS-02 — `LLMAgent.generate_outbound_message` produces evidence text

- **A2 surface:** `backend/app/services/rfq_orchestrator.py:596-607` (notify_award), 631–637 (notify_reject).
- **A4 dependency:** `LLMAgent.generate_outbound_message`.
- **Governance clause at risk:** §2.3 ("Terms sent = terms stored").
- **Why it matters:** Outbound award / reject text is LLM-generated and not persisted (F-A2-OPUS-12). A4 audit must determine whether `generate_outbound_message` is a deterministic templating function (no model call) or an LLM call. If LLM, the design needs a deterministic fallback path before being acceptable in a binding economic message.

### X-A2-OPUS-03 — Confidence threshold of 0.85 hard-coded in A4

- **A2 surface:** `backend/app/services/rfq_orchestrator.py:411` (`if LLMAgent.should_auto_create_quote(parsed):`).
- **A4 dependency:** `llm_agent.CONFIDENCE_THRESHOLD = 0.85`.
- **Governance clause at risk:** §2.5 ("Incomplete quotes hard-fail" — what is the calibration of 0.85?).
- **Why it matters:** A2 trusts a single hard-coded threshold inside A4 to gate quote auto-creation. The constitutional posture toward LLM in economic decisions is unclear; A4 audit should confirm whether 0.85 is calibrated against a labeled corpus and whether the threshold can be changed without code review.

---

## Coverage attestation

- **Files I read in full:** `backend/app/services/rfq_service.py`, `backend/app/services/rfq_orchestrator.py`, `backend/app/models/rfqs.py`, `backend/app/models/quotes.py`, `backend/app/api/routes/rfqs.py`, `backend/app/schemas/rfq.py`, `docs/audits/2026-05-06-phase-a2-stage1-opus-prompt.md`.
- **Files I grep'd but did not read fully:** `backend/app/services/rfq_engine.py`, `backend/app/services/rfq_message_builder.py` (only verified absence of `rfq_number`/`RFQ#` substring), `backend/app/services/llm_agent.py` (only verified `CONFIDENCE_THRESHOLD = 0.85` and `should_auto_create_quote` shape — A4 module), `backend/app/models/contracts.py` (only verified `unique=True` on reference column), `backend/alembic/versions/004_create_rfq_tables.py` (only verified `sent_at` not-null).
- **Files I did not examine (out of scope):** `backend/app/services/whatsapp_service.py`, `backend/app/services/whatsapp_providers/`, `backend/app/services/webhook_processor.py`, `backend/app/services/llm_agent.py` (internals), `backend/app/services/linkage_service.py` (Phase A1, fechada), `backend/app/services/exposure_service.py`, all test files (consulted only as evidence of coverage gaps, not audited), other migrations.
- **Tools used:** Read 5 times, Grep / Bash-grep 8 times.

---

## Open questions for jury

1. **Spread direction.** F-A2-OPUS-05 asserts that spread ranking is sign-direction-wrong for a buying-side institutional principal. The codebase has no explicit `direction` on the parent SPREAD RFQ. Is the institutional convention that the *principal of the SPREAD parent* is always the seller of the spread (so `reverse=True` is unconditionally correct)? If so, this finding is a Tier 3 documentation gap rather than Tier 1 logic. [NEEDS JURY VERIFICATION]
2. **`award` vs. `award_quote` design intent.** F-A2-OPUS-22 reads §2.2 ("Exactly one canonical Award action") as forbidding the existence of `award_quote`. An alternative reading is that `award_quote` is the canonical action and `award` is the auto-pick-from-ranking variant. Either way the audit-trail asymmetry (no `ranking_snapshot` in `award_quote`) is Tier 1. The existence of two paths is Tier 1 *if* governance requires uniqueness of action. [NEEDS JURY VERIFICATION]
3. **`_auto_create_quote` calling `session.commit()` inside a service.** rfq_orchestrator.py:530 commits inside the orchestrator method, departing from the route-layer commit boundary used elsewhere in the codebase. This is functionally a worker-process pattern; is the orchestrator considered a worker process distinct from the FastAPI request lifecycle, or is this a bug that mixes lifecycles? [NEEDS JURY VERIFICATION]
4. **`RFQQuote` evidence model (F-A2-OPUS-14).** Is the institutional view that rejected quotes can be hard-deleted (lighter audit footprint) or must be preserved (full reconstruction)? If the former, F-A2-OPUS-14 is rejected; if the latter, Tier 1 stands. [NEEDS JURY VERIFICATION]
5. **Schema vs. code mismatch on `sent_at` (F-A2-OPUS-10).** Is there a hidden migration making `sent_at` nullable that I missed? My audit checked `alembic/versions/004_create_rfq_tables.py`; if a later migration relaxed the constraint, the finding downgrades to a stale-comment bug. [NEEDS JURY VERIFICATION]
