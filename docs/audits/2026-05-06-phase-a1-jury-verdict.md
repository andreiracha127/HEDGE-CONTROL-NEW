# Phase A1 — Stage 3 Jury — Consolidated Verdict

**Date:** 2026-05-06
**Phase:** A1 — Primitives Econômicas
**Inputs:**
- Auditor A: docs/audits/2026-05-06-phase-a1-findings-opus.md (commit f1420524b3436145e5afd47f42589bbc1e43b0f4)
- Auditor B: docs/audits/2026-05-06-phase-a1-findings-gemini.md (commit f1420524b3436145e5afd47f42589bbc1e43b0f4)
**Code state:** `f1420524b3436145e5afd47f42589bbc1e43b0f4`

## 1. Verdict summary

- **Tier 1 (Critical, constitutional violation, ship-blocker):** 9 findings
- **Tier 2 (High, should fix pre-prod):** 1 finding
- **Tier 3 (Medium, defer-acceptable):** 2 findings
- **Tier 4 (Low, hygiene):** 4
- **Anti-findings (rejected from Stage 1/2):** 4 items
- **Subsumed:** 4 items

**Overall constitutional posture:** FAIL

Reason: multiple Tier 1 hard-fail violations are present. The most direct blockers are silent P&L pricing fallback at `backend/app/services/deal_engine.py:61-79`, over-allocation race plus downstream clamp at `backend/app/services/linkage_service.py:41-69` and `backend/app/services/exposure_engine.py:73-81`, missing audit evidence for economic mutations at `backend/app/api/routes/deals.py:70-170` and `backend/app/api/routes/exposures.py:51-57`, and commodity-blind commercial exposure at `backend/app/models/orders.py:49-106` plus `backend/app/services/exposure_engine.py:109-117`.

## 2. Convergent findings (both auditors caught — high confidence)

### J-A1-01 — P&L snapshots silently proceed without proven market price
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.6, §2.7
- **Source findings:** F-A1-OPUS-03 + F-A1-GEMINI-01; F-A1-OPUS-11 subsumed
- **Files\Lines:** `backend/app/services/deal_engine.py:44-79`, `backend/app/services/deal_engine.py:390-405`, `backend/app/services/deal_engine.py:423-498`
- **Issue:**
  > ```python
  >     except Exception:
  >         logger.debug(
  >             "market_price_unavailable commodity=%s date=%s", commodity, as_of_date
  >         )
  >         return None
  > ```
  > ```python
  >         if market_price is not None:
  >             return qty * market_price
  >         return qty * float(order.avg_entry_price or 0)
  > ```
  > ```python
  >                 else:
  >                     mtm = 0.0
  > ```
- **Mechanism (jury-verified):**
  `_get_market_price` catches every `Exception` and returns `None` at `deal_engine.py:61-79`. `compute_deal_pnl` then persists a `DealPNLSnapshot` at `deal_engine.py:487-498`. Physical variable-price orders fall back to `avg_entry_price` via `_order_value` at `deal_engine.py:390-405`, while hedge MTM becomes `0.0` at `deal_engine.py:469-477`. The idempotency hash at `deal_engine.py:44-58` includes only deal id, date, and link ids, so it cannot prove which price reference fed the snapshot.
- **Recommended fix direction:**
  Remove silent fallback for missing price evidence. P&L snapshot creation and breakdown must hard-fail when D-1 settlement price cannot be proven for any variable-price physical leg or active hedge leg. Persist price evidence or include price-source identity/date/value in the snapshot/hash so repeated runs are verifiable.
- **Acceptance criteria for remediation:**
  - [ ] `deal_engine.py` raises a domain/HTTP error when market price lookup cannot prove the reference.
  - [ ] `DealPNLSnapshot` records or hashes market-price provenance.
  - [ ] Tests assert no snapshot row is persisted when price evidence is missing.
  - [ ] Tests assert a corrected price reference cannot return a stale snapshot with the old hash.
