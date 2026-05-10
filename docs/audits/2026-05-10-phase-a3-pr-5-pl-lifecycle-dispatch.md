# Phase A3 / PR-A3-5 Dispatch - P&L Lifecycle Semantics

**Date:** 2026-05-10  
**Base:** `main` at `df39d6bc754b` after PR #49  
**Branch:** `audit-a3/pl-lifecycle-semantics`  
**Findings closed:** `J-A3-OPUS-09`  

---

## 1. Mission

Close the last open Phase A3 finding by fixing P&L lifecycle semantics for
partially settled hedge contracts.

Current P&L computes realized P&L from the cashflow ledger, but zeroes
`unrealized_mtm` for every contract status except `active`. That silently drops
the remaining open MTM tail for `partially_settled` contracts, even though
`compute_mtm_for_contract()` already supports both `active` and
`partially_settled`.

PR-A3-5 must align P&L with MTM:

- `active`: compute realized ledger P&L plus unrealized MTM.
- `partially_settled`: compute realized ledger P&L plus remaining unrealized MTM.
- `settled`: compute realized ledger P&L and explicitly set unrealized MTM to zero.
- `cancelled` or unknown status: hard-fail explicitly; do not return a silent zero.

This is a lifecycle semantics fix, not a P&L framework rewrite.

---

## 2. Source Evidence

Read these before coding:

- `docs/audits/2026-05-09-phase-a3-jury-verdict.md:137-143`
  - `J-A3-OPUS-09` validated finding.
- `docs/audits/2026-05-09-phase-a3-jury-verdict.md:187`
  - Wave 5 recommendation: align partially-settled contract handling with MTM and reject unsupported statuses explicitly.
- `docs/governance.md:131-159`
  - Valuation views must be explicit and methodology-bound.
- `docs/governance.md:171-186`
  - Hard-fail discipline; no silent fallback.
- `docs/governance.md:220-228`
  - Output contract: precise, structured, verifiable, audit-friendly, free of speculation.
- `backend/app/services/pl_calculation_service.py:17-124`
  - Current `compute_pl()` implementation.
- `backend/app/services/pl_calculation_service.py:107-111`
  - Current bug: non-`active` status gets `unrealized_mtm = Decimal("0")`.
- `backend/app/services/mtm_contract_service.py:19-67`
  - MTM already supports `active` and `partially_settled`, hard-fails other statuses.
- `backend/app/services/pl_snapshot_service.py:20-102`
  - P&L snapshot hash includes realized, unrealized, and price references.
- `backend/app/models/contracts.py:47-66`
  - Status enum and lifecycle transitions.
- `backend/tests/test_pl_calculation_service.py`
  - Focused `compute_pl()` tests to extend.
- `backend/tests/test_pl_snapshot_realized_from_ledger.py`
  - Snapshot idempotency/hash tests to extend.
- `backend/tests/test_cashflow_ledger_settlement.py:272-303`
  - Existing realized P&L settlement tests.

---

## 3. Scope IN

### 3.1 Replace implicit non-active zeroing with explicit lifecycle helper

Modify `backend/app/services/pl_calculation_service.py`.

Keep realized ledger calculation as-is. Do not change ledger ingestion or
settlement amount derivation.

Add a helper near `compute_pl()`:

```python
def _compute_unrealized_mtm_for_contract(
    db: Session,
    contract: HedgeContract,
    period_end: date,
    append_reference: Callable[[PriceReferenceEntry], None],
) -> Decimal:
    if contract.status in (
        HedgeContractStatus.active,
        HedgeContractStatus.partially_settled,
    ):
        mtm = compute_mtm_for_contract(
            db, contract_id=contract.id, as_of_date=period_end
        )
        if mtm.price_quote is None:
            raise HTTPException(
                status_code=status.HTTP_424_FAILED_DEPENDENCY,
                detail=f"MTM result for {contract.id} has no price provenance",
            )
        append_reference(
            PriceReferenceEntry(
                symbol=mtm.price_quote.symbol,
                source=mtm.price_quote.source,
                settlement_date=mtm.price_quote.settlement_date,
                value=mtm.price_quote.value,
            )
        )
        return Decimal(mtm.mtm_value)

    if contract.status == HedgeContractStatus.settled:
        return Decimal("0")

    if contract.status == HedgeContractStatus.cancelled:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="P&L is not defined for cancelled hedge contracts",
        )

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported hedge contract status for P&L: {contract.status}",
    )
```

If the executor chooses not to add a helper, the same status matrix must still
be implemented directly in `compute_pl()`. The helper form is preferred because
it prevents the old broad `contract.status != active` branch from reappearing.

Import prerequisite if using the helper annotation:

```python
from collections.abc import Callable
```

### 3.2 Update `compute_pl()` call site

Replace:

```python
if contract.status != HedgeContractStatus.active:
    unrealized_mtm = Decimal("0")
else:
    mtm = compute_mtm_for_contract(db, contract_id=entity_id, as_of_date=period_end)
    unrealized_mtm = Decimal(mtm.mtm_value)
    _append_reference(
        PriceReferenceEntry(
            symbol=mtm.price_quote.symbol,
            source=mtm.price_quote.source,
            settlement_date=mtm.price_quote.settlement_date,
            value=mtm.price_quote.value,
        )
    )
```

with:

```python
unrealized_mtm = _compute_unrealized_mtm_for_contract(
    db=db,
    contract=contract,
    period_end=period_end,
    append_reference=_append_reference,
)
```

Do not catch `HTTPException` from `compute_mtm_for_contract()`. Missing price
evidence must keep propagating as HTTP 424. Unsupported MTM statuses must remain
hard-fails, not zero defaults.

### 3.3 Preserve price-reference semantics

`price_references` must continue to include:

- priced ledger references from realized cashflow entries;
- the MTM price reference for `active` contracts;
- the MTM price reference for `partially_settled` contracts.

`settled` contracts must not trigger a new unrealized MTM price lookup. Their
`price_references` should come only from realized ledger entries in the period.

Deduplication through `_append_reference()` must remain intact.

### 3.4 Preserve snapshot hash semantics

Do not change `backend/app/services/pl_snapshot_service.py` hash format unless
tests prove a bug caused by the lifecycle change. The current hash includes:

- `entity_type`;
- `entity_id`;
- `period_start`;
- `period_end`;
- `realized_pl`;
- `unrealized_mtm`;
- `price_references`.

That is sufficient for PR-A3-5. The intended behavior is that a
`partially_settled` contract with a non-zero remaining MTM tail produces a
different snapshot hash than the old erroneous zero-MTM value.

---

## 4. Scope OUT

- Do not modify `docs/governance.md`.
- Do not change cashflow ledger ingestion.
- Do not change settlement amount derivation.
- Do not change MTM price lookup behavior.
- Do not change `compute_mtm_for_contract()` unless a test proves a direct bug in that function.
- Do not implement order P&L. Current order P&L hard-fail remains out of scope.
- Do not change deal-level P&L (`deal_engine.py`, `DealPNLSnapshot`, or A1 P&L artifacts).
- Do not add migrations; this is behavior and tests only unless OpenAPI/schema changes unexpectedly.
- Do not alter Scenario P&L semantics in `scenario_whatif_service.py`; Scenario was already handled in earlier A3 waves.

---

## 5. Acceptance Criteria

- [ ] `compute_pl()` no longer contains the broad branch `contract.status != HedgeContractStatus.active` that silently zeros all non-active contracts.
- [ ] `HedgeContractStatus.active` computes unrealized MTM through `compute_mtm_for_contract()`.
- [ ] `HedgeContractStatus.partially_settled` computes unrealized MTM through `compute_mtm_for_contract()`.
- [ ] `HedgeContractStatus.settled` explicitly returns `unrealized_mtm == Decimal("0")` while preserving realized ledger P&L and realized price references.
- [ ] `HedgeContractStatus.cancelled` hard-fails with a controlled `HTTPException`, not a zero P&L.
- [ ] Missing D-1 price evidence for `active` or `partially_settled` contracts still propagates HTTP 424 from MTM.
- [ ] `price_references` includes the MTM quote for `partially_settled` contracts.
- [ ] P&L snapshots for `partially_settled` contracts persist non-zero `unrealized_mtm`, price references, and a 64-character `inputs_hash`.
- [ ] Existing realized P&L from ledger tests still pass.
- [ ] `docs/governance.md` has no diff.

Mechanical grep checks after implementation:

```bash
grep -n "contract.status != HedgeContractStatus.active" backend/app/services/pl_calculation_service.py
grep -n "unrealized_mtm = Decimal(\"0\")" backend/app/services/pl_calculation_service.py
git diff -- docs/governance.md
```

Expected:

- The first grep returns zero matches.
- The second grep may return one match only in the explicit `settled` branch; it must not be inside a broad non-active branch.
- `git diff -- docs/governance.md` is empty.

---

## 6. Required Tests

### 6.1 Partially-settled contract contributes unrealized MTM

Add to `backend/tests/test_pl_calculation_service.py`:

- Create a `HedgeContract(status=HedgeContractStatus.partially_settled)`.
- Seed D-1 price evidence for `period_end`.
- Optionally seed one realized ledger settlement inside the period.
- Call `compute_pl(session, "hedge_contract", contract.id, period_start, period_end)`.
- Assert:
  - `unrealized_mtm` equals the same MTM formula as `compute_mtm_for_contract()`.
  - `realized_pl` still reflects ledger entries if seeded.
  - `price_references` includes the MTM quote.

