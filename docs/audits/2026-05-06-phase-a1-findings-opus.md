# Phase A1 — Stage 1 Findings — Auditor A (Opus)

**Date:** 2026-05-06
**Scope commit:** `f1420524b3436145e5afd47f42589bbc1e43b0f4`
**Files audited:**
- `backend/app/services/exposure_engine.py`
- `backend/app/services/exposure_service.py`
- `backend/app/services/deal_engine.py`
- `backend/app/services/linkage_service.py`
- `backend/app/models/exposure.py`
- `backend/app/models/deal.py`
- `backend/app/models/linkages.py`
- `backend/app/api/routes/exposures.py`
- `backend/app/api/routes/deals.py`
- `backend/app/api/routes/linkages.py`
- `backend/app/schemas/exposure_engine.py`
- (adjacent, consulted only) `backend/app/models/orders.py`, `backend/app/models/contracts.py`, `backend/app/services/contract_service.py`, `backend/app/services/rfq_service.py` (`determine_contract_legs`), `backend/app/api/dependencies/audit.py`, `backend/app/core/pagination.py`

## Executive summary

- Tier 1 (Critical, constitutional violation, ship-blocker): **9** findings
- Tier 2 (High, should fix pre-merge / pre-prod): **5** findings
- Tier 3 (Medium, defer-acceptable): **3** findings
- Tier 4 (Low, hygiene): **4** items (count only)
- Anti-findings (rejection of suspected issues): **3** items

**Overall constitutional posture:** **FAIL**

The economic primitives audited contain multiple direct violations of the canonical model (§2.1, §2.2, §2.4, §2.5, §2.6) and the auditability contract (§2.7). The dominant failure modes are:

1. **Silent fallback / clamp on over-allocation and missing market price** (§2.6 forbids both).
2. **No audit emission on Deal mutations and Exposure reconcile** (§2.7 contract violated; §2.6 "no mutation without evidence").
3. **Boundary between commercial and global preserved by convention only** — `HedgeOrderLinkage` accepts mismatched direction (SO ↔ Long, PO ↔ Short) without rejection (§2.4).
4. **Exposure includes settled / soft-deleted entities** in live aggregates (§2.6 over-allocation surface; §2.1 state-correctness).
5. **Float arithmetic on tonnage and price** in `Order`, `HedgeContract`, `HedgeOrderLinkage` defeats reproducibility (§2.7 verifiable, deterministic).
6. **Multi-commodity domain is unsupported by `Order` model**, yet `ExposureEngineService.reconcile_from_orders` hard-codes `commodity="ALUMINUM"` and `ExposureService.compute_*_snapshot` aggregates orders with no commodity discriminator (§2.1 canonical model, §2.5 KPI per-commodity).

---

## Structured Q&A

### Q1 — Hard-fail em over-allocation

**Answer:** **Não — falha silenciosa em pelo menos dois caminhos críticos.**

**Evidence (over-allocation clamped to zero, `exposure_engine.py:73-83`):**
```python
            # Compute hedge-adjusted open tons
            hedged_qty = linked_map.get(str(order.id), 0.0)
            open_qty = max(float(order.quantity_mt) - hedged_qty, 0.0)

            # Determine status based on hedging
            if hedged_qty <= 0:
                exp_status = ExposureStatus.open
            elif open_qty <= 0:
                exp_status = ExposureStatus.fully_hedged
```

**Evidence (LinkageService check, `linkage_service.py:52-61`):**
```python
        if float(order_linked_qty or 0.0) + quantity_mt > order.quantity_mt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linkage exceeds order quantity",
            )
        if float(contract_linked_qty or 0.0) + quantity_mt > contract.quantity_mt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Linkage exceeds contract quantity",
            )
```

**Mechanism:**
The `LinkageService.create` enforces `linked + new > base` only at write time, **without a row lock or DB unique/check constraint** (Q9). If a race wins or migrations introduce an over-allocation, downstream `reconcile_from_orders` does **not** raise; it clamps `open_qty` via `max(..., 0.0)` (line 75), persists `original_tons = order.quantity_mt` while linked rows total more, and writes status `fully_hedged`. The ledger is silently corrupted.

A second, separate detection path exists in `exposure_service.compute_commercial_snapshot` / `compute_global_snapshot` (`exposure_service.py:42-61, 196-225`) where `func.min(residual_qty) < 0` raises `HTTP_409_CONFLICT`. This is **detection-after-the-fact** at read time — by then the bad row already exists. The constitutional rule is "Exposure would be over-allocated → hard-fail" which the write path violates.

**Severity if violation:** **Tier 1**

---

### Q2 — Determinismo da classificação de hedge

**Answer:** **Sim, deterministic na criação, mas o estado serializado é vulnerável a drift.**

**Evidence (deterministic lookup at create, `contract_service.py:66-78`):**
```python
        classification = (
            HedgeClassification.long
            if fixed_leg.side == HedgeLegSideSchema.buy
            else HedgeClassification.short
        )

        contract = HedgeContract(
            commodity=payload.commodity,
            quantity_mt=payload.quantity_mt,
            fixed_leg_side=HedgeLegSide(fixed_leg.side.value),
            variable_leg_side=HedgeLegSide(variable_leg.side.value),
            classification=classification,
            ...
        )
```

**Evidence (RFQ path, `rfq_service.py:141-144`):**
```python
        if direction == RFQDirection.buy:
            return HedgeLegSide.buy, HedgeLegSide.sell, HedgeClassification.long
        return HedgeLegSide.sell, HedgeLegSide.buy, HedgeClassification.short
```

**Evidence (independent persistence, `models/contracts.py:108-121`):**
```python
    fixed_leg_side: Mapped[HedgeLegSide] = mapped_column(
        Enum(HedgeLegSide, name="hedge_leg_side"),
        nullable=False,
    )
    variable_leg_side: Mapped[HedgeLegSide] = mapped_column(
        Enum(HedgeLegSide, name="hedge_leg_side"),
        nullable=False,
    )
    classification: Mapped[HedgeClassification] = mapped_column(
        Enum(HedgeClassification, name="hedge_classification"),
        nullable=False,
    )
```

**Mechanism:**
The classification is derived deterministically by `if/else` (no heuristic, no ordering). However it is then **persisted as an independent column** alongside `fixed_leg_side` and `variable_leg_side`. There is **no DB CHECK constraint, generated column, or trigger** that enforces `classification == long ⇔ fixed_leg_side == buy`. Any future migration, manual UPDATE, admin tooling, or new write path can desynchronize the three fields, yielding a contract whose serialization claims `Hedge Long` while `fixed_leg_side == sell`. All downstream consumers (`exposure_service`, `exposure_engine.compute_net_exposure`, `deal_engine._validate_hedge_direction`) read `contract.classification` — drift becomes silently load-bearing. §2.3 requires this rule to be **absolute**; "by-construction-at-create-only" is not absolute.

The classification is **not recomputed** at query/serialization, so there is no per-request drift, only long-tail drift across the contract's lifetime.

**Severity if violation:** **Tier 1** (drift surface), Tier 2 if jury accepts construction-time-only as adequate.

---

### Q3 — Reconstrutibilidade do cálculo de exposure

**Answer:** **Parcial — modelo é state-shaped, mas os inputs primários são mutáveis sem snapshot e várias mutações não têm trail.**

**Evidence (state-shaped, `models/exposure.py:75-79`):**
```python
    original_tons: Mapped[float] = mapped_column(Numeric(15, 3), nullable=False)
    open_tons: Mapped[float] = mapped_column(Numeric(15, 3), nullable=False)
    price_per_ton: Mapped[float | None] = mapped_column(Numeric(15, 2), nullable=True)
    settlement_month: Mapped[str | None] = mapped_column(String(7), nullable=True)
    status: Mapped[ExposureStatus] = mapped_column(
        Enum(ExposureStatus, name="exposure_status"),
```

**Evidence (state mutated in place, `exposure_engine.py:95-107`):**
```python
            if existing:
                changed = False
                if float(existing.original_tons) != float(order.quantity_mt):
                    existing.original_tons = order.quantity_mt
                    changed = True
                if float(existing.open_tons) != open_qty:
                    existing.open_tons = open_qty
                    changed = True
                if existing.status != exp_status:
                    existing.status = exp_status
                    changed = True
```

**Evidence (no audit on reconcile, `routes/exposures.py:50-56`):**
```python
@router.post("/reconcile", response_model=ReconcileResponse)
def reconcile_exposures(
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    result = ExposureEngineService.reconcile_from_orders(session)
    return result
```