- **Reasoning over reviewers:**
  Adopted both reviewers on the hard-fail violation. Opus had the fuller mechanism because it tied the fallback to physical valuation and `inputs_hash`; Gemini correctly identified the constitutional blocker.

### J-A1-02 — Economic mutations bypass signed audit evidence
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.6, §2.7
- **Source findings:** F-A1-OPUS-02 + F-A1-GEMINI-03
- **Files\Lines:** `backend/app/api/routes/deals.py:70-170`, `backend/app/api/routes/exposures.py:51-57`, `backend/app/services/exposure_engine.py:95-122`
- **Issue:**
  > ```python
  > @router.post("", response_model=DealRead, status_code=status.HTTP_201_CREATED)
  > def create_deal(
  >     body: DealCreate,
  >     _: None = Depends(require_any_role("trader", "risk_manager")),
  >     session: Session = Depends(get_session),
  > ):
  > ```
  > ```python
  > @router.post("/reconcile", response_model=ReconcileResponse)
  > def reconcile_exposures(
  >     _user: dict = Depends(get_current_user),
  >     session: Session = Depends(get_session),
  > ):
  >     result = ExposureEngineService.reconcile_from_orders(session)
  > ```
- **Mechanism (jury-verified):**
  `routes/linkages.py:42-63` wires `audit_event`, `mark_audit_success`, and `request.state.audit_commit()`. The deal mutation routes at `routes/deals.py:70-170` have no audit dependency while creating deals, adding/removing links, and creating P&L snapshots. The reconcile route at `routes/exposures.py:51-57` also lacks audit wiring, while `reconcile_from_orders` mutates or creates `Exposure` rows at `exposure_engine.py:95-122`.
- **Recommended fix direction:**
  Wire signed audit emission for every route and service path that mutates `Deal`, `DealLink`, `DealPNLSnapshot`, `Exposure`, or hedge task economic status. Reconcile likely needs a persisted reconciliation-run identifier so the audit row has a durable entity id.
- **Acceptance criteria for remediation:**
  - [ ] Deal create/link/delete and P&L snapshot routes emit audit events on success.
  - [ ] Exposure reconcile emits a signed audit event with a durable run/entity id.
  - [ ] Tests assert audit rows are written for each economic mutation.
  - [ ] Tests assert failed mutations do not mark audit success.
- **Reasoning over reviewers:**
  Gemini caught the exposure-reconcile slice; Opus correctly broadened the same root cause to deal and P&L mutation endpoints.

### J-A1-03 — Linkage creation has a TOCTOU over-allocation race
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.6
- **Source findings:** F-A1-OPUS-04 + F-A1-GEMINI-04
- **Files\Lines:** `backend/app/services/linkage_service.py:27-69`, `backend/app/models/linkages.py:11-26`
- **Issue:**
  > ```python
  >         order_linked_qty = (
  >             session.query(func.coalesce(func.sum(HedgeOrderLinkage.quantity_mt), 0.0))
  >             .filter(HedgeOrderLinkage.order_id == order_id)
  >             .scalar()
  >         )
  > ```
  > ```python
  >         if float(order_linked_qty or 0.0) + quantity_mt > order.quantity_mt:
  >             raise HTTPException(
  >                 status_code=status.HTTP_400_BAD_REQUEST,
  >                 detail="Linkage exceeds order quantity",
  >             )
  > ```
  > ```python
  >         session.add(linkage)
  >         session.commit()
  > ```
- **Mechanism (jury-verified):**
  `LinkageService.create` reads linked totals, checks limits, inserts, and commits without `with_for_update`, serializable retry handling, or a database constraint enforcing aggregate capacity. The model at `models/linkages.py:11-26` has FKs only; it cannot prevent concurrent transactions from each seeing the same remaining capacity. That can commit an over-allocation, violating the hard-fail rule before any read-time residual validation sees it.
- **Recommended fix direction:**
  Make linkage allocation atomic. Lock the relevant order and hedge contract rows before summing, or enforce serializable transactions with retry, plus a durable database-level invariant or materialized allocation ledger that makes over-allocation impossible to commit.