Use the existing helper style in `test_pl_calculation_service.py`; avoid adding
new fixture infrastructure unless needed.

### 6.2 Partially-settled missing price hard-fails

Add a focused test:

- Create a `partially_settled` contract with fixed price and quantity.
- Do not seed D-1 price evidence for `period_end`.
- Call `compute_pl(...)`.
- Assert HTTP 424 and a detail that points to missing/unprovable price evidence.

This proves PR-A3-5 did not reintroduce fallback or silent zero behavior.

### 6.3 Settled contract remains realized-only

Extend or add a test proving:

- A `settled` contract with ledger entries in the period returns realized P&L.
- `unrealized_mtm == Decimal("0")`.
- No new MTM market quote is required at `period_end` for the settled branch.
- Realized ledger price references still appear when ledger entries carry them.

This preserves existing behavior for economically closed contracts while making
the branch explicit.

### 6.4 Cancelled contract hard-fails

Add a test:

- Create a `HedgeContract(status=HedgeContractStatus.cancelled)`.
- Call `compute_pl(...)`.
- Assert controlled `HTTPException` with status 409 and detail containing
  `cancelled`.

Do not let cancelled contracts return zero P&L.

### 6.5 Snapshot persists partially-settled MTM evidence

Add to `backend/tests/test_pl_snapshot_realized_from_ledger.py` or a focused
P&L snapshot test module:

- Create a `partially_settled` contract.
- Seed D-1 price evidence.
- Call `create_pl_snapshot(...)`.
- Assert:
  - `snapshot.unrealized_mtm` is non-zero and equals expected MTM.
  - `snapshot.price_references` contains the MTM quote.
  - `snapshot.inputs_hash` is not null and length 64.
  - a second identical call returns the same snapshot id and same hash.

### 6.6 Existing settlement P&L tests still pass

Do not rewrite `backend/tests/test_cashflow_ledger_settlement.py` broadly. It
already covers realized P&L sign behavior:

- `test_settlement_compute_pl_realized_long_side`
- `test_settlement_compute_pl_realized_short_side`

Run it as part of the focused suite.

---

## 7. Verification Commands

Run focused tests first:

```bash
python -m pytest backend/tests/test_pl_calculation_service.py backend/tests/test_pl_snapshot_realized_from_ledger.py backend/tests/test_cashflow_ledger_settlement.py -v
```

Run adjacent valuation tests:

```bash
python -m pytest backend/tests/test_mtm_contract_service.py backend/tests/test_mtm_snapshot_service.py backend/tests/test_cashflow_baseline_service.py -v
```

Run schema/API drift checks:

```bash
git diff -- docs/api/openapi_v1.json frontend-svelte/src/lib/api/schema.d.ts
```

Expected: no diff. If there is a diff, explain why in the PR body and include
the regenerated files only if required by a real schema change.

Run grep/diff gates:

```bash
git diff --check
git diff -- docs/governance.md
grep -n "contract.status != HedgeContractStatus.active" backend/app/services/pl_calculation_service.py
```

Then run the full backend suite:

```bash
python -m pytest backend/tests/ -q
```

If the known Python 3.14 `backend/tests/test_ws.py` failures recur, report them
separately with exact test names and also run:

```bash
python -m pytest backend/tests/ --ignore=backend/tests/test_ws.py -q
```

---

## 8. PR Body Requirements

The PR body must include:

- Dispatch file path.
- Finding closed: `J-A3-OPUS-09`.
- Status matrix implemented:
  - `active`;
  - `partially_settled`;
  - `settled`;
  - `cancelled`.
- Files changed.
- Tests run and exact results.
- Confirmation that `docs/governance.md` has no diff.
- Confirmation that no migration was added.
- Hook v2 artifact path and summary.
- Any hook/Codex catches and how they were fixed.

---

## 9. DO NOT

- Do not silently zero any lifecycle state other than the explicit `settled` branch.
- Do not catch and downgrade MTM price lookup failures.
- Do not make P&L depend on current mutable price state without preserving `price_references`.
- Do not remove realized ledger P&L for settled contracts.
- Do not implement order P&L.
- Do not touch deal-level P&L.
- Do not change governance.
- Do not use `--no-verify` without orchestrator authorization.
- Do not merge. Open PR only.

---

## 10. Executor Workflow

1. Create a dedicated worktree from latest `origin/main`.
2. Create branch `audit-a3/pl-lifecycle-semantics`.
3. Implement only this dispatch.
4. Run focused tests before broader suites.
5. Run all verification commands in §7.
6. Push normally and let hook v2 run.
7. Absorb real hook P1/P2 catches with follow-up commits.
8. Open PR.
9. Request Codex Connector review.
10. Report final head SHA, PR URL, tests, hook artifact, and catches fixed.