**Mechanism:**
- `Exposure` is a snapshot row (state, not event log) — good w.r.t. §2.1.
- However, `original_tons`, `open_tons`, `status` are **mutated in place** by `reconcile_from_orders` with no before/after audit trail and no `audit_event` dependency on the route.
- The route also calls `session.commit()` from inside the service without wrapping a try/rollback (`exposure_engine.py:122`), so partial failure leaves a torn write.
- Determinism cross-process: `reconcile_from_orders` queries `session.query(Order).all()` with **no ORDER BY** (Q8) and uses `dict()` keyed by `str(order.id)` — aggregation is order-independent for SUMs, but the **insertion order of new `Exposure` rows depends on DB scan order**, leading to non-byte-equal reproductions of the audit table. UUIDs are random, so even commit timestamps would diverge across runs.
- Reproducibility from primaries (orders + linkages) is approximately yes, **except** that `Order` has no historical version (no event sourcing) — if an order's `quantity_mt` was edited, the prior exposure cannot be reconstructed.

**Severity if violation:** **Tier 1** (audit trail), Tier 2 (cross-process determinism).

---

### Q4 — Boundary entre commercial e global

**Answer:** **Por convenção, não por construção.** Há um caminho onde unlinked vira efetivamente "linked-equivalente" via `HedgeOrderLinkage` mal-direcionado.

**Evidence (linkage service rejects no direction mismatch, `linkage_service.py:20-71`):**
```python
    @staticmethod
    def create(
        session: Session,
        order_id: UUID,
        contract_id: UUID,
        quantity_mt: float,
    ) -> HedgeOrderLinkage:
        order = session.get(Order, order_id)
        if not order:
            raise HTTPException(...)

        contract = session.get(HedgeContract, contract_id)
        if not contract:
            raise HTTPException(...)

        order_linked_qty = (
            session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
            .filter(HedgeOrderLinkage.order_id == order_id)
            .scalar()
        )
        ...
        if float(order_linked_qty or 0.0) + quantity_mt > order.quantity_mt:
            raise HTTPException(...)
        if float(contract_linked_qty or 0.0) + quantity_mt > contract.quantity_mt:
            raise HTTPException(...)

        linkage = HedgeOrderLinkage(
            order_id=order_id,
            contract_id=contract_id,
            quantity_mt=quantity_mt,
        )
```

**Evidence (`exposure_service.py` aggregates by classification regardless of which side the linked order is, `exposure_service.py:200-225`):**
```python
        residual_contract_qty = HedgeContract.quantity_mt - func.coalesce(
            linked_by_contract.c.linked_qty, 0.0
        )
        ...
        hedge_long = float(
            session.query(func.coalesce(func.sum(residual_contract_qty), 0.0))
            ...
            .filter(HedgeContract.classification == HedgeClassification.long)
            .scalar()
            or 0.0
        )
```

**Mechanism:**
- `LinkageService.create` does **not** validate that a `Long` (buy) hedge is linked to a Purchase Order or that a `Short` (sell) hedge is linked to a Sales Order.
- The semantic rule §2.4 (linked → reduces both sides correctly) is enforced **only inside `DealEngineService._validate_hedge_direction`** (`deal_engine.py:152-219`) — i.e., for the `Deal`/`DealLink` aggregate, **not** for `HedgeOrderLinkage` itself.
- Linkages live in a separate model (`hedge_order_linkages`) that is the **input** to `compute_global_snapshot` and `compute_commercial_snapshot`. A SO ↔ Long-hedge linkage will reduce `commercial_active` (via SO residual) and reduce `hedge_long` (via contract residual), so `global_passive = commercial_passive + hedge_long` decreases. Net effect: the snapshot reports lower passive than reality — a silent, structural mis-allocation at the §2.4 boundary.
- `HedgeOrderLinkage` table has no DB-level check constraint binding `order.order_type` to `contract.classification`. Boundary preservation is naming-convention-grade, not constructional.

**Severity if violation:** **Tier 1**

Additionally, race condition in `LinkageService.create` (Q9) can create link/unlink windows where `compute_commercial_snapshot._validate_residuals_non_negative` triggers **after** a row already exists — i.e., the snapshot endpoint hard-fails for live data instead of refusing the linkage at write time. (Subsumed under Q1.)

---

### Q5 — Variable-price vs fixed-price

**Answer:** **Sim, único campo (`Order.price_type`) consultado em vários sítios; sem redundância silenciosa, mas há um caminho onde fixed-price gera P&L tratado como variable-fallback.**

**Evidence (Order model, `models/orders.py:29-31, 57-59`):**
```python
class PriceType(enum.Enum):
    fixed = "fixed"
    variable = "variable"
...
    price_type: Mapped[PriceType] = mapped_column(
        Enum(PriceType, name="price_type"), nullable=False
    )
```

**Evidence (early-skip in reconcile, `exposure_engine.py:62-63`):**
```python
            if order.price_type == PriceType.fixed:
                continue
```

**Evidence (filter in commercial snapshot, `exposure_service.py:55, 64, 116, etc.`):**
```python
            .filter(
                Order.order_type == OrderType.sales,
                Order.price_type == PriceType.variable,
            )
```

**Evidence (P&L mixes fixed and variable through a single function, `deal_engine.py:389-405`):**
```python
    @staticmethod
    def _order_value(
        order: Order,
        market_price: float | None,
    ) -> float:
        """Return the monetary value for one order (qty × effective price)."""
        qty = float(order.quantity_mt)
        if order.price_type == PriceType.fixed:
            return qty * float(order.avg_entry_price or 0)
        if market_price is not None:
            return qty * market_price
        return qty * float(order.avg_entry_price or 0)
```

**Mechanism:**
- `Order.price_type` is the single source of truth across `exposure_engine`, `exposure_service`, `deal_engine`, `_validate_hedge_direction`. No duplication. ✓
- `_validate_hedge_direction` (`deal_engine.py:201-210`) explicitly rejects hedging a fixed-price order with `HTTP_422`. ✓
- However, in `_order_value`, when an order is variable-price and `market_price` is `None` (price reference unavailable), the code falls back to `order.avg_entry_price` — i.e., the system silently **switches a variable-price order to fixed-price valuation** for P&L. This is the "Price reference cannot be proven" hard-fail trigger of §2.6, and it is fed into the persisted P&L snapshot.
- No regression risk for *exposure* generation from fixed-price orders (correctly skipped), but the *P&L pipeline* effectively treats fixed and variable identically when `market_price is None`.

**Severity if violation:** **Tier 1** (price-reference fallback in P&L). Single-source-of-truth itself is fine.

---

### Q6 — Unidades (MT consistency)

**Answer:** **MT é convenção, mas o tipo de coluna é Float em vários lugares de risco institucional. Não há conversões kg/lb/USD no código auditado, mas Decimal não é uniforme.**

**Evidence (Float columns on quantities and prices):**
- `models/orders.py:60` — `quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)`
- `models/orders.py:65` — `avg_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)`
- `models/contracts.py:68` — `quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)`
- `models/contracts.py:80` — `fixed_price_value: Mapped[float | None] = mapped_column(Float, nullable=True)`
- `models/linkages.py:24` — `quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)`

**Evidence (Numeric columns, by contrast):**
- `models/exposure.py:77-79` — `original_tons: Mapped[float] = mapped_column(Numeric(15, 3), ...)` (good)
- `models/deal.py:65-71` — `total_physical_tons / total_hedge_tons / hedge_ratio` use `Numeric(15,3)` and `Numeric(5,2)` (good)

**Evidence (Float arithmetic propagates, `exposure_engine.py:38-45`):**
```python
        rows = (
            session.query(
                HedgeOrderLinkage.order_id,
                func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0).label(
                    "linked_qty"
                ),
            )
            ...
        )
        return {str(r.order_id): float(r.linked_qty) for r in rows}
```