- **Acceptance criteria for remediation:**
  - [ ] Concurrent linkage creation cannot allocate more than order quantity.
  - [ ] Concurrent linkage creation cannot allocate more than contract quantity.
  - [ ] Tests simulate two sessions racing on the same order/contract capacity.
  - [ ] Failed concurrent allocation leaves no committed partial linkage.
- **Reasoning over reviewers:**
  Worst-of severity applies. Gemini marked Tier 2, but the resulting state is direct over-allocation, which §2.6 makes Tier 1.

### J-A1-04 — Institutional MT and price primitives use binary float
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.1, §2.6, §2.7
- **Source findings:** F-A1-OPUS-05 + F-A1-GEMINI-05
- **Files\Lines:** `backend/app/models/orders.py:61-66`, `backend/app/models/contracts.py:68-89`, `backend/app/models/linkages.py:25`, `backend/app/services/linkage_service.py:52-57`
- **Issue:**
  > ```python
  >     quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
  >     avg_entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
  > ```
  > ```python
  >     quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
  >     fixed_price_value: Mapped[float | None] = mapped_column(Float, nullable=True)
  > ```
  > ```python
  >     quantity_mt: Mapped[float] = mapped_column(Float, nullable=False)
  > ```
- **Mechanism (jury-verified):**
  Canonical input quantities for orders, hedge contracts, and linkages are `Float`, and boundary checks compare sums as floats at `linkage_service.py:52-57`. Derived models such as `Exposure` and `Deal` use `Numeric`, but services convert to `float` before comparisons and assignments. This can produce false over-allocation failures, missed near-boundary violations, non-reproducible sums, and status flips around exact hedge thresholds.
- **Recommended fix direction:**
  Migrate MT quantities and financial prices to `Numeric`/`Decimal` end to end, including Pydantic schemas and service arithmetic. Define a single quantization policy for MT and price precision and use it before comparisons.
- **Acceptance criteria for remediation:**
  - [ ] Order, contract, linkage, exposure, deal, and P&L quantity/price paths use `Decimal`.
  - [ ] Boundary checks quantize before comparison.
  - [ ] Tests cover `0.1 + 0.2 == 0.3`-style allocation and exact fully-hedged status.
  - [ ] Existing aggregate tests pass without float approximations.
- **Reasoning over reviewers:**
  Opus tied float use to hard-fail boundary behavior; Gemini identified the primitive mismatch. The severity is Tier 1 because over-allocation and economic evidence depend on exact thresholds.

## 3. Opus-only findings (jury-validated)

### J-A1-OPUS-01 — Reconcile clamps over-allocation instead of hard-failing
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.6
- **Source findings:** F-A1-OPUS-01
- **Files\Lines:** `backend/app/services/exposure_engine.py:73-81`
- **Issue:**
  > ```python
  >             hedged_qty = linked_map.get(str(order.id), 0.0)
  >             open_qty = max(float(order.quantity_mt) - hedged_qty, 0.0)
  > ```
  > ```python
  >             elif open_qty <= 0:
  >                 exp_status = ExposureStatus.fully_hedged
  > ```
- **Mechanism (jury-verified):**
  If existing linkage rows already exceed an order's quantity, `reconcile_from_orders` converts the negative residual into zero and marks the exposure fully hedged. This hides the violated invariant rather than raising. Gemini's Q1 accepted only the normal `LinkageService.create` path and did not account for races, imports, or data drift.
- **Recommended fix direction:**
  Replace the clamp with an explicit residual assertion before status calculation. Reconcile must refuse to persist an exposure snapshot when linked quantity exceeds order quantity.
- **Acceptance criteria for remediation:**
  - [ ] `reconcile_from_orders` raises on negative residual.
  - [ ] Test constructs over-linked data and asserts reconcile fails.
  - [ ] No exposure row is created or updated on failed reconcile.
