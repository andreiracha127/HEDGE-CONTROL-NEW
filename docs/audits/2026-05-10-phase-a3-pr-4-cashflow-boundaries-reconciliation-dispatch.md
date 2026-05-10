# Phase A3 - PR-A3-4 Dispatch - Cashflow Boundaries and Ledger/Baseline Reconciliation

**Wave:** 4 (depends on Wave 1 PR #41, Wave 2 PR #44, Wave 3 PR #47)
**Stage:** Remediation (post-jury)
**Authoring date:** 2026-05-10
**Findings covered:** J-A3-04 (T1, Baseline reads Analytic and Scenario labels Analytic as Baseline) + J-A3-OPUS-08 (T2, Ledger and Baseline lack a reconciliation invariant)
**Branch name:** `audit-a3/cashflow-boundaries-reconciliation`
**Base:** `main` (currently `40aa682d6`, post-PR-#47 cashflow projection hardening merge)

---

## 0. Refresh notes (read first)

This is the first PR-A3-4 dispatch. It is intentionally narrower than "cashflow refactor".

Verified against `main = 40aa682d6`:

- `backend/app/services/cashflow_baseline_service.py:10` imports `compute_cashflow_analytic`.
- `backend/app/services/cashflow_baseline_service.py:42-44` computes Baseline by calling Analytic, then persists `analytic.model_dump(mode="json")`.
- `backend/app/schemas/scenario.py:95-97` declares `ScenarioCashflowSnapshot.analytic` and `.baseline` with the same `CashFlowAnalyticResponse` type.
- `backend/app/services/scenario_whatif_service.py:523-530` builds one `cashflow_analytic` object and assigns it to both `analytic` and `baseline`.
- `backend/app/services/cashflow_ledger_service.py:77-157` now derives ledger rows server-side and persists price provenance for the floating leg.
- `backend/app/models/cashflow.py:25-41` stores `CashFlowBaselineSnapshot.snapshot_data` as JSON and `total_net_cashflow` as a column, so PR-A3-4 can change the snapshot payload contract without a migration.
- `docs/governance.md:131-159` already defines cashflow views and Projection-specific invariants after PR #47. PR-A3-4 does not need another constitutional change.

The institutional issue is not that Baseline and Analytic share arithmetic. The issue is that Baseline is currently an alias of Analytic, and Scenario publishes a Baseline field that is literally the Analytic object. Ledger also exists as accounting evidence but Baseline does not persist any realized-ledger reconciliation evidence. That is a cashflow-boundary failure.

---

## 1. Mission

Close PR-A3-4 by making cashflow boundaries explicit and auditable:

1. Baseline must be persisted by `cashflow_baseline_service` through a Baseline-owned builder. It must not import or call `compute_cashflow_analytic`, and it must not persist an Analytic response dump as its snapshot payload.
2. Baseline snapshot data must include realized ledger evidence up to `as_of_date`, with a deterministic reconciliation block proving how the persisted `total_net_cashflow` was formed.
3. Scenario must stop exposing a fake Baseline. `ScenarioCashflowSnapshot.baseline` is removed; What-if keeps its in-memory Analytic cashflow view only. If a future product needs Scenario-vs-Baseline comparison, it must be designed as a separate explicit contract, not by duplicating Analytic.

After PR-A3-4:

- `cashflow_baseline_service.py` has no `compute_cashflow_analytic` import and no `CashFlowAnalyticResponse` dependency.
- `create_cashflow_baseline_snapshot()` persists a Baseline payload shaped as:

```json
{
  "view": "baseline",
  "as_of_date": "2026-02-01",
  "unrealized_items": [],
  "realized_ledger_entries": [],
  "reconciliation": {
    "unrealized_total_usd": "0.000000",
    "realized_total_usd": "0.000000",
    "total_net_cashflow": "0.000000",
    "unrealized_item_count": 0,
    "ledger_entry_count": 0
  }
}
```

- `CashFlowBaselineSnapshot.total_net_cashflow` equals `Decimal(reconciliation["total_net_cashflow"])`.
- `reconciliation["total_net_cashflow"]` equals `unrealized_total_usd + realized_total_usd`.
- `realized_total_usd` equals the sum of signed ledger entries where `IN` is positive and `OUT` is negative.
- Baseline includes realized ledger entries with provenance fields already landed by Wave 1.
- Scenario response schema no longer contains `cashflow_snapshot.baseline`.

---

## 2. Reference docs and code (read before coding)

- `docs/audits/2026-05-09-phase-a3-jury-verdict.md`:
  - J-A3-04 section - Baseline cashflow reads Analytic and scenario labels Analytic as Baseline.
  - J-A3-OPUS-08 section - Ledger and Baseline lack a reconciliation invariant.
  - Remediation plan recommendation section, Wave 4.
- `docs/governance.md:131-159` - CashFlow views, one methodology per endpoint, no fallback pricing regimes, Projection invariants.
- `docs/governance.md:171-186` - hard-fail rules and no mixed regimes.
- `docs/governance.md:220-228` - output contract: explicit, audit-friendly, free of speculation.
- `backend/app/services/cashflow_baseline_service.py:1-86` - target Baseline service.
- `backend/app/services/cashflow_analytic_service.py:15-68` - current Analytic implementation. Read it to understand current arithmetic, but do not make Baseline call it.
- `backend/app/services/cashflow_ledger_service.py:77-157` - derived ledger entry and provenance contract.
- `backend/app/services/cashflow_ledger_service.py:299-315` - `list_entries_by_contract()`, useful reference for deterministic ledger ordering.
- `backend/app/models/cashflow.py:25-41` - Baseline snapshot model.
- `backend/app/models/cashflow.py:44-90` - ledger event and entry model.
- `backend/app/schemas/cashflow.py:34-68` - `CashFlowItem`, `CashFlowAnalyticResponse`, `CashFlowBaselineSnapshotResponse`.
- `backend/app/schemas/scenario.py:95-113` - scenario cashflow response schema.
- `backend/app/services/scenario_whatif_service.py:510-530` - current duplicate Analytic/Baseline assignment.
- `backend/tests/test_cashflow_baseline_service.py` - existing baseline tests to extend.
- `backend/tests/test_scenario_whatif_run.py` - scenario response tests to update.

---

## 3. Scope IN

### 3.1 Baseline-owned snapshot builder

Modify `backend/app/services/cashflow_baseline_service.py`.

Remove:

```python
from app.services.cashflow_analytic_service import compute_cashflow_analytic
```

Do not replace it with a wrapper around Analytic. Baseline owns its own snapshot construction.

Add helpers in `cashflow_baseline_service.py`:

```python
def _signed_ledger_amount(entry: CashFlowLedgerEntry) -> Decimal:
    amount = Decimal(str(entry.amount))
    if entry.direction == "IN":
        return amount
    if entry.direction == "OUT":
        return -amount
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Unsupported ledger direction: {entry.direction}",
    )
```

```python
def _ledger_entry_payload(entry: CashFlowLedgerEntry) -> dict:
    signed_amount = _signed_ledger_amount(entry)
    return {
        "id": str(entry.id),
        "hedge_contract_id": str(entry.hedge_contract_id),
        "source_event_type": entry.source_event_type,
        "source_event_id": str(entry.source_event_id) if entry.source_event_id else None,
        "leg_id": entry.leg_id,
        "cashflow_date": entry.cashflow_date.isoformat(),
        "currency": entry.currency,
        "direction": entry.direction,
        "amount": str(Decimal(str(entry.amount))),
        "signed_amount_usd": str(signed_amount),
        "price_source": entry.price_source,
        "price_symbol": entry.price_symbol,
        "price_settlement_date": (
            entry.price_settlement_date.isoformat()
            if entry.price_settlement_date is not None
            else None
        ),
        "price_value": str(entry.price_value) if entry.price_value is not None else None,
    }
```

```python
def _load_realized_ledger_entries(db: Session, as_of_date: date) -> list[CashFlowLedgerEntry]:
    return (
        db.query(CashFlowLedgerEntry)
        .filter(
            CashFlowLedgerEntry.source_event_type == SOURCE_EVENT_TYPE,
            CashFlowLedgerEntry.cashflow_date <= as_of_date,
        )
        .order_by(
            CashFlowLedgerEntry.cashflow_date.asc(),
            CashFlowLedgerEntry.hedge_contract_id.asc(),
            CashFlowLedgerEntry.leg_id.asc(),
            CashFlowLedgerEntry.created_at.asc(),
        )
        .all()
    )
```

Add a Baseline-owned unrealized item builder. It may call MTM services directly because MTM is the valuation primitive; it must not call Analytic.

Contracts:

- Include `HedgeContractStatus.active` and `HedgeContractStatus.partially_settled`.
- Skip `settled` contracts for unrealized items; their realized flows belong in ledger entries.
- Preserve price provenance fields in each `CashFlowItem`.

Orders:

- Include variable orders with MTM-eligible conventions, mirroring Analytic eligibility.
- Preserve price provenance fields in each `CashFlowItem`.

Acceptable implementation shape:

```python
def _build_unrealized_items(db: Session, as_of_date: date) -> list[CashFlowItem]:
    items: list[CashFlowItem] = []
    # Query active + partially_settled contracts and variable MTM-eligible orders.
    # Call compute_mtm_for_contract / compute_mtm_for_order directly.
    # Convert MTMResultResponse to CashFlowItem with price provenance.
    return items
```

This intentionally shares the same pricing primitives as Analytic without making Baseline a proxy for Analytic.

### 3.2 Baseline payload contract and reconciliation invariant

Replace the current lines `42-45` pattern:

```python
analytic = compute_cashflow_analytic(db, as_of_date=as_of_date)
total = Decimal(analytic.total_net_cashflow)
payload = _canonicalize_snapshot_payload(analytic.model_dump(mode="json"))
inputs_hash = _compute_inputs_hash(as_of_date, payload, total)
```

with Baseline-owned payload creation:

```python
unrealized_items = _build_unrealized_items(db, as_of_date)
realized_entries = _load_realized_ledger_entries(db, as_of_date)

unrealized_total = sum((item.amount_usd for item in unrealized_items), Decimal("0"))
realized_payload = [_ledger_entry_payload(entry) for entry in realized_entries]
realized_total = sum(
    (Decimal(item["signed_amount_usd"]) for item in realized_payload),
    Decimal("0"),
)
total = unrealized_total + realized_total

payload = _canonicalize_snapshot_payload(
    {
        "view": "baseline",
        "as_of_date": as_of_date.isoformat(),
        "unrealized_items": [
            item.model_dump(mode="json") for item in unrealized_items
        ],
        "realized_ledger_entries": realized_payload,
        "reconciliation": {
            "unrealized_total_usd": str(unrealized_total),
            "realized_total_usd": str(realized_total),
            "total_net_cashflow": str(total),
            "unrealized_item_count": len(unrealized_items),
            "ledger_entry_count": len(realized_payload),
        },
    }
)
inputs_hash = _compute_inputs_hash(as_of_date, payload, total)
```

Update `_canonicalize_snapshot_payload()` so it sorts both:

- `unrealized_items` by `(object_type, object_id)`.
- `realized_ledger_entries` by `(cashflow_date, hedge_contract_id, leg_id, source_event_id or "")`.

Keep the existing conflict behavior: if an existing snapshot for `as_of_date` does not match the newly derived payload, return HTTP 409. Do not silently rewrite old analytic-shaped snapshots into the new Baseline shape.

### 3.3 Scenario response boundary

Modify `backend/app/schemas/scenario.py`.

Current:

```python
class ScenarioCashflowSnapshot(BaseModel):
    analytic: CashFlowAnalyticResponse
    baseline: CashFlowAnalyticResponse
```

Replace with:

```python
class ScenarioCashflowSnapshot(BaseModel):
    analytic: CashFlowAnalyticResponse
```

Modify `backend/app/services/scenario_whatif_service.py`.

Current:

```python
cashflow_snapshot = ScenarioCashflowSnapshot(
    analytic=cashflow_analytic, baseline=cashflow_analytic
)
```

Replace with:

```python
cashflow_snapshot = ScenarioCashflowSnapshot(analytic=cashflow_analytic)
```

Do not add a new scenario baseline comparison field in this PR. That would be a product/API design task and would need its own contract: baseline snapshot selection, missing baseline handling, and comparison semantics.

### 3.4 OpenAPI/frontend schema regeneration

Because `ScenarioCashflowSnapshot` changes, regenerate API artifacts:

- `docs/api/openapi_v1.json`
- `frontend-svelte/src/lib/api/schema.d.ts`

No frontend component change is expected unless the generated type change exposes a real consumer. Current search on `main = 40aa682d6` found no direct frontend read of `cashflow_snapshot.baseline`.

### 3.5 No model migration

PR-A3-4 must not add a migration unless the executor finds a hard blocker. The existing `CashFlowBaselineSnapshot.snapshot_data JSON` and `total_net_cashflow Numeric` fields are sufficient for the new payload contract.

`alembic heads` must remain a single head at `038_a3_price_provenance`.

---

## 4. Scope OUT

- Do not change `docs/governance.md`. PR #47 already declared Projection; PR-A3-4 is enforcement against existing governance.
- Do not refactor all cashflow services into a shared framework.
- Do not add a Scenario-vs-Baseline comparison feature.
- Do not persist Scenario outputs.
- Do not change the ledger ingestion API.
- Do not change settlement amount derivation rules from Wave 1.
- Do not touch PR-A3-5 / J-A3-OPUS-09 partially-settled P&L lifecycle logic.
- Do not relax hard-fail behavior for price lookup or unsupported ledger directions.

---

## 5. Acceptance criteria

- [ ] `backend/app/services/cashflow_baseline_service.py` no longer imports `compute_cashflow_analytic`.
- [ ] `backend/app/services/cashflow_baseline_service.py` no longer contains `analytic.model_dump`.
- [ ] Baseline snapshot payload root contains exactly the institutional fields `view`, `as_of_date`, `unrealized_items`, `realized_ledger_entries`, `reconciliation`.
- [ ] `snapshot_data["view"] == "baseline"`.
- [ ] `snapshot_data["reconciliation"]["total_net_cashflow"] == snapshot.total_net_cashflow` after Decimal normalization.
- [ ] `snapshot_data["reconciliation"]["total_net_cashflow"] == realized_total_usd + unrealized_total_usd`.
- [ ] Realized ledger reconciliation signs `IN` as positive and `OUT` as negative.
- [ ] Unsupported ledger direction hard-fails with HTTP 422; no silent ignore.
- [ ] Baseline unrealized items include `active` and `partially_settled` contracts; `settled` contracts are represented only through realized ledger entries.
- [ ] Scenario response no longer includes `cashflow_snapshot.baseline`.
- [ ] `backend/app/services/scenario_whatif_service.py` no longer contains `baseline=cashflow_analytic`.
- [ ] OpenAPI and `schema.d.ts` are regenerated and included if they change.
- [ ] `docs/governance.md` has no diff.
- [ ] `alembic heads` remains one head: `038_a3_price_provenance`.

Mechanical grep checks:

```bash
grep -n "compute_cashflow_analytic\|analytic.model_dump" backend/app/services/cashflow_baseline_service.py
grep -n "baseline=cashflow_analytic" backend/app/services/scenario_whatif_service.py
grep -n "baseline: CashFlowAnalyticResponse" backend/app/schemas/scenario.py
```

All three commands must return zero matches after the fix.

---

## 6. Required tests

Extend `backend/tests/test_cashflow_baseline_service.py`.

Before adding new tests, update existing Baseline tests that assume the old
Analytic-shaped payload. In particular,
`test_cashflow_baseline_per_row_provenance_quadruple_inside_snapshot_data`
currently reads:

```python
item = snapshot.snapshot_data["cashflow_items"][0]
```

Change it to read the new Baseline-owned key:

```python
item = snapshot.snapshot_data["unrealized_items"][0]
```

Keep the existing assertions for `price_source`, `price_symbol`,
`price_settlement_date`, and `price_value`; those provenance fields remain
inside each unrealized item. Do not leave any test that indexes
`snapshot_data["cashflow_items"]`, because PR-A3-4 explicitly removes that
Analytic-shaped root key from Baseline.

### 6.1 Baseline no longer proxies Analytic

Add a test that creates a baseline snapshot and asserts the new payload shape:

```python
def test_cashflow_baseline_snapshot_uses_baseline_payload_contract(client) -> None:
    _insert_price(settlement_date=date(2026, 1, 30), price_usd=110.0)
    _create_variable_sales_order(client, avg_entry_price=100.0)

    with SessionLocal() as session:
        snapshot = create_cashflow_baseline_snapshot(
            session, as_of_date=date(2026, 2, 1), correlation_id="c-1"
        )

    assert snapshot.snapshot_data["view"] == "baseline"
    assert set(snapshot.snapshot_data) == {
        "view",
        "as_of_date",
        "unrealized_items",
        "realized_ledger_entries",
        "reconciliation",
    }
    assert "cashflow_items" not in snapshot.snapshot_data
```

Also add a static boundary test if the project accepts source-inspection tests:

```python
def test_cashflow_baseline_service_does_not_import_analytic() -> None:
    source = Path("backend/app/services/cashflow_baseline_service.py").read_text()
    assert "compute_cashflow_analytic" not in source
    assert "analytic.model_dump" not in source
```

This is not style policing; it pins the constitutional boundary from J-A3-04.

### 6.2 Ledger reconciliation is persisted

Add a test that:

1. Creates an active hedge contract.
2. Seeds the required settlement price.
3. Calls `ingest_hedge_contract_settlement()` with derived fixed and float leg amounts.
4. Creates a Baseline snapshot with `as_of_date >= cashflow_date`.
5. Asserts both ledger entries appear in `snapshot_data["realized_ledger_entries"]`.
6. Asserts `realized_total_usd` equals signed ledger sum.
7. Asserts `total_net_cashflow` equals realized plus unrealized.

Use existing ledger tests in `backend/tests/test_cashflow_ledger_settlement.py` as fixture guidance. Do not duplicate an end-to-end settlement suite; this test only proves Baseline consumes ledger evidence and stores reconciliation.

### 6.3 Partially settled unrealized tail is included by Baseline

Add a test that creates a `HedgeContract(status=HedgeContractStatus.partially_settled)` with price evidence and no new settlement event, then creates a Baseline snapshot.

Assert:

- One unrealized item exists for that contract.
- The item carries price provenance.
- The item is not represented as a realized ledger entry unless ledger rows actually exist.

This closes the OPUS-08 edge where Analytic excludes non-active contracts while MTM supports partially-settled contracts.

### 6.4 Unsupported ledger direction hard-fails

Add a focused service test that inserts a `CashFlowLedgerEntry(direction="SIDEWAYS")` directly, then calls `create_cashflow_baseline_snapshot()`.

Assert:

- HTTP 422.
- Detail contains `Unsupported ledger direction`.

This protects the reconciliation invariant from silently dropping bad accounting rows.

### 6.5 Existing snapshot conflict still protects reconstruction

Adapt `test_snapshot_conflict_returns_409` if necessary so the conflict is against the new payload shape.

The behavior must remain:

- First create returns a persisted snapshot.
- If persisted `snapshot_data` or `total_net_cashflow` is mutated, second create for same `as_of_date` raises HTTP 409.

Also add or extend a deterministic-hash test so it proves canonical ordering is
part of the hash input for both payload arrays:

- `unrealized_items` sorted by `(object_type, object_id)`.
- `realized_ledger_entries` sorted by `(cashflow_date, hedge_contract_id, leg_id, source_event_id or "")`.

If a test inserts a direct ledger row with `source_event_id=None`, it must prove
the `source_event_id or ""` sort key is deterministic. Normal settlement-ledger
rows created by `ingest_hedge_contract_settlement()` should still carry a
non-null `source_event_id`.

### 6.6 Scenario no longer emits fake Baseline

Extend `backend/tests/test_scenario_whatif_run.py`.

Add or update:

```python
def test_scenario_cashflow_snapshot_has_no_fake_baseline(client) -> None:
    symbol = "LME_ALU_CASH_SETTLEMENT_DAILY"
    _insert_price(symbol, settlement_date=date(2026, 1, 29), price_usd=105.0)
    _insert_price(symbol, settlement_date=date(2026, 1, 30), price_usd=110.0)
    _insert_contract(quantity_mt=5.0, entry_price=100.0)

    response = client.post(
        "/scenario/what-if/run",
        json={
            "as_of_date": "2026-02-01",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "deltas": [],
        },
    )

    assert response.status_code == 200
    cashflow = response.json()["cashflow_snapshot"]
    assert set(cashflow) == {"analytic"}
    assert "baseline" not in cashflow
```

Update any existing tests that assume `cashflow_snapshot.baseline` exists. Do not replace it with another fake field.

---

## 7. Verification commands

Run focused tests first:

```bash
pytest backend/tests/test_cashflow_baseline_service.py backend/tests/test_scenario_whatif_run.py -v
```

Run cashflow adjacent tests:

```bash
pytest backend/tests/test_cashflow_analytic_service.py backend/tests/test_cashflow_ledger_service.py backend/tests/test_cashflow_ledger_settlement.py backend/tests/test_cashflow_projection_service.py backend/tests/test_cashflow_projection_routes.py -v
```

Run schema and migration checks:

```bash
alembic heads
```

Regenerate OpenAPI and frontend schema:

```bash
cd backend && DATABASE_URL=sqlite:///:memory: SECRET_KEY=dummy JWT_SIGNING_SECRET=dummy AUDIT_HMAC_KEY=dummy AUDIT_SIGNING_KEY=test python -c "from app.main import app; import json; json.dump(app.openapi(), open('../docs/api/openapi_v1.json', 'w'), indent=2, sort_keys=True)"
cd ../frontend-svelte && OPENAPI_SOURCE=../docs/api/openapi_v1.json node scripts/regen-schema.mjs
```

Run diff/grep gates:

```bash
git diff --check
git diff -- docs/governance.md
grep -n "compute_cashflow_analytic\|analytic.model_dump" backend/app/services/cashflow_baseline_service.py
grep -n "baseline=cashflow_analytic" backend/app/services/scenario_whatif_service.py
grep -n "baseline: CashFlowAnalyticResponse" backend/app/schemas/scenario.py
```

Expected:

- `git diff --check` is clean.
- `git diff -- docs/governance.md` is empty.
- Each grep returns zero matches.

Then run the full backend suite:

```bash
pytest backend/tests/ -v
```

Known local baseline note: if the only failures are the existing Python 3.14 `backend/tests/test_ws.py` `asyncio.get_event_loop()` failures, report them as baseline noise with exact counts. Do not hide new cashflow/scenario failures behind that baseline.

---

## 8. Workflow

1. `git fetch origin`
2. `git worktree add D:/Projetos/Hedge-Control-New-pr-a3-4 origin/main`
3. `cd D:/Projetos/Hedge-Control-New-pr-a3-4`
4. `git checkout -b audit-a3/cashflow-boundaries-reconciliation`
5. `python scripts/install_git_hooks.py`
6. Confirm hook v2 active: `git config core.hooksPath` returns `.githooks`.
7. Read the jury sections for J-A3-04 and J-A3-OPUS-08 in full.
8. Implement Baseline-owned payload and reconciliation per sections 3.1-3.2.
9. Remove fake Scenario Baseline per section 3.3.
10. Regenerate OpenAPI/frontend schema per section 3.4.
11. Run focused tests first, then adjacent cashflow tests, then full backend.
12. Push normally. Do not use `--no-verify` unless explicitly authorized by the orchestrator.
13. Open a PR against `main`. Do not auto-merge.
14. Wait for Codex Connector review. Adjudicate every catch by direct code reading before accepting or rejecting it.

---

## 9. PR shape

**Title:** `fix(audit-a3): PR-A3-4 - cashflow boundaries and baseline reconciliation`

**Body skeleton:**

```markdown
## Summary

Wave 4 of Phase A3 remediation. Closes J-A3-04 and J-A3-OPUS-08.

- Baseline snapshot creation no longer imports or calls Analytic.
- Baseline snapshot payload now has an explicit `view="baseline"` contract:
  `unrealized_items`, `realized_ledger_entries`, and `reconciliation`.
- Baseline reconciliation persists ledger realized-to-date evidence and proves
  `total_net_cashflow = unrealized_total_usd + realized_total_usd`.
- Scenario no longer emits `cashflow_snapshot.baseline` as a duplicate
  Analytic object.
- OpenAPI and frontend schema regenerated for the Scenario response change.

## Files changed

- `backend/app/services/cashflow_baseline_service.py`
- `backend/app/schemas/scenario.py`
- `backend/app/services/scenario_whatif_service.py`
- `backend/tests/test_cashflow_baseline_service.py`
- `backend/tests/test_scenario_whatif_run.py`
- `docs/api/openapi_v1.json`
- `frontend-svelte/src/lib/api/schema.d.ts`

## Acceptance evidence

- [ ] Focused tests: include the exact command and pass/fail counts from this PR run.
- [ ] Adjacent cashflow tests: include the exact command and pass/fail counts from this PR run.
- [ ] Full backend: include the exact command and pass/fail counts; separate any known `test_ws.py` Python 3.14 baseline failures from regressions.
- [ ] `alembic heads`: `038_a3_price_provenance`
- [ ] `git diff --check`: clean
- [ ] `git diff -- docs/governance.md`: empty
- [ ] grep `compute_cashflow_analytic|analytic.model_dump` in baseline service: zero matches
- [ ] grep `baseline=cashflow_analytic` in scenario service: zero matches
- [ ] grep `baseline: CashFlowAnalyticResponse` in scenario schema: zero matches

## Constitutional impact

Enforces cashflow view boundaries and output auditability under
`docs/governance.md` VALUATION/MTM/CASHFLOW, hard-fail, and output-contract
sections. No Constitution change in this PR.

## Out of scope

- P&L partially-settled lifecycle semantics (PR-A3-5 / J-A3-OPUS-09)
- Scenario-vs-Baseline comparison feature
- Ledger ingestion API changes
- Model migration
- Any change to `docs/governance.md`

## Closes

J-A3-04 + J-A3-OPUS-08.
```

---

## 10. Constraints - what NOT to do

- Do not keep `compute_cashflow_analytic` in `cashflow_baseline_service.py`.
- Do not keep `analytic.model_dump()` as the Baseline payload source.
- Do not keep `ScenarioCashflowSnapshot.baseline` if it is just another `CashFlowAnalyticResponse`.
- Do not add a new fake baseline-like scenario field.
- Do not silently skip unsupported ledger directions.
- Do not include settled contracts in `unrealized_items`; settled flows belong in realized ledger evidence.
- Do not omit partially-settled contracts from Baseline unrealized items.
- Do not mutate existing snapshots to the new shape; conflicting persisted snapshots must continue to return HTTP 409.
- Do not modify `docs/governance.md`.
- Do not add an Alembic migration unless a hard blocker is discovered and documented.
- Do not use `--no-verify` or `--force`.
- Do not auto-merge.

---

## 11. Final report shape

When complete, report back with:

- Branch, PR URL, final SHA.
- Files touched, grouped by service/schema/test/generated.
- Focused test counts and adjacent cashflow test counts.
- Full backend test count, with baseline failures separated from regressions.
- Codex Connector review state and catches absorbed/rejected.
- Hook v2 artifact path and `tool_calls` summary.
- Grep evidence for the three zero-match boundary checks.
- `docs/governance.md` zero-diff evidence.
- OpenAPI/frontend schema regeneration evidence.

Keep the report under 600 words.