**Mechanism:**
- The naming convention is consistent (`quantity_mt`, `original_tons`, `open_tons`, `total_physical_tons`). No kg/lb/USD conversion was found.
- However, the **canonical input columns** (`Order.quantity_mt`, `HedgeContract.quantity_mt`, `HedgeOrderLinkage.quantity_mt`) are `sqlalchemy.Float` (IEEE-754 double), not `Numeric`. All sums and residuals computed in SQL or Python are float.
- The **derived snapshot columns** (`Exposure.original_tons`, `Deal.total_physical_tons`) are `Numeric(15,3)`, but they receive float assignments (`exposure_engine.py:98`, `deal_engine.py:799-801`) — SQLAlchemy converts to Decimal at DB layer, but the Python-side equality compare on line 97 (`float(existing.original_tons) != float(order.quantity_mt)`) defeats Decimal benefits.
- This is incompatible with §2.7 ("verifiable") because two different processes on different float ULPs can disagree on whether `existing.open_tons != open_qty` — leading to write-amplification or equality-mismatch behavior depending on FPU.
- No rounding mode is ever set (no `Decimal.quantize`, no banker's-rounding policy). For a system that compares "remaining capacity" by `>` and `<=`, accumulated float error at large book sizes is observable.

**Severity if violation:** **Tier 1** (institutional risk quantity in float; floats compared with `<=` for boundary checks).

---

### Q7 — Evidence / audit trail

**Answer:** **Não — múltiplos endpoints de mutação econômica não emitem `audit_event`.**

**Evidence (linkages route does emit audit, `routes/linkages.py:41-62`):**
```python
@router.post(
    "", response_model=HedgeOrderLinkageRead, status_code=status.HTTP_201_CREATED
)
@limiter.limit(RATE_LIMIT_MUTATION)
def create_linkage(
    payload: HedgeOrderLinkageCreate,
    request: Request,
    _: None = Depends(
        audit_event(
            entity_type="linkage",
            event_type="created",
        )
    ),
    __: None = Depends(require_role("trader")),
    session: Session = Depends(get_session),
) -> HedgeOrderLinkageRead:
    linkage = LinkageService.create(...)
    mark_audit_success(request, linkage.id)
    request.state.audit_commit()
    return HedgeOrderLinkageRead.model_validate(linkage)
```

**Evidence (deals routes do NOT emit audit, `routes/deals.py:69-82, 132-153, 156-169`):**
```python
@router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
def create_deal(
    body: DealCreate,
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
):
    ...
    deal = DealEngineService.create_deal(session, data)
    return deal

@router.post(
    "/{deal_id}/links", response_model=DealLinkRead, status_code=status.HTTP_201_CREATED
)
def add_link(
    deal_id: UUID,
    body: DealLinkCreate,
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
):
    return DealEngineService.add_link(...)

@router.delete("/{deal_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_link(
    deal_id: UUID,
    link_id: UUID,
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
):
    DealEngineService.remove_link(session, deal_id, link_id)

@router.post(
    "/{deal_id}/pnl-snapshot",
    response_model=DealPNLSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
def trigger_pnl_snapshot(
    deal_id: UUID,
    snapshot_date: date = Query(default=None),
    _: None = Depends(require_any_role("trader", "risk_manager")),
    session: Session = Depends(get_session),
):
    if snapshot_date is None:
        snapshot_date = date.today()
    return DealEngineService.compute_deal_pnl(session, deal_id, snapshot_date)
```

**Evidence (exposure reconcile route does NOT emit audit, `routes/exposures.py:50-56`):**
```python
@router.post("/reconcile", response_model=ReconcileResponse)
def reconcile_exposures(
    _user: dict = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    result = ExposureEngineService.reconcile_from_orders(session)
    return result
```

**Mechanism:**
- `audit_event` (`api/dependencies/audit.py:24-63`) is HMAC-SHA256-signed and idempotent (records once per request via `audit_should_record` flag, see `AuditTrailService.record`). Used correctly by `orders`, `contracts`, `linkages`, `cashflow`, `pl`, `mtm`, `rfqs`, `westmetall` routes.
- The Deal aggregate is a **first-class economic primitive** (carries P&L snapshots, links to orders + hedges, drives the deal hedge-ratio status). Mutations on `Deal` (`create_deal`, `add_link`, `remove_link`, `compute_deal_pnl`) all bypass `audit_event`.
- `reconcile_exposures` mutates the `Exposure` table without audit.
- §2.7 mandates "precise, structured, verifiable, audit-friendly" outputs for all persistence. §2.6 forbids "mutation without evidence". Both clauses are violated for these endpoints.

**Severity if violation:** **Tier 1**

---

### Q8 — Determinismo de ordering / iteração

**Answer:** **Inconclusivo nas paths de mutação; OK nas listagens via `paginate`.**

**Evidence (paginate enforces stable order, `core/pagination.py:61`):**
```python
    rows = query.order_by(created_at_col.asc(), id_col.asc()).limit(limit + 1).all()
```

**Evidence (no ORDER BY in reconcile, `exposure_engine.py:58`):**
```python
        orders = session.query(Order).all()
```

**Evidence (no ORDER BY in deal recompute, `deal_engine.py:777`):**
```python
        links = session.query(DealLink).filter(DealLink.deal_id == deal.id).all()
```

**Mechanism:**
- `paginate` overrides the caller's `order_by` and applies `(created_at ASC, id ASC)` — stable. ✓
- `reconcile_from_orders`, `_recompute_tons`, `compute_deal_pnl`, `compute_pnl_breakdown` iterate query results with no `ORDER BY`. For aggregations (sum, max), the result is order-independent at the `Decimal/float`-add level, but **float addition is not associative** — different evaluation order yields different ULPs. Combined with float columns (Q6), cross-process determinism is not guaranteed.
- Python `dict` insertion order is reliable since 3.7, but the iteration over `agg.values()` in `compute_net_exposure` (`exposure_engine.py:230`) depends on the order in which DB rows were observed; nothing guarantees the same DB row order across processes.

**Severity if violation:** **Tier 2** (dependent on Decimal/Float resolution from Q6).

---

### Q9 — Concurrency / race conditions

**Answer:** **Sim — TOCTOU em `LinkageService.create` e em `DealEngineService.add_link`; nenhum row lock, nenhum índice único composto, nenhuma versão optimistic.**

**Evidence (TOCTOU in linkage create, `linkage_service.py:41-71`):**
```python
        order_linked_qty = (
            session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
            .filter(HedgeOrderLinkage.order_id == order_id)
            .scalar()
        )
        contract_linked_qty = (
            session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
            .filter(HedgeOrderLinkage.contract_id == contract_id)
            .scalar()
        )

        if float(order_linked_qty or 0.0) + quantity_mt > order.quantity_mt:
            raise HTTPException(...)
        if float(contract_linked_qty or 0.0) + quantity_mt > contract.quantity_mt:
            raise HTTPException(...)

        linkage = HedgeOrderLinkage(
            order_id=order_id,
            contract_id=contract_id,
            quantity_mt=quantity_mt,
        )
        session.add(linkage)
        session.commit()
```

**Evidence (`HedgeOrderLinkage` model has no relevant unique constraint or row-lock pattern, `models/linkages.py:10-25`):**
```python
class HedgeOrderLinkage(Base):
    __tablename__ = "hedge_order_linkages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("orders.id", ondelete="RESTRICT"),
        nullable=False,
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("hedge_contracts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[DateTime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

**Mechanism:**
- Two concurrent calls `LinkageService.create(order_X, contract_Y, qty=80)` against an order with `quantity_mt=100` and zero existing linkages: both transactions read `order_linked_qty=0`, both pass `0+80 ≤ 100`, both `INSERT`. Final state: 160 MT linked against a 100 MT order — over-allocation.
- No `SELECT ... FOR UPDATE` on `Order` / `HedgeContract`, no `EXCLUDE` constraint, no advisory lock, no `version` column on `Order`/`HedgeContract`/`HedgeOrderLinkage`.
- Same anti-pattern in `DealEngineService.add_link` (`deal_engine.py:262-345`): cross-deal uniqueness check + qty validations are read-then-write without lock.
- Detection-after-the-fact still exists in `_validate_residuals_non_negative` at snapshot read time, but by then the over-allocation is committed and the constitution's hard-fail-on-write requirement is violated. (Subsumed under F-A1-OPUS-01.)

**Severity if violation:** **Tier 1**

---

### Q10 — Hard-fail vs degraded mode

**Answer:** **Sim — pelo menos um `try/except` que engole erro econômico explicitamente.**

**Evidence (price-lookup swallowing all exceptions, `deal_engine.py:61-79`):**
```python
def _get_market_price(
    session: Session, commodity: str, as_of_date: date
) -> float | None:
    """Try to fetch the D-1 settlement price; return None on failure."""
    try:
        from app.services.price_lookup_service import (
            get_cash_settlement_price_d1,
            resolve_symbol,
        )

        symbol = resolve_symbol(commodity)
        return float(
            get_cash_settlement_price_d1(session, symbol=symbol, as_of_date=as_of_date)
        )
    except Exception:
        logger.debug(
            "market_price_unavailable commodity=%s date=%s", commodity, as_of_date
        )
        return None
```

**Evidence (downstream silent zero MTM, `deal_engine.py:469-481`):**
```python
                if market_price is not None:
                    mtm = (
                        tons * (price - market_price)
                        if is_sell
                        else tons * (market_price - price)
                    )
                else:
                    mtm = 0.0

                if contract.status == HedgeContractStatus.settled:
                    hedge_pnl_realized += mtm
                else:
                    hedge_pnl_mtm += mtm
```

**Mechanism:**
- The `_get_market_price` helper catches **bare `Exception`**, downgrades to `logger.debug` (sub-INFO; effectively invisible), and returns `None`.
- Callers (`compute_deal_pnl`, `compute_pnl_breakdown`, `_order_value`) accept `None` and either zero out the hedge MTM or fall back to `avg_entry_price` for variable-price orders (Q5).
- The persisted `DealPNLSnapshot.total_pnl` therefore stores a number whose price reference cannot be proven — this is precisely §2.6's "Price reference cannot be proven → MUST hard-fail".
- The `inputs_hash` (`deal_engine.py:44-58`) hashes only `deal_id`, `snapshot_date`, and `link_ids` — it does **not** hash `market_price` or its source. A subsequent recomputation with a real market price returns the cached "fallback" snapshot via the early-return at line 433 (`if existing: return existing`), permanently locking in the degraded-mode P&L.

**Severity if violation:** **Tier 1**

---

## Findings

### F-A1-OPUS-01 — Silent over-allocation clamp in `reconcile_from_orders`
- **Files\Lines:** `backend/app/services/exposure_engine.py:73-83`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6 ("Exposure would be over-allocated → MUST hard-fail")
- **Issue:**
  ```python
              hedged_qty = linked_map.get(str(order.id), 0.0)
              open_qty = max(float(order.quantity_mt) - hedged_qty, 0.0)

              # Determine status based on hedging
              if hedged_qty <= 0:
                  exp_status = ExposureStatus.open
              elif open_qty <= 0:
                  exp_status = ExposureStatus.fully_hedged
              else:
                  exp_status = ExposureStatus.partially_hedged
  ```
- **Mechanism:**
  If `hedged_qty > order.quantity_mt` (over-allocation introduced by a race on `LinkageService.create` — see F-A1-OPUS-04 — or by direct DB import), `max(..., 0.0)` silently clamps to zero, status is set to `fully_hedged`, and `existing.original_tons = order.quantity_mt` is overwritten without comment. No exception, no log, no audit (F-A1-OPUS-02).
- **Reproduction / impact:**
  Order(qty=100); two parallel `POST /linkages` with qty=80 each both win → table has 160 MT linked. `POST /exposures/reconcile` then writes `Exposure(open_tons=0, status=fully_hedged)` — the operator sees a "covered" position; the actual book is over-hedged by 60 MT.
- **Suggested direction:**
  Replace `max(...,0.0)` with explicit raise (HTTP 409 or domain exception). Detection at write-time (linkage) plus explicit assertion at reconcile time, not silent clamping.
- **Adjacent risk:**
  Same `max(...,0.0)` clamping pattern not found elsewhere in scope, but the absence of `_validate_residuals_non_negative` in `reconcile_from_orders` (which `exposure_service` does have) implies the two services disagree on the hard-fail invariant.

---

### F-A1-OPUS-02 — Deal mutations and Exposure reconcile emit no `audit_event`
- **Files\Lines:** `backend/app/api/routes/deals.py:69-82, 132-143, 146-153, 156-169`; `backend/app/api/routes/exposures.py:50-56`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6 ("No mutation without evidence"), §2.7 (audit-friendly outputs)
- **Issue:**
  ```python
  @router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
  def create_deal(
      body: DealCreate,
      _: None = Depends(require_any_role("trader", "risk_manager")),
      session: Session = Depends(get_session),
  ):
      ...
      deal = DealEngineService.create_deal(session, data)
      return deal

  @router.post("/{deal_id}/links", ...)
  def add_link(...):
      return DealEngineService.add_link(...)

  @router.delete("/{deal_id}/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
  def remove_link(...):
      DealEngineService.remove_link(session, deal_id, link_id)

  @router.post("/{deal_id}/pnl-snapshot", ...)
  def trigger_pnl_snapshot(...):
      return DealEngineService.compute_deal_pnl(session, deal_id, snapshot_date)
  ```
  ```python
  @router.post("/reconcile", response_model=ReconcileResponse)
  def reconcile_exposures(
      _user: dict = Depends(get_current_user),
      session: Session = Depends(get_session),
  ):
      result = ExposureEngineService.reconcile_from_orders(session)
      return result
  ```
- **Mechanism:**
  Other mutation routes in the codebase (`orders`, `contracts`, `linkages`, `pl`, `mtm`) wire the HMAC-signed `audit_event` dependency from `api/dependencies/audit.py:24` and invoke `request.state.audit_commit()` after success. The Deal/PNL/reconcile routes do not. `Deal`, `DealLink`, `DealPNLSnapshot` mutations and `Exposure.original_tons/open_tons/status` mutations therefore have no signed evidence.
- **Reproduction / impact:**
  After a regulator request "show every mutation that affected exposure for deal X between dates A and B", the system can only return application-log fragments (which are not HMAC-signed and live outside the audit trail), violating reconstructability.
- **Suggested direction:**
  Wire the `audit_event` dependency on every Deal/PNL/reconcile mutation. The `entity_type` strings should be `deal`, `deal_link`, `deal_pnl_snapshot`, `exposure_reconcile`. The reconcile case may need a synthetic `entity_id` (e.g., a `ReconciliationRun` record).
- **Adjacent risk:**
  Whatever pre-existing audit gap also exists for any non-route mutation paths (RFQ award flow, scheduler) — out of scope here, but worth a follow-up.

---

### F-A1-OPUS-03 — Silent fallback when market price is unavailable in P&L
- **Files\Lines:** `backend/app/services/deal_engine.py:61-79, 389-405, 469-481, 599-625`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6 ("Price reference cannot be proven → MUST hard-fail"), §2.7 (audit-friendly, free of speculation)
- **Issue:**
  ```python
  def _get_market_price(
      session: Session, commodity: str, as_of_date: date
  ) -> float | None:
      """Try to fetch the D-1 settlement price; return None on failure."""
      try:
          from app.services.price_lookup_service import (
              get_cash_settlement_price_d1,
              resolve_symbol,
          )

          symbol = resolve_symbol(commodity)
          return float(
              get_cash_settlement_price_d1(session, symbol=symbol, as_of_date=as_of_date)
          )
      except Exception:
          logger.debug(
              "market_price_unavailable commodity=%s date=%s", commodity, as_of_date
          )
          return None
  ```
  ```python
                  if market_price is not None:
                      mtm = (
                          tons * (price - market_price)
                          if is_sell
                          else tons * (market_price - price)
                      )
                  else:
                      mtm = 0.0
  ```
- **Mechanism:**
  Bare `except Exception` swallows network errors, missing-symbol errors, type errors — anything. Downstream callers (`_order_value`, `compute_deal_pnl`, `compute_pnl_breakdown`) substitute `avg_entry_price` for variable orders or `mtm = 0.0` for hedges, then **persist** the resulting `DealPNLSnapshot`. The snapshot's `inputs_hash` does not include the market price source (`deal_engine.py:44-58`), so a later recomputation returns the corrupted snapshot via the cache check at line 433.
- **Reproduction / impact:**
  Westmetall feed outage at the moment a trader hits `POST /deals/{id}/pnl-snapshot` → snapshot stored with hedge_pnl_mtm=0 and physical valued at entry price; subsequent retries return the same wrong snapshot until links change.
- **Suggested direction:**
  Either (a) raise a domain exception → HTTP 409/422 when market_price is unresolvable for variable-price/active hedges, or (b) include the price-source provenance in `inputs_hash` and snapshot, with explicit "evidence missing" status the operator must override.
- **Adjacent risk:**
  Same fallback-to-entry-price pattern in `_order_value` (`deal_engine.py:401-405`) for variable-price orders — same constitutional violation in the physical leg.

---

### F-A1-OPUS-04 — TOCTOU race in `LinkageService.create` and `DealEngineService.add_link`
- **Files\Lines:** `backend/app/services/linkage_service.py:41-71`; `backend/app/services/deal_engine.py:262-345`; `backend/app/models/linkages.py:10-25`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.6 ("Exposure would be over-allocated → MUST hard-fail")
- **Issue:**
  ```python
          order_linked_qty = (
              session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
              .filter(HedgeOrderLinkage.order_id == order_id)
              .scalar()
          )
          contract_linked_qty = (
              session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
              .filter(HedgeOrderLinkage.contract_id == contract_id)
              .scalar()
          )

          if float(order_linked_qty or 0.0) + quantity_mt > order.quantity_mt:
              raise HTTPException(...)
          if float(contract_linked_qty or 0.0) + quantity_mt > contract.quantity_mt:
              raise HTTPException(...)

          linkage = HedgeOrderLinkage(
              order_id=order_id,
              contract_id=contract_id,
              quantity_mt=quantity_mt,
          )
          session.add(linkage)
          session.commit()
  ```
- **Mechanism:**
  Read-then-write across two transactions. Default SQLAlchemy session uses Postgres' default `READ COMMITTED` isolation. Two concurrent `create` calls each see `linked = 0`, both pass the bound check, both `INSERT`. Final state: over-allocated table that subsequently triggers the **read-time** `_validate_residuals_non_negative` 409 in `compute_commercial_snapshot` — the linkage is already committed; the snapshot endpoint becomes a denial-of-service surface for queries on the affected commodity until manually repaired. [NEEDS JURY VERIFICATION on Postgres isolation default in this app's DB session config.]
- **Reproduction / impact:**
  Two traders racing to hedge the same order; both see the order as un-hedged in the UI; both submit linkage; both succeed with HTTP 201; subsequent `GET /exposures/commercial` returns HTTP 409 instead of a snapshot.
- **Suggested direction:**
  Either (a) `SELECT ... FOR UPDATE` on `Order`/`HedgeContract` rows, then re-read the linkage sum; or (b) a Postgres `EXCLUDE USING gist` constraint enforcing `Σ HedgeOrderLinkage.quantity_mt ≤ orders.quantity_mt` (likely needs a materialized side table); or (c) `serializable` isolation for this transaction with retry on `40001`.
- **Adjacent risk:**
  Same pattern in `DealEngineService.add_link` for cross-deal uniqueness and qty checks. `DealEngineService._recompute_tons` (`deal_engine.py:775-810`) also reads-then-writes `total_physical_tons/total_hedge_tons/hedge_ratio` without lock.

---

### F-A1-OPUS-05 — Float (IEEE-754) used for institutional risk quantities and prices
- **Files\Lines:** `backend/app/models/orders.py:60, 65`; `backend/app/models/contracts.py:68, 80, 88`; `backend/app/models/linkages.py:24`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.7 ("verifiable, audit-friendly")
- **Issue:**
  ```python
  # orders.py
      quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
      ...
      avg_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)

  # contracts.py
      quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
      ...
      fixed_price_value: Mapped[float | None] = mapped_column(Float, nullable=True)
      ...
      premium_discount: Mapped[float | None] = mapped_column(
          Float, default=0, nullable=True
      )

  # linkages.py
      quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
  ```
- **Mechanism:**
  - `Order.quantity_mt`, `HedgeContract.quantity_mt`, `HedgeOrderLinkage.quantity_mt` are all `Float`. Sums of large books overflow representable-doubles' precision (~15 sig digits), and float addition is non-associative — different aggregation orders give different results, defeating §2.7 "verifiable". The `Exposure` snapshot column (`Numeric(15,3)`) is wider than the input it stores, so precision is lost on write, not on store.
  - `over-allocation` checks use `>` against floats, e.g. `linkage_service.py:52`. Boundary near-equality cases (`linked + qty == order.quantity_mt + 1e-12`) can flip the inequality based on FPU. Combined with §2.6 hard-fail-on-over-allocation, this is a constitutional failure surface.
  - `fixed_price_value` and `avg_entry_price` are also Float — P&L sums lose pennies on large books.
- **Reproduction / impact:**
  Linkage of qty `0.1+0.2` (Python: 0.30000000000000004) against an order of `0.3` MT will fail `linked+qty > order.qty` even though the trader entered exactly 0.1+0.2.
- **Suggested direction:**
  Migrate `Order.quantity_mt`, `HedgeContract.quantity_mt`, `HedgeOrderLinkage.quantity_mt` to `Numeric(15,3)`; prices to `Numeric(15,4)` or wider; add `Decimal` end-to-end on write paths; centralize a `quantize` policy in a `core.numeric` module.
- **Adjacent risk:**
  Likely affects every other quantity/price column in the codebase (Cashflow, RFQ quote, etc.) — out of scope here but cross-system.

---

### F-A1-OPUS-06 — `compute_global_snapshot` and `compute_commercial_snapshot` ignore hedge `status`/`deleted_at` and order `deleted_at`
- **Files\Lines:** `backend/app/services/exposure_service.py:21-330` (entire class, no filters on lifecycle columns); contrast with `backend/app/services/exposure_engine.py:148-208` which does filter
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.1 (state, not log), §2.5 (Global KPI must reflect live positions), §2.6 (hard-fail surfaces depend on correct base)
- **Issue:**
  ```python
          # --- Hedge contracts ---
          ...
          residual_contract_qty = HedgeContract.quantity_mt - func.coalesce(
              linked_by_contract.c.linked_qty, 0.0
          )

          min_contract_residual = (
              session.query(func.min(residual_contract_qty))
              .outerjoin(
                  linked_by_contract, HedgeContract.id == linked_by_contract.c.contract_id
              )
              .scalar()
          )
          ...
          hedge_long = float(
              session.query(func.coalesce(func.sum(residual_contract_qty), 0.0))
              .outerjoin(...)
              .filter(HedgeContract.classification == HedgeClassification.long)
              .scalar()
              or 0.0
          )
  ```
  No `.filter(HedgeContract.deleted_at.is_(None))` and no `.filter(HedgeContract.status.in_(["active", "partially_settled"]))` — settled, cancelled, and soft-deleted hedges are summed.
  Similarly, no `.filter(Order.deleted_at.is_(None))` anywhere in `compute_commercial_snapshot` / `compute_global_snapshot`.
- **Mechanism:**
  `models/contracts.py:144-147` defines `deleted_at`. `models/orders.py:104` defines `deleted_at`. `exposure_engine.compute_net_exposure` correctly filters `HedgeContract.deleted_at.is_(None)` and `HedgeContract.status.in_([...])`. The `exposure_service` snapshot path (which is the one exposed by `/exposures/global` and `/exposures/commercial`) does **not** filter — meaning settled/cancelled/deleted entities continue to inflate or deflate the live KPI.
- **Reproduction / impact:**
  Operator settles a Short hedge of 200 MT (status → `settled`); `GET /exposures/global` continues to report `hedge_short_mt += 200`, and `global_active_mt` is overstated by 200 MT until the row is hard-deleted.
- **Suggested direction:**
  Add `deleted_at IS NULL` and `status IN (active, partially_settled)` filters to all `Order` and `HedgeContract` queries in `exposure_service`. Ideally make these the default via SQLAlchemy event listeners or query factories so future engines cannot regress.
- **Adjacent risk:**
  Cashflow projection (`cashflow_projection_service.py`) — out of scope, but likely the same bug per Grep findings.

---

### F-A1-OPUS-07 — `HedgeOrderLinkage` accepts direction-mismatched pairs (SO ↔ Long, PO ↔ Short)
- **Files\Lines:** `backend/app/services/linkage_service.py:20-71`; `backend/app/models/linkages.py:10-25`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.4 ("boundary preserved by construction, not convention"), §2.5 (Global decomposition assumes correct linkage)
- **Issue:**
  ```python
  class LinkageService:
      """Validates overflow constraints and persists a new HedgeOrderLinkage."""

      @staticmethod
      def create(
          session: Session,
          order_id: UUID,
          contract_id: UUID,
          quantity_mt: float,
      ) -> HedgeOrderLinkage:
          order = session.get(Order, order_id)
          ...
          contract = session.get(HedgeContract, contract_id)
          ...
          # only quantity checks below — no direction match check
  ```
- **Mechanism:**
  `LinkageService.create` validates only quantity. There is no check that a `HedgeClassification.long` (buy) hedge can only link to a `OrderType.purchase`, or that `short` can only link to `sales`. The direction rule is enforced in `DealEngineService._validate_hedge_direction` (`deal_engine.py:181-219`) — but `Deal`/`DealLink` is a *different aggregate* from `HedgeOrderLinkage`. The two are not foreign-keyed.
  As a result, `compute_global_snapshot`'s decomposition `global_active = commercial_active + hedge_short_residual` can be subtly wrong: a SO ↔ Long-hedge linkage drops `commercial_active` (correct semantic for "this SO is hedged") and drops `hedge_long_residual` (incorrect — Long-residual should only fall when a PO was hedged).
- **Reproduction / impact:**
  `POST /linkages {order_id=SO_X, contract_id=Long_Y, quantity_mt=50}` succeeds. `commercial_active` falls by 50. `hedge_long_residual` falls by 50. `global_passive` falls by 50. The risk dashboard reports a smaller passive book than reality.
- **Suggested direction:**
  Add a direction-match check to `LinkageService.create` (mirror of `DealEngineService._validate_hedge_direction`). Ideally also add a DB CHECK constraint enforcing `(order.order_type='SO' AND contract.classification='short') OR (order.order_type='PO' AND contract.classification='long')` on insert (would require a denormalized column or trigger).
- **Adjacent risk:**
  Whatever ingestion path bulk-imports linkages (RFQ award, scheduler) — verify they don't bypass `LinkageService.create`.

---

### F-A1-OPUS-08 — `HedgeContract.classification` is independently mutable from `fixed_leg_side`
- **Files\Lines:** `backend/app/models/contracts.py:108-121`
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.3 ("Esta regra é absoluta. … input não-deterministicamente ordenado é violação P1")
- **Issue:**
  ```python
      fixed_leg_side: Mapped[HedgeLegSide] = mapped_column(
          Enum(HedgeLegSide, name="hedge_leg_side"),
          nullable=False,
      )
      variable_leg_side: Mapped[HedgeLegSide] = mapped_column(
          Enum(HedgeLegSide, name="hedge_leg_side"),
          nullable=False,
      )
      classification: Mapped[HedgeClassification] = mapped_column(
          Enum(HedgeClassification, name="hedge_classification"),
          nullable=False,
      )
  ```
- **Mechanism:**
  At create time, `ContractService.create` (`contract_service.py:66-78`) and `RFQService.determine_contract_legs` (`rfq_service.py:141-144`) derive `classification` deterministically from `fixed_leg.side`. But the three columns are independent in the schema — no DB CHECK constraint, no generated column, no trigger. Any future migration, admin SQL, or new code path that updates one column without updating the others creates a contract whose serialization claims `Hedge Long` while `fixed_leg_side == sell`. Consumers downstream rely on `contract.classification` (`exposure_service.py:269-291`, `deal_engine.py:181, 302, 467, 611`).
  §2.3 declares the classification rule "absolute". Persistence-as-three-independent-columns means absoluteness depends on application-layer discipline at every write path — not "by construction".
- **Reproduction / impact:**
  Admin runs `UPDATE hedge_contracts SET classification='long' WHERE id='...'` (without flipping `fixed_leg_side`). Future P&L and exposure decompositions silently misclassify.
- **Suggested direction:**
  Make `classification` a generated column (Postgres `GENERATED ALWAYS AS (CASE WHEN fixed_leg_side='buy' THEN 'long' ELSE 'short' END) STORED`), or drop the column entirely and compute it via Python `@hybrid_property` from `fixed_leg_side`. Either way, eliminate the drift surface.
- **Adjacent risk:**
  `HedgeContract.direction` `@property` (`contracts.py:148-150`) already reads `classification` and could disagree with `fixed_leg_side`-derived truth. The `tons` and `price_per_ton` aliases (lines 152-160) are similarly redundant projections.

---

### F-A1-OPUS-09 — `Order` has no `commodity` column; `reconcile_from_orders` hardcodes "ALUMINUM" and global snapshot aggregates orders without commodity
- **Files\Lines:** `backend/app/services/exposure_engine.py:108-117`; `backend/app/services/exposure_service.py:48-80, 156-180`; `backend/app/models/orders.py:48-105` (no `commodity` field)
- **Severity:** Tier 1
- **Constitutional rule violated:** §2.1 (canonical model assumes commodity-scoped exposure), §2.5 (Global KPI is per-commodity)
- **Issue:**
  ```python
              else:
                  exposure = Exposure(
                      commodity="ALUMINUM",  # default commodity
                      direction=direction,
                      source_type=source_type,
                      source_id=order.id,
                      original_tons=order.quantity_mt,
                      open_tons=open_qty,
                      price_per_ton=order.avg_entry_price,
                      status=exp_status,
                  )
  ```
  And in `compute_commercial_snapshot`:
  ```python
          pre_active = float(
              session.query(func.coalesce(func.sum(Order.quantity_mt), 0.0))
              .filter(
                  Order.order_type == OrderType.sales,
                  Order.price_type == PriceType.variable,
              )
              .scalar()
              or 0.0
          )
  ```
  There is no `.filter(Order.commodity == ...)` and no commodity grouping. Inspection of `models/orders.py` confirms there is no `commodity` column on `Order`.
- **Mechanism:**
  - `reconcile_from_orders` writes every exposure as `commodity="ALUMINUM"`. If non-aluminum orders ever exist (or if the system expands), exposures are misclassified.
  - `compute_commercial_snapshot` and `compute_global_snapshot` aggregate **all** variable-price orders into one bucket — multi-commodity SO and PO net against each other in the same book, violating §2.1 (commodity is fundamental to the canonical model).
  - `HedgeContract.commodity` is a real column (`models/contracts.py:67`), so hedges *are* per-commodity, but linkages mix orders (commodity-less) with hedges (commodity-bearing) — a structural mismatch.
- **Reproduction / impact:**
  Trader books an Aluminum SO (100 MT) and a Copper PO (100 MT, both variable). `commercial_net_mt = 100 - 100 = 0`. The dashboard reports zero net exposure; reality is +100 Al and -100 Cu, completely uncovered.
- **Suggested direction:**
  Add `Order.commodity` (NOT NULL) and migrate; commodity-group every aggregator in `exposure_service`. Drop the hardcoded "ALUMINUM" in `reconcile_from_orders`.
- **Adjacent risk:**
  Every Order-consuming service (`deal_engine`, `cashflow_projection`, `pl`) inherits the same multi-commodity blindness.

---

### F-A1-OPUS-10 — Service-layer `session.commit()` without rollback discipline
- **Files\Lines:** `backend/app/services/exposure_engine.py:122, 280, 310, 357`; `backend/app/services/deal_engine.py:143, 357, 383, 498, 707`; `backend/app/services/linkage_service.py:69`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.7 (audit-friendly persistence)
- **Issue:**
  ```python
          session.commit()
          return {
              "created": created,
              "updated": updated,
              "message": "Reconciliation completed",
          }
  ```
  Inside service methods that may be called from background jobs or bulk operations, `session.commit()` is the last call with no `try/except` wrapping a `rollback`. If the FastAPI route's `get_session` dependency expects to manage the transaction lifecycle, the service has already committed; route-level rollback is then a no-op.
- **Mechanism:**
  Mixing service-layer commits with route-layer/dependency-managed sessions makes partial-failure recovery indeterministic. Any post-commit error (e.g., Pydantic serialization in `model_validate`) leaves the DB committed without a corresponding successful HTTP 2xx — worse, in linkage's case, `request.state.audit_commit()` is called *after* `session.commit()`, so a crash between the two yields a committed linkage with no signed audit row (regression relative to F-A1-OPUS-02 even when audit is wired).
- **Reproduction / impact:**
  Ingest a batch of 100 orders → `reconcile_from_orders` partially writes 60 then crashes on the 61st (e.g., DB connection drop) → 60 exposures committed without audit; the route returns 500.
- **Suggested direction:**
  Push commits to a single boundary (the route or a `unit_of_work` context manager). Audit commits and DB commits should be co-transactional or compensating.
- **Adjacent risk:**
  Same anti-pattern in every other service that calls `session.commit()`.

---

### F-A1-OPUS-11 — `DealPNLSnapshot.inputs_hash` does not include market-price provenance
- **Files\Lines:** `backend/app/services/deal_engine.py:44-58, 422-435`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.7 (verifiable, free of speculation)
- **Issue:**
  ```python
  def _compute_inputs_hash(
      deal_id: _uuid.UUID,
      snapshot_date: date,
      link_ids: list[_uuid.UUID],
  ) -> str:
      """SHA-256 hash that changes when the deal's links change."""
      data = json.dumps(
          {
              "deal_id": str(deal_id),
              "snapshot_date": str(snapshot_date),
              "links": sorted(str(lid) for lid in link_ids),
          },
          sort_keys=True,
      )
      return hashlib.sha256(data.encode()).hexdigest()
  ```
  ```python
          existing = (
              session.query(DealPNLSnapshot)
              .filter(DealPNLSnapshot.inputs_hash == inputs_hash)
              .first()
          )
          if existing:
              return existing
  ```
- **Mechanism:**
  The hash discriminates only on `(deal_id, snapshot_date, sorted link_ids)`. Two snapshots taken minutes apart with the same links but different market prices (e.g., re-run after Westmetall recovers from outage in F-A1-OPUS-03) **collide on the hash**, and the cached "fallback-zeroed" snapshot is returned instead of recomputing.
- **Reproduction / impact:**
  Trader hits `POST /deals/{id}/pnl-snapshot` during a price feed outage → snapshot stored with `hedge_pnl_mtm=0`. Trader retries 10 minutes later (feed recovered) → same `inputs_hash`, returns the corrupted snapshot.
- **Suggested direction:**
  Include the market price (or its source ID + as_of_date + value) in the `inputs_hash`. Surface "evidence missing" explicitly when market_price is None (per F-A1-OPUS-03), and refuse to write a snapshot at all in that case.
- **Adjacent risk:**
  Same idempotency-key ambiguity pattern likely present elsewhere — out of scope.

---

### F-A1-OPUS-12 — `ExposureEngineService.compute_net_exposure` decomposition assumes `Exposure.commodity` is meaningful
- **Files\Lines:** `backend/app/services/exposure_engine.py:133-235`
- **Severity:** Tier 2 (subsumed by F-A1-OPUS-09 if commodity hardcoding is fixed; standalone Tier 2 because the SQL is brittle)
- **Constitutional rule violated:** §2.5 (KPI is per-commodity)
- **Issue:**
  ```python
          for grow in global_rows:
              c = grow.commodity.upper() if grow.commodity else grow.commodity
              if c not in agg:
                  agg[c] = {...}
  ```
- **Mechanism:**
  The aggregator groups by `Exposure.commodity` (which is always "ALUMINUM" today, see F-A1-OPUS-09) AND by `HedgeContract.commodity` (which is a real per-row value). When a non-aluminum hedge exists, `agg` will create a separate bucket for it that has no commercial side — a phantom net position. Conversely, an aluminum exposure plus a copper hedge will appear in two buckets that cannot reconcile.
- **Reproduction / impact:** As in F-A1-OPUS-09.
- **Suggested direction:** Same as F-A1-OPUS-09 (add `Order.commodity`).
- **Adjacent risk:** N/A.

---

### F-A1-OPUS-13 — `DealEngineService._recompute_tons` divides float by float for `hedge_ratio`
- **Files\Lines:** `backend/app/services/deal_engine.py:799-810`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.7 (verifiable, deterministic)
- **Issue:**
  ```python
          deal.total_physical_tons = physical_tons
          deal.total_hedge_tons = hedge_tons
          deal.hedge_ratio = (hedge_tons / physical_tons) if physical_tons > 0 else 0

          # Auto-update status
          ratio = deal.hedge_ratio
          if ratio <= 0:
              deal.status = DealStatus.open
          elif ratio < 1.0:
              deal.status = DealStatus.partially_hedged
          else:
              deal.status = DealStatus.fully_hedged
  ```
- **Mechanism:**
  `hedge_ratio` is computed as Python float division (because `physical_tons` and `hedge_tons` are accumulated as float in lines 779-797), then assigned to a `Numeric(5,2)` column. The status branch on `ratio < 1.0` and `ratio >= 1.0` flips at FPU boundaries when `physical_tons == hedge_tons` numerically but differs by one ULP. A "fully hedged" deal can flip to "partially_hedged" or back across requests.
- **Reproduction / impact:**
  Deal with physical=100.0, hedge=100.0 (exact). Add/remove a 0-MT link. `_recompute_tons` recomputes via `float()` of `Numeric` order/contract qty fields stored as `Float` — sums may now equal `99.99999999999999`. Status flips.
- **Suggested direction:**
  Compute `hedge_ratio` with `Decimal` and `quantize`; or use `>= - epsilon` boundary checks; or align `Order.quantity_mt` / `HedgeContract.quantity_mt` types with `Deal.total_*_tons` (Decimal).
- **Adjacent risk:** All boundary checks across float quantities.

---

### F-A1-OPUS-14 — Reconcile / list / iteration without ORDER BY makes process-comparison non-byte-equal
- **Files\Lines:** `backend/app/services/exposure_engine.py:58, 248, 257, 293`; `backend/app/services/deal_engine.py:159, 423, 556, 565, 746, 777`; `backend/app/services/exposure_service.py:73-95, 156-180`
- **Severity:** Tier 2
- **Constitutional rule violated:** §2.7 (deterministic outputs)
- **Issue:**
  ```python
          orders = session.query(Order).all()
  ```
  ```python
          links = session.query(DealLink).filter(DealLink.deal_id == deal.id).all()
  ```
- **Mechanism:**
  Per Q8: aggregate sums are commutative *if* arithmetic is associative; floats are not (F-A1-OPUS-05). A re-run reading rows in a different order can produce a snapshot with a different `total_pnl` at the LSB level. Combined with the `inputs_hash` issue (F-A1-OPUS-11), the snapshot is non-reproducible at byte equality.
- **Reproduction / impact:**
  Audit: "show me the same snapshot from process A and process B" → the two snapshots may differ by 1 cent on a large book.
- **Suggested direction:** Add explicit `.order_by(...id)` to every read-aggregate path; combined with Decimal migration, this restores byte equality.
- **Adjacent risk:** N/A.

---

### F-A1-OPUS-15 — `DealEngineService.add_link`: `cross_deal` lookup ignores soft-deleted deals
- **Files\Lines:** `backend/app/services/deal_engine.py:108-128, 261-280`
- **Severity:** Tier 3
- **Constitutional rule violated:** §2.7 (audit-friendly), boundary cleanliness
- **Issue:**
  ```python
          cross_deal = (
              session.query(DealLink)
              .filter(
                  DealLink.linked_type == resolved_type,
                  DealLink.linked_id == linked_id,
              )
              .first()
          )
          if cross_deal:
              other_deal = session.get(Deal, cross_deal.deal_id)
              other_ref = (
                  other_deal.reference if other_deal else str(cross_deal.deal_id)
              )
              raise HTTPException(
                  status_code=status.HTTP_409_CONFLICT,
                  detail=(
                      f"This {resolved_type.value} is already linked to deal "
                      f"{other_ref}. ..."
                  ),
              )
  ```
- **Mechanism:**
  The cross-deal uniqueness check looks at `DealLink` regardless of whether the parent `Deal.is_deleted`. If a deal was soft-deleted but its links remained, a new attempt to link the same entity refuses, citing a deal that the user can no longer see in `list_deals` (which filters `is_deleted == False`).
- **Reproduction / impact:**
  Trader soft-deletes a deal, then tries to recreate it with the same orders → 409, with a reference to the deleted deal.
- **Suggested direction:**
  Add `.join(Deal).filter(Deal.is_deleted == False)` to the cross-deal lookup, or hard-cascade `DealLink` when soft-deleting `Deal`.
- **Adjacent risk:** Same `DealLink` table queried elsewhere (`compute_pnl_breakdown`, `_recompute_tons`) without `is_deleted` join.

---

### F-A1-OPUS-16 — `Exposure.is_deleted` filter applied inconsistently
- **Files\Lines:** `backend/app/services/exposure_engine.py:90-93, 157, 252, 377, 403`
- **Severity:** Tier 3
- **Constitutional rule violated:** §2.1 (state correctness)
- **Issue:**
  Filter exists on `compute_net_exposure` (line 157), `list_pending_tasks` related queries (via join), and `list_exposures` (line 377). But `reconcile_from_orders` (line 86-93) only filters on existing exposures — when scanning Orders to *create* new exposures, the prior-deleted exposure is invisible, so a new one is created. Two exposures (one deleted, one active) coexist for the same `source_id`.
- **Mechanism:**
  `Exposure.is_deleted` is `Boolean default False`, but the lookup in `reconcile_from_orders` line 86-93 only matches `is_deleted == False`. If a soft-delete ever happened on an exposure, reconcile creates a duplicate. Other queries that don't filter `is_deleted` (none in scope per audit, but worth verifying) would double-count.
- **Reproduction / impact:** Soft-delete an exposure manually; rerun reconcile; second exposure row appears for the same order.
- **Suggested direction:** Either disallow soft-delete on exposures (it's a derived snapshot, no need), or always look up by `(source_id)` regardless of `is_deleted` and undelete instead of creating.
- **Adjacent risk:** Same pattern likely in `Deal` (`is_deleted`).

---

### F-A1-OPUS-17 — `HedgeOrderLinkage` has no soft-delete; deletion flow is implicit hard-delete with `ondelete=RESTRICT`
- **Files\Lines:** `backend/app/models/linkages.py:10-25`; `backend/app/services/linkage_service.py` (no `delete` method); `backend/app/api/routes/linkages.py` (no DELETE route in scope reading)
- **Severity:** Tier 3
- **Constitutional rule violated:** §2.7 (audit-friendly persistence)
- **Issue:**
  ```python
  class HedgeOrderLinkage(Base):
      __tablename__ = "hedge_order_linkages"
      id: Mapped[uuid.UUID] = mapped_column(...)
      order_id: Mapped[uuid.UUID] = mapped_column(
          UUID(as_uuid=True),
          ForeignKey("orders.id", ondelete="RESTRICT"),
          nullable=False,
      )
      contract_id: Mapped[uuid.UUID] = mapped_column(
          UUID(as_uuid=True),
          ForeignKey("hedge_contracts.id", ondelete="RESTRICT"),
          nullable=False,
      )
      quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
      created_at: Mapped[DateTime] = mapped_column(...)
  ```
- **Mechanism:**
  No `deleted_at` / `is_deleted` column. No `LinkageService.delete`, no DELETE route. Modifying a linkage requires hard delete + new insert, which is a non-audited mutation if/when it happens via admin SQL or future endpoints. Constitution requires audit on every mutation; hard-delete is mutation-without-trail by default.
- **Reproduction / impact:** Admin removes a wrongly-created linkage → row vanishes → no audit trail of who/when.
- **Suggested direction:** Add `deleted_at`/`is_deleted` to `HedgeOrderLinkage`; soft-delete with audit_event.
- **Adjacent risk:** N/A.

---

### Tier 4 (count only)

- 4 hygiene items observed (stale comment in `exposure_engine.py:147` "Convention: positive = Vendido (short)…" without unit; `dict()` debug noise in `deal_engine._get_market_price`; `_validate_residuals_non_negative` `error_detail` overwritten only when first arg used; SQLAlchemy `Numeric(15,3)` mixed with raw `Float` columns in same model file).

---

## Anti-findings (issues you considered but rejected)

### A-A1-OPUS-01 — "Classification can be ambiguous because the order of `payload.legs` matters"
- **Initial concern:** I suspected `next(leg for leg in payload.legs if leg.price_type == HedgeLegPriceType.fixed)` could pick a non-deterministic leg if multiple `fixed` legs were present, making classification heuristic.
- **Actual code (`backend/app/services/contract_service.py:60-65`):**
  ```python
          fixed_leg = next(
              leg for leg in payload.legs if leg.price_type == HedgeLegPriceType.fixed
          )
          variable_leg = next(
              leg for leg in payload.legs if leg.price_type == HedgeLegPriceType.variable
          )
  ```
- **Why it is NOT a bug (in the audited scope):**
  Per §2.3, hedges have **exactly 2 legs** (one fixed, one variable). The Pydantic schema for `HedgeContractCreate` ([NEEDS JURY VERIFICATION] — schema not directly read by this auditor) is expected to enforce the 2-leg invariant. If that is enforced, `next(...)` is uniquely determined. The bug surface is *if* the schema permits 2 fixed legs — that's a different finding (schema validation), and not one I can prove from in-scope files alone.

### A-A1-OPUS-02 — "Audit middleware HMAC is not cryptographically verified on read"
- **Initial concern:** I worried that `audit_event` writes signed rows but reads might bypass verification.
- **Actual code (`backend/app/api/routes/audit.py:57-62`, out-of-scope but checked):**
  ```python
  def verify_audit_event(...):
      """Verify the HMAC signature of an audit event."""
  ```
- **Why it is NOT a bug:** A verification endpoint exists (`/audit/{id}/verify`), and `AuditTrailService` uses `hmac.compare_digest` (`backend/app/services/audit_trail_service.py:55-57`) for constant-time comparison. The signing path is sound. The constitutional gap is **emission**, not verification (see F-A1-OPUS-02).

### A-A1-OPUS-03 — "`compute_net_exposure` aggregation order non-determinism"
- **Initial concern:** `for row in rows:` iterates without `ORDER BY` and adds floats into a `dict[str, dict]`.
- **Actual code (`backend/app/services/exposure_engine.py:165-191`):**
  ```python
          rows = q.all()
          ...
          for row in rows:
              c = row.commodity.upper() if row.commodity else row.commodity
              if c not in agg:
                  agg[c] = {...}
              ...
              if row.direction == ExposureDirection.long:
                  agg[c]["long_original"] += original_val
                  agg[c]["long_hedged"] += hedged_val
              else:
                  agg[c]["short_original"] += original_val
                  agg[c]["short_hedged"] += hedged_val
  ```
- **Why it is NOT a bug here:** The aggregation is `GROUP BY commodity, direction` in SQL — the loop sees one row per `(commodity, direction)`, so each `agg[c][...]` is assigned at most twice per commodity (once for long, once for short). There is no order-dependent associativity issue at this level. (The float-accumulation issue exists *inside* SQL `SUM(...)` — that's covered by F-A1-OPUS-05/F-A1-OPUS-14.)

---

## Coverage attestation

- **Files I read in full:** `backend/app/services/exposure_engine.py`, `backend/app/services/deal_engine.py`, `backend/app/services/linkage_service.py`, `backend/app/schemas/exposure_engine.py`.
- **Files I navigated via Serena symbolic tools (full bodies retrieved on demand):** `backend/app/services/exposure_service.py` (entire `ExposureService`), `backend/app/models/exposure.py` (`Exposure`), `backend/app/models/deal.py` (`Deal`), `backend/app/models/linkages.py` (`HedgeOrderLinkage`), `backend/app/models/contracts.py` (`HedgeContract`, `HedgeClassification`), `backend/app/models/orders.py` (`Order`, `OrderType`, `PriceType`), `backend/app/api/routes/exposures.py` (4 functions), `backend/app/api/routes/deals.py` (4 functions), `backend/app/api/routes/linkages.py` (`create_linkage`), `backend/app/services/contract_service.py` (`ContractService.create`), `backend/app/services/rfq_service.py` (`determine_contract_legs`), `backend/app/api/dependencies/audit.py` (`audit_event`), `backend/app/core/pagination.py` (`paginate`).
- **Files I grep'd but did not read fully:** `backend/app/api/routes/audit.py`, `backend/app/services/audit_trail_service.py` (only HMAC paths confirmed via Grep).
- **Files I did not examine (out of scope):** All other services/routes/migrations.
- **Tools used:** Read 5 times, Grep 5 times, Serena `get_symbols_overview` 9 times, Serena `find_symbol` 13 times, Bash 1 time (commit SHA).

---

## Open questions for jury

1. Is `HedgeContractCreate` Pydantic schema enforced to exactly 2 legs (1 fixed + 1 variable)? If not, `contract_service.create`'s `next(... if leg.price_type == HedgeLegPriceType.fixed)` is non-deterministic — promotes A-A1-OPUS-01 to a P1 finding.
2. What is the configured Postgres transaction isolation level for the FastAPI session factory? `READ COMMITTED` keeps F-A1-OPUS-04 at Tier 1; `REPEATABLE READ` or `SERIALIZABLE` lowers severity but only with retry-on-conflict logic.
3. Is `Order.commodity` actually missing, or is commodity derived from `counterparty_id`? I confirmed via `find_symbol` that there is no `commodity` field on `Order`, but a join via `Counterparty` could in principle exist — if so, the multi-commodity bug (F-A1-OPUS-09) is mitigated only if every aggregator joins through that table. None do today.
4. Is `Deal.is_deleted` filter applied across the entire `DealLink`-consuming surface, or are some queries dropping it? My read coverage of `deal_engine.py` showed inconsistent `is_deleted` filters (e.g., `_recompute_tons`, `compute_pnl_breakdown` filters `Deal.is_deleted` but `DealLink` queries do not).
5. The constitution says `Commercial Net = Active – Passive` is a **closed form**, not derived by aggregation. `compute_commercial_snapshot` (`exposure_service.py:131-141`) returns `commercial_net_mt = residual_active - residual_passive` where `residual_active` and `residual_passive` are `SUM(Order.quantity_mt - linked.linked_qty)` aggregated from rows. Does the jury accept this as "closed form" (state) or "aggregation"? My read: it is aggregation across rows, but the result is a state snapshot — borderline.