- **Why Gemini missed:** Gemini treated write-time validation as exhaustive and did not validate the downstream reconcile path under corrupted/raced state.

### J-A1-OPUS-02 — Live exposure snapshots include deleted, settled, and cancelled entities
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.1, §2.5
- **Source findings:** F-A1-OPUS-06
- **Files\Lines:** `backend/app/services/exposure_service.py:72-303`, `backend/app/models/orders.py:101-106`, `backend/app/models/contracts.py:105-146`
- **Issue:**
  > ```python
  >             .filter(
  >                 Order.order_type == OrderType.sales,
  >                 Order.price_type == PriceType.variable,
  >             )
  > ```
  > ```python
  >             .filter(HedgeContract.classification == HedgeClassification.long)
  > ```
- **Mechanism (jury-verified):**
  `Order` has `deleted_at` at `models/orders.py:101-106`, and `HedgeContract` has `status` and `deleted_at` at `models/contracts.py:105-146`. `compute_commercial_snapshot` and `compute_global_snapshot` do not filter `Order.deleted_at`, `HedgeContract.deleted_at`, or live hedge statuses. The global route at `routes/exposures.py:38-43` exposes this service directly, so settled/cancelled/deleted economic rows remain in live KPI calculations.
- **Recommended fix direction:**
  Add lifecycle filters to every order and hedge query that contributes to commercial/global snapshots. Live exposure should include non-deleted variable-price orders and non-deleted active/partially-settled hedge contracts only.
- **Acceptance criteria for remediation:**
  - [ ] Deleted orders are excluded from commercial and global exposure.
  - [ ] Deleted, settled, and cancelled hedge contracts are excluded from live global exposure.
  - [ ] Tests cover each lifecycle exclusion.
  - [ ] `compute_net_exposure` and `ExposureService` lifecycle semantics match.
- **Why Gemini missed:** Gemini validated the formula shape but did not inspect lifecycle filters against the models.

### J-A1-OPUS-03 — HedgeOrderLinkage permits direction-mismatched hedge/order pairs
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.4, §2.5
- **Source findings:** F-A1-OPUS-07
- **Files\Lines:** `backend/app/services/linkage_service.py:20-69`, `backend/app/services/deal_engine.py:181-219`
- **Issue:**
  > ```python
  >         contract = session.get(HedgeContract, contract_id)
  >         if not contract:
  >             raise HTTPException(
  >                 status_code=status.HTTP_404_NOT_FOUND,
  >                 detail="Hedge contract not found",
  >             )
  > ```
  > ```python
  >         if float(contract_linked_qty or 0.0) + quantity_mt > contract.quantity_mt:
  >             raise HTTPException(
  >                 status_code=status.HTTP_400_BAD_REQUEST,
  >                 detail="Linkage exceeds contract quantity",
  >             )
  > ```
- **Mechanism (jury-verified):**
  `LinkageService.create` validates existence and capacity only. It never checks `Order.order_type` against `HedgeContract.classification`. `DealEngineService._validate_hedge_direction` enforces long-to-PO and short-to-SO at `deal_engine.py:181-219`, but `DealLink` is a different aggregate from `HedgeOrderLinkage`, and exposure snapshots use `HedgeOrderLinkage`.
- **Recommended fix direction:**
  Mirror the hedge-direction rule in `LinkageService.create`, and preferably make the invariant database-enforced through a trigger or denormalized checked side fields.
- **Acceptance criteria for remediation:**
  - [ ] Long hedge cannot be linked to a sales order.
  - [ ] Short hedge cannot be linked to a purchase order.
  - [ ] Tests cover both rejected pairings.
  - [ ] Existing valid SO-short and PO-long linkages still pass.
- **Why Gemini missed:** Gemini validated commercial/global formulas assuming the linkage table already encoded valid semantics.

### J-A1-OPUS-04 — Hedge classification can drift from fixed leg side
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.3, §2.7
- **Source findings:** F-A1-OPUS-08
- **Files\Lines:** `backend/app/models/contracts.py:110-121`, `backend/app/services/contract_service.py:60-78`, `backend/app/schemas/contracts.py:57-73`
- **Issue:**
  > ```python
  >     fixed_leg_side: Mapped[HedgeLegSide] = mapped_column(
  >         Enum(HedgeLegSide, name="hedge_leg_side"),
  >         nullable=False,
  >     )
  >     classification: Mapped[HedgeClassification] = mapped_column(
  >         Enum(HedgeClassification, name="hedge_classification"),
  >         nullable=False,
  >     )
  > ```
- **Mechanism (jury-verified):**
  The create path is deterministic: `ContractService.create` selects the fixed leg and derives classification at `contract_service.py:60-78`, and the schema enforces exactly one fixed leg and one variable leg at `schemas/contracts.py:57-73`. The bug is not creation-time ambiguity. The drift surface is that `fixed_leg_side`, `variable_leg_side`, and `classification` are independent persisted columns with no generated column, check, or trigger. Downstream exposure and P&L logic reads `classification` as truth.
- **Recommended fix direction:**
  Eliminate independent mutability. Derive classification from `fixed_leg_side` through a generated column, hybrid property, or strict database constraint that rejects inconsistent rows.
- **Acceptance criteria for remediation:**
  - [ ] Database cannot store fixed buy with short classification or fixed sell with long classification.
  - [ ] Tests assert inconsistent rows are rejected or impossible.
  - [ ] Read models serialize the deterministic classification.
- **Why Gemini missed:** Gemini stopped at the deterministic application create path and did not adjudicate the persistence invariant required by "absolute".

### J-A1-OPUS-05 — Orders are commodity-blind while exposures hardcode ALUMINUM
- **Adjudicated severity:** Tier 1
- **Constitutional rule:** §2.1, §2.5
- **Source findings:** F-A1-OPUS-09
- **Files\Lines:** `backend/app/models/orders.py:49-106`, `backend/app/services/exposure_engine.py:109-117`, `backend/app/services/exposure_service.py:72-162`
- **Issue:**
  > ```python
  > class Order(Base):
  >     __tablename__ = "orders"
  > ```
  > ```python
  >                 exposure = Exposure(
  >                     commodity="ALUMINUM",  # default commodity
  >                     direction=direction,
  > ```
  > ```python
  >             .filter(
  >                 Order.order_type == OrderType.sales,
  >                 Order.price_type == PriceType.variable,
  >             )
  > ```
- **Mechanism (jury-verified):**
  `Order` has no commodity column in the model or migrations. `reconcile_from_orders` therefore writes every derived `Exposure` as `ALUMINUM`. `ExposureService` aggregates all variable-price orders without commodity grouping. Hedge contracts do have `commodity`, so the system can produce per-commodity hedge data but cannot correctly match or net commercial orders by commodity.
- **Recommended fix direction:**
  Add a required commodity to orders and migrate existing data explicitly. Replace the hardcoded exposure commodity with the order commodity and make commercial/global snapshots commodity-scoped or grouped.
- **Acceptance criteria for remediation:**
  - [ ] `Order.commodity` exists, is required, and is populated by migration.
  - [ ] Reconcile copies commodity from order to exposure.
  - [ ] Commercial/global exposure tests cover at least two commodities that must not net against each other.
  - [ ] Existing single-commodity tests remain stable.
- **Why Gemini missed:** Gemini treated the formula as scalar and did not check whether commercial inputs carried the commodity dimension.

### J-A1-OPUS-06 — Service-layer commits are not coordinated with rollback and audit boundaries
- **Adjudicated severity:** Tier 2
- **Constitutional rule:** §2.7
- **Source findings:** F-A1-OPUS-10
- **Files\Lines:** `backend/app/services/exposure_engine.py:122`, `backend/app/services/deal_engine.py:143`, `backend/app/services/deal_engine.py:498`, `backend/app/services/linkage_service.py:69`, `backend/app/api/routes/linkages.py:58-62`
- **Issue:**
  > ```python
  >         session.commit()
  >         session.refresh(linkage)
  >         return linkage
  > ```
  > ```python
  >     linkage = LinkageService.create(
  >         session, payload.order_id, payload.contract_id, payload.quantity_mt
  >     )
  >     mark_audit_success(request, linkage.id)
  >     request.state.audit_commit()
  > ```
- **Mechanism (jury-verified):**
  Services commit internally, while routes sometimes perform audit work after the service returns. In `create_linkage`, the DB commit happens inside `LinkageService.create` before `mark_audit_success` and `audit_commit`. A crash or serialization error in that gap can leave an economic mutation committed without its audit evidence. There is also no explicit rollback boundary around multi-step service mutations.
- **Recommended fix direction:**
  Move commits to a single unit-of-work boundary that can include audit success marking, or make DB commit and audit commit explicitly compensating and recoverable. Services should flush/return domain objects; routes or a transaction manager should commit.
- **Acceptance criteria for remediation:**
  - [ ] Linkage/deal/exposure mutation commits and audit commits are ordered under one defined boundary.
  - [ ] Tests simulate post-service failure and assert no unaudited committed mutation remains.
  - [ ] Service methods have consistent rollback behavior.
- **Why Gemini missed:** Gemini focused on individual economic invariants rather than transaction/audit boundary composition.

### J-A1-OPUS-07 — Soft-deleted deals can retain invisible DealLink ownership
- **Adjudicated severity:** Tier 3
- **Constitutional rule:** §2.7
- **Source findings:** F-A1-OPUS-15
- **Files\Lines:** `backend/app/models/deal.py:80-99`, `backend/app/services/deal_engine.py:261-280`, `backend/app/services/deal_engine.py:722-734`
- **Issue:**
  > ```python
  >         cross_deal = (
  >             session.query(DealLink)
  >             .filter(
  >                 DealLink.linked_type == resolved_type,
  >                 DealLink.linked_id == linked_id,
  >                 DealLink.deal_id != deal_id,
  >             )
  >             .first()
  >         )
  > ```
- **Mechanism (jury-verified):**
  `Deal` has `is_deleted`, and normal list/get filters exclude deleted deals. `DealLink` has a unique constraint on `(linked_type, linked_id)` and no lifecycle column. If a deal is marked deleted while its links remain, those links still block reuse but the owning deal is hidden from normal deal reads. I did not find an in-scope deal-delete route, so this is latent rather than an observed route behavior.
- **Recommended fix direction:**
  Define the lifecycle contract for deleted deals and their links. Either cascade/hard-remove links with audit, soft-delete links, or make reuse checks join visible deals and reconcile the database unique constraint accordingly.
- **Acceptance criteria for remediation:**
  - [ ] Test covers linking an entity after its prior parent deal is deleted/archived.
  - [ ] DB constraints and service checks agree on deleted deal semantics.
- **Why Gemini missed:** This is a lifecycle edge case outside Gemini's main exposure formula review.

### J-A1-OPUS-08 — Exposure soft-delete can create duplicate source snapshots
- **Adjudicated severity:** Tier 3
- **Constitutional rule:** §2.1
- **Source findings:** F-A1-OPUS-16
- **Files\Lines:** `backend/app/models/exposure.py:88-97`, `backend/app/services/exposure_engine.py:85-119`
- **Issue:**
  > ```python
  >                 .filter(
  >                     Exposure.source_id == order.id,
  >                     Exposure.is_deleted == False,  # noqa: E712
  >                 )
  >                 .first()
  > ```
- **Mechanism (jury-verified):**
  `Exposure` has `is_deleted` and `deleted_at`. Reconcile searches only non-deleted exposure rows for the order source. If an exposure row is ever soft-deleted, reconcile will create a new active exposure for the same `source_id` rather than undeleting or updating the canonical state row. No in-scope delete route was found, so this is a latent state-integrity issue.
- **Recommended fix direction:**
  Decide whether derived exposures can be soft-deleted. If yes, reconcile should handle existing deleted rows deterministically. If no, remove the lifecycle fields or prevent deletion.
- **Acceptance criteria for remediation:**
  - [ ] Test covers reconcile after an exposure row is marked deleted.
  - [ ] Reconcile cannot create ambiguous active/deleted duplicate snapshots for the same source.
- **Why Gemini missed:** Gemini correctly accepted state mutation but did not test the soft-delete branch of state identity.

## 4. Gemini-only findings (jury-validated)

No Gemini-only finding was promoted as a standalone issue. F-A1-GEMINI-01, 03, 04, and 05 are convergent with Opus findings. F-A1-GEMINI-02 is rejected as a Tier 1 hard-fail claim in Anti-findings.

## 5. Anti-findings (FPs from Stage 1/2)

### A-A1-J-01 — Gemini F-A1-GEMINI-02 as Tier 1 hard-fail ordering bug
- **Source:** F-A1-GEMINI-02; related to A-A1-OPUS-03
- **Reviewer claim:**
  > `compute_net_exposure` has no `.order_by()`, so dict aggregation makes exposure net aggregation non-deterministic and Tier 1.
- **Actual code:**
  > ```python
  >         q = q.group_by(Exposure.commodity, Exposure.direction)
  >         rows = q.all()
  > ```
  > ```python
  >         gq = gq.group_by(HedgeContract.commodity, HedgeContract.classification)
  >         global_rows = gq.all()
  > ```
- **Why it is NOT a bug:**
  The cited loop receives grouped SQL rows, not raw line items. The missing `ORDER BY` can make list output order unstable, but it does not by itself change the computed exposure values, and it is not a §2.6 hard-fail violation. The reproducibility risk from float arithmetic/order is already handled by J-A1-04 and S-A1-J-04.

### A-A1-J-02 — Opus anti-claim that hedge leg order can make classification ambiguous
- **Source:** A-A1-OPUS-01
- **Reviewer claim:**
  > `next(...)` over `payload.legs` might be ambiguous if multiple fixed legs are present.
- **Actual code:**
  > ```python
  >         if len(self.legs) != 2:
  >             raise ValueError("hedge contract must have exactly two legs")
  > ```
  > ```python
  >         if len(fixed_legs) != 1 or len(variable_legs) != 1:
  >             raise ValueError(
  >                 "hedge contract must have exactly one fixed leg and one variable leg"
  >             )
  > ```
- **Why it is NOT a bug:**
  `HedgeContractCreate` enforces exactly two legs with exactly one fixed and one variable leg before `ContractService.create` derives classification. Creation-time classification is deterministic. J-A1-OPUS-04 is a different finding: persisted drift after creation.

### A-A1-J-03 — Gemini anti-claim that Exposure needs an event log
- **Source:** A-A1-GEMINI-01
- **Reviewer claim:**
  > Updating `Exposure.open_tons` in place might be a bug because historical changes are not stored in the exposure row.
- **Actual code:**
  > ```python
  >                 if float(existing.open_tons) != open_qty:
  >                     existing.open_tons = open_qty
  >                     changed = True
  > ```
- **Why it is NOT a bug:**
  Governance §2.1 explicitly defines Exposure as state, not event. In-place state update is acceptable. The bug is missing audit evidence for the mutation, covered by J-A1-02.

### A-A1-J-04 — Opus F-A1-OPUS-17 current hard-delete risk in HedgeOrderLinkage
- **Source:** F-A1-OPUS-17
- **Reviewer claim:**
  > `HedgeOrderLinkage` lacks soft-delete, so modifying a linkage requires hard delete plus new insert and loses audit trail.
- **Actual code:**
  > ```python
  > class HedgeOrderLinkage(Base):
  >     __tablename__ = "hedge_order_linkages"
  > ```
  > ```python
  > @router.get("/{linkage_id}", response_model=HedgeOrderLinkageRead)
  > def get_linkage(
  > ```
- **Why it is NOT a bug:**
  In the audited linkage route/service there is create, list, and get, but no delete or update path. An admin SQL hard-delete would be outside the in-scope application behavior. Future linkage mutation should be designed with audit, but this is not a current Phase A1 bug.

## 6. Subsumed findings

### S-A1-J-01 — F-A1-OPUS-11 subsumed by J-A1-01
- **Reason:** J-A1-01 requires no P&L snapshot without proven price evidence and requires price provenance in the snapshot/hash. That covers the stale `inputs_hash` cache failure.

### S-A1-J-02 — F-A1-OPUS-12 subsumed by J-A1-OPUS-05
- **Reason:** The `compute_net_exposure` commodity decomposition bug is a direct consequence of order commodity blindness and hardcoded `Exposure.commodity`. Fixing J-A1-OPUS-05 removes the root cause.

### S-A1-J-03 — F-A1-OPUS-13 subsumed by J-A1-04
- **Reason:** `_recompute_tons` hedge ratio float division is one manifestation of binary-float quantity arithmetic. Decimal/quantized primitives and comparisons in J-A1-04 cover it.

### S-A1-J-04 — F-A1-OPUS-14 subsumed by J-A1-04
- **Reason:** The serious byte-reproducibility issue in unordered aggregate paths depends on float non-associativity. Deterministic ordering is useful acceptance hardening, but the economic root cause is J-A1-04.

## 7. Fresh findings (jury caught what both missed — rare)

No fresh findings.

## 8. Open questions for orchestrator

None.

## 9. Remediation dispatch metadata

For the orchestrator to decide remediation scope:

- **Total Tier 1 fixes required:** 9
- **Total Tier 2 fixes required:** 1
- **Total Tier 3 fixes deferrable:** 2
- **Estimated remediation scope:** split per concern
- **Critical sequencing:** fix J-A1-04 Decimal primitives before finalizing boundary tests for J-A1-03 and J-A1-OPUS-01; fix J-A1-OPUS-05 commodity model before remediating J-A1-OPUS-02 global/commercial snapshot filters; define transaction/audit boundary J-A1-OPUS-06 before wiring all J-A1-02 audit calls.
- **Required regression tests:**
  - `backend/tests/test_linkages.py` — covers J-A1-03, J-A1-OPUS-03
  - `backend/tests/test_exposure_engine.py` — covers J-A1-OPUS-01, J-A1-OPUS-05, J-A1-OPUS-08
  - `backend/tests/test_exposures_commercial.py` — covers J-A1-OPUS-02, J-A1-OPUS-05
  - `backend/tests/test_exposures_global.py` — covers J-A1-OPUS-02, J-A1-OPUS-03, J-A1-OPUS-05
  - `backend/tests/test_deal_engine.py` — covers J-A1-01, J-A1-02, J-A1-04, J-A1-OPUS-07
  - `backend/tests/test_contract_service.py` — covers J-A1-OPUS-04
  - New transaction/audit tests — cover J-A1-02 and J-A1-OPUS-06

## 10. Self-bias confession (mandatory)

Per the 3-model audit pattern:

- **Findings I reversed from my first pass:** 2 (F-A1-GEMINI-02 downgraded/rejected as Tier 1 after reading grouped SQL; F-A1-OPUS-17 rejected as current bug after confirming no in-scope delete/update path)
- **Findings where I gave benefit-of-doubt to a reviewer:** 2 (F-A1-OPUS-08 classification drift promoted despite deterministic create path because §2.3 requires an absolute invariant; F-A1-OPUS-15 kept as Tier 3 despite no in-scope deal-delete route because the model/service state can represent the inconsistency)
- **Findings where I overruled both reviewers:** 1 (Gemini passed over-allocation in Q1, but Opus's reconcile clamp plus race mechanism is valid; Opus's broader ordering F14 was subsumed rather than promoted independently)
- **Findings where I disagreed with worst-of-severity and downgraded:** 1 (F-A1-GEMINI-02 from Tier 1 to anti-finding/subsumed ordering hardening, because the cited mechanism does not alter economic values)
